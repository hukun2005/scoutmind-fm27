"""V3.3.2-05 AI Transfer Director 测试：报价确定性、条款、谈判、存档隔离。"""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import (
    Club,
    FmSave,
    Player,
    PlayerInstance,
    PlayerSnapshot,
    Transfer,
    TransferFeeComponent,
)
from app.services import transfer_director
from app.utils import utcnow


def _player(
    db: Session,
    save: FmSave,
    *,
    name: str = "Test Striker",
    uid: str = "p-1",
    age: int = 25,
    ca: int = 150,
    pa: int = 165,
    wage: int | None = 20_000,
    market_value: int | None = 10_000_000,
    contract_end: date | None = date(2029, 6, 30),
    position: str = "ST",
    listed: bool | None = None,
) -> PlayerInstance:
    club = Club(fm_save_id=save.id, uid=f"club-{uid}", name="Alpha FC")
    db.add(club)
    db.commit()
    player = Player(full_name=name, normalized_name=name.lower())
    db.add(player)
    db.commit()
    instance = PlayerInstance(
        player_id=player.id,
        fm_save_id=save.id,
        save_local_uid=uid,
        club_id=club.id,
        position=position,
    )
    db.add(instance)
    db.commit()
    snapshot = PlayerSnapshot(
        player_instance_id=instance.id,
        observed_at=utcnow(),
        game_date=date(2026, 7, 1),
        age=age,
        ca=ca,
        pa=pa,
        market_value=market_value,
        wage=wage,
        contract_end=contract_end,
        club_id=club.id,
        position=position,
        source="fm27_live_reader",
    )
    db.add(snapshot)
    db.commit()
    instance.latest_snapshot_id = snapshot.id
    if listed is not None:
        from app.models import PlayerAvailability

        db.add(
            PlayerAvailability(
                player_instance_id=instance.id,
                observed_at=utcnow(),
                listed=listed,
                source="fm27_live_reader",
            )
        )
    db.commit()
    return instance


def test_purchase_offers_are_deterministic_with_three_scenarios(db: Session, save: FmSave) -> None:
    instance = _player(db, save)
    first = transfer_director.generate_purchase_offers(db, instance)
    second = transfer_director.generate_purchase_offers(db, instance)
    assert first["available"] is True
    assert [offer["offer_type"] for offer in first["offers"]] == ["conservative", "competitive", "fast_close"]
    assert first["basis"]["kind"] == "market_value_only"
    assert first["offers"] == second["offers"]
    # 未知值不补 0：没有额外条款时 addons 为 None，而不是 0
    assert first["offers"][0]["addons_potential"] is None
    # 立即支付 + 分期 = 固定承诺
    competitive = first["offers"][1]
    assert competitive["immediate_payment"] + competitive["installments_total"] == competitive["total_committed"]
    # 预算未提供时必须明确提示
    assert any("预算" in warning for warning in first["warnings"])
    assert first["budget"]["provided"] is False


def test_purchase_offers_refuse_to_invent_amounts(db: Session, save: FmSave) -> None:
    instance = _player(db, save, market_value=None)
    result = transfer_director.generate_purchase_offers(db, instance)
    assert result["available"] is False
    assert result["offers"] == []
    assert result["basis"]["base"] is None
    assert any("不编造金额" in warning for warning in result["warnings"])


def test_contract_remaining_months_lowers_purchase_price(db: Session, save: FmSave) -> None:
    short = _player(db, save, uid="short", contract_end=date(2026, 9, 1))
    long = _player(db, save, uid="long", contract_end=date(2031, 6, 30))
    short_offer = transfer_director.generate_purchase_offers(db, short)["offers"][1]
    long_offer = transfer_director.generate_purchase_offers(db, long)["offers"][1]
    assert short_offer["total_committed"] < long_offer["total_committed"]


def test_age_and_listing_adjust_purchase_price(db: Session, save: FmSave) -> None:
    young = _player(db, save, uid="young", age=20)
    veteran = _player(db, save, uid="old", age=35)
    young_offer = transfer_director.generate_purchase_offers(db, young)["offers"][1]
    veteran_offer = transfer_director.generate_purchase_offers(db, veteran)["offers"][1]
    assert young_offer["total_committed"] > veteran_offer["total_committed"]

    listed = _player(db, save, uid="listed", listed=True)
    unlisted = _player(db, save, uid="unlisted", listed=False)
    assert (
        transfer_director.generate_purchase_offers(db, listed)["offers"][1]["total_committed"]
        < transfer_director.generate_purchase_offers(db, unlisted)["offers"][1]["total_committed"]
    )


def test_budget_check_flags_infeasible_offer(db: Session, save: FmSave) -> None:
    instance = _player(db, save)
    result = transfer_director.generate_purchase_offers(db, instance, budget=1_000)
    assert result["budget"]["provided"] is True
    assert all(offer["budget_feasible"] is False for offer in result["offers"])
    assert all("预算" in offer["rationale"]["budget_note"] for offer in result["offers"])


def test_sale_offers_three_scenarios_and_squad_gap(db: Session, save: FmSave) -> None:
    instance = _player(db, save)
    result = transfer_director.generate_sale_offers(db, instance)
    assert [offer["offer_type"] for offer in result["offers"]] == ["quick_sale", "fair_sale", "max_value"]
    assert result["offers"][2]["sell_on_pct"] == 10.0
    assert result["squad_impact"]["same_position_peers"] == 1
    assert result["squad_impact"]["squad_gap_risk"] == "high"
    assert result["squad_impact"]["wage_release"] == 20_000 * 52
    # 出售会释放工资：工资影响为负数
    assert result["offers"][0]["wage_impact"] == -(20_000 * 52)


def test_clauses_and_history_are_returned_with_provenance(db: Session, save: FmSave) -> None:
    instance = _player(db, save)
    transfer = Transfer(
        fm_save_id=save.id,
        source_record_id="tr-1",
        player_instance_id=instance.id,
        player_name="Test Striker",
        from_club_id=None,
        to_club_id=instance.club_id,
        transfer_type="permanent",
        status="completed",
        transfer_date=date(2025, 7, 1),
        currency="EUR",
        base_fee=8_000_000,
        source="local_import",
        confidence=0.9,
    )
    db.add(transfer)
    db.commit()
    db.add(
        TransferFeeComponent(
            transfer_id=transfer.id,
            component_type="installment",
            amount=2_000_000,
            status="scheduled",
            due_date=date(2026, 1, 1),
            condition=None,
            source="local_import",
            confidence=0.8,
            payment_schedule="2026-01-01 / 2026-07-01 各 50%",
        )
    )
    db.add(
        TransferFeeComponent(
            transfer_id=transfer.id,
            component_type="sell_on",
            amount=None,
            status="conditional_unknown",
            condition="二次转会分成 10%",
            source="local_import",
        )
    )
    db.commit()
    context = transfer_director.player_transfer_context(db, instance)
    assert len(context["transfer_history"]) == 1
    assert len(context["clauses"]) == 2
    installment = next(item for item in context["clauses"] if item["clause_type"] == "installment")
    assert installment["payment_schedule"].startswith("2026-01-01")
    assert installment["source"] == "local_import"
    unknown = next(item for item in context["clauses"] if item["clause_type"] == "sell_on")
    assert unknown["clause_value"] is None
    assert "transfer_history" not in context["missing_fields"]
    assert "transfer_clauses" not in context["missing_fields"]


def test_club_summary_keeps_currencies_separate(db: Session, save: FmSave) -> None:
    club = Club(fm_save_id=save.id, uid="user-club", name="My Club")
    db.add(club)
    db.commit()
    save.user_club_id = club.id
    db.commit()
    for index, currency in enumerate(("EUR", "GBP")):
        db.add(
            Transfer(
                fm_save_id=save.id,
                source_record_id=f"buy-{index}",
                player_name=f"Player {index}",
                to_club_id=club.id,
                transfer_type="permanent",
                status="completed",
                transfer_date=date(2026, 7, 1),
                currency=currency,
                base_fee=1_000_000,
                source="local_import",
            )
        )
    db.commit()
    summary = transfer_director.club_transfer_summary(db, save.id, club.id)
    assert summary["purchases"] == 2
    assert summary["cash_out_by_currency"] == {"EUR": 1_000_000.0, "GBP": 1_000_000.0}


def test_negotiation_flow_and_review(client: TestClient, db: Session, save: FmSave) -> None:
    instance = _player(db, save)
    created = client.post(
        "/api/v1/transfer-director/negotiations",
        json={"instance_id": instance.id, "direction": "purchase", "initial_ask": 9_000_000},
    )
    assert created.status_code == 201, created.text
    negotiation_id = created.json()["negotiation_id"]
    assert created.json()["status"] == "DRAFT"

    submitted = client.post(
        f"/api/v1/transfer-director/negotiations/{negotiation_id}/events",
        json={"event_type": "offer_submitted", "amount": 8_000_000},
    )
    assert submitted.status_code == 201, submitted.text
    assert submitted.json()["negotiation"]["status"] == "SUBMITTED"

    counter = client.post(
        f"/api/v1/transfer-director/negotiations/{negotiation_id}/events",
        json={"event_type": "counter_received", "amount": 9_500_000},
    )
    assert counter.json()["negotiation"]["status"] == "COUNTERED"

    completed = client.post(
        f"/api/v1/transfer-director/negotiations/{negotiation_id}/events",
        json={"event_type": "completed", "amount": 9_200_000, "data": {"terms": {"installments": 3}}},
    )
    assert completed.json()["negotiation"]["status"] == "COMPLETED"

    review = client.get(f"/api/v1/transfer-director/negotiations/{negotiation_id}/review").json()
    assert review["outcome"] == "成交"
    assert review["delta"] == 200_000
    assert abs(review["delta_pct"] - 2.2) < 0.05
    assert review["round_count"] == 3
    assert any("样本不足" in warning for warning in review["warnings"])

    blocked = client.post(
        f"/api/v1/transfer-director/negotiations/{negotiation_id}/events",
        json={"event_type": "offer_submitted", "amount": 1},
    )
    assert blocked.status_code == 409


def test_duplicate_event_is_idempotent(client: TestClient, db: Session, save: FmSave) -> None:
    instance = _player(db, save)
    negotiation_id = client.post(
        "/api/v1/transfer-director/negotiations",
        json={"instance_id": instance.id, "direction": "sale", "initial_ask": 5_000_000},
    ).json()["negotiation_id"]
    body = {"event_type": "offer_submitted", "amount": 4_500_000, "occurred_at": "2026-07-01T10:00:00"}
    first = client.post(f"/api/v1/transfer-director/negotiations/{negotiation_id}/events", json=body)
    second = client.post(f"/api/v1/transfer-director/negotiations/{negotiation_id}/events", json=body)
    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is True
    detail = client.get(f"/api/v1/transfer-director/negotiations/{negotiation_id}").json()
    assert len([event for event in detail["events"] if event["event_type"] == "offer_submitted"]) == 1


def test_offers_and_negotiations_are_save_scoped(client: TestClient, db: Session, save: FmSave) -> None:
    instance = _player(db, save)
    created = client.post(
        "/api/v1/transfer-director/negotiations",
        json={"instance_id": instance.id, "direction": "purchase", "initial_ask": 1_000_000},
    )
    negotiation_id = created.json()["negotiation_id"]

    other_save = FmSave(user_id=save.user_id, name="另一个存档", is_active=False)
    db.add(other_save)
    db.commit()

    hidden = client.get(
        f"/api/v1/transfer-director/negotiations/{negotiation_id}", params={"save_id": other_save.id}
    )
    assert hidden.status_code == 404
    foreign_instance = client.get(
        f"/api/v1/transfer-director/player/{instance.id}", params={"save_id": other_save.id}
    )
    assert foreign_instance.status_code == 404


def test_overview_reports_missing_transfer_capability(client: TestClient, save: FmSave) -> None:
    response = client.get("/api/v1/transfer-director/overview")
    assert response.status_code == 200
    payload = response.json()
    assert payload["capabilities"]["auto_transfer_history"] is False
    assert payload["capabilities"]["auto_budget"] is False
    assert "历史转会" in payload["message"]


def test_purchase_offer_endpoint_rejects_foreign_player(client: TestClient, db: Session, save: FmSave) -> None:
    response = client.post("/api/v1/transfer-director/player/999999/purchase-offers", json={})
    assert response.status_code == 404


def test_transfer_status_history_keeps_each_transition(db: Session, save: FmSave) -> None:
    """agreed/pending → completed 必须保留历史，重复导入同一状态不新增。"""
    from sqlalchemy import select

    from app.models import TransferStatusHistory
    from tests.helpers import import_document, player_row, scan_document, transfer_row

    players = [player_row("P1", "History Player")]
    import_document(
        db,
        scan_document(
            scan_id="scan-history-1",
            players=players,
            transfers=[transfer_row("T1", "P1", "History Player", fee=5_000_000, status="pending")],
        ),
    )
    rows = list(db.scalars(select(TransferStatusHistory).order_by(TransferStatusHistory.id)))
    assert [(row.previous_status, row.new_status) for row in rows] == [(None, "pending")]

    import_document(
        db,
        scan_document(
            scan_id="scan-history-2",
            players=players,
            transfers=[transfer_row("T1", "P1", "History Player", fee=5_000_000, status="completed")],
        ),
    )
    rows = list(db.scalars(select(TransferStatusHistory).order_by(TransferStatusHistory.id)))
    assert [(row.previous_status, row.new_status) for row in rows] == [
        (None, "pending"),
        ("pending", "completed"),
    ]

    import_document(
        db,
        scan_document(
            scan_id="scan-history-3",
            players=players,
            transfers=[transfer_row("T1", "P1", "History Player", fee=5_000_000, status="completed")],
        ),
    )
    rows = list(db.scalars(select(TransferStatusHistory).order_by(TransferStatusHistory.id)))
    assert len(rows) == 2

    direct = transfer_director.player_transfer_context(
        db, db.query(PlayerInstance).filter(PlayerInstance.fm_save_id == save.id).order_by(PlayerInstance.id).first()
    )
    assert direct["transfer_history"][0]["status"] == "completed"
