"""SM-022：历史转会金额解析与币种标准化。"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.ingestion.amounts import parse_amount
from app.models import Club, Transfer

def _club(db, save, name: str) -> Club:
    uid = "club-" + name.lower().replace(" ", "-")
    club = db.scalar(select(Club).where(Club.fm_save_id == save.id, Club.uid == uid))
    if club is None:
        club = Club(fm_save_id=save.id, uid=uid, name=name)
        db.add(club)
        db.commit()
    return club


def _imported_transfer(db, save, *, record: str, amount: str, currency: str, to_club: Club, status: str = "completed") -> Transfer:
    cls = _club(db, save, "From " + record)
    row = Transfer(
        fm_save_id=save.id,
        source_record_id=record,
        player_name=f"P {record}",
        from_club_id=cls.id,
        to_club_id=to_club.id,
        transfer_type="permanent",
        status=status,
        transfer_date=date(2026, 7, 1),
        currency=currency,
        base_fee=float(amount),
        effective_fee=float(amount),
        source="manual",
    )
    db.add(row)
    db.commit()
    return row


# ---------------------------------------------------------------- SM-022


@pytest.mark.parametrize(
    ("raw", "expected", "currency"),
    [
        ("2500000", 2_500_000, "EUR"),
        ("2,500,000", 2_500_000, "EUR"),
        ("£2.5m", 2_500_000, "GBP"),
        ("€12.5M", 12_500_000, "EUR"),
        ("500K", 500_000, "EUR"),
        ("1.2 million", 1_200_000, "EUR"),
        ("150万", 1_500_000, "EUR"),
        ("1200万", 12_000_000, "EUR"),
    ],
)
def test_amount_formats(raw: str, expected: float, currency: str) -> None:
    parsed = parse_amount(raw, "EUR")
    assert parsed.ok, parsed.error
    assert parsed.amount == pytest.approx(expected)
    assert parsed.currency == currency


def test_amount_rejects_unknown_and_missing_currency() -> None:
    assert parse_amount("abc", "EUR").error
    assert parse_amount("2.5M", None).error, "没有币种时必须拒绝，不能默认 EUR"
    assert parse_amount("2.5M", "XYZ").error


def _csv(rows: list[str], header: str | None = None) -> bytes:
    base = header or (
        "player_name,transfer_date,status,transfer_type,from_club,to_club,base_fee,currency,source_record_id\n"
    )
    return (base + "\n".join(rows) + "\n").encode("utf-8")


def test_import_keeps_raw_and_currency(client: TestClient, db, save) -> None:
    response = client.post(
        f"/api/v1/imports/transfers/history?save_id={save.id}",
        files={"file": ("fees.csv", _csv(["Fee Player,2026-07-01,completed,permanent,Club A,Club B,£2.5m,GBP,F1"]), "text/csv")},
    )
    assert response.status_code == 201, response.text
    assert response.json()["imported"] == 1
    transfer = db.scalars(select(Transfer).where(Transfer.source_record_id == "F1")).one()
    assert transfer.base_fee == pytest.approx(2_500_000)
    assert transfer.currency == "GBP"
    assert transfer.fee_raw == "£2.5m"
    assert transfer.currency_original == "GBP"


def test_import_rejects_unsupported_amount_with_row(client: TestClient, db, save) -> None:
    response = client.post(
        f"/api/v1/imports/transfers/history?save_id={save.id}",
        files={"file": ("bad.csv", _csv(["Bad Fee,2026-07-01,completed,permanent,A,B,not-a-number,EUR,B1"]), "text/csv")},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["imported"] == 0
    assert body["errors"][0]["code"] == "invalid_amount"
    assert body["errors"][0]["row"] == 1


def test_import_rejects_missing_currency_for_bare_number(client: TestClient, db, save) -> None:
    header = "player_name,transfer_date,status,transfer_type,from_club,to_club,base_fee,source_record_id\n"
    response = client.post(
        f"/api/v1/imports/transfers/history?save_id={save.id}",
        files={"file": ("noc.csv", _csv(["No Currency,2026-07-01,completed,permanent,A,B,2500000,N1"], header), "text/csv")},
    )
    assert response.status_code == 201
    assert response.json()["imported"] == 0
    assert response.json()["errors"][0]["code"] == "missing_currency"


def test_mixed_currency_row_is_rejected(client: TestClient, db, save) -> None:
    rows = ["Mixed,2026-07-01,completed,permanent,A,B,£2.5m,EUR,M1"]
    response = client.post(
        f"/api/v1/imports/transfers/history?save_id={save.id}",
        files={"file": ("mixed.csv", _csv(rows), "text/csv")},
    )
    assert response.status_code == 201
    assert response.json()["imported"] == 0
    assert response.json()["errors"][0]["code"] == "mixed_currency"


