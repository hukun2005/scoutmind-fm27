"""SM-061A：字段证据采样上传、去重与存档隔离。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.ingestion.importer import ScanImporter
from app.ingestion.protocol import ScanPayload
from app.models import FieldEvidenceSample, FmSave, PlayerInstance, User

from tests.helpers import player_row, scan_document


def _import_player(db, save, uid: str = "CAP1", name: str = "Capture One") -> PlayerInstance:
    payload = scan_document(scan_id=f"sm061a-{uid}", players=[player_row(uid, name, age=21, ca=120, pa=160)])
    ScanImporter(db).import_payload(save.id, ScanPayload.model_validate(payload))
    db.commit()
    return db.scalar(select(PlayerInstance).where(PlayerInstance.fm_save_id == save.id))


def _item(instance_id: int, **overrides) -> dict:
    item = {
        "player_instance_id": instance_id,
        "field_id": "CON_EXPIRY",
        "object_type": "contract",
        "raw_value": "0x1234",
        "expected_value": "2027-06-30",
        "game_build": "26620374",
        "plugin_version": "27.1.0+2505117",
        "layout_version": "FM27_1",
        "game_date": "2026-07-01",
        "observed_at": "2026-11-22T10:00:00Z",
        "evidence_source": "reader_capture",
        "validation_status": "Candidate",
        "simulated": False,
    }
    item.update(overrides)
    return item


def test_capture_and_idempotent_duplicate(client, db, save) -> None:
    instance = _import_player(db, save)
    response = client.post("/api/v1/field-evidence/captures", json={"items": [_item(instance.id)]})
    assert response.status_code == 201, response.text
    assert response.json() == {"saved": 1, "duplicates": 0, "total": 1}
    again = client.post("/api/v1/field-evidence/captures", json={"items": [_item(instance.id)]})
    assert again.json() == {"saved": 0, "duplicates": 1, "total": 1}
    db.expire_all()
    assert db.query(FieldEvidenceSample).count() == 1


def test_same_field_different_observation_is_independent(client, db, save) -> None:
    instance = _import_player(db, save)
    client.post("/api/v1/field-evidence/captures", json={"items": [_item(instance.id)]})
    response = client.post(
        "/api/v1/field-evidence/captures",
        json={"items": [_item(instance.id, observed_at="2026-11-22T11:00:00Z")]},
    )
    assert response.status_code == 201
    assert response.json()["saved"] == 1
    assert db.query(FieldEvidenceSample).count() == 2


def test_instance_uid_resolution_and_unknown_uid(client, db, save) -> None:
    instance = _import_player(db, save, uid="CAPUID")
    response = client.post(
        "/api/v1/field-evidence/captures",
        json={"items": [_item(0, player_instance_id=None, player_instance_uid="CAPUID")]},
    )
    assert response.status_code == 201, response.text
    unknown = client.post(
        "/api/v1/field-evidence/captures",
        json={"items": [_item(0, player_instance_id=None, player_instance_uid="MISSING")]},
    )
    assert unknown.status_code == 404


def test_foreign_instance_is_rejected_without_writes(client, db, save) -> None:
    other_user = User(username="sm061a-other", display_name="other")
    db.add(other_user)
    db.commit()
    other = FmSave(user_id=other_user.id, name="other", game_version="27.1", game_build="x", is_active=False)
    db.add(other)
    db.commit()
    foreign = _import_player(db, other, uid="FOREIGN")
    response = client.post("/api/v1/field-evidence/captures", json={"items": [_item(foreign.id)]})
    assert response.status_code == 404
    assert db.query(FieldEvidenceSample).count() == 0


def test_simulated_verified_is_rejected(client, db, save) -> None:
    instance = _import_player(db, save)
    response = client.post(
        "/api/v1/field-evidence/captures",
        json={"items": [_item(instance.id, simulated=True, validation_status="Verified")]},
    )
    assert response.status_code == 422
    assert db.query(FieldEvidenceSample).count() == 0


def test_duplicate_inside_batch_fails_whole_batch(client, db, save) -> None:
    instance = _import_player(db, save)
    response = client.post(
        "/api/v1/field-evidence/captures",
        json={"items": [_item(instance.id), _item(instance.id)]},
    )
    assert response.status_code == 422
    assert db.query(FieldEvidenceSample).count() == 0


def test_summary_counts_real_and_simulated(client, db, save) -> None:
    instance = _import_player(db, save)
    client.post(
        "/api/v1/field-evidence/captures",
        json={"items": [
            _item(instance.id, field_id="CON_EXPIRY"),
            _item(instance.id, field_id="PERO_COMMON_NAME", object_type="person",
                  observed_at="2026-11-22T12:00:00Z", simulated=True, validation_status="Candidate"),
            _item(instance.id, field_id="CON_EXPIRY", observed_at="2026-11-22T13:00:00Z",
                  simulated=True, validation_status="Pending"),
        ]},
    )
    summary = client.get("/api/v1/field-evidence/summary").json()
    assert summary["total"] == 3
    assert summary["fields"]["CON_EXPIRY"] == {"real": 1, "simulated": 1}
    assert summary["fields"]["PERO_COMMON_NAME"]["simulated"] == 1
