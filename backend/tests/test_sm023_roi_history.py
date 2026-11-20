"""SM-023：转会 ROI 历史成本计算。"""

from __future__ import annotations

from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.analytics.roi import transfer_roi
from app.models import Club, Player, PlayerInstance, PlayerSnapshot, Transfer


def _club(db, save, name: str) -> Club:
    uid = "club-" + name.lower().replace(" ", "-")
    club = db.scalar(select(Club).where(Club.fm_save_id == save.id, Club.uid == uid))
    if club is None:
        club = Club(fm_save_id=save.id, uid=uid, name=name)
        db.add(club)
        db.commit()
    return club

def _instance(db, save, uid: str) -> PlayerInstance:
    player = Player(full_name=f"Roi {uid}", normalized_name=f"roi-{uid.lower()}")
    db.add(player)
    db.commit()
    instance = PlayerInstance(player_id=player.id, fm_save_id=save.id, save_local_uid=uid)
    db.add(instance)
    db.commit()
    return instance


def _snapshot(db, instance, *, when: datetime, wage: int | None, market: int | None, contract_end: date | None, ca: int = 140, pa: int = 170) -> None:
    db.add(
        PlayerSnapshot(
            player_instance_id=instance.id,
            observed_at=when,
            game_date=when.date(),
            age=24,
            ca=ca,
            pa=pa,
            market_value=market,
            wage=wage,
            contract_end=contract_end,
            source="manual",
        )
    )
    db.commit()


def _buy(db, save, instance, *, fee: float | None = 10_000_000, when: date = date(2026, 7, 1), currency: str = "EUR") -> Transfer:
    club_a = _club(db, save, "Buyer ROI")
    club_b = _club(db, save, "Seller ROI")
    row = Transfer(
        fm_save_id=save.id,
        source_record_id=f"ROI-{instance.id}-{when.isoformat()}",
        player_instance_id=instance.id,
        player_name="Roi Player",
        from_club_id=club_b.id,
        to_club_id=club_a.id,
        transfer_type="permanent",
        status="completed",
        transfer_date=when,
        currency=currency,
        base_fee=fee,
        effective_fee=fee,
        source="manual",
    )
    db.add(row)
    db.commit()
    return row


def test_accounting_uses_wage_at_transfer_not_current(client: TestClient, db, save) -> None:
    instance = _instance(db, save, "R1")
    _snapshot(
        db, instance,
        when=datetime(2026, 6, 1, 12),
        wage=10_000, market=8_000_000, contract_end=date(2029, 6, 30),
    )
    _snapshot(
        db, instance,
        when=datetime(2026, 11, 1, 12),
        wage=50_000, market=18_000_000, contract_end=date(2031, 6, 30),
    )
    buy = _buy(db, save, instance)
    body = transfer_roi(db, buy.id)
    assert body["buy_context"]["wage"] == 10_000
    assert body["current"]["wage"] == 50_000
    assert body["accounting"]["wage_at_transfer"] == 10_000
    assert body["accounting"]["years"] == pytest.approx(3.08, rel=0.05), "用买入时的合同，而不是续约后的"
    assert body["accounting"]["total"] < 10_000_000 + 50_000 * 52 * 5


def test_accounting_is_null_without_buy_time_snapshot(client: TestClient, db, save) -> None:
    instance = _instance(db, save, "R2")
    _snapshot(db, instance, when=datetime(2026, 9, 1, 12), wage=20_000, market=10_000_000, contract_end=date(2030, 6, 30))
    buy = _buy(db, save, instance)
    body = transfer_roi(db, buy.id)
    assert body["accounting"] is None
    assert body["buy_context"]["available"] is False
    assert any("买入当时" in item for item in body["missing"])


def test_missing_fee_gives_null_cash_and_reason(client: TestClient, db, save) -> None:
    instance = _instance(db, save, "R3")
    _snapshot(db, instance, when=datetime(2026, 6, 1, 12), wage=10_000, market=5_000_000, contract_end=date(2029, 6, 30))
    buy = _buy(db, save, instance, fee=None)
    body = transfer_roi(db, buy.id)
    assert body["buy"]["cash_cost"] is None
    assert body["cash"]["realized_profit"] is None
    assert body["cash"]["realized_note"]


def test_sale_selection_is_deterministic_and_skips_incomplete(client: TestClient, db, save) -> None:
    instance = _instance(db, save, "R4")
    buy = _buy(db, save, instance)
    buyer = db.get(Club, buy.to_club_id)
    later = _club(db, save, "Later Club")
    second = _club(db, save, "Second Club")
    # 未完成的卖出不参与
    db.add(
        Transfer(
            fm_save_id=save.id, source_record_id="pending-sale", player_instance_id=instance.id,
            player_name="Roi Player", from_club_id=buyer.id, to_club_id=later.id,
            transfer_type="permanent", status="agreed", transfer_date=date(2026, 8, 1),
            currency="EUR", effective_fee=99_000_000, source="manual",
        )
    )
    db.commit()
    # 两笔已完成卖出：按日期+id 取最早
    first_sale = Transfer(
        fm_save_id=save.id, source_record_id="sale-1", player_instance_id=instance.id,
        player_name="Roi Player", from_club_id=buyer.id, to_club_id=later.id,
        transfer_type="permanent", status="completed", transfer_date=date(2026, 9, 1),
        currency="EUR", effective_fee=25_000_000, source="manual",
    )
    second_sale = Transfer(
        fm_save_id=save.id, source_record_id="sale-2", player_instance_id=instance.id,
        player_name="Roi Player", from_club_id=buyer.id, to_club_id=second.id,
        transfer_type="permanent", status="completed", transfer_date=date(2027, 1, 1),
        currency="EUR", effective_fee=30_000_000, source="manual",
    )
    db.add_all([first_sale, second_sale])
    db.commit()
    body = transfer_roi(db, buy.id)
    assert body["sale"]["available"] is True
    assert body["sale"]["fee"] == 25_000_000
    assert body["cash"]["realized_profit"] == 15_000_000


def test_loan_buyout_counts_as_sale_and_cross_currency_is_unknown(client: TestClient, db, save) -> None:
    instance = _instance(db, save, "R5")
    buy = _buy(db, save, instance)
    buyer = db.get(Club, buy.to_club_id)
    target = _club(db, save, "Target")
    db.add(
        Transfer(
            fm_save_id=save.id, source_record_id="buyout", player_instance_id=instance.id,
            player_name="Roi Player", from_club_id=buyer.id, to_club_id=target.id,
            transfer_type="loan_buyout", status="completed", transfer_date=date(2027, 6, 1),
            currency="GBP", effective_fee=20_000_000, source="manual",
        )
    )
    db.commit()
    body = transfer_roi(db, buy.id)
    assert body["sale"]["available"] is True
    assert body["cash"]["realized_profit"] is None, "跨币种不换算"
    assert "币种" in body["cash"]["realized_note"]


