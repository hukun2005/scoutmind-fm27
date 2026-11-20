"""SM-011：Identity Resolution Center 后端测试。"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.ingestion.importer import ScanImporter
from app.ingestion.protocol import ScanPayload
from app.models import (
    IdentityConflict,
    IdentityConflictAction,
    IdentityMatch,
    Player,
    PlayerInstance,
    PlayerSnapshot,
    Transfer,
    User,
    FmSave,
)

from tests.helpers import player_row, scan_document


def _import(db, save_id: int, document: dict):
    payload = ScanPayload.model_validate(document)
    outcome = ScanImporter(db).import_payload(save_id, payload)
    db.commit()
    return outcome


def _make_conflict(db, save_id: int, uid: str = "C1") -> int:
    """构造一条真实冲突：先导入 A（有生日），再导入同 UID 且异名异生日。"""
    _import(db, save_id, scan_document(scan_id=f"{uid}-a", players=[player_row(uid, "Existing Person", age=20)]))
    _import(db, save_id, scan_document(scan_id=f"{uid}-b", players=[player_row(uid, "Incoming Person", age=35)]))
    conflict = db.scalars(select(IdentityConflict).where(IdentityConflict.save_local_uid == uid)).first()
    assert conflict is not None
    return conflict.id


def test_list_conflicts_with_filters(client: TestClient, db, save) -> None:
    conflict_id = _make_conflict(db, save.id)
    response = client.get("/api/v1/identity/conflicts")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["counts"]["open"] >= 1
    assert any(item["id"] == conflict_id for item in body["items"])
    item = next(item for item in body["items"] if item["id"] == conflict_id)
    assert item["suggestion"]["decision"] in {"same", "different", "defer"}
    assert item["existing"]["name"] and item["incoming"]["name"]

    filtered = client.get("/api/v1/identity/conflicts?reason=birth_date_mismatch")
    assert filtered.status_code == 200
    assert all(row["reason"] == "birth_date_mismatch" for row in filtered.json()["items"])

    paged = client.get("/api/v1/identity/conflicts?page=1&page_size=1")
    assert paged.json()["page_size"] == 1
    assert len(paged.json()["items"]) <= 1


def test_detail_contains_evidence_and_history(client: TestClient, db, save) -> None:
    conflict_id = _make_conflict(db, save.id, "C2")
    response = client.get(f"/api/v1/identity/conflicts/{conflict_id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["existing"]["player_id"]
    assert body["incoming"]["player_id"]
    assert body["existing"]["snapshot_count"] >= 1
    assert body["evidence"] is not None
    assert body["history"] == []


def test_merge_same_person_moves_instances_and_snapshots(client: TestClient, db, save) -> None:
    conflict_id = _make_conflict(db, save.id, "C3")
    conflict = db.get(IdentityConflict, conflict_id)
    existing_id, incoming_id = conflict.existing_player_id, conflict.incoming_player_id
    snapshots_before = db.scalar(select(func.count()).select_from(PlayerSnapshot))
    instances_before = db.scalar(select(func.count()).select_from(PlayerInstance))

    response = client.post(
        f"/api/v1/identity/conflicts/{conflict_id}/resolve",
        json={"decision": "same", "keep": "existing", "note": "确认同一人"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "resolved"
    assert body["merged"]["instances_moved"] >= 1

    db.expire_all()
    assert db.scalar(select(func.count()).select_from(PlayerSnapshot)) == snapshots_before, "快照不能丢"
    assert db.scalar(select(func.count()).select_from(PlayerInstance)) == instances_before, "实例不能丢"
    assert db.get(Player, incoming_id) is None or db.scalar(
        select(func.count()).select_from(PlayerInstance).where(PlayerInstance.player_id == incoming_id)
    ) == 0
    assert db.get(IdentityConflict, conflict_id).status == "resolved"
    audit = db.scalars(select(IdentityConflictAction).where(IdentityConflictAction.conflict_id == conflict_id)).all()
    assert len(audit) == 1
    assert audit[0].action == "same"
    assert audit[0].note == "确认同一人"


def test_merge_different_people_keeps_both(client: TestClient, db, save) -> None:
    conflict_id = _make_conflict(db, save.id, "C4")
    before = db.scalar(select(func.count()).select_from(Player))
    response = client.post(f"/api/v1/identity/conflicts/{conflict_id}/resolve", json={"decision": "different"})
    assert response.status_code == 200
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(Player)) == before, "确认不同人不得合并"
    conflict = db.get(IdentityConflict, conflict_id)
    assert conflict.status == "resolved" and conflict.resolution == "manual_distinct"


def test_defer_keeps_conflict_outstanding(client: TestClient, db, save) -> None:
    conflict_id = _make_conflict(db, save.id, "C5")
    response = client.post(f"/api/v1/identity/conflicts/{conflict_id}/resolve", json={"decision": "defer", "note": "以后再核对"})
    assert response.status_code == 200
    conflict = db.get(IdentityConflict, conflict_id)
    assert conflict.status == "deferred"
    deferred = client.get("/api/v1/identity/conflicts?status=deferred").json()
    assert any(item["id"] == conflict_id for item in deferred["items"])


def test_concurrent_resolution_is_rejected(client: TestClient, db, save) -> None:
    conflict_id = _make_conflict(db, save.id, "C6")
    first = client.post(f"/api/v1/identity/conflicts/{conflict_id}/resolve", json={"decision": "different"})
    assert first.status_code == 200
    second = client.post(f"/api/v1/identity/conflicts/{conflict_id}/resolve", json={"decision": "same"})
    assert second.status_code == 409, second.text
    assert second.json()["error"]["code"] == "conflict_already_resolved"


def test_cross_save_access_is_rejected(client: TestClient, db, save) -> None:
    other_user = User(username="other", display_name="别人")
    db.add(other_user)
    db.commit()
    foreign = FmSave(user_id=other_user.id, name="别人存档", game_version="27.1", game_build="x")
    db.add(foreign)
    db.commit()
    _make_conflict(db, foreign.id, "C7")
    foreign_conflict = db.scalars(select(IdentityConflict).where(IdentityConflict.save_local_uid == "C7")).first()

    list_response = client.get("/api/v1/identity/conflicts")
    assert all(item["id"] != foreign_conflict.id for item in list_response.json()["items"])

    detail = client.get(f"/api/v1/identity/conflicts/{foreign_conflict.id}")
    assert detail.status_code == 404
    resolve = client.post(f"/api/v1/identity/conflicts/{foreign_conflict.id}/resolve", json={"decision": "different"})
    assert resolve.status_code == 404


def test_audit_history_is_exposed(client: TestClient, db, save) -> None:
    conflict_id = _make_conflict(db, save.id, "C8")
    client.post(f"/api/v1/identity/conflicts/{conflict_id}/resolve", json={"decision": "defer", "note": "第一次"})
    detail = client.get(f"/api/v1/identity/conflicts/{conflict_id}").json()
    assert len(detail["history"]) == 1
    assert detail["history"][0]["action"] == "defer"
    assert detail["history"][0]["note"] == "第一次"
