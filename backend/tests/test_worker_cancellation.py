"""V3.2.7.4：Worker 真实取消（状态机、检查点、原子边界、幂等、启动恢复）。

取消不是删除任务：queued/running → cancel_requested → cancelled；
业务写入必须整体回滚；已提交的任务不可撤销。
"""

from __future__ import annotations

import threading

import pytest
from sqlalchemy import func, select, update

from app.ingestion import cancellation
from app.ingestion.importer import ImportCancelled, ScanImporter, recover_interrupted_imports
from app.ingestion.protocol import ScanPayload
from app.models import FmSave, ImportJob, PlayerSnapshot, SaveIdentityAuditEvent
from app.services.write_safety import acquire_write_fence, resolve_write_context

from tests.helpers import player_row, scan_document
from tests.write_safety_support import make_engine, prepare_write_env, seed_save


def _document(scan_id: str) -> ScanPayload:
    return ScanPayload.model_validate(scan_document(scan_id=scan_id, players=[player_row("P1", "甲")]))


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


def _jobs(db, status: str | None = None) -> list[ImportJob]:
    query = select(ImportJob)
    if status:
        query = query.where(ImportJob.status == status)
    return list(db.scalars(query))


def test_cancel_during_apply_rolls_back_and_marks_cancelled(tmp_path, monkeypatch):
    """真实线程：Worker 正在写库时收到取消，提交前必须整体回滚。"""
    _engine, Factory = make_engine(tmp_path)
    save_id = seed_save(Factory)
    with Factory() as setup:
        identity, session, _gate = prepare_write_env(setup, save_id)
        identity_id, session_id = identity.id, session.id

    entered = threading.Event()
    release = threading.Event()
    state: dict[str, int] = {}
    original_apply = ScanImporter._apply

    def slow_apply(self, job, payload):
        state["job_id"] = job.id
        entered.set()
        assert release.wait(20), "测试未释放 Worker"
        return original_apply(self, job, payload)

    monkeypatch.setattr(ScanImporter, "_apply", slow_apply)
    outcome: dict[str, object] = {}

    def worker() -> None:
        with Factory() as db:
            fence = _fence(db, save_id, identity_id, session_id, "op-cancel")
            try:
                ScanImporter(db, raw_dir=tmp_path / "raw").import_payload(
                    save_id,
                    _document("scan-cancel"),
                    identity_id=identity_id,
                    session_id=session_id,
                    fence=fence,
                    operation_id="op-cancel",
                )
            except ImportCancelled as exc:
                outcome["cancelled"] = exc.job.id
            except Exception as exc:  # 让断言报告真实原因
                outcome["error"] = repr(exc)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    assert entered.wait(20), "导入未进入写入阶段"
    job_id = state["job_id"]
    with Factory() as db:
        assert db.get(ImportJob, job_id).status == "running"

    cancellation.request_cancel(job_id)
    release.set()
    thread.join(30)

    assert outcome.get("cancelled") == job_id, outcome
    with Factory() as db:
        job = db.get(ImportJob, job_id)
        assert job.status == "cancelled"
        assert job.cancelled_at is not None
        assert job.rejected_reason is None
        assert db.scalar(select(func.count()).select_from(PlayerSnapshot)) == 0
        events = list(
            db.scalars(
                select(SaveIdentityAuditEvent).where(SaveIdentityAuditEvent.event_type == "worker_cancelled")
            )
        )
        assert len(events) == 1
        assert events[0].fm_save_id == save_id


def test_cancel_requested_before_claim_marks_cancelled(tmp_path):
    """queued 任务在认领前被取消：Worker 不得开始写入。"""
    _engine, Factory = make_engine(tmp_path)
    save_id = seed_save(Factory)
    with Factory() as db:
        identity, session, _gate = prepare_write_env(db, save_id)
        importer = ScanImporter(db, raw_dir=tmp_path / "raw")
        payload = _document("scan-queued")
        job = importer._begin_job(
            save_id,
            payload,
            None,
            b"{}",
            identity_id=identity.id,
            session_id=session.id,
            operation_id="op-queued",
            save_generation=0,
        )
        cancellation.request_cancel(job.id)
        db.execute(
            update(ImportJob)
            .where(ImportJob.id == job.id)
            .values(status="cancel_requested")
            .execution_options(synchronize_session=False)
        )
        db.commit()

        with pytest.raises(ImportCancelled):
            importer._claim_job(job)
        db.expire_all()
        cancelled = db.get(ImportJob, job.id)
        assert cancelled.status == "cancelled"
        assert cancelled.cancelled_at is not None
        assert db.scalar(select(func.count()).select_from(PlayerSnapshot)) == 0


def test_cancelled_job_can_be_retried_with_new_operation(tmp_path):
    """取消不写业务数据，因此允许用同一 scan_id + 新 operation_id 重新导入。"""
    _engine, Factory = make_engine(tmp_path)
    save_id = seed_save(Factory)
    with Factory() as db:
        identity, session, _gate = prepare_write_env(db, save_id)
        db.add(
            ImportJob(
                fm_save_id=save_id,
                scan_id="scan-retry",
                source="reader",
                schema_version="1.0",
                status="cancelled",
                operation_id="op-old",
                save_identity_id=identity.id,
                save_session_id=session.id,
                save_generation=0,
            )
        )
        db.commit()
        fence = _fence(db, save_id, identity.id, session.id, "op-new")
        outcome = ScanImporter(db, raw_dir=tmp_path / "raw").import_payload(
            save_id,
            _document("scan-retry"),
            identity_id=identity.id,
            session_id=session.id,
            fence=fence,
            operation_id="op-new",
        )
        assert outcome.status == "succeeded"
        db.expire_all()
        job = db.scalar(select(ImportJob).where(ImportJob.scan_id == "scan-retry"))
        assert job.status == "succeeded"
        assert job.operation_id == "op-new"
        assert job.attempt_count == 1
        assert db.scalar(select(func.count()).select_from(PlayerSnapshot)) >= 1


def test_startup_recovery_cancels_requested_and_audits(tmp_path):
    """后端重启：cancel_requested 必须落 cancelled，running/queued 落 failed，并写恢复审计。"""
    _engine, Factory = make_engine(tmp_path)
    save_id = seed_save(Factory)
    with Factory() as db:
        db.add_all(
            [
                ImportJob(fm_save_id=save_id, scan_id="s-cancel", source="reader", schema_version="1.0", status="cancel_requested"),
                ImportJob(fm_save_id=save_id, scan_id="s-run", source="reader", schema_version="1.0", status="running"),
                ImportJob(fm_save_id=save_id, scan_id="s-queued", source="reader", schema_version="1.0", status="queued"),
            ]
        )
        db.commit()

    assert recover_interrupted_imports(Factory) == 3

    with Factory() as db:
        statuses = {job.scan_id: job.status for job in _jobs(db)}
        assert statuses == {"s-cancel": "cancelled", "s-run": "failed", "s-queued": "failed"}
        recovered = list(
            db.scalars(
                select(SaveIdentityAuditEvent).where(SaveIdentityAuditEvent.event_type == "worker_recovered")
            )
        )
        restarted = list(
            db.scalars(select(SaveIdentityAuditEvent).where(SaveIdentityAuditEvent.event_type == "backend_restarted"))
        )
        assert len(recovered) == 3
        assert len(restarted) == 1


def test_cross_process_cancel_before_commit_rolls_back(tmp_path, monkeypatch):
    """另一个后端进程写入 cancel_requested 后，Worker 不得把终态覆盖成 succeeded。"""
    _engine, Factory = make_engine(tmp_path)
    save_id = seed_save(Factory)
    with Factory() as setup:
        identity, session, _gate = prepare_write_env(setup, save_id)
        identity_id, session_id = identity.id, session.id

    original_apply = ScanImporter._apply

    def cancel_in_other_process(self, job, payload):
        # 模拟另一个后端进程：只能改数据库状态，无法置位本进程的 threading.Event。
        with Factory() as other:
            other.execute(
                update(ImportJob)
                .where(ImportJob.id == job.id)
                .values(status="cancel_requested")
                .execution_options(synchronize_session=False)
            )
            other.commit()
        return original_apply(self, job, payload)

    monkeypatch.setattr(ScanImporter, "_apply", cancel_in_other_process)
    with Factory() as db:
        fence = _fence(db, save_id, identity_id, session_id, "op-xproc")
        with pytest.raises(ImportCancelled):
            ScanImporter(db, raw_dir=tmp_path / "raw").import_payload(
                save_id,
                _document("scan-xproc"),
                identity_id=identity_id,
                session_id=session_id,
                fence=fence,
                operation_id="op-xproc",
            )

    with Factory() as db:
        job = db.scalar(select(ImportJob).where(ImportJob.scan_id == "scan-xproc"))
        assert job.status == "cancelled"
        assert job.cancelled_at is not None
        assert db.scalar(select(func.count()).select_from(PlayerSnapshot)) == 0


def test_checkpoint_reads_cancel_requested_from_database(tmp_path, monkeypatch):
    """安全检查点必须能读到另一个进程提交的 cancel_requested（不只依赖进程内事件）。"""
    _engine, Factory = make_engine(tmp_path)
    save_id = seed_save(Factory)
    with Factory() as setup:
        identity, session, _gate = prepare_write_env(setup, save_id)
        identity_id, session_id = identity.id, session.id

    original_apply = ScanImporter._apply
    seen: dict[str, bool] = {}

    def cancel_then_check(self, job, payload):
        with Factory() as other:
            other.execute(
                update(ImportJob)
                .where(ImportJob.id == job.id)
                .values(status="cancel_requested")
                .execution_options(synchronize_session=False)
            )
            other.commit()
        seen["db"] = self._cancel_requested_in_db(job.id)
        self._check_cancel(job, 200)  # 命中检查点：必须读取数据库状态
        return original_apply(self, job, payload)

    monkeypatch.setattr(ScanImporter, "_apply", cancel_then_check)
    with Factory() as db:
        fence = _fence(db, save_id, identity_id, session_id, "op-checkpoint")
        with pytest.raises(ImportCancelled):
            ScanImporter(db, raw_dir=tmp_path / "raw").import_payload(
                save_id,
                _document("scan-checkpoint"),
                identity_id=identity_id,
                session_id=session_id,
                fence=fence,
                operation_id="op-checkpoint",
            )

    assert seen.get("db") is True
    with Factory() as db:
        job = db.scalar(select(ImportJob).where(ImportJob.scan_id == "scan-checkpoint"))
        assert job.status == "cancelled"
        assert db.scalar(select(func.count()).select_from(PlayerSnapshot)) == 0


def test_cancel_finished_job_is_not_cancellable_and_is_idempotent(client, save, db):
    """HTTP：已完成任务取消返回 409；queued 任务取消幂等且只写一次审计。"""
    from tests.test_unified_import_identity import _register, _scan_doc, _start

    identity = _register(client, save)
    session = _start(client, save, identity["identity_id"])
    response = client.post(
        "/api/v1/imports/scan",
        params={
            "save_identity_id": identity["identity_id"],
            "save_session_id": session["session_id"],
            "operation_id": "op-finished",
        },
        json=_scan_doc("scan-finished"),
    )
    assert response.status_code in {200, 201}, response.text
    job_id = response.json()["job_id"]

    cancel = client.post(f"/api/v1/imports/{job_id}/cancel")
    assert cancel.status_code == 409, cancel.text
    assert cancel.json()["error"]["code"] == "import_not_cancellable"

    queued = ImportJob(fm_save_id=save.id, scan_id="scan-queued-http", source="reader", schema_version="1.0", status="queued")
    db.add(queued)
    db.commit()
    first = client.post(f"/api/v1/imports/{queued.id}/cancel")
    second = client.post(f"/api/v1/imports/{queued.id}/cancel")
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "cancelled"
    assert second.status_code == 200, second.text
    assert second.json()["already_cancelled"] is True
    db.expire_all()
    assert db.get(ImportJob, queued.id).status == "cancelled"
    audits = list(
        db.scalars(
            select(SaveIdentityAuditEvent).where(SaveIdentityAuditEvent.event_type == "worker_cancel_requested")
        )
    )
    assert len(audits) == 1
    cancelled_audits = list(
        db.scalars(
            select(SaveIdentityAuditEvent).where(SaveIdentityAuditEvent.event_type == "worker_cancelled")
        )
    )
    assert len(cancelled_audits) == 1
