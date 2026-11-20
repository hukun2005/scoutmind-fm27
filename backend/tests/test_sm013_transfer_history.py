"""SM-013：历史转会数据管道测试。"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.ingestion.transfer_history import TRANSFER_STATUSES, TRANSFER_TYPES
from app.models import Transfer, TransferFeeComponent, TransferImportRun, TransferSource


CSV_HEADER = (
    "player_name,transfer_date,status,transfer_type,from_club,to_club,base_fee,add_on_fee,"
    "loan_fee,sell_on_pct,currency,source_record_id,addon_status\n"
)


def _csv(*rows: str) -> bytes:
    return (CSV_HEADER + "\n".join(rows) + "\n").encode("utf-8")


def _post_csv(client: TestClient, save_id: int, raw: bytes, *, name: str = "history.csv"):
    return client.post(
        f"/api/v1/imports/transfers/history?save_id={save_id}",
        files={"file": (name, raw, "text/csv")},
    )


def test_status_and_type_domains_are_explicit() -> None:
    assert "completed" in TRANSFER_STATUSES and "agreed" in TRANSFER_STATUSES
    assert "unknown" in TRANSFER_STATUSES
    assert "loan_with_option" in TRANSFER_TYPES and "buyback" in TRANSFER_TYPES


def test_import_mixed_statuses_and_types(client: TestClient, db, save) -> None:
    raw = _csv(
        "A Player,2026-07-01,completed,permanent,Club A,Club B,10000000,1000000,,10,EUR,T1,paid",
        "B Player,2026-07-02,completed,loan,Club A,Club C,,,500000,0,EUR,T2,",
        "C Player,2026-07-03,agreed,permanent,Club A,Club D,20000000,2000000,,0,EUR,T3,pending",
        "D Player,2026-07-04,cancelled,permanent,Club A,Club E,5000000,,,0,EUR,T4,",
        "E Player,2026-07-05,pending,loan_with_option,Club A,Club F,,,100000,0,EUR,T5,",
        "F Player,2026-07-06,completed,free_transfer,Club B,Club A,0,,,0,EUR,T6,",
    )
    response = _post_csv(client, save.id, raw)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["imported"] == 6
    assert body["status_counts"]["completed"] == 3
    assert body["status_counts"]["agreed"] == 1
    assert body["status_counts"]["cancelled"] == 1
    assert body["loan_rows"] == 2
    assert body["addons"]["paid"] == 1
    assert body["addons"]["pending"] == 1
    assert body["transfer_history_available"] is True

    completed = db.scalars(select(Transfer).where(Transfer.status == "completed")).all()
    assert len(completed) == 3
    paid = next(item for item in completed if item.source_record_id == "T1")
    assert paid.effective_fee == 11_000_000, "已支付附加条款才能计入成交金额"
    agreed = db.scalars(select(Transfer).where(Transfer.status == "agreed")).one()
    assert agreed.effective_fee == 20_000_000, "agreed 的成交金额只记录，不等于支出"


def test_unknown_status_is_rejected_not_completed(client: TestClient, db, save) -> None:
    raw = _csv(
        "X Player,2026-07-01,unknown,permanent,Club A,Club B,1,,,0,EUR,X1,",
        "Y Player,2026-07-01,completed,permanent,Club A,Club B,1,,,0,EUR,Y1,",
    )
    response = _post_csv(client, save.id, raw)
    assert response.status_code == 201
    body = response.json()
    assert body["imported"] == 1
    assert body["rejected"] == 1
    assert body["errors"][0]["code"] == "unknown_status"
    assert db.scalar(select(Transfer).where(Transfer.source_record_id == "X1")) is None


def test_duplicate_import_is_idempotent(client: TestClient, db, save) -> None:
    raw = _csv("Dup Player,2026-07-01,completed,permanent,Club A,Club B,1,,,0,EUR,D1,")
    first = _post_csv(client, save.id, raw).json()
    second = _post_csv(client, save.id, raw).json()
    assert first["imported"] == 1
    assert second["imported"] == 0
    assert second["duplicates"] == 1
    assert db.scalar(select(Transfer).where(Transfer.source_record_id == "D1")) is not None


def test_natural_key_duplicate_across_sources(client: TestClient, db, save) -> None:
    first = _csv("Same Player,2026-07-01,completed,permanent,Club A,Club B,1,,,0,EUR,N1,")
    second = _csv("Same Player,2026-07-01,completed,permanent,Club A,Club B,1,,,0,EUR,N2,")
    assert _post_csv(client, save.id, first, name="one.csv").json()["imported"] == 1
    body = _post_csv(client, save.id, second, name="two.csv").json()
    assert body["imported"] == 0
    assert body["duplicates"] == 1


def test_missing_required_fields_are_reported(client: TestClient, db, save) -> None:
    raw = _csv(
        ",2026-07-01,completed,permanent,Club A,Club B,1,,,0,EUR,M1,",
        "No Date,,completed,permanent,Club A,Club B,1,,,0,EUR,M2,",
        "No To,2026-07-01,completed,permanent,Club A,,1,,,0,EUR,M3,",
        "Bad Type,2026-07-01,completed,weird,Club A,Club B,1,,,0,EUR,M4,",
    )
    body = _post_csv(client, save.id, raw).json()
    assert body["imported"] == 0
    codes = {error["code"] for error in body["errors"]}
    assert {"missing_player", "invalid_date", "missing_to_club", "invalid_type"} <= codes


def test_import_run_and_source_are_recorded(client: TestClient, db, save) -> None:
    raw = _csv("R Player,2026-07-01,completed,permanent,Club A,Club B,1,,,0,EUR,R1,")
    body = _post_csv(client, save.id, raw).json()
    run = db.get(TransferImportRun, body["batch_id"])
    assert run is not None and run.imported == 1
    assert run.content_sha256 and len(run.content_sha256) == 64
    source = db.get(TransferSource, run.source_id)
    assert source is not None and source.supports_history is True
    transfer = db.scalars(select(Transfer).where(Transfer.source_record_id == "R1")).one()
    assert transfer.raw_payload_json, "原始行必须留存"
    assert transfer.source_id == source.id


def test_coverage_reports_no_history_before_import(client: TestClient, save) -> None:
    response = client.get(f"/api/v1/transfers/coverage?save_id={save.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["transfer_history"]["available"] is False
    assert body["coverage_note"]


def test_json_import_supported(client: TestClient, db, save) -> None:
    payload = {
        "transfers": [
            {
                "player_name": "Json Player",
                "transfer_date": "2026-08-01",
                "status": "completed",
                "transfer_type": "permanent",
                "from_club": "Club A",
                "to_club": "Club B",
                "base_fee": "12,500,000",
                "currency": "EUR",
                "source_record_id": "J1",
            }
        ]
    }
    response = client.post(
        f"/api/v1/imports/transfers/history?save_id={save.id}",
        files={"file": ("history.json", json.dumps(payload).encode("utf-8"), "application/json")},
    )
    assert response.status_code == 201, response.text
    assert response.json()["imported"] == 1
    transfer = db.scalars(select(Transfer).where(Transfer.source_record_id == "J1")).one()
    assert transfer.base_fee == 12_500_000


def test_loan_fee_is_kept_separate_from_base_fee(client: TestClient, db, save) -> None:
    raw = _csv("Loan Player,2026-07-01,completed,loan_with_option,Club A,Club B,,,750000,0,EUR,L1,")
    _post_csv(client, save.id, raw)
    transfer = db.scalars(select(Transfer).where(Transfer.source_record_id == "L1")).one()
    assert transfer.loan_fee == 750_000
    assert transfer.base_fee is None
