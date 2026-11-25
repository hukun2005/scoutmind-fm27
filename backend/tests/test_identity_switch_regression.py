"""V3.2.7.4：PR #8 审核缺陷回归（F-01 身份切换新会话可写、F-02 captures 具备 writer fence）。
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.api.routes_capture import _assert_capture_fence
from app.ingestion.importer import ScanImporter
from app.ingestion.protocol import ScanPayload
from app.models import FmSave, PlayerSnapshot, SaveSession
from app.services import write_safety
from app.services.write_safety import acquire_write_fence, resolve_write_context

from tests.helpers import player_row, scan_document
from tests.write_safety_support import (
    FINGERPRINT_B,
    add_session,
    add_verified_identity,
    make_engine,
    prepare_write_env,
    seed_save,
)


def _document(scan_id: str) -> ScanPayload:
    return ScanPayload.model_validate(scan_document(scan_id=scan_id, players=[player_row("P1", "甲")]))


def test_identity_switch_keeps_new_session_writable(tmp_path):
    """F-01：同一存档切换身份后，新会话必须保持 verified 且能立即写入。"""
    _engine, Factory = make_engine(tmp_path)
    save_id = seed_save(Factory)
    with Factory() as db:
        identity_a, session_a, gate = prepare_write_env(db, save_id)
        assert gate.generation == 0

        identity_b = add_verified_identity(db, save_id, fingerprint=FINGERPRINT_B)
        session_b = add_session(db, save_id, identity_b.id, key="session-b", bind=False)
        write_safety.bind_session_to_gate(db, db.get(FmSave, save_id), session_b)
        db.commit()

        db.expire_all()
        fresh_b = db.get(SaveSession, session_b.id)
        fresh_a = db.get(SaveSession, session_a.id)
        fresh_gate = write_safety.ensure_gate(db, save_id)
        assert fresh_b.session_status == "verified", "身份切换不得把新会话一起失效"
        assert fresh_b.session_epoch == 1
        assert fresh_a.session_status == "invalidated"
        assert fresh_gate.current_session_id == fresh_b.id

        context = resolve_write_context(
            db,
            db.get(FmSave, save_id),
            identity_id=identity_b.id,
            session_id=fresh_b.id,
            operation_id="op-switch-b",
        )
        assert context is not None and context.session_epoch == 1
        outcome = ScanImporter(db, raw_dir=tmp_path / "raw").import_payload(
            save_id,
            _document("scan-switch-b"),
            identity_id=identity_b.id,
            session_id=fresh_b.id,
            fence=acquire_write_fence(db, context),
            operation_id="op-switch-b",
        )
        assert outcome.status == "succeeded"
        assert db.scalar(select(func.count()).select_from(PlayerSnapshot)) >= 1


def test_capture_fence_rejects_write_after_generation_advances(tmp_path):
    """F-02：采集元数据在代次推进后必须被 fence 拒绝，而不是静默提交。"""
    _engine, Factory = make_engine(tmp_path)
    save_id = seed_save(Factory)
    with Factory() as db:
        identity, session, _gate = prepare_write_env(db, save_id)
        context = resolve_write_context(
            db,
            db.get(FmSave, save_id),
            identity_id=identity.id,
            session_id=session.id,
        )
        assert context is not None
        fence = acquire_write_fence(db, context)
        write_safety.rotate_generation(db, db.get(FmSave, save_id), reason="test_switch", actor="test")
        db.commit()

        with pytest.raises(HTTPException) as rejected:
            _assert_capture_fence(db, fence)
        assert rejected.value.status_code == 409
        assert rejected.value.detail["code"] == "write_fence_stale"
