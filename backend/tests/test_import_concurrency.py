"""V3.2.7.3：真实并发（多线程 + 多连接 + 屏障），不是单线程顺序调用。

覆盖：
* 写入窗口内发生存档切换：导入必须整体回滚（P0 竞态）；
* 两个并发导入都能成功且数据不丢失（SQLite 写串行化）；
* 同一 operation_id 并发重放只写一次；
* 两个 Agent 并发创建会话被数据库约束/代次串行化。
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select

from app.ingestion.importer import ImportInProgressError, ScanImporter
from app.ingestion.protocol import ScanPayload
from app.models import FmSave, ImportJob, PlayerSnapshot, SaveSession, SaveWriteGate
from app.services import save_identity as identity_service
from app.services import write_safety
from app.services.write_safety import WriteRejected, acquire_write_fence, resolve_write_context

from tests.helpers import player_row, scan_document
from tests.write_safety_support import GAME_BUILD, make_engine, prepare_write_env, seed_save


def _document(scan_id: str, uid: str = "P1") -> ScanPayload:
    return ScanPayload.model_validate(scan_document(scan_id=scan_id, players=[player_row(uid, "甲")]))


def _fence(db, save_id: int, identity_id: int, session_id: int, operation_id: str):
    save = db.get(FmSave, save_id)
    context = resolve_write_context(
        db, save, identity_id=identity_id, session_id=session_id, operation_id=operation_id
    )
    assert context is not None
    return acquire_write_fence(db, context)


def test_switch_during_import_window_rolls_back_everything(tmp_path, monkeypatch):
    """真实并发：导入已开始、另一连接完成切换，导入必须整体回滚。"""
    _engine, Factory = make_engine(tmp_path)
    save_id = seed_save(Factory)
    with Factory() as setup:
        identity, session, _gate = prepare_write_env(setup, save_id)
        identity_id, session_id = identity.id, session.id

    apply_entered = threading.Event()
    switch_done = threading.Event()
    original_apply = ScanImporter._apply
    outcome: dict[str, object] = {}

    def slow_apply(self, job, payload):
        apply_entered.set()
        assert switch_done.wait(30), "切换线程未在超时内完成"
        return original_apply(self, job, payload)

    monkeypatch.setattr(ScanImporter, "_apply", slow_apply)

    def import_worker():
        with Factory() as db:
            fence = _fence(db, save_id, identity_id, session_id, "op-race")
            try:
                ScanImporter(db, raw_dir=tmp_path / "raw").import_payload(
                    save_id,
                    _document("scan-race"),
                    identity_id=identity_id,
                    session_id=session_id,
                    fence=fence,
                    operation_id="op-race",
                )
            except WriteRejected as rejected:
                outcome["rejected"] = rejected.code
            except Exception as exc:  # 让断言报告真实原因
                outcome["error"] = repr(exc)

    worker = threading.Thread(target=import_worker, daemon=True)
    worker.start()
    assert apply_entered.wait(30), "导入未进入写入阶段"

    with Factory() as switcher:
        switched = write_safety.rotate_generation(
            switcher, switcher.get(FmSave, save_id), reason="save_switch", actor="thread"
        )
        switcher.commit()
        assert switched == 1
    switch_done.set()
    worker.join(timeout=60)
    assert not worker.is_alive()
    assert outcome.get("rejected") == "write_fence_stale", outcome

    with Factory() as db:
        job = db.scalar(select(ImportJob).where(ImportJob.operation_id == "op-race"))
        assert job.status == "rejected"
        assert job.rejected_reason == "write_fence_stale"
        assert db.query(PlayerSnapshot).count() == 0


def test_two_concurrent_imports_both_commit_without_loss(tmp_path):
    _engine, Factory = make_engine(tmp_path)
    save_id = seed_save(Factory)
    with Factory() as setup:
        identity, session, _gate = prepare_write_env(setup, save_id)
        identity_id, session_id = identity.id, session.id

    barrier = threading.Barrier(2)

    def run(uid: str, scan_id: str):
        with Factory() as db:
            fence = _fence(db, save_id, identity_id, session_id, f"op-{uid}")
            barrier.wait(timeout=20)
            outcome = ScanImporter(db, raw_dir=tmp_path / f"raw-{uid}").import_payload(
                save_id,
                _document(scan_id, uid),
                identity_id=identity_id,
                session_id=session_id,
                fence=fence,
                operation_id=f"op-{uid}",
            )
            return outcome.status, outcome.job_id

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, uid, f"scan-{uid}") for uid in ("P1", "P2")]
        results = [future.result(timeout=90) for future in futures]

    assert all(status in {"succeeded", "partial"} for status, _ in results)
    assert len({job_id for _, job_id in results}) == 2
    with Factory() as db:
        assert db.query(PlayerSnapshot).count() == 2


def test_same_operation_concurrent_replay_writes_once(tmp_path):
    _engine, Factory = make_engine(tmp_path)
    save_id = seed_save(Factory)
    with Factory() as setup:
        identity, session, _gate = prepare_write_env(setup, save_id)
        identity_id, session_id = identity.id, session.id

    barrier = threading.Barrier(2)

    def run(scan_id: str):
        with Factory() as db:
            fence = _fence(db, save_id, identity_id, session_id, "op-shared")
            barrier.wait(timeout=20)
            for _attempt in range(5):
                try:
                    outcome = ScanImporter(db, raw_dir=tmp_path / f"raw-{scan_id}").import_payload(
                        save_id,
                        _document(scan_id, "P1"),
                        identity_id=identity_id,
                        session_id=session_id,
                        fence=fence,
                        operation_id="op-shared",
                    )
                    return outcome.job_id, outcome.duplicate
                except ImportInProgressError:
                    # 另一个线程正在导入同一操作：等它提交后再走幂等返回。
                    db.rollback()
                    threading.Event().wait(0.1)
            raise AssertionError("同一 operation_id 一直处于导入中")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, f"scan-{index}") for index in range(2)]
        results = [future.result(timeout=90) for future in futures]

    assert len({job_id for job_id, _ in results}) == 1
    assert sorted(duplicate for _, duplicate in results) == [False, True]
    with Factory() as db:
        assert db.query(ImportJob).filter(ImportJob.operation_id == "op-shared").count() == 1
        assert db.query(PlayerSnapshot).count() == 1


def test_concurrent_session_starts_serialize_on_single_current(tmp_path):
    _engine, Factory = make_engine(tmp_path)
    save_id = seed_save(Factory)
    with Factory() as setup:
        from tests.write_safety_support import add_verified_identity

        record = add_verified_identity(setup, save_id)
        setup.commit()
        identity_id = record.id

    barrier = threading.Barrier(2)

    def start(key: str):
        from app.schemas import SaveSessionStartIn

        with Factory() as db:
            payload = SaveSessionStartIn(
                save_id=save_id,
                identity_id=identity_id,
                session_key=key,
                process_id=1111,
                game_build=GAME_BUILD,
                agent_id=f"agent-{key}",
            )
            barrier.wait(timeout=20)
            session = identity_service.start_session(db, db.get(FmSave, save_id), payload)
            db.commit()
            return session.id, session.session_epoch

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(start, key) for key in ("k-a", "k-b")]
        results = [future.result(timeout=90) for future in futures]

    with Factory() as db:
        gate = db.scalar(select(SaveWriteGate).where(SaveWriteGate.fm_save_id == save_id))
        sessions = list(db.scalars(select(SaveSession).where(SaveSession.fm_save_id == save_id)))
        # 两个会话都被创建，但同一个代次里只有一个是 current。
        assert len(sessions) == 2
        assert gate.current_session_id in {session_id for session_id, _ in results}
        assert all(epoch == gate.generation for _, epoch in results)
        assert sum(1 for row in sessions if row.session_status == "verified") == 2
        assert db.scalar(select(SaveWriteGate).where(SaveWriteGate.fm_save_id == save_id)).generation == 0
