"""V3.3.2-07 B-04~B-07：三套报价、币种、预算与历史案例动态调整。"""

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
    TransferOffer,
)
from app.services import transfer_director
from app.utils import utcnow

API = "/api/v1"


def _player(
    db: Session,
    save: FmSave,
    *,
    uid: str = "q-1",
    name: str = "Quote Player",
    age: int = 25,
    ca: int | None = 150,
    market_value: int | None = 10_000_000,
    contract_end: date | None = date(2029, 6, 30),
    position: str = "ST",
) -> PlayerInstance:
    club = Club(fm_save_id=save.id, uid=f"club-{uid}", name=f"Club {uid}")
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
        pa=(ca + 10) if ca is not None else None,
        market_value=market_value,
        wage=20_000,
        contract_end=contract_end,
        club_id=club.id,
        position=position,
        source="fm27_live_reader",
    )
    db.add(snapshot)
    db.commit()
    instance.latest_snapshot_id = snapshot.id
    db.commit()
    return instance


def _case_transfer(db: Session, save: FmSave, *, record_id: str, instance: PlayerInstance,
                   fee: float, age: int = 25) -> Transfer:
    row = Transfer(
        fm_save_id=save.id,
        source_record_id=record_id,
        player_instance_id=instance.id,
        player_name=f"Case {record_id}",
        transfer_type="permanent",
        status="completed",
        transfer_date=date(2026, 1, 1),
        currency="EUR",
        base_fee=fee,
        fee_paid=fee,
        player_age_at_transfer=age,
        contract_remaining_months=24,
        source="test_fixture",
    )
    db.add(row)
    db.commit()
    return row


def test_purchase_offers_three_and_deterministic(db: Session, save: FmSave) -> None:
    instance = _player(db, save)
    first = transfer_director.generate_purchase_offers(db, instance)
    second = transfer_director.generate_purchase_offers(db, instance)
    assert first["available"] is True
    assert [offer["offer_type"] for offer in first["offers"]] == ["conservative", "competitive", "fast_close"]
    assert first["offers"] == second["offers"]
    assert first["budget_status"] == "unknown"
    assert "预算状态未知" in first["budget_note"]


def test_sale_offers_three_and_no_auto_listing(db: Session, save: FmSave) -> None:
    instance = _player(db, save)
    offers_before = db.query(TransferOffer).count()
    result = transfer_director.generate_sale_offers(db, instance)
    assert [offer["offer_type"] for offer in result["offers"]] == ["quick_sale", "fair_sale", "max_value"]
    assert db.query(TransferOffer).count() == offers_before
    assert instance.player is not None
    assert db.query(TransferOffer).count() == 0


def test_loan_offers_option_vs_obligation(db: Session, save: FmSave) -> None:
    instance = _player(db, save)
    offers = transfer_director.generate_loan_offers(db, instance)["offers"]
    assert [offer["offer_type"] for offer in offers] == ["low_cost_loan", "development_loan", "loan_to_buy"]
    development = offers[1]
    assert development["buy_option_fee"] is not None
    assert development["buy_obligation_fee"] is None
    obligation = offers[2]
    assert obligation["buy_option_fee"] is None
    assert obligation["buy_obligation_fee"] is not None


def test_unknown_currency_is_not_eur(db: Session, save: FmSave) -> None:
    instance = _player(db, save)
    result = transfer_director.generate_purchase_offers(db, instance)
    assert result["currency"] is None
    assert result["currency_known"] is False
    assert "未知" in result["currency_note"]
    assert all(offer["currency"] is None for offer in result["offers"])


def test_currency_from_transfer_history(db: Session, save: FmSave) -> None:
    case_player = _player(db, save, uid="gbp")
    _case_transfer(db, save, record_id="gbp-1", instance=case_player, fee=9_000_000)
    row = db.query(Transfer).filter(Transfer.source_record_id == "gbp-1").one()
    row.currency_original = "GBP"
    db.commit()

    instance = _player(db, save, uid="target")
    result = transfer_director.generate_purchase_offers(db, instance)
    assert result["currency"] == "GBP"
    assert result["currency_known"] is True
    assert result["currency_source"] == "transfer_history"


def test_history_adjusts_quote_with_before_after(db: Session, save: FmSave) -> None:
    for index, fee in enumerate((12_000_000, 13_000_000, 14_000_000)):
        case_instance = _player(db, save, uid=f"case-{index}", name=f"Case {index}")
        _case_transfer(db, save, record_id=f"case-{index}", instance=case_instance, fee=fee)

    target = _player(db, save, uid="adjust-target")
    result = transfer_director.generate_purchase_offers(db, target)
    adjustment = result["strategy_adjustment"]
    assert adjustment["applied"] is True
    assert adjustment["after"] != adjustment["before"]
    assert adjustment["case_ids"]
    assert len(adjustment["case_ids"]) == 3
    assert 0.85 <= adjustment["multiplier"] <= 1.15
    assert adjustment["sample_size"] == 3


def test_no_history_keeps_base_rules(db: Session, save: FmSave) -> None:
    instance = _player(db, save)
    result = transfer_director.generate_purchase_offers(db, instance)
    adjustment = result["strategy_adjustment"]
    assert adjustment["applied"] is False
    assert adjustment["multiplier"] == 1.0
    assert adjustment["case_ids"] == []
    assert result["offers"][1]["total_committed"] == result["offers"][1]["strategy_adjustment"]["before"]


def test_adjustment_is_clamped_and_non_negative(db: Session, save: FmSave) -> None:
    for index in range(3):
        case_instance = _player(db, save, uid=f"cheap-{index}", name=f"Cheap {index}")
        _case_transfer(db, save, record_id=f"cheap-{index}", instance=case_instance, fee=1_000_000)
    target = _player(db, save, uid="clamp-target")
    result = transfer_director.generate_purchase_offers(db, target)
    assert result["strategy_adjustment"]["multiplier"] == 0.85
    for offer in result["offers"]:
        for key in ("base_fee", "immediate_payment", "total_committed", "potential_total"):
            assert offer[key] is None or offer[key] >= 0
        if offer["installments_total"] is not None:
            assert offer["immediate_payment"] + offer["installments_total"] == offer["total_committed"]


def test_budget_unknown_message(db: Session, save: FmSave) -> None:
    instance = _player(db, save)
    result = transfer_director.generate_purchase_offers(db, instance)
    assert result["budget_status"] == "unknown"
    assert result["budget_note"] == "预算状态未知，无法确认该报价符合俱乐部财政条件。"
    assert all(offer["budget_feasible"] is None for offer in result["offers"])


def test_budget_insufficient_flags_offers(db: Session, save: FmSave) -> None:
    instance = _player(db, save)
    result = transfer_director.generate_purchase_offers(db, instance, budget=1.0)
    assert result["budget_status"] == "insufficient"
    assert any(offer["budget_feasible"] is False for offer in result["offers"])


def test_saved_offer_currency_unknown(client: TestClient, db: Session, save: FmSave) -> None:
    instance = _player(db, save)
    response = client.post(
        f"{API}/transfer-director/offers?instance_id={instance.id}",
        json={"direction": "purchase", "offer_type": "conservative", "currency": None},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["currency"] is None
    assert body["currency_known"] is False
    assert "未知" in body["currency_note"]
    row = db.get(TransferOffer, body["offer_id"])
    assert row is not None and row.currency == "UNKNOWN"
