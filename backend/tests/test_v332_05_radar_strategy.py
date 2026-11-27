"""V3.3.2-05 扩展版：机会雷达、成交策略学习、租借报价。"""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Alert,
    Club,
    FmSave,
    Player,
    PlayerAvailability,
    PlayerInstance,
    PlayerSnapshot,
    Transfer,
    TransferFeeComponent,
    TransferOpportunity,
    TransferOpportunityEvent,
)
from app.services import transfer_director, transfer_radar, transfer_strategy
from app.utils import utcnow


def _seed_player(
    db: Session,
    save: FmSave,
    club: Club,
    *,
    name: str,
    uid: str,
    age: int = 25,
    ca: int = 150,
    pa: int = 165,
    market_value: int | None = 10_000_000,
    wage: int | None = 20_000,
    contract_end: date | None = date(2027, 6, 30),
    game_date: date | None = date(2026, 7, 1),
    position: str = "ST",
    listed: bool | None = False,
    loan_listed: bool | None = False,
    set_for_release: bool | None = False,
) -> PlayerInstance:
    player = Player(full_name=name, normalized_name=name.lower())
    db.add(player)
    db.flush()
    instance = PlayerInstance(player_id=player.id, fm_save_id=save.id, save_local_uid=uid, club_id=club.id)
    db.add(instance)
    db.flush()
    snapshot = PlayerSnapshot(
        player_instance_id=instance.id,
        observed_at=utcnow(),
        game_date=game_date,
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
    db.flush()
    instance.latest_snapshot_id = snapshot.id
    db.add(
        PlayerAvailability(
            player_instance_id=instance.id,
            observed_at=utcnow(),
            listed=listed,
            loan_listed=loan_listed,
            set_for_release=set_for_release,
            source="fm27_live_reader",
        )
    )
    db.commit()
    return instance


def _club(db: Session, save: FmSave, name: str = "Alpha FC") -> Club:
    club = Club(fm_save_id=save.id, uid=f"club-{name}", name=name)
    db.add(club)
    db.commit()
    return club


def _scan(db: Session, save: FmSave) -> dict:
    return transfer_radar.scan(db, save.id, observed_at=utcnow())


def _opportunities(db: Session, save: FmSave, instance_id: int) -> dict[str, TransferOpportunity]:
    rows = db.scalars(
        select(TransferOpportunity).where(
            TransferOpportunity.fm_save_id == save.id,
            TransferOpportunity.player_instance_id == instance_id,
        )
    )
    return {row.opportunity_type: row for row in rows}


def test_scan_confirms_listed_loan_and_contract_buckets(db: Session, save: FmSave) -> None:
    club = _club(db, save)
    listed = _seed_player(db, save, club, name="Listed One", uid="u1", listed=True)
    loaned = _seed_player(db, save, club, name="Loan One", uid="u2", loan_listed=True)
    expiring = _seed_player(
        db, save, club, name="Expiring One", uid="u3", contract_end=date(2026, 11, 1), game_date=date(2026, 7, 1)
    )
    result = _scan(db, save)

    assert result["scanned_players"] == 3
    assert result["created"] >= 3
    assert "listed" in _opportunities(db, save, listed.id)
    assert "loan_listed" in _opportunities(db, save, loaned.id)
    bucket = _opportunities(db, save, expiring.id)["contract_expiring"]
    assert bucket.active and bucket.verified_status == "confirmed"
    assert '"bucket": "6m"' in bucket.detail_json


def test_false_flag_is_not_an_opportunity_and_missing_flag_is_null(db: Session, save: FmSave) -> None:
    club = _club(db, save)
    clean = _seed_player(db, save, club, name="Clean", uid="c1", listed=False, loan_listed=False,
                         contract_end=None)
    _scan(db, save)
    rows = _opportunities(db, save, clean.id)
    assert "listed" not in rows and "loan_listed" not in rows
    listed_row = db.scalar(
        select(TransferOpportunity).where(
            TransferOpportunity.fm_save_id == save.id,
            TransferOpportunity.player_instance_id == clean.id,
            TransferOpportunity.opportunity_type == "listed",
        )
    )
    assert listed_row is None


def test_state_changes_are_recorded_and_scan_is_idempotent(db: Session, save: FmSave) -> None:
    club = _club(db, save)
    instance = _seed_player(db, save, club, name="Flip", uid="f1", listed=True)
    first = _scan(db, save)
    assert first["events"] >= 1
    assert first["alerts_created"] >= 1
    second = _scan(db, save)
    assert second["events"] == 0
    assert second["alerts_created"] == 0

    availability = db.scalar(
        select(PlayerAvailability).where(PlayerAvailability.player_instance_id == instance.id)
    )
    availability.observed_at = utcnow()
    availability.listed = False
    db.commit()

    third = _scan(db, save)
    assert third["deactivated"] >= 1
    rows = _opportunities(db, save, instance.id)
    assert rows["listed"].active is False
    events = db.scalars(
        select(TransferOpportunityEvent).where(
            TransferOpportunityEvent.fm_save_id == save.id,
            TransferOpportunityEvent.player_instance_id == instance.id,
        )
    ).all()
    assert any(event.event_type == "withdrawn" for event in events)
    withdrawn_alerts = db.scalars(
        select(Alert).where(Alert.fm_save_id == save.id, Alert.alert_type == "listed_withdrawn")
    ).all()
    assert withdrawn_alerts and "撤销挂牌" in withdrawn_alerts[0].title

    availability = db.get(PlayerAvailability, availability.id)
    availability.observed_at = utcnow()
    availability.listed = True
    db.commit()
    fourth = _scan(db, save)
    assert fourth["updated"] >= 1
    events = db.scalars(
        select(TransferOpportunityEvent).where(
            TransferOpportunityEvent.fm_save_id == save.id,
            TransferOpportunityEvent.player_instance_id == instance.id,
        )
    ).all()
    assert any(event.event_type == "reappeared" for event in events)


def test_inferred_opportunities_require_club_data_and_are_marked_inferred(db: Session, save: FmSave) -> None:
    club = _club(db, save, "Big Club")
    players = [
        _seed_player(db, save, club, name=f"Squad {index}", uid=f"s{index}", ca=120, age=27)
        for index in range(5)
    ]
    veteran = _seed_player(
        db, save, club, name="Veteran", uid="vet", ca=130, age=33,
        contract_end=date(2027, 6, 30), game_date=date(2026, 7, 1),
    )
    _scan(db, save)
    inferred = _opportunities(db, save, veteran.id).get("ai_inferred")
    assert inferred is not None
    assert inferred.verified_status == "inferred"
    assert "长期规划" in inferred.detail_json

    save.user_club_id = club.id
    db.commit()
    _scan(db, save)
    veteran_row = _opportunities(db, save, veteran.id).get("ai_inferred")
    assert veteran_row is not None and veteran_row.active is False

    small_club = _club(db, save, "Small Club")
    solo = _seed_player(db, save, small_club, name="Solo", uid="solo", ca=150, age=33)
    _scan(db, save)
    assert _opportunities(db, save, solo.id).get("ai_inferred") is None
    assert players  # keep fixture alive


def test_contract_bucket_change_to_six_months_alerts(db: Session, save: FmSave) -> None:
    club = _club(db, save)
    instance = _seed_player(
        db, save, club, name="Ticking", uid="tick", ca=160,
        contract_end=date(2026, 10, 1), game_date=date(2025, 10, 15),
    )
    _scan(db, save)
    assert '"bucket": "12m"' in _opportunities(db, save, instance.id)["contract_expiring"].detail_json

    later = PlayerSnapshot(
        player_instance_id=instance.id,
        observed_at=utcnow(),
        game_date=date(2026, 5, 1),
        age=25,
        ca=160,
        pa=165,
        market_value=10_000_000,
        wage=20_000,
        contract_end=date(2026, 10, 1),
        club_id=club.id,
        position="ST",
        source="fm27_live_reader",
    )
    db.add(later)
    db.flush()
    db.get(PlayerInstance, instance.id).latest_snapshot_id = later.id
    db.commit()

    result = _scan(db, save)
    assert result["events"] >= 1
    alert = db.scalar(
        select(Alert).where(Alert.fm_save_id == save.id, Alert.alert_type == "contract_6m")
    )
    assert alert is not None and "合同进入 6 个月" in alert.title


def test_summary_reports_unsupported_transfer_intent_and_budget(db: Session, save: FmSave) -> None:
    club = _club(db, save)
    _seed_player(db, save, club, name="Listed", uid="l1", listed=True)
    summary = transfer_radar.summary(db, save.id)
    assert summary["counts"]["listed"] == 1
    assert summary["capabilities"]["transfer_intent"] == "unsupported"
    assert summary["capabilities"]["transfer_budget"] == "unsupported"
    assert "transfer_intent" in summary["unsupported_fields"]
    assert summary["auto_scan"] is not None


def test_save_isolation(db: Session, save: FmSave) -> None:
    other = FmSave(user_id=save.user_id, name="另一个存档", game_version="27.0", game_build="test")
    db.add(other)
    db.commit()
    club_a = _club(db, save, "Club A")
    club_b = _club(db, other, "Club B")
    _seed_player(db, save, club_a, name="A Player", uid="same", listed=True)
    _seed_player(db, other, club_b, name="B Player", uid="same", listed=True)
    _scan(db, save)
    listing = transfer_radar.list_opportunities(db, save.id, auto_scan=False)
    assert listing["total"] == 1
    assert listing["items"][0]["player_name"] == "A Player"
    other_rows = db.scalars(
        select(TransferOpportunity).where(TransferOpportunity.fm_save_id == other.id)
    ).all()
    assert other_rows == []


def test_list_filters_and_primary_dedupe(db: Session, save: FmSave) -> None:
    club = _club(db, save)
    both = _seed_player(db, save, club, name="Both", uid="b1", listed=True, loan_listed=True,
                        contract_end=date(2026, 10, 1), game_date=date(2026, 7, 1))
    _scan(db, save)
    default = transfer_radar.list_opportunities(db, save.id, auto_scan=False)
    assert default["total"] == 1
    assert default["items"][0]["opportunity_type"] == "listed"
    assert set(default["items"][0]["types"]) == {"listed", "loan_listed", "contract_expiring"}

    loan_only = transfer_radar.list_opportunities(db, save.id, opportunity_type="loan_listed", auto_scan=False)
    assert loan_only["total"] == 1
    assert loan_only["items"][0]["instance_id"] == both.id

    search = transfer_radar.list_opportunities(db, save.id, search="Both", auto_scan=False)
    assert search["total"] == 1
    empty = transfer_radar.list_opportunities(db, save.id, search="Nobody", auto_scan=False)
    assert empty["total"] == 0
    grouped = transfer_radar.list_opportunities(db, save.id, group="strong", auto_scan=False)
    assert all(item["recommendation_group"] == "strong" for item in grouped["items"])


def test_radar_api_endpoints(client: TestClient, db: Session, save: FmSave) -> None:
    club = _club(db, save)
    instance = _seed_player(db, save, club, name="API Listed", uid="api1", listed=True)
    summary = client.get("/api/v1/transfer-director/opportunities/summary")
    assert summary.status_code == 200
    listing = client.get("/api/v1/transfer-director/opportunities")
    assert listing.status_code == 200
    assert listing.json()["total"] >= 1
    detail = client.get(f"/api/v1/transfer-director/opportunities/{instance.id}")
    assert detail.status_code == 200
    assert detail.json()["opportunity"]["instance_id"] == instance.id
    refresh = client.post("/api/v1/transfer-director/opportunities/refresh")
    assert refresh.status_code == 200
    alerts = client.get("/api/v1/transfer-director/alerts")
    assert alerts.status_code == 200
    if alerts.json()["items"]:
        alert_id = alerts.json()["items"][0]["alert_id"]
        assert client.post(f"/api/v1/transfer-director/alerts/{alert_id}/read").status_code == 200
    assert client.get("/api/v1/transfer-director/opportunities/999999").status_code == 404


def test_loan_offers_are_deterministic_and_flagged_when_not_loan_listed(db: Session, save: FmSave) -> None:
    club = _club(db, save)
    instance = _seed_player(db, save, club, name="Loan Target", uid="loan1", loan_listed=False)
    first = transfer_director.generate_loan_offers(db, instance)
    second = transfer_director.generate_loan_offers(db, instance)
    assert first["available"] is True
    assert [offer["offer_type"] for offer in first["offers"]] == ["low_cost_loan", "development_loan", "loan_to_buy"]
    assert first["offers"] == second["offers"]
    assert any("未标记可租借" in warning for warning in first["warnings"])
    low, development, buyout = first["offers"]
    assert low["loan_fee"] < development["loan_fee"] < buyout["loan_fee"]
    assert development["buy_option_fee"] is not None
    assert buyout["buy_obligation_fee"] is not None
    assert low["buy_option_fee"] is None and low["buy_obligation_fee"] is None
    assert buyout["potential_total"] == buyout["loan_fee"] + buyout["buy_obligation_fee"]


def test_loan_offers_refuse_without_valuation(db: Session, save: FmSave) -> None:
    club = _club(db, save)
    instance = _seed_player(db, save, club, name="No Value", uid="nv1", market_value=None)
    result = transfer_director.generate_loan_offers(db, instance)
    assert result["available"] is False
    assert result["offers"] == []


def _transfer(db: Session, save: FmSave, player: PlayerInstance, *, fee: float, ttype: str = "permanent",
              contract_remaining: int = 12, addons: float | None = None, sell_on: float | None = None,
              source: str = "csv_import") -> Transfer:
    transfer = Transfer(
        fm_save_id=save.id,
        source_record_id=f"t-{player.id}-{fee}-{ttype}",
        player_instance_id=player.id,
        player_name=f"Case {player.id}",
        transfer_type=ttype,
        status="completed",
        transfer_date=date(2026, 1, 1),
        currency="EUR",
        base_fee=fee,
        fee_paid=fee,
        effective_fee=fee,
        addons_potential=addons,
        player_age_at_transfer=24,
        contract_remaining_months=contract_remaining,
        sell_on_clause_pct=sell_on,
        source=source,
        confidence=1.0,
    )
    db.add(transfer)
    db.flush()
    db.add(
        TransferFeeComponent(
            transfer_id=transfer.id,
            component_type="installment",
            amount=fee * 0.4,
            status="scheduled",
            source=source,
        )
    )
    db.commit()
    return transfer


def test_strategy_cases_and_similar_matching(db: Session, save: FmSave) -> None:
    club = _club(db, save)
    for index in range(3):
        case_player = _seed_player(db, save, club, name=f"Case {index}", uid=f"case{index}", position="ST",
                                   age=24, market_value=10_000_000)
        _transfer(db, save, case_player, fee=9_000_000 + index, contract_remaining=12)
    target = _seed_player(db, save, club, name="Target", uid="target", position="ST", age=25,
                          market_value=11_000_000, contract_end=date(2027, 6, 30), game_date=date(2026, 7, 1))

    cases = transfer_strategy.list_cases(db, save.id)
    assert cases["available"] is True
    assert cases["total"] == 3
    assert cases["items"][0]["case_origin"] == "imported"
    assert cases["items"][0]["installments"]["count"] == 1

    similar = transfer_strategy.similar_cases(db, save.id, target.id)
    assert similar["available"] is True
    assert similar["items"][0]["match_pct"] > 50
    assert "位置组相同" in similar["items"][0]["matched_features"]

    insights = transfer_strategy.insights(db, save.id)
    assert insights["available"] is True
    payment = next(item for item in insights["patterns"] if item["key"] == "installments")
    assert payment["sufficient_sample"] is True
    assert payment["case_ids"]


def test_strategy_reports_insufficient_sample_and_demo_origin(db: Session, save: FmSave) -> None:
    club = _club(db, save)
    demo_player = _seed_player(db, save, club, name="Demo Case", uid="demo1")
    _transfer(db, save, demo_player, fee=1_000_000, source="synthetic_fixture")
    cases = transfer_strategy.list_cases(db, save.id, case_origin="demo")
    assert cases["total"] == 1
    insights = transfer_strategy.insights(db, save.id)
    payment = next(item for item in insights["patterns"] if item["key"] == "installments")
    assert payment["sufficient_sample"] is False
    assert "样本不足" in payment["summary"]
    assert insights["totals"]["demo_cases"] == 1
    assert "演示" in insights["message"]

    empty = transfer_strategy.list_cases(db, 0)
    assert empty["available"] is False


def test_strategy_api_endpoints(client: TestClient, db: Session, save: FmSave) -> None:
    club = _club(db, save)
    target = _seed_player(db, save, club, name="Strategy Target", uid="st1")
    assert client.get("/api/v1/transfer-director/strategy-cases").status_code == 200
    assert client.get(f"/api/v1/transfer-director/strategy-cases/similar/{target.id}").status_code == 200
    insights = client.get("/api/v1/transfer-director/strategy-insights")
    assert insights.status_code == 200
    loan = client.post("/api/v1/transfer-director/offers/loan", params={"instance_id": target.id})
    assert loan.status_code == 200
    assert loan.json()["direction"] == "loan"
    assert client.get("/api/v1/transfer-director/offers/999999").status_code == 404
