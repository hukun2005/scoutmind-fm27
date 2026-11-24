"""Phase 5 验收：导入事务的原子性、失败可重试与幂等去重。

覆盖任务书要求的四类真实事务行为：

* 提交前身份校验失败 → 回滚本次全部写入，任务记为 ``failed``，不留下“半次导入”。
* 写入中途异常 → 同样回滚，且 ``failed`` 任务保留身份/会话归属以便审计。
* 失败后同一 ``scan_id`` 可以重新导入，重试成功后只有一份数据。
* 已成功的 ``scan_id`` 重复提交只返回幂等结果，不重复写库。
"""

from __future__ import annotations

import pytest

from app.ingestion.importer import ScanImporter
from app.ingestion.protocol import ScanPayload
from app.models import ImportJob, PlayerInstance, PlayerSnapshot, Transfer

from tests.helpers import RAW_DIR, ensure_save, player_row, scan_document, transfer_row


def _payload(scan_id: str = "scan-tx-1") -> ScanPayload:
    """A payload that writes instances, snapshots and transfers."""
    return ScanPayload.model_validate(
        scan_document(
            scan_id=scan_id,
            players=[
                player_row("P1", "Transaction Player", ca=148),
                player_row("P2", "Second Player", ca=132),
            ],
            transfers=[transfer_row("T1", "P1", "Transaction Player", fee=22_000_000)],
        )
    )


def test_final_guard_failure_leaves_no_rows_and_failed_job(db):
    """提交前身份校验失败：本次写入整体作废，任务为 failed，归属仍可审计。"""
    save_id = ensure_save(db)
    importer = ScanImporter(db, raw_dir=RAW_DIR)

    def reject() -> None:
        raise RuntimeError("会话在提交前失效")

    with pytest.raises(RuntimeError):
        importer.import_payload(save_id, _payload(), identity_id=7, session_id=11, final_guard=reject)

    db.expire_all()
    assert db.query(PlayerInstance).count() == 0
    assert db.query(PlayerSnapshot).count() == 0
    assert db.query(Transfer).count() == 0
    job = db.query(ImportJob).one()
    assert job.status == "failed"
    assert job.save_identity_id == 7
    assert job.save_session_id == 11
    assert "提交前身份校验失败" in job.warnings_json


def test_mid_apply_failure_rolls_back_partial_rows(db, monkeypatch):
    """写入中途异常：已写入的行必须回滚，不能留下部分成功的任务。"""
    save_id = ensure_save(db)
    original_apply = ScanImporter._apply

    def explode(self, job, payload):  # type: ignore[no-untyped-def]
        original_apply(self, job, payload)
        raise RuntimeError("模拟写入中途崩溃")

    monkeypatch.setattr(ScanImporter, "_apply", explode)
    with pytest.raises(RuntimeError):
        ScanImporter(db, raw_dir=RAW_DIR).import_payload(save_id, _payload())

    db.expire_all()
    assert db.query(PlayerSnapshot).count() == 0
    assert db.query(Transfer).count() == 0
    job = db.query(ImportJob).one()
    assert job.status == "failed"
    assert "模拟写入中途崩溃" in job.warnings_json


def test_failed_scan_can_be_retried_with_same_scan_id(db):
    """身份校验失败后，同一 scan_id 重新导入应成功且不重复。"""
    save_id = ensure_save(db)
    payload = _payload()

    with pytest.raises(RuntimeError):
        ScanImporter(db, raw_dir=RAW_DIR).import_payload(
            save_id,
            payload,
            final_guard=lambda: (_ for _ in ()).throw(RuntimeError("身份失效")),
        )

    outcome = ScanImporter(db, raw_dir=RAW_DIR).import_payload(save_id, payload)
    assert outcome.status == "succeeded"
    assert outcome.duplicate is False
    assert db.query(PlayerSnapshot).count() == 2
    assert db.query(Transfer).count() == 1
    jobs = db.query(ImportJob).all()
    assert len(jobs) == 1
    assert jobs[0].status == "succeeded"
    assert jobs[0].player_count == 2


def test_repeat_submission_is_idempotent_and_writes_nothing(db):
    """同一 scan_id 成功导入后再次提交：duplicate=True，行数不增加。"""
    save_id = ensure_save(db)
    payload = _payload()
    first = ScanImporter(db, raw_dir=RAW_DIR).import_payload(save_id, payload)
    second = ScanImporter(db, raw_dir=RAW_DIR).import_payload(save_id, payload)

    assert first.duplicate is False
    assert second.duplicate is True
    # 幂等命中只回放首次导入的计数摘要，本次不再写入任何快照。
    assert second.snapshots_created == 0
    assert db.query(PlayerSnapshot).count() == 2
    assert db.query(Transfer).count() == 1
    assert db.query(ImportJob).count() == 1
