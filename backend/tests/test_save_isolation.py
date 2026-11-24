"""V3.2.7 Phase 5：写接口的存档身份 / 会话隔离校验。"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.save_context import assert_job_context, build_final_guard, resolve_save_context
from app.models import FmSave, SaveIdentity, SaveSession

from tests.helpers import player_row, scan_document


def _identity(
    db,
    save_id: int,
    *,
    status: str = "verified",
    build: str = "26577676",
    fingerprint: str = "si:v1:file:sha256-test",
) -> SaveIdentity:
    identity = SaveIdentity(
        fm_save_id=save_id,
        identity_status=status,
        identity_confidence="verified" if status == "verified" else "medium",
        identity_fingerprint=fingerprint,
        identity_kind="save_file",
        game_build=build,
    )
    db.add(identity)
    db.commit()
    return identity


def _session(
    db,
    save_id: int,
    identity_id: int | None,
    *,
    status: str = "verified",
    build: str = "26577676",
    key: str = "4242:2026-11-24T10:00:00:26577676",
) -> SaveSession:
    session = SaveSession(
        fm_save_id=save_id,
        save_identity_id=identity_id,
        session_key=key,
        session_status=status,
        game_build=build,
        process_id=4242,
    )
    db.add(session)
    db.commit()
    return session


def _post_scan(client, save_id: int, query: str):
    document = scan_document(scan_id=f"iso-{uuid4().hex[:12]}", players=[player_row("P1", "Isolated")])
    files = {"file": ("scan.json", json.dumps(document).encode("utf-8"), "application/json")}
    return client.post(f"/api/v1/imports/scan?save_id={save_id}{query}", files=files)


def _error_code(response) -> str:
    return response.json()["error"]["code"]


def test_import_rejects_identity_of_another_save(client, db, save):
    other = FmSave(user_id=save.user_id, name="另一个存档", game_build="26577676")
    db.add(other)
    db.commit()
    foreign = _identity(db, other.id, fingerprint="si:v1:file:other")

    response = _post_scan(client, save.id, f"&save_identity_id={foreign.id}")

    assert response.status_code == 409
    assert _error_code(response) == "save_context_mismatch"


def test_import_rejects_unverified_identity(client, db, save):
    identity = _identity(db, save.id, status="candidate")

    response = _post_scan(client, save.id, f"&save_identity_id={identity.id}")

    assert response.status_code == 409
    assert _error_code(response) == "save_identity_unverified"


def test_import_rejects_conflicting_identity(client, db, save):
    identity = _identity(db, save.id, status="conflict")

    response = _post_scan(client, save.id, f"&save_identity_id={identity.id}")

    assert response.status_code == 409
    assert _error_code(response) == "save_context_mismatch"


def test_import_rejects_invalidated_old_session(client, db, save):
    identity = _identity(db, save.id)
    old = _session(db, save.id, identity.id, status="invalidated")

    response = _post_scan(client, save.id, f"&save_identity_id={identity.id}&save_session_id={old.id}")

    assert response.status_code == 409
    assert _error_code(response) == "save_session_invalidated"


def test_import_pauses_while_switching(client, db, save):
    identity = _identity(db, save.id)
    switching = _session(db, save.id, identity.id, status="switching")

    response = _post_scan(client, save.id, f"&save_identity_id={identity.id}&save_session_id={switching.id}")

    assert response.status_code == 409
    assert _error_code(response) == "save_switch_in_progress"


def test_import_rejects_session_bound_to_other_identity(client, db, save):
    identity = _identity(db, save.id, fingerprint="si:v1:file:a")
    other_identity = _identity(db, save.id, fingerprint="si:v1:file:b")
    bound_elsewhere = _session(db, save.id, other_identity.id, key="9999:2026-11-24T10:00:00:26577676")

    response = _post_scan(
        client,
        save.id,
        f"&save_identity_id={identity.id}&save_session_id={bound_elsewhere.id}",
    )

    assert response.status_code == 409
    assert _error_code(response) == "save_context_mismatch"


def test_import_rejects_session_build_mismatch(client, db, save):
    identity = _identity(db, save.id, build="26577676")
    stale_build = _session(db, save.id, identity.id, build="26620374")

    response = _post_scan(
        client, save.id, f"&save_identity_id={identity.id}&save_session_id={stale_build.id}"
    )

    assert response.status_code == 409
    assert _error_code(response) == "save_context_mismatch"


def test_import_records_verified_identity_and_session(client, db, save):
    identity = _identity(db, save.id)
    session = _session(db, save.id, identity.id)

    response = _post_scan(
        client, save.id, f"&save_identity_id={identity.id}&save_session_id={session.id}"
    )

    assert response.status_code == 201
    job_id = response.json()["job_id"]
    detail = client.get(f"/api/v1/imports/{job_id}").json()
    assert detail["save_identity_id"] == identity.id
    assert detail["save_session_id"] == session.id
    assert detail["save_id"] == save.id


def test_import_without_context_keeps_legacy_behaviour(client, db, save):
    response = _post_scan(client, save.id, "")

    assert response.status_code == 201
    job_id = response.json()["job_id"]
    detail = client.get(f"/api/v1/imports/{job_id}").json()
    assert detail["save_identity_id"] is None
    assert detail["save_session_id"] is None


def test_capture_rejects_invalidated_session(client, db, save):
    identity = _identity(db, save.id)
    old = _session(db, save.id, identity.id, status="invalidated")

    response = client.post(
        f"/api/v1/captures?save_id={save.id}&save_identity_id={identity.id}&save_session_id={old.id}",
        json={"status": "scanning", "game_date": "2026-11-24", "reader_version": "0.1.0"},
    )

    assert response.status_code == 409
    assert _error_code(response) == "save_session_invalidated"


def test_capture_records_identity_and_session(client, db, save):
    identity = _identity(db, save.id)
    session = _session(db, save.id, identity.id)

    response = client.post(
        f"/api/v1/captures?save_id={save.id}&save_identity_id={identity.id}&save_session_id={session.id}",
        json={"status": "scanning", "game_date": "2026-11-24", "reader_version": "0.1.0"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["save_identity_id"] == identity.id
    assert body["save_session_id"] == session.id


def test_final_guard_blocks_session_invalidated_during_import(db, save):
    identity = _identity(db, save.id)
    session = _session(db, save.id, identity.id)

    # 任务启动时的校验通过
    resolve_save_context(db, save, identity.id, session.id)

    # 导入期间另一个 Agent 检测到存档切换并失效了旧会话
    session.session_status = "invalidated"
    db.commit()

    guard = build_final_guard(db, save, identity.id, session.id)
    assert guard is not None
    with pytest.raises(HTTPException) as excinfo:
        guard()
    assert excinfo.value.status_code == 409
    assert excinfo.value.detail["code"] == "save_session_invalidated"


def test_final_guard_passes_when_context_unchanged(db, save):
    identity = _identity(db, save.id)
    session = _session(db, save.id, identity.id)

    guard = build_final_guard(db, save, identity.id, session.id)

    assert guard is not None
    guard()  # 不抛异常即为通过


def test_final_guard_absent_without_declared_context(db, save):
    assert build_final_guard(db, save, None, None) is None


def test_job_context_resume_rules():
    assert_job_context(None, None, None, None)
    assert_job_context(1, 10, 1, 10)

    with pytest.raises(HTTPException) as mismatch:
        assert_job_context(1, 10, 2, 10)
    assert mismatch.value.detail["code"] == "save_context_mismatch"

    with pytest.raises(HTTPException) as switched:
        assert_job_context(1, 10, 1, 11)
    assert switched.value.detail["code"] == "save_session_invalidated"

    with pytest.raises(HTTPException) as unknown:
        assert_job_context(1, 10, 1, None)
    assert unknown.value.detail["code"] == "save_session_invalidated"
