"""V3.2.7.3：统一导入入口的身份/会话/代次保护。

覆盖四个写入口（scan、transfers、squad-csv、captures）：
* 未进入协议的旧存档保持历史行为（无 gate，无上下文）；
* 一旦有 gate，缺少身份或会话一律 409，不产生"默认会话"；
* 有效上下文正常写入并记录 operation_id / save_generation；
* 切换后旧会话无法再写；跨存档会话被拒绝。
"""

from __future__ import annotations

from sqlalchemy import select

from app.models import FmSave, ImportJob, PlayerSnapshot, SaveIdentityAuditEvent, SaveSession

from tests.helpers import club_row, player_row, scan_document
from tests.write_safety_support import GAME_BUILD

FP_A = "si:v1:file:" + "a" * 64


def _code(response) -> str:
    return response.json()["error"]["code"]


def _register(client, save: FmSave, **overrides) -> dict:
    body = {
        "save_id": save.id,
        "fingerprint": FP_A,
        "fingerprint_version": 1,
        "identity_status": "verified",
        "confidence": "verified",
        "kind": "save_file",
        "game_build": GAME_BUILD,
        "plugin_version": "27.1.0+2505117",
        "ambiguous": False,
        "evidence": [
            {"type": "save_file_metadata", "source": "file", "hash": FP_A, "confidence": "medium"},
            {"type": "user_confirmed", "source": "user", "hash": FP_A, "confidence": "high"},
        ],
    }
    body.update(overrides)
    response = client.post("/api/v1/save-identities/register", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def _start(client, save: FmSave, identity_id: int, key: str = "k-1") -> dict:
    response = client.post(
        "/api/v1/save-sessions/start",
        json={
            "save_id": save.id,
            "identity_id": identity_id,
            "session_key": key,
            "process_id": 4242,
            "game_build": GAME_BUILD,
            "agent_id": "agent-test",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _scan_doc(scan_id: str) -> dict:
    return scan_document(
        scan_id=scan_id,
        players=[player_row("P1", "甲", club_uid="C1")],
        clubs=[club_row("C1", "Northbridge United", user_club=True), club_row("C2", "Kingsport City")],
    )


def test_legacy_save_without_gate_keeps_historical_path(client, save, db):
    response = client.post("/api/v1/imports/scan", json=_scan_doc("legacy-scan"))
    assert response.status_code in {200, 201}, response.text
    assert response.json()["status"] in {"succeeded", "partial"}
    db.expire_all()
    job = db.scalar(select(ImportJob).where(ImportJob.scan_id == "legacy-scan"))
    assert job.save_identity_id is None
    assert job.save_generation is None


def test_legacy_write_is_audited(client, save, db):
    response = client.post("/api/v1/imports/scan", json=_scan_doc("legacy-audit"))
    assert response.status_code in {200, 201}, response.text
    db.expire_all()
    event = db.scalar(
        select(SaveIdentityAuditEvent).where(SaveIdentityAuditEvent.event_type == "legacy_write_allowed")
    )
    assert event is not None
    assert event.fm_save_id == save.id


def test_legacy_writes_can_be_disabled_by_config(client, save, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "write_safety_legacy_allowed", False)
    response = client.post("/api/v1/imports/scan", json=_scan_doc("legacy-disabled"))
    assert response.status_code == 409
    assert _code(response) == "write_context_required"


def test_gated_save_rejects_import_without_context(client, save, db):
    identity = _register(client, save)
    _start(client, save, identity["identity_id"])

    response = client.post("/api/v1/imports/scan", json=_scan_doc("no-context"))
    assert response.status_code == 409
    assert _code(response) == "write_context_required"
    assert db.query(PlayerSnapshot).count() == 0

    identity_only = client.post(
        "/api/v1/imports/scan", params={"save_identity_id": identity["identity_id"]}, json=_scan_doc("identity-only")
    )
    assert identity_only.status_code == 409
    assert _code(identity_only) == "write_context_required"


def test_gated_save_accepts_valid_context_and_records_operation(client, save, db):
    identity = _register(client, save)
    session = _start(client, save, identity["identity_id"])

    response = client.post(
        "/api/v1/imports/scan",
        params={
            "save_identity_id": identity["identity_id"],
            "save_session_id": session["session_id"],
            "operation_id": "op-http-1",
        },
        json=_scan_doc("gated-ok"),
    )
    assert response.status_code in {200, 201}, response.text
    db.expire_all()
    job = db.scalar(select(ImportJob).where(ImportJob.scan_id == "gated-ok"))
    assert job.operation_id == "op-http-1"
    assert job.save_generation == 0
    assert job.save_session_id == session["session_id"]
    assert db.query(PlayerSnapshot).count() >= 1

    replay = client.post(
        "/api/v1/imports/scan",
        params={
            "save_identity_id": identity["identity_id"],
            "save_session_id": session["session_id"],
            "operation_id": "op-http-1",
        },
        json=_scan_doc("gated-ok"),
    )
    assert replay.status_code in {200, 201}, replay.text
    assert replay.json()["duplicate"] is True
    assert replay.json()["job_id"] == job.id

    # V3.2.7.4：同一 operation_id 但内容不同必须冲突，绝不能被当作“重复成功”。
    conflict = client.post(
        "/api/v1/imports/scan",
        params={
            "save_identity_id": identity["identity_id"],
            "save_session_id": session["session_id"],
            "operation_id": "op-http-1",
        },
        json=_scan_doc("gated-ok-replay"),
    )
    assert conflict.status_code == 409, conflict.text
    assert _code(conflict) == "operation_conflict"
    db.expire_all()
    assert db.query(PlayerSnapshot).count() >= 1


def test_other_import_entrypoints_require_context(client, save):
    identity = _register(client, save)
    _start(client, save, identity["identity_id"])

    transfers = client.post(
        "/api/v1/imports/transfers",
        json={"schema_version": "1.0", "scan": {"scan_id": "t-1"}, "transfers": []},
    )
    assert transfers.status_code == 409, transfers.text
    assert _code(transfers) == "write_context_required"

    squad = client.post(
        "/api/v1/imports/squad-csv",
        content=b"name,ca,pa\nX,100,120\n",
        headers={"content-type": "text/csv"},
    )
    assert squad.status_code == 409, squad.text
    assert _code(squad) == "write_context_required"

    capture = client.post(
        "/api/v1/captures",
        json={"reader_version": "27.1.0", "game_build": GAME_BUILD, "scan_scope": "players", "status": "scanning"},
    )
    assert capture.status_code == 409, capture.text
    assert _code(capture) == "write_context_required"


def test_import_with_session_of_other_save_is_rejected(client, save, db):
    identity = _register(client, save)
    session = _start(client, save, identity["identity_id"])

    other_save = FmSave(user_id=save.user_id, name="另一个存档", game_version="27.0", game_build=GAME_BUILD, is_active=False)
    db.add(other_save)
    db.commit()

    response = client.post(
        "/api/v1/imports/scan",
        params={
            "save_id": other_save.id,
            "save_identity_id": identity["identity_id"],
            "save_session_id": session["session_id"],
            "operation_id": "op-cross-save",
        },
        json=_scan_doc("cross-save"),
    )
    assert response.status_code == 409, response.text
    assert _code(response) == "save_context_mismatch"


def test_after_switch_old_context_cannot_import(client, save, db):
    identity = _register(client, save)
    session = _start(client, save, identity["identity_id"])

    switched = client.post(
        f"/api/v1/save-sessions/{session['session_id']}/switch", json={"reason": "save_switch"}
    )
    assert switched.status_code == 200
    assert switched.json()["generation"] == 1

    response = client.post(
        "/api/v1/imports/scan",
        params={
            "save_identity_id": identity["identity_id"],
            "save_session_id": session["session_id"],
            "operation_id": "op-old-session",
        },
        json=_scan_doc("old-session"),
    )
    assert response.status_code == 409, response.text
    assert _code(response) in {"write_session_epoch_stale", "save_session_invalidated"}
    assert db.query(PlayerSnapshot).count() == 0

    # 旧会话也不能靠心跳"复活"。
    heartbeat = client.post(
        f"/api/v1/save-sessions/{session['session_id']}/heartbeat",
        json={"identity_id": identity["identity_id"], "game_build": GAME_BUILD},
    )
    assert heartbeat.status_code == 409


def test_new_session_after_switch_can_write(client, save, db):
    identity = _register(client, save)
    first = _start(client, save, identity["identity_id"], key="k-first")
    client.post(f"/api/v1/save-sessions/{first['session_id']}/switch", json={"reason": "restart"})

    second = _start(client, save, identity["identity_id"], key="k-second")
    assert second["session_epoch"] == 1

    response = client.post(
        "/api/v1/imports/scan",
        params={
            "save_identity_id": identity["identity_id"],
            "save_session_id": second["session_id"],
            "operation_id": "op-new-session",
        },
        json=_scan_doc("new-session"),
    )
    assert response.status_code in {200, 201}, response.text
    db.expire_all()
    job = db.scalar(select(ImportJob).where(ImportJob.scan_id == "new-session"))
    assert job.save_generation == 1
    assert db.get(SaveSession, second["session_id"]).session_epoch == 1
