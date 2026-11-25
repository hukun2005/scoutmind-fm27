"""V3.2.7.2 Phase 2：存档身份注册、验证、会话生命周期与审计。

真实 HTTP（FastAPI TestClient + SQLite）覆盖：
* 客户端声明不能直接变成 verified，必须按证据封顶；
* 重复注册幂等，不重复写证据；
* 同存档不同指纹进入冲突流程；
* 会话 start/heartbeat/end/invalidate 与心跳过期；
* 采集 PATCH 的上下文校验；
* 审计事件不可覆盖。
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.models import FmSave, SaveEvidence, SaveIdentity, SaveIdentityAuditEvent, SaveIdentityConflict, SaveSession
from app.utils import utcnow

FP_A = "si:v1:file:" + "a" * 64
FP_B = "si:v1:file:" + "b" * 64
BUILD = "26620374"


def _metadata_evidence(sha: str = FP_A) -> list[dict]:
    return [
        {
            "type": "save_file_metadata",
            "source": "file",
            "hash": sha,
            "version": "31434197",
            "confidence": "medium",
            "observed_at": "2026-11-25T00:00:00Z",
        }
    ]


def _register(client, save: FmSave, **overrides) -> dict:
    body = {
        "save_id": save.id,
        "fingerprint": FP_A,
        "fingerprint_version": 1,
        "identity_status": "candidate",
        "confidence": "medium",
        "kind": "save_file",
        "game_build": BUILD,
        "plugin_version": "27.1.0+2505117",
        "ambiguous": False,
        "evidence": _metadata_evidence(),
    }
    body.update(overrides)
    response = client.post("/api/v1/save-identities/register", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def _code(response) -> str:
    return response.json()["error"]["code"]


def test_declared_verified_without_evidence_is_not_trusted(client, save):
    payload = _register(client, save, identity_status="verified", evidence=[])
    assert payload["identity_status"] == "unknown"
    assert payload["verified_at"] is None


def test_declared_verified_needs_user_confirmation(client, save):
    payload = _register(client, save, identity_status="verified")
    assert payload["identity_status"] == "candidate"
    assert payload["confidence"] == "medium"


def test_user_confirmed_secondary_evidence_verifies(client, save):
    payload = _register(
        client,
        save,
        identity_status="verified",
        evidence=_metadata_evidence()
        + [{"type": "user_confirmed", "source": "user", "hash": FP_A, "confidence": "high"}],
    )
    assert payload["identity_status"] == "verified"
    assert payload["verified_at"] is not None
    assert payload["evidence_level"] == "secondary"


def test_register_is_idempotent(client, save):
    first = _register(client, save)
    second = _register(client, save)
    assert first["identity_id"] == second["identity_id"]
    assert len(second["evidence"]) == 1


def test_unresolved_fingerprint_never_reaches_verified(client, save):
    payload = _register(
        client,
        save,
        fingerprint="si:v1:unresolved:26620374",
        identity_status="verified",
        evidence=_metadata_evidence("unresolved")
        + [{"type": "user_confirmed", "source": "user", "hash": "unresolved", "confidence": "high"}],
    )
    assert payload["identity_status"] == "discovered"


def test_different_fingerprint_enters_conflict(client, save, db):
    verified = _register(
        client,
        save,
        identity_status="verified",
        evidence=_metadata_evidence()
        + [{"type": "user_confirmed", "source": "user", "hash": FP_A, "confidence": "high"}],
    )
    assert verified["identity_status"] == "verified"

    other = _register(
        client,
        save,
        fingerprint=FP_B,
        identity_status="verified",
        evidence=_metadata_evidence(FP_B)
        + [{"type": "user_confirmed", "source": "user", "hash": FP_B, "confidence": "high"}],
    )
    assert other["identity_status"] == "conflict"

    db.expire_all()
    assert db.get(SaveIdentity, verified["identity_id"]).identity_status == "verified"
    conflict = db.query(SaveIdentityConflict).filter_by(status="open").one()
    assert conflict.conflicting_identity_id == other["identity_id"]
    event_types = [row.event_type for row in db.query(SaveIdentityAuditEvent).all()]
    assert "identity_conflict" in event_types


def test_verify_requires_matching_fingerprint_and_evidence(client, save):
    candidate = _register(client, save)

    wrong = client.post(
        f"/api/v1/save-identities/{candidate['identity_id']}/verify",
        json={"confirmed_fingerprint": FP_B, "basis": "用户确认", "actor": "tester"},
    )
    assert wrong.status_code == 409
    assert _code(wrong) == "save_context_mismatch"

    no_evidence = _register(client, save, fingerprint=FP_B, evidence=[])
    blocked = client.post(
        f"/api/v1/save-identities/{no_evidence['identity_id']}/verify",
        json={"confirmed_fingerprint": FP_B, "basis": "用户确认", "actor": "tester"},
    )
    assert blocked.status_code == 409
    assert _code(blocked) == "save_identity_unverified"


def test_verify_upgrades_candidate_and_audits(client, save, db):
    candidate = _register(client, save)
    response = client.post(
        f"/api/v1/save-identities/{candidate['identity_id']}/verify",
        json={"confirmed_fingerprint": FP_A, "basis": "用户确认界面生涯一致", "actor": "tester"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["identity_status"] == "verified"
    assert payload["verified_by"] == "tester"

    audit = client.get("/api/v1/save-identity-audit", params={"identity_id": candidate["identity_id"]})
    assert audit.status_code == 200
    events = audit.json()["items"]
    assert events[0]["event_type"] == "identity_verified"
    assert events[0]["new_status"] == "verified"
    assert events[0]["evidence_summary"]["basis"] == "用户确认界面生涯一致"


def test_verify_resolves_conflict(client, save, db):
    _register(
        client,
        save,
        identity_status="verified",
        evidence=_metadata_evidence()
        + [{"type": "user_confirmed", "source": "user", "hash": FP_A, "confidence": "high"}],
    )
    conflicted = _register(
        client,
        save,
        fingerprint=FP_B,
        identity_status="verified",
        evidence=_metadata_evidence(FP_B)
        + [{"type": "user_confirmed", "source": "user", "hash": FP_B, "confidence": "high"}],
    )
    response = client.post(
        f"/api/v1/save-identities/{conflicted['identity_id']}/verify",
        json={"confirmed_fingerprint": FP_B, "basis": "确认是新存档", "actor": "tester"},
    )
    assert response.status_code == 200, response.text
    db.expire_all()
    conflict = db.query(SaveIdentityConflict).filter_by(conflicting_identity_id=conflicted["identity_id"]).one()
    assert conflict.status == "resolved"
    assert conflict.resolution == "user_confirmed"


def test_register_rejects_foreign_save(client, save, db):
    other = FmSave(user_id=save.user_id, name="另一个存档", is_active=False)
    db.add(other)
    db.commit()
    response = client.post(
        "/api/v1/save-identities/register",
        json={
            "save_id": other.id,
            "fingerprint": FP_A,
            "identity_status": "candidate",
            "evidence": _metadata_evidence(),
        },
    )
    assert response.status_code == 409
    assert _code(response) == "save_context_mismatch"


def _verified_identity(client, save) -> dict:
    return _register(
        client,
        save,
        identity_status="verified",
        evidence=_metadata_evidence()
        + [{"type": "user_confirmed", "source": "user", "hash": FP_A, "confidence": "high"}],
    )


def _start(client, save, identity_id: int, key: str = "66972:2026-11-24T15:57:31:26620374") -> dict:
    response = client.post(
        "/api/v1/save-sessions/start",
        json={
            "save_id": save.id,
            "identity_id": identity_id,
            "session_key": key,
            "process_id": 66972,
            "game_build": BUILD,
            "agent_id": "agent-test",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_session_start_requires_verified_identity(client, save):
    candidate = _register(client, save)
    blocked = _start(client, save, candidate["identity_id"])
    assert blocked["status"] == "created"

    verified = _verified_identity(client, save)
    allowed = _start(client, save, verified["identity_id"], key="70001:2026-11-25T00:00:00:26620374")
    assert allowed["status"] == "verified"
    assert allowed["last_heartbeat_at"] is not None


def test_session_start_is_idempotent(client, save):
    identity = _verified_identity(client, save)
    first = _start(client, save, identity["identity_id"])
    second = _start(client, save, identity["identity_id"])
    assert first["session_id"] == second["session_id"]


def test_session_start_rejects_foreign_identity(client, save, db):
    other = FmSave(user_id=save.user_id, name="另一个存档", is_active=False)
    db.add(other)
    db.commit()
    identity = _verified_identity(client, save)
    response = client.post(
        "/api/v1/save-sessions/start",
        json={"save_id": other.id, "identity_id": identity["identity_id"], "session_key": "1:x:26620374"},
    )
    assert response.status_code == 409
    assert _code(response) == "save_context_mismatch"


def test_heartbeat_success(client, save):
    identity = _verified_identity(client, save)
    session = _start(client, save, identity["identity_id"])
    response = client.post(
        f"/api/v1/save-sessions/{session['session_id']}/heartbeat",
        json={"identity_id": identity["identity_id"], "fingerprint": FP_A, "game_build": BUILD},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "verified"


def test_heartbeat_fingerprint_mismatch_invalidates(client, save, db):
    identity = _verified_identity(client, save)
    session = _start(client, save, identity["identity_id"])
    response = client.post(
        f"/api/v1/save-sessions/{session['session_id']}/heartbeat",
        json={"identity_id": identity["identity_id"], "fingerprint": FP_B},
    )
    assert response.status_code == 409
    assert _code(response) == "save_context_mismatch"
    db.expire_all()
    row = db.get(SaveSession, session["session_id"])
    assert row.session_status == "invalidated"
    assert row.invalidated_reason == "fingerprint_mismatch"

    again = client.post(
        f"/api/v1/save-sessions/{session['session_id']}/heartbeat",
        json={"identity_id": identity["identity_id"], "fingerprint": FP_A},
    )
    assert again.status_code == 409
    assert _code(again) == "save_session_invalidated"


def test_heartbeat_expiry_invalidates(client, save, db):
    identity = _verified_identity(client, save)
    session = _start(client, save, identity["identity_id"])
    db.expire_all()
    row = db.get(SaveSession, session["session_id"])
    row.last_heartbeat_at = utcnow() - timedelta(minutes=10)
    db.commit()

    response = client.post(
        f"/api/v1/save-sessions/{session['session_id']}/heartbeat",
        json={"identity_id": identity["identity_id"], "fingerprint": FP_A},
    )
    assert response.status_code == 409
    assert _code(response) == "save_session_invalidated"
    db.expire_all()
    assert db.get(SaveSession, session["session_id"]).invalidated_reason == "expired"


def test_session_end_and_invalidate(client, save, db):
    identity = _verified_identity(client, save)
    session = _start(client, save, identity["identity_id"])
    ended = client.post(f"/api/v1/save-sessions/{session['session_id']}/end")
    assert ended.status_code == 200
    assert ended.json()["status"] == "closed"

    second = _start(client, save, identity["identity_id"], key="70000:2026-11-25T00:00:00:26620374")
    invalid = client.post(
        f"/api/v1/save-sessions/{second['session_id']}/invalidate",
        json={"reason": "save_switched"},
    )
    assert invalid.status_code == 200
    assert invalid.json()["status"] == "invalidated"
    assert invalid.json()["invalidated_reason"] == "save_switched"


def test_capture_gate_reports_blockers(client, save):
    candidate = _register(client, save)
    detail = client.get(f"/api/v1/save-identities/{candidate['identity_id']}")
    assert detail.status_code == 200
    assert detail.json()["capture_allowed"] is False
    assert detail.json()["blockers"]

    identity = _verified_identity(client, save)
    session = _start(client, save, identity["identity_id"])
    allowed = client.get(f"/api/v1/save-identities/{identity['identity_id']}")
    assert allowed.json()["capture_allowed"] is True
    assert allowed.json()["blockers"] == []

    client.post(f"/api/v1/save-sessions/{session['session_id']}/invalidate", json={"reason": "game_closed"})
    blocked = client.get(f"/api/v1/save-identities/{identity['identity_id']}")
    assert blocked.json()["capture_allowed"] is False


def test_capture_patch_checks_context(client, save, db):
    identity = _verified_identity(client, save)
    session = _start(client, save, identity["identity_id"])
    created = client.post(
        "/api/v1/captures",
        params={"save_identity_id": identity["identity_id"], "save_session_id": session["session_id"]},
        json={"reader_version": "27.1.0", "game_build": BUILD, "scan_scope": "players", "status": "scanning"},
    )
    assert created.status_code == 201, created.text
    capture_id = created.json()["id"]

    other = SaveIdentity(
        fm_save_id=save.id,
        identity_status="verified",
        identity_confidence="verified",
        identity_fingerprint=FP_B,
        identity_kind="save_file",
        game_build=BUILD,
    )
    db.add(other)
    db.commit()

    # V3.2.7.3：存档已有写入门，缺少会话不再降级为“仅身份”写入。
    missing_session = client.patch(
        f"/api/v1/captures/{capture_id}",
        params={"save_identity_id": identity["identity_id"]},
        json={"status": "completed"},
    )
    assert missing_session.status_code == 409
    assert _code(missing_session) == "write_context_required"

    mismatch = client.patch(
        f"/api/v1/captures/{capture_id}",
        params={"save_identity_id": other.id, "save_session_id": session["session_id"]},
        json={"status": "completed"},
    )
    assert mismatch.status_code == 409
    assert _code(mismatch) == "save_context_mismatch"

    ok = client.patch(
        f"/api/v1/captures/{capture_id}",
        params={"save_identity_id": identity["identity_id"], "save_session_id": session["session_id"]},
        json={"status": "completed"},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "completed"
    assert ok.json()["save_identity_id"] == identity["identity_id"]


def test_audit_events_are_immutable(db, save):
    event = SaveIdentityAuditEvent(fm_save_id=save.id, event_type="registered", actor="tester", occurred_at=utcnow())
    db.add(event)
    db.commit()
    event.event_type = "tampered"
    with pytest.raises(ValueError):
        db.commit()


def test_evidence_deduplication_in_db(client, save, db):
    _register(client, save)
    _register(client, save)
    db.expire_all()
    identity = db.query(SaveIdentity).one()
    assert db.query(SaveEvidence).filter_by(save_identity_id=identity.id).count() == 1
