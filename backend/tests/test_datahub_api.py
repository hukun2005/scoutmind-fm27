"""V3.3.0 data hub API: status panel, one-click import, repair audit query."""

from __future__ import annotations

import json

from app.models import ImportJob, PlayerSnapshot

from tests.helpers import player_row, scan_document


def _raw(document: dict) -> bytes:
    return json.dumps(document, ensure_ascii=False).encode("utf-8")


def test_status_returns_real_counts(client, save):
    response = client.get("/api/v1/data-hub/status")
    assert response.status_code == 200
    body = response.json()
    assert body["save"]["id"] == save.id
    assert set(body["records"]) >= {"players", "clubs", "transfers"}
    assert body["records"]["players"] == 0
    assert body["health"]["status"] == "empty"
    assert "game" in body and "detected" in body["game"]
    assert body["needs_confirmation"]["total"] == 0


def test_import_endpoint_returns_pass_and_audit(client, save):
    document = scan_document(players=[{**player_row("P1", "  A  "), "ca": "150"}])
    response = client.post(
        "/api/v1/data-hub/import",
        files={"file": ("scan.json", _raw(document), "application/json")},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "PASS"
    assert body["import"]["job_id"]
    assert body["counts"]["repaired"] >= 2
    assert body["verification"]["status"] == "PASS"
    assert body["detection"]["source"] == "scan_json"

    job_id = body["import"]["job_id"]
    repairs = client.get("/api/v1/data-hub/repairs", params={"import_job_id": job_id})
    assert repairs.status_code == 200
    assert repairs.json()["total"] >= 2
    assert all(item["decision"] == "repaired" for item in repairs.json()["items"])

    status = client.get("/api/v1/data-hub/status").json()
    assert status["records"]["players"] == 1
    assert status["last_sync"]["job_id"] == job_id


def test_import_endpoint_dry_run_writes_nothing(client, save, db):
    response = client.post(
        "/api/v1/data-hub/import",
        params={"dry_run": True},
        files={"file": ("scan.json", _raw(scan_document(players=[player_row("P1", "A")])), "application/json")},
    )
    assert response.status_code == 201
    assert response.json()["import"]["dry_run"] is True
    assert db.query(ImportJob).count() == 0
    assert db.query(PlayerSnapshot).count() == 0


def test_unsupported_version_returns_compatibility_error(client, save, db):
    document = scan_document(players=[player_row("P1", "A")])
    document["schema_version"] = "3.0"
    response = client.post(
        "/api/v1/data-hub/import",
        files={"file": ("scan.json", _raw(document), "application/json")},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unsupported_version"
    assert db.query(ImportJob).count() == 0


def test_unknown_file_is_rejected(client, save):
    response = client.post(
        "/api/v1/data-hub/import",
        files={"file": ("notes.txt", b"hello world", "text/plain")},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unsupported_format"


def test_repeated_import_is_reported_as_duplicate(client, save, db):
    raw = _raw(scan_document(players=[player_row("P1", "A")]))
    first = client.post("/api/v1/data-hub/import", files={"file": ("scan.json", raw, "application/json")})
    second = client.post("/api/v1/data-hub/import", files={"file": ("scan.json", raw, "application/json")})
    assert first.status_code == 201 and second.status_code == 201
    assert second.json()["import"]["duplicate"] is True
    assert db.query(PlayerSnapshot).count() == 1


def test_repairs_of_another_job_are_not_found(client, save):
    response = client.get("/api/v1/data-hub/repairs", params={"import_job_id": 999999})
    assert response.status_code == 404
