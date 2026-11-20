"""SM-026：金额解析严格性与 ROI 完整性。"""

from __future__ import annotations

from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.analytics.roi import transfer_roi
from app.ingestion.amounts import parse_amount, parse_plain_number, parse_ratio
from app.models import Club, Player, PlayerInstance, PlayerSnapshot, Transfer, TransferFeeComponent

CSV_HEADER = (
    "player_name,transfer_date,status,transfer_type,from_club,to_club,base_fee,currency,"
    "source_record_id,wage_contribution,sell_on_pct\n"
)


def _csv(*rows: str) -> bytes:
    return (CSV_HEADER + "\n".join(rows) + "\n").encode("utf-8")


@pytest.mark.parametrize("raw", ["2,5", "1,2,3", "2.5.5", "-5", "2,5000", "1,23,456", "abc", "2.5M extra"])
def test_invalid_amount_formats_are_rejected(raw: str) -> None:
    parsed = parse_amount(raw, "EUR")
    assert parsed.error, f"{raw} 不应被接受"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0", 0),
        ("0.5", 0.5),
        ("2500000.25", 2_500_000.25),
        ("2,500,000", 2_500_000),
        ("£2.5m", 2_500_000),
        ("1200万", 12_000_000),
    ],
)
def test_valid_amounts_still_parse(raw: str, expected: float) -> None:
    parsed = parse_amount(raw, "EUR")
    assert parsed.ok, parsed.error
    assert parsed.amount == pytest.approx(expected)


def test_empty_and_unknown_markers() -> None:
    assert parse_amount("", "EUR").amount is None and parse_amount("", "EUR").error is None
    assert parse_amount(None, "EUR").amount is None
    unknown = parse_amount("N/A", "EUR")
    assert unknown.amount is None and unknown.error


def test_ratio_and_plain_number_are_strict() -> None:
    assert parse_ratio("10")[0] == 10
    assert parse_ratio("10%")[0] == 10
    assert parse_ratio("12.5 %")[0] == 12.5
    assert parse_ratio("150")[1], "百分比不能超过 100"
    assert parse_ratio("10.5.5")[1]
    assert parse_ratio("abc")[1]
    assert parse_plain_number("10,000")[0] == 10_000
    assert parse_plain_number("10k")[1], "工资分摊不接受单位"


def test_import_rejects_invalid_ratio_and_wage(client: TestClient, db, save) -> None:
    raw = _csv(
        "R1,2026-07-01,completed,permanent,A,B,1,EUR,P1,12k,10",
        "R2,2026-07-01,completed,permanent,A,B,1,EUR,P2,1000,150",
    )
    response = client.post(
        f"/api/v1/imports/transfers/history?save_id={save.id}",
        files={"file": ("bad-ratios.csv", raw, "text/csv")},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["imported"] == 0
    codes = {error["code"] for error in body["errors"]}
    assert {"invalid_wage_contribution", "invalid_sell_on"} <= codes


def _club(db, save, name: str) -> Club:
    uid = "club-" + name.lower().replace(" ", "-")
    club = db.scalar(select(Club).where(Club.fm_save_id == save.id, Club.uid == uid))
    if club is None:
        club = Club(fm_save_id=save.id, uid=uid, name=name)
        db.add(club)
        db.commit()
    return club


def _instance(db, save, uid: str) -> PlayerInstance:
    player = Player(full_name=f"P {uid}", normalized_name=f"p-{uid.lower()}")
    db.add(player)
    db.commit()
    instance = PlayerInstance(player_id=player.id, fm_save_id=save.id, save_local_uid=uid)
    db.add(instance)
    db.commit()
    return instance


def _buy(db, save, instance, *, fee=10_000_000, loan_fee=None, transfer_type="permanent") -> Transfer:
    seller = _club(db, save, "Seller X")
    buyer = _club(db, save, "Buyer X")
    row = Transfer(
        fm_save_id=save.id,
        source_record_id=f"X-{instance.id}-{transfer_type}",
        player_instance_id=instance.id,
        player_name="P X",
        from_club_id=seller.id,
        to_club_id=buyer.id,
        transfer_type=transfer_type,
        status="completed",
        transfer_date=date(2026, 7, 1),
        currency="EUR",
        base_fee=fee,
        effective_fee=fee,
        loan_fee=loan_fee,
        source="manual",
    )
    db.add(row)
    db.commit()
    return row


def _sell(db, save, instance, buy, *, fee=20_000_000) -> Transfer:
    row = Transfer(
        fm_save_id=save.id,
        source_record_id=f"S-{instance.id}",
        player_instance_id=instance.id,
        player_name="P X",
        from_club_id=buy.to_club_id,
        to_club_id=buy.from_club_id,
        transfer_type="permanent",
        status="completed",
        transfer_date=date(2027, 1, 1),
        currency="EUR",
        effective_fee=fee,
        source="manual",
    )
    db.add(row)
    db.commit()
    return row


def test_unknown_addon_status_blocks_realized_profit(client: TestClient, db, save) -> None:
    instance = _instance(db, save, "A1")
    buy = _buy(db, save, instance)
    _sell(db, save, instance, buy)
    db.add(TransferFeeComponent(transfer_id=buy.id, component_type="addon", amount=2_000_000, status="mystery"))
    db.commit()
    body = transfer_roi(db, buy.id)
    assert body["buy"]["cash_cost_complete"] is False
    assert body["cash"]["realized_profit"] is None
    assert "不完整" in body["cash"]["realized_note"]


def test_lower_bound_and_complete_cost_are_distinct(client: TestClient, db, save) -> None:
    instance = _instance(db, save, "A2")
    buy = _buy(db, save, instance)
    db.add(TransferFeeComponent(transfer_id=buy.id, component_type="addon", amount=2_000_000, status="paid"))
    db.add(TransferFeeComponent(transfer_id=buy.id, component_type="addon", amount=3_000_000, status="pending"))
    db.add(TransferFeeComponent(transfer_id=buy.id, component_type="addon", amount=None, status="paid"))
    db.commit()
    body = transfer_roi(db, buy.id)
    assert body["buy"]["cash_cost"] == 12_000_000
    assert body["buy"]["cash_cost_lower_bound"] == 12_000_000
    assert body["buy"]["cash_cost_complete"] is False, "金额缺失的附加条款让成本不完整"


def test_loan_fee_is_cash_cost_and_base_fee_ignored(client: TestClient, db, save) -> None:
    instance = _instance(db, save, "A3")
    buy = _buy(db, save, instance, fee=50_000_000, loan_fee=1_000_000, transfer_type="loan")
    body = transfer_roi(db, buy.id)
    assert body["buy"]["is_loan"] is True
    assert body["buy"]["cash_cost"] == 1_000_000, "租借按租借费，不按标称转会费"
    assert body["buy"]["loan_fee"] == 1_000_000


def test_sell_on_clause_is_not_income_without_trigger(client: TestClient, db, save) -> None:
    instance = _instance(db, save, "A4")
    buy = _buy(db, save, instance, fee=10_000_000)
    buy.sell_on_clause_pct = 20
    db.commit()
    _sell(db, save, instance, buy, fee=20_000_000)
    body = transfer_roi(db, buy.id)
    assert body["cash"]["realized_profit"] == 10_000_000, "只算现金，不把二转比例折成收入"
    assert "不把比例折算成收入" in body["buy"]["sell_on_note"]
