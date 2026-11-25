"""V3.2.7.4：operation_id / scan_id 幂等与内容冲突。

原则：
* 同键 + 同内容 → 返回原结果（duplicate）且不重复写入；
* 同键 + 不同内容 → 409 冲突，绝不写入；
* 被 fence 拒绝的 operation → 409，不自动重放；
* 每次重放/冲突都累加 attempt_count 并写审计。
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import func, select

from app.ingestion.importer import OperationConflict, OperationRejected, ScanImporter
from app.models import FmSave, ImportJob, Player, PlayerInstance, PlayerSnapshot, SaveIdentityAuditEvent
from app.services.write_safety import acquire_write_fence, resolve_write_context

from tests.helpers import player_row, scan_document
from tests.write_safety_support import make_engine, prepare_write_env, seed_save


def _raw(scan_id: str, name: str = "甲") -> bytes:
    return json.dumps(scan_document(scan_id=scan_id, players=[player_row("P1", name)]), ensure_ascii=False).encode()


def _fence(db, save_id: int, identity_id: int, session_id: int, operation_id: str):
    context = resolve_write_context(
        db,
        db.get(FmSave, save_id),
        identity_id=identity_id,
        session_id=session_id,
        operation_id=operation_id,
    )
    assert context is not None
    return acquire_write_fence(db, context)


def _import(db, tmp_path, save_id, identity_id, session_id, operation_id, raw):
    return ScanImporter(db, raw_dir=tmp_path / "raw").import_bytes(
        save_id,
        raw,
        identity_id=identity_id,
        session_id=session_id,
        fence=_fence(db, save_id, identity_id, session_id, operation_id),
        operation_id=operation_id,
    )


def test_same_operation_same_payload_returns_duplicate_and_counts_attempt(tmp_path):
    _engine, Factory = make_engine(tmp_path)
    save_id = seed_save(Factory)
    raw = _raw("scan-op-1")
    with Factory() as db:
        identity, session, _gate = prepare_write_env(db, save_id)
        first = _import(db, tmp_path, save_id, identity.id, session.id, "op-1", raw)
        assert first.duplicate is False
        second = _import(db, tmp_path, save_id, identity.id, session.id, "op-1", raw)
        assert second.duplicate is True
        assert second.job_id == first.job_id

    with Factory() as db:
        job = db.get(ImportJob, first.job_id)
        assert job.attempt_count == 2
        assert db.scalar(select(func.count()).select_from(PlayerSnapshot)) >= 1
        replayed = list(
            db.scalars(select(SaveIdentityAuditEvent).where(SaveIdentityAuditEvent.event_type == "operation_replayed"))
        )
        assert len(replayed) == 1


def test_same_operation_different_payload_conflicts(tmp_path):
    _engine, Factory = make_engine(tmp_path)
    save_id = seed_save(Factory)
    with Factory() as db:
        identity, session, _gate = prepare_write_env(db, save_id)
        outcome = _import(db, tmp_path, save_id, identity.id, session.id, "op-2", _raw("scan-op-2", "甲"))
        with pytest.raises(OperationConflict) as conflict:
            _import(db, tmp_path, save_id, identity.id, session.id, "op-2", _raw("scan-op-2", "乙"))
        assert conflict.value.code == "operation_conflict"

    with Factory() as db:
        job = db.get(ImportJob, outcome.job_id)
        assert job.status == "succeeded"
        assert job.attempt_count == 2
        events = list(
            db.scalars(select(SaveIdentityAuditEvent).where(SaveIdentityAuditEvent.event_type == "operation_conflict"))
        )
        assert len(events) == 1
        # 冲突不得写入新内容：仍是第一次导入的那一名球员。
        names = list(
            db.scalars(
                select(Player.full_name)
                .join(PlayerInstance, PlayerInstance.player_id == Player.id)
                .join(PlayerSnapshot, PlayerSnapshot.player_instance_id == PlayerInstance.id)
            )
        )
        assert names == ["甲"]


def test_same_scan_different_payload_without_operation_conflicts(tmp_path):
    _engine, Factory = make_engine(tmp_path)
    save_id = seed_save(Factory)
    with Factory() as db:
        identity, session, _gate = prepare_write_env(db, save_id)
        _import(db, tmp_path, save_id, identity.id, session.id, "op-3", _raw("scan-op-3", "甲"))
        with pytest.raises(OperationConflict) as conflict:
            _import(db, tmp_path, save_id, identity.id, session.id, "op-3b", _raw("scan-op-3", "乙"))
        assert conflict.value.code == "scan_payload_mismatch"


def test_rejected_operation_replay_is_refused(tmp_path):
    _engine, Factory = make_engine(tmp_path)
    save_id = seed_save(Factory)
    with Factory() as db:
        identity, session, _gate = prepare_write_env(db, save_id)
        db.add(
            ImportJob(
                fm_save_id=save_id,
                scan_id="scan-rejected",
                source="reader",
                schema_version="1.0",
                status="rejected",
                rejected_reason="write_fence_stale",
                operation_id="op-rejected",
                save_identity_id=identity.id,
                save_session_id=session.id,
                save_generation=0,
            )
        )
        db.commit()
        with pytest.raises(OperationRejected):
            _import(db, tmp_path, save_id, identity.id, session.id, "op-rejected", _raw("scan-rejected-new"))
