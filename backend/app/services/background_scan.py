"""V3.3.2-05.2 本地后台任务执行器。

* 任务状态持久化在 ``background_tasks``，进程内由**有界**线程池执行，不引入 Redis/Celery；
* 同存档同锁键只允许一个活跃任务，数据库部分唯一索引兜底；
* 支持进度、检查点、优雅取消、有限重试、超时与应用重启恢复；
* 内部错误码/堆栈只进日志与开发报告，普通用户只看到可理解的文案。
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError

from ..config import settings
from ..db import SessionLocal
from ..models import BackgroundTask, FmSave, ImportJob
from ..utils import iso, utcnow
from . import club_linkage, transfer_radar

logger = logging.getLogger("scoutmind.background")

FULL_SCAN = "FULL_SCAN"
INCREMENTAL_SCAN = "INCREMENTAL_SCAN"
CLUB_LINK_REPAIR = "CLUB_LINK_REPAIR"
RECOVERY_SCAN = "RECOVERY_SCAN"
TRANSFER_LEARNING = "TRANSFER_LEARNING"
TASK_TYPES = (FULL_SCAN, INCREMENTAL_SCAN, CLUB_LINK_REPAIR, RECOVERY_SCAN, TRANSFER_LEARNING)
SCAN_TYPES = (FULL_SCAN, INCREMENTAL_SCAN, RECOVERY_SCAN)

LOCK_KEYS = {
    FULL_SCAN: "scan",
    INCREMENTAL_SCAN: "scan",
    RECOVERY_SCAN: "scan",
    CLUB_LINK_REPAIR: "club_link",
    TRANSFER_LEARNING: "learning",
}

ACTIVE_STATUSES = ("PENDING", "RUNNING", "CANCELLING")
TERMINAL_STATUSES = ("COMPLETED", "PARTIAL", "FAILED", "CANCELLED")

STATUS_MESSAGES = {
    "PENDING": "扫描任务已排队",
    "RUNNING": "正在更新转会情报",
    "CANCELLING": "正在取消扫描",
    "CANCELLED": "扫描已取消",
    "COMPLETED": "转会情报更新完成",
    "PARTIAL": "本次更新只完成了部分数据处理，现有数据不会被删除",
    "FAILED": "本次转会情报更新未能完成，系统可以安全重试",
}


class TaskTimeout(Exception):
    """任务超过配置的最长执行时间。"""


_executor: ThreadPoolExecutor | None = None
_executor_lock = threading.Lock()


def _executor_instance() -> ThreadPoolExecutor:
    global _executor
    with _executor_lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(
                max_workers=max(1, settings.scan_workers), thread_name_prefix="scoutmind-scan"
            )
        return _executor


def _submit(task_id: str) -> None:
    _executor_instance().submit(_run_task, task_id)


def shutdown_executor() -> None:
    """应用关闭：运行中的任务标记为 PARTIAL，避免永久占用活跃锁。"""
    global _executor
    session = SessionLocal()
    try:
        for task in session.scalars(select(BackgroundTask).where(BackgroundTask.status == "RUNNING")):
            task.status = "PARTIAL"
            task.error_code = "app_shutdown"
            task.error_message = "应用关闭，任务已安全停止"
            task.finished_at = utcnow()
        session.commit()
    finally:
        session.close()
    with _executor_lock:
        if _executor is not None:
            _executor.shutdown(wait=False, cancel_futures=True)
            _executor = None


def _loads(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _current_stage(task: BackgroundTask) -> str:
    """用户可读的当前阶段；不暴露内部状态机。"""
    if task.status == "PENDING":
        return "排队中"
    if task.status == "CANCELLING":
        return "正在取消"
    if task.status == "CANCELLED":
        return "已取消"
    if task.status == "COMPLETED":
        return "已完成"
    if task.status == "PARTIAL":
        return "部分完成"
    if task.status == "FAILED":
        return "未完成"
    if task.task_type == CLUB_LINK_REPAIR:
        return "修复俱乐部关联"
    if task.task_type == TRANSFER_LEARNING:
        return "学习转会市场"
    if int(task.total or 0) > 0 and int(task.processed or 0) >= int(task.total or 0):
        return "更新机会"
    return "分析球员状态"


def _eta_seconds(task: BackgroundTask) -> int | None:
    """只有样本足够（已处理 ≥ 50）且仍在运行时才估算剩余时间，不编造。"""
    if task.status != "RUNNING" or task.started_at is None:
        return None
    total = int(task.total or 0)
    processed = int(task.processed or 0)
    if total <= 0 or processed < 50:
        return None
    elapsed = (utcnow() - task.started_at).total_seconds()
    if elapsed <= 0:
        return None
    remaining = max(0, total - processed)
    return max(0, int(round(elapsed / processed * remaining)))


def _resumable(task: BackgroundTask) -> bool:
    if task.task_type == CLUB_LINK_REPAIR:
        return True
    if task.task_type == TRANSFER_LEARNING:
        return _loads(task.checkpoint_json).get("cursor") is not None
    return _loads(task.checkpoint_json).get("last_instance_id") is not None


def serialize(task: BackgroundTask) -> dict[str, Any]:
    """对外的最小状态视图：不暴露堆栈、SQL 或内部对象。"""
    return {
        "task_id": task.task_id,
        "save_id": task.fm_save_id,
        "task_type": task.task_type,
        "status": task.status,
        "status_key": task.status,
        "current_stage": _current_stage(task),
        "eta_seconds": _eta_seconds(task),
        "heartbeat_at": iso(task.heartbeat_at),
        "resumable": _resumable(task),
        "progress": round(float(task.progress or 0.0), 2),
        "total": int(task.total or 0),
        "processed": int(task.processed or 0),
        "matched": int(task.matched or 0),
        "failed": int(task.failed or 0),
        "started_at": iso(task.started_at),
        "finished_at": iso(task.finished_at),
        "error_code": task.error_code,
        "error_message": task.error_message,
        "created_by": task.created_by,
        "source_snapshot_id": task.source_snapshot_id,
        "attempt_count": int(task.attempt_count or 0),
        "checkpoint": _loads(task.checkpoint_json),
        "result": _loads(task.result_json),
        "message": STATUS_MESSAGES.get(task.status, task.status),
        "cancel_requested": task.status == "CANCELLING",
    }


def _active_task(db, save_id: int, lock_key: str) -> BackgroundTask | None:
    return db.scalar(
        select(BackgroundTask)
        .where(
            BackgroundTask.fm_save_id == save_id,
            BackgroundTask.lock_key == lock_key,
            BackgroundTask.status.in_(ACTIVE_STATUSES),
        )
        .order_by(BackgroundTask.id.desc())
    )


def _latest_import_job_id(db, save_id: int) -> int | None:
    return db.scalar(select(func.max(ImportJob.id)).where(ImportJob.fm_save_id == save_id))


def create_task(
    db, save_id: int, task_type: str, *, created_by: str = "user", autostart: bool = True
) -> tuple[dict[str, Any], bool]:
    """创建任务；已有同锁键活跃任务时复用（``reused=True``），不重复启动。"""
    if task_type not in TASK_TYPES:
        raise ValueError(f"unsupported task_type: {task_type}")
    if db.get(FmSave, save_id) is None:
        raise ValueError("存档不存在")
    lock_key = LOCK_KEYS[task_type]
    active = _active_task(db, save_id, lock_key)
    if active is not None:
        return serialize(active), True
    task = BackgroundTask(
        task_id=str(uuid.uuid4()),
        fm_save_id=save_id,
        task_type=task_type,
        lock_key=lock_key,
        status="PENDING",
        created_by=created_by,
        source_snapshot_id=_latest_import_job_id(db, save_id),
    )
    db.add(task)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        active = _active_task(db, save_id, lock_key)
        if active is None:
            raise
        return serialize(active), True
    if autostart:
        _submit(task.task_id)
    return serialize(task), False


def cancel_task(db, save_id: int, task_id: str) -> dict[str, Any] | None:
    """幂等取消：终态直接返回；活跃任务进入 CANCELLING，由执行器在当前批次后停止。"""
    task = db.scalar(
        select(BackgroundTask).where(
            BackgroundTask.task_id == task_id, BackgroundTask.fm_save_id == save_id
        )
    )
    if task is None:
        return None
    if task.status not in TERMINAL_STATUSES:
        task.status = "CANCELLING"
        task.cancel_requested_at = utcnow()
        db.commit()
    return serialize(task)


def get_task(db, save_id: int, task_id: str) -> dict[str, Any] | None:
    task = db.scalar(
        select(BackgroundTask).where(
            BackgroundTask.task_id == task_id, BackgroundTask.fm_save_id == save_id
        )
    )
    return serialize(task) if task is not None else None


def list_tasks(db, save_id: int, *, active_only: bool = False, limit: int = 20) -> dict[str, Any]:
    query = select(BackgroundTask).where(BackgroundTask.fm_save_id == save_id)
    if active_only:
        query = query.where(BackgroundTask.status.in_(ACTIVE_STATUSES))
    rows = list(db.scalars(query.order_by(BackgroundTask.id.desc()).limit(limit)))
    return {"items": [serialize(row) for row in rows], "total": len(rows)}


def _cancel_requested(session, task_id: str) -> bool:
    status = session.scalar(
        select(BackgroundTask.status).where(BackgroundTask.task_id == task_id)
    )
    return status == "CANCELLING"


def _last_scan_finished_at(session, save_id: int) -> datetime | None:
    return session.scalar(
        select(func.max(BackgroundTask.finished_at)).where(
            BackgroundTask.fm_save_id == save_id,
            BackgroundTask.task_type.in_(SCAN_TYPES),
            BackgroundTask.status.in_(("COMPLETED", "PARTIAL")),
        )
    )


def _retry_or_fail(session, task_id: str, code: str, message: str) -> None:
    task = session.scalar(select(BackgroundTask).where(BackgroundTask.task_id == task_id))
    if task is None:
        return
    if int(task.attempt_count or 0) < max(1, settings.scan_max_attempts):
        task.status = "PENDING"
        task.error_code = code
        task.error_message = message[:512]
        task.heartbeat_at = None
        session.commit()
        _submit(task_id)
        return
    task.status = "FAILED"
    task.error_code = code
    task.error_message = message[:512]
    task.finished_at = utcnow()
    session.commit()


def _run_task(task_id: str) -> None:
    session = SessionLocal()
    started = time.monotonic()
    try:
        task = session.scalar(select(BackgroundTask).where(BackgroundTask.task_id == task_id))
        if task is None or task.status != "PENDING":
            return
        task.status = "RUNNING"
        task.started_at = utcnow()
        task.heartbeat_at = utcnow()
        task.attempt_count = int(task.attempt_count or 0) + 1
        session.commit()
        save_id = task.fm_save_id
        checkpoint = _loads(task.checkpoint_json)
        mode = "incremental" if task.task_type == INCREMENTAL_SCAN else "full"
        since_time = _last_scan_finished_at(session, save_id) if mode == "incremental" else None
        if mode == "incremental" and since_time is None:
            mode = "full"

        def progress_cb(processed: int, total: int, matched: int, failed: int, last_id: int | None) -> None:
            if time.monotonic() - started > settings.scan_task_timeout_seconds:
                raise TaskTimeout("task_timeout")
            session.refresh(task)
            task.processed = int(processed)
            task.total = int(total)
            task.matched = int(matched)
            task.failed = int(failed)
            task.progress = round(processed / total * 100, 2) if total else (100.0 if processed else 0.0)
            task.heartbeat_at = utcnow()
            task.checkpoint_json = json.dumps(
                {
                    "last_instance_id": last_id,
                    "token": task.task_id,
                    "mode": mode,
                    "processed": processed,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            session.commit()

        if task.task_type == CLUB_LINK_REPAIR:
            result = club_linkage.repair(session, save_id, dry_run=False)
            task.total = int(result["scanned"])
            task.processed = int(result["scanned"])
            task.matched = int(result["linked"])
            task.failed = int(result["failed"])
            task.progress = 100.0
        elif task.task_type == TRANSFER_LEARNING:
            from . import transfer_learning

            def learning_progress(processed: int, total: int, created: int, skipped: int, last_id: int) -> None:
                if time.monotonic() - started > settings.scan_task_timeout_seconds:
                    raise TaskTimeout("task_timeout")
                session.refresh(task)
                task.processed = int(processed)
                task.total = int(total)
                task.matched = int(created)
                # 重复事件属于正常去重，不计为失败。
                task.failed = 0
                task.progress = round(processed / total * 100, 2) if total else 100.0
                task.heartbeat_at = utcnow()
                session.commit()

            result = transfer_learning.process_incremental(
                session,
                save_id,
                checkpoint=checkpoint,
                token=task.task_id,
                cancel_cb=lambda: _cancel_requested(session, task_id),
                progress_cb=learning_progress,
            )
            task.total = int(result.get("total") or 0)
            task.processed = int(result.get("processed") or 0)
            task.matched = int(result.get("events_created") or 0)
            task.failed = 0
            task.progress = 100.0
            task.checkpoint_json = json.dumps(
                {"cursor": result.get("checkpoint") or {}}, ensure_ascii=False, sort_keys=True
            )
            task.status = "CANCELLED" if result.get("cancelled") else "COMPLETED"
            task.finished_at = utcnow()
            task.heartbeat_at = utcnow()
            task.result_json = json.dumps(result, ensure_ascii=False, sort_keys=True, default=str)
            session.commit()
            return
        else:
            result = transfer_radar.scan_batched(
                session,
                save_id,
                batch_size=settings.scan_batch_size,
                mode=mode,
                since_time=since_time,
                token=task.task_id,
                checkpoint=checkpoint,
                cancel_cb=lambda: _cancel_requested(session, task_id),
                progress_cb=progress_cb,
            )
            task.total = int(task.total or result["scanned_players"])
            task.processed = int(result["scanned_players"])
            task.matched = int(result["created"]) + int(result["updated"])
            task.failed = 0
            task.progress = 100.0

        task.status = "COMPLETED" if int(task.failed or 0) == 0 else "PARTIAL"
        task.finished_at = utcnow()
        task.heartbeat_at = utcnow()
        if task.task_type == INCREMENTAL_SCAN and not result.get("incremental_available", False):
            task.error_code = "incremental_fallback_full"
            task.error_message = "缺少可靠变化标识，已安全退回分批全量扫描"
        task.result_json = json.dumps(result, ensure_ascii=False, sort_keys=True, default=str)
        session.commit()
    except transfer_radar.ScanCancelled as exc:
        task = session.scalar(select(BackgroundTask).where(BackgroundTask.task_id == task_id))
        if task is not None:
            task.status = "CANCELLED"
            task.finished_at = utcnow()
            task.checkpoint_json = json.dumps(exc.checkpoint, ensure_ascii=False, sort_keys=True)
            task.progress = (
                round(exc.checkpoint.get("processed", 0) / exc.checkpoint["total"] * 100, 2)
                if exc.checkpoint.get("total")
                else task.progress
            )
            session.commit()
    except TaskTimeout:
        session.rollback()
        _fail(session, task_id, "task_timeout", "扫描超过允许的最长时间，已安全停止")
    except OperationalError as exc:
        session.rollback()
        logger.warning("后台任务 %s 遇到数据库忙，准备重试：%s", task_id, exc)
        _retry_or_fail(session, task_id, "database_busy", "数据库忙，任务可以安全重试")
    except Exception as exc:  # noqa: BLE001 - 任务失败必须落到状态里，不能只留堆栈
        session.rollback()
        logger.exception("后台任务 %s 执行失败", task_id)
        _fail(session, task_id, "internal_error", "内部处理未完成，本次数据不会被删除")
    finally:
        session.close()


def _fail(session, task_id: str, code: str, message: str) -> None:
    task = session.scalar(select(BackgroundTask).where(BackgroundTask.task_id == task_id))
    if task is None:
        return
    task.status = "FAILED"
    task.error_code = code
    task.error_message = message[:512]
    task.finished_at = utcnow()
    session.commit()


def recover(session_factory=None) -> int:
    """启动时恢复未完成任务：有检查点的续跑，否则标记 PARTIAL，绝不永久 RUNNING。"""
    factory = session_factory or SessionLocal
    session = factory()
    to_start: list[str] = []
    try:
        tasks = list(
            session.scalars(select(BackgroundTask).where(BackgroundTask.status.in_(ACTIVE_STATUSES)))
        )
        for task in tasks:
            if task.status == "CANCELLING":
                task.status = "CANCELLED"
                task.finished_at = utcnow()
                task.error_code = "cancelled_on_restart"
                continue
            checkpoint = _loads(task.checkpoint_json)
            resumable = task.task_type == CLUB_LINK_REPAIR
            if task.task_type == TRANSFER_LEARNING:
                resumable = checkpoint.get("cursor") is not None
            elif task.task_type != CLUB_LINK_REPAIR:
                resumable = checkpoint.get("last_instance_id") is not None
            if resumable:
                task.status = "PENDING"
                task.heartbeat_at = None
                to_start.append(task.task_id)
            else:
                task.status = "PARTIAL"
                task.error_code = "app_restart"
                task.error_message = "应用重启，未完成的扫描已安全停止，可重新尝试"
                task.finished_at = utcnow()
        session.commit()
        count = len(tasks)
    finally:
        session.close()
    for task_id in to_start:
        _submit(task_id)
    return count
