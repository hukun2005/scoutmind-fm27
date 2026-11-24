"""SM-067：游戏日期来源、可信度与倒退保护。"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CaptureRun

PREFIX = "/api/v1"


def _post(client: TestClient, **body) -> dict:
    response = client.post(f"{PREFIX}/captures", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_date_provenance_round_trips(client: TestClient) -> None:
    row = _post(
        client,
        game_date="2026-07-28",
        reader_version="0.1.0",
        status="completed",
        date_source="game_memory",
        date_confidence="verified",
        date_read_status="detected",
    )
    assert row["game_date"] == "2026-07-28"
    assert row["date_source"] == "game_memory"
    assert row["date_confidence"] == "verified"
    assert row["date_read_status"] == "detected"

    listed = client.get(f"{PREFIX}/captures").json()
    assert listed["items"][0]["date_confidence"] == "verified"


def test_verified_date_requires_a_source(client: TestClient) -> None:
    response = client.post(
        f"{PREFIX}/captures",
        json={"game_date": "2026-07-28", "status": "completed", "date_confidence": "verified"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "verified_date_without_source"


def test_unknown_values_are_rejected(client: TestClient) -> None:
    for body, code in (
        ({"date_source": "vibes"}, "invalid_date_source"),
        ({"date_confidence": "certain"}, "invalid_date_confidence"),
        ({"date_read_status": "maybe"}, "invalid_date_read_status"),
    ):
        response = client.post(f"{PREFIX}/captures", json={"status": "monitoring", **body})
        assert response.status_code == 422, body
        assert response.json()["error"]["code"] == code


def test_missing_date_is_marked_unknown_not_verified(client: TestClient) -> None:
    row = _post(client, status="monitoring", reader_version="0.1.0")
    assert row["game_date"] is None
    assert row["date_source"] == "unknown"
    assert row["date_confidence"] == "unknown"
    assert row["date_read_status"] == "unavailable"


def test_date_regression_is_flagged_not_silently_accepted(client: TestClient) -> None:
    _post(
        client,
        game_date="2026-08-10",
        reader_version="0.1.0",
        status="completed",
        date_source="game_memory",
        date_confidence="verified",
        date_read_status="detected",
    )
    older = _post(
        client,
        game_date="2026-07-01",
        reader_version="0.1.0",
        status="date_detected",
        date_source="reader_date_probe",
        date_confidence="verified",
        date_read_status="detected",
    )
    assert older["date_read_status"] == "regressed"
    assert older["date_confidence"] == "unverified", "倒退的日期不能被标成 verified"


def test_same_scope_and_date_updates_instead_of_duplicating(client: TestClient, db: Session) -> None:
    first = _post(client, game_date="2026-07-28", reader_version="0.1.0", status="scanning", scan_scope="players")
    second = _post(client, game_date="2026-07-28", reader_version="0.1.0", status="completed", scan_scope="players")
    assert first["id"] == second["id"]
    assert second["status"] == "completed"
    assert db.scalar(select(func.count()).select_from(CaptureRun)) == 1

    supplemental = _post(
        client,
        game_date="2026-07-28",
        reader_version="0.2.0",
        status="completed",
        scan_scope="players",
        revision=1,
        supplemental=True,
    )
    assert supplemental["id"] != first["id"]
    assert supplemental["supplemental"] is True
    assert db.scalar(select(func.count()).select_from(CaptureRun)) == 2
