"""V3.2.7.3：提交阶段数据库 fencing。

覆盖：
* 当前代次可以提交，任务记录 operation_id / save_generation；
* 取到门票后存档被切换：整次导入回滚，任务 rejected，业务行 0 条；
* 代次不变但当前会话被取代：同样拒绝；
* 同一 operation_id 重放不会二次写入。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.ingestion.importer import ScanImporter
from app.ingestion.protocol import ScanPayload
from app.models import FmSave, ImportJob, PlayerSnapshot, SaveWriteGate
from app.services import write_safety
from app.services.write_safety import WriteRejected, acquire_write_fence, resolve_write_context

from tests.helpers import player_row, scan_document
from tests.write_safety_support import make_engine, prepare_write_env, seed_save


def _fence(db, save_id: int, identity, session, operation_id: str):
    save = db.get(FmSave, save_id)
    context = resolve_write_context(
        db, save, identity_id=identity.id, session_id=session.id, operation_id=operation_id
    )
    assert context is not None
    return acquire_write_fence(db, context)


def _document(scan_id: str):
    return ScanPayload.model_validate(scan_document(scan_id=scan_id, players=[player_row("P1", "甲")]))


def test_current_fence_commits_and_records_generation(tmp_path):
    _, Factory = make_engine(tmp_path)
    save_id = seed_save(Factory)
    with Factory() as db:
        identity, session, _gate = prepare_write_env(db, save_id)
        fence = _fence(db, save_id, identity, session, "op-current")
        outcome = ScanImporter(db, raw_dir=tmp_path / "raw").import_payload(
            save_id,
            _document("scan-current"),
            identity_id=identity.id,
            session_id=session.id,
            fence=fence,
            operation_id="op-current",
        )
        assert outcome.status in {"succeeded", "partial"}
        job = db.get(ImportJob, outcome.job_id)
        assert job.save_generation == 0
        assert job.operation_id == "op-current"
        assert job.rejected_reason is None
        assert db.query(PlayerSnapshot).count() == 1


def test_switch_before_commit_rejects_whole_import(tmp_path):
    _, Factory = make_engine(tmp_path)
    save_id = seed_save(Factory)
    with Factory() as db:
        identity, session, _gate = prepare_write_env(db, save_id)
        fence = _fence(db, save_id, identity, session, "op-stale")
        # 门票已取得，随后存档切换（另一个事务）提交。
        write_safety.rotate_generation(db, db.get(FmSave, save_id), reason="save_switch", actor="tester")
        db.commit()

        with pytest.raises(WriteRejected) as rejected:
            ScanImporter(db, raw_dir=tmp_path / "raw").import_payload(
                save_id,
                _document("scan-stale"),
                identity_id=identity.id,
                session_id=session.id,
                fence=fence,
                operation_id="op-stale",
            )
        assert rejected.value.code == "write_fence_stale"

        db.expire_all()
        job = db.scalar(select(ImportJob).where(ImportJob.operation_id == "op-stale"))
        assert job is not None
        assert job.status == "rejected"
        assert job.rejected_reason == "write_fence_stale"
        assert job.finished_at is not None
        # 业务数据一行都不能留下。
        assert db.query(PlayerSnapshot).count() == 0


def test_superseded_session_rejected_even_if_generation_matches(tmp_path):
    _, Factory = make_engine(tmp_path)
    save_id = seed_save(Factory)
    with Factory() as db:
        identity, session, _gate = prepare_write_env(db, save_id)
        fence = _fence(db, save_id, identity, session, "op-superseded")

        # 代次不变，但当前会话被另一个会话取代（模拟旧 Agent 重新上线）。
        from tests.write_safety_support import add_session

        replacement = add_session(db, save_id, identity.id, key="session-new", bind=False)
        gate = db.scalar(select(SaveWriteGate).where(SaveWriteGate.fm_save_id == save_id))
        gate.current_session_id = replacement.id
        db.commit()

        with pytest.raises(WriteRejected):
            ScanImporter(db, raw_dir=tmp_path / "raw").import_payload(
                save_id,
                _document("scan-superseded"),
                identity_id=identity.id,
                session_id=session.id,
                fence=fence,
                operation_id="op-superseded",
            )
        assert db.query(PlayerSnapshot).count() == 0


def test_operation_id_replay_is_idempotent(tmp_path):
    _, Factory = make_engine(tmp_path)
    save_id = seed_save(Factory)
    with Factory() as db:
        identity, session, _gate = prepare_write_env(db, save_id)
        importer = ScanImporter(db, raw_dir=tmp_path / "raw")
        fence = _fence(db, save_id, identity, session, "op-once")
        first = importer.import_payload(
            save_id,
            _document("scan-once"),
            identity_id=identity.id,
            session_id=session.id,
            fence=fence,
            operation_id="op-once",
        )
        second = importer.import_payload(
            save_id,
            # 不同 scan_id、相同 operation_id：仍必须复用第一次的结果。
            _document("scan-once-replay"),
            identity_id=identity.id,
            session_id=session.id,
            fence=fence,
            operation_id="op-once",
        )
        assert second.duplicate is True
        assert second.job_id == first.job_id
        assert db.query(PlayerSnapshot).count() == 1
        assert db.scalar(select(ImportJob.operation_id).where(ImportJob.id == first.job_id)) == "op-once"


def test_identity_switch_advances_generation_and_invalidates_old_session(tmp_path):
    _, Factory = make_engine(tmp_path)
    save_id = seed_save(Factory)
    with Factory() as db:
        identity, session, gate = prepare_write_env(db, save_id)
        assert gate.generation == 0

        from tests.write_safety_support import FINGERPRINT_B, add_session, add_verified_identity

        other_identity = add_verified_identity(db, save_id, FINGERPRINT_B)
        new_session = add_session(db, save_id, other_identity.id, key="session-b", bind=False)
        write_safety.bind_session_to_gate(db, db.get(FmSave, save_id), new_session)
        db.commit()

        db.expire_all()
        refreshed = db.get(type(session), session.id)
        assert refreshed.session_status == "invalidated"
        assert refreshed.invalidated_reason == "identity_switch"
        updated_gate = db.scalar(select(SaveWriteGate).where(SaveWriteGate.fm_save_id == save_id))
        assert updated_gate.generation == 1
        assert updated_gate.current_session_id == new_session.id
        assert db.get(type(new_session), new_session.id).session_epoch == 1
