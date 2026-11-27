"""V3.3.2-07 普通用户体验：首次启动检查、数据中心、诊断与安全修复。

原则：

* 只输出用户能理解的状态文案，不返回堆栈、SQL 或内部对象；
* 诊断只读，不写业务表；
* 修复只执行可验证的安全项（目前仅俱乐部关联），其余明确跳过并说明原因。
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..models import (
    BackgroundTask,
    Club,
    DataSource,
    FmSave,
    ImportJob,
    PlayerInstance,
    PlayerSnapshot,
    Transfer,
    TransferOpportunity,
)
from ..utils import iso, utcnow
from . import club_linkage, query_cache

ACTIVE_TASK_STATUSES = ("PENDING", "RUNNING", "CANCELLING")
SCAN_TYPES = ("FULL_SCAN", "INCREMENTAL_SCAN", "RECOVERY_SCAN")
STALE_SCAN_DAYS = 7

#: 内部错误码 → 普通用户可理解的提示。未知错误码有兜底，绝不回显原始异常。
ERROR_MESSAGES: dict[str, str] = {
    "missing_data": "部分数据暂时无法获取",
    "data_source_unavailable": "暂时无法连接游戏数据",
    "database_busy": "系统正在处理其他任务",
    "task_interrupted": "上次任务未完成，可以继续",
    "version_incompatible": "当前游戏版本暂不支持完整读取",
    "repair_failed": "部分问题需要重新检查",
    "app_restart": "应用重启，上次任务已安全停止",
    "task_timeout": "本次处理时间过长，已安全停止",
    "club_link_unverified": "部分球员的俱乐部归属暂时无法确认",
    "player_identity_unverified": "部分球员身份需要人工确认",
    "incremental_fallback_full": "已自动改为完整扫描",
}

UNSAFE_TARGET_REASONS = {
    "player_identity": "不确定身份不允许自动修复",
    "contract": "不确定的合同信息不允许自动修复",
    "delete_duplicates": "需要删除原始数据的修复不允许自动执行",
}

SAFE_TARGETS = ("club_links",)


def friendly_message(code: str | None) -> str:
    """把内部错误码转成用户可读文案；未知码使用兜底，不回显原始异常。"""
    if code and code in ERROR_MESSAGES:
        return ERROR_MESSAGES[code]
    return "系统暂时无法完成该操作，请稍后重试"


def _check(key: str, label: str, status: str, detail: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"key": key, "label": label, "status": status}
    if detail:
        payload["detail"] = detail
    return payload


def _check_status(status: str) -> str:
    return status if status in {"ready", "checking", "needs_attention", "unavailable"} else "checking"


def _database_ready(db: Session) -> bool:
    try:
        db.execute(select(1))
        return True
    except Exception:  # noqa: BLE001 - 环境探测不能把异常抛给用户
        return False


def _migration_check(db: Session) -> dict[str, Any]:
    try:
        current = db.execute(text("select version_num from alembic_version")).scalar()
    except Exception:  # noqa: BLE001 - 测试库或内置建表没有 alembic_version
        return _check("migration", "数据迁移", "ready", "数据库结构已就绪")
    if current:
        return _check("migration", "数据迁移", "ready", "数据库结构已是最新")
    return _check("migration", "数据迁移", "needs_attention", "需要初始化数据库")


def _last_updated_at(db: Session, save_id: int) -> str | None:
    finished = db.scalar(
        select(func.max(ImportJob.finished_at)).where(
            ImportJob.fm_save_id == save_id, ImportJob.finished_at.is_not(None)
        )
    )
    if finished is not None:
        return iso(finished)
    observed = db.scalar(
        select(func.max(PlayerSnapshot.observed_at))
        .join(PlayerInstance, PlayerInstance.latest_snapshot_id == PlayerSnapshot.id)
        .where(PlayerInstance.fm_save_id == save_id)
    )
    return iso(observed)


def _active_tasks(db: Session, save_id: int) -> list[BackgroundTask]:
    return list(
        db.scalars(
            select(BackgroundTask)
            .where(
                BackgroundTask.fm_save_id == save_id,
                BackgroundTask.status.in_(ACTIVE_TASK_STATUSES),
            )
            .order_by(BackgroundTask.id.desc())
            .limit(5)
        )
    )


def _readable_task(task: BackgroundTask) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "task_type": task.task_type,
        "status": task.status,
        "message": "任务未完成，可以继续" if task.status != "CANCELLING" else "正在取消",
        "processed": int(task.processed or 0),
        "total": int(task.total or 0),
    }


def onboarding(db: Session, save: FmSave) -> dict[str, Any]:
    """首次启动：环境检查 + 数据准备 + 完成摘要。"""
    db_ok = _database_ready(db)
    health = club_linkage.health(db, save.id) if db_ok else {}
    player_count = int(health.get("total_players") or 0)
    club_count = int(
        db.scalar(select(func.count()).select_from(Club).where(Club.fm_save_id == save.id)) or 0
    )
    opportunity_count = int(
        db.scalar(
            select(func.count())
            .select_from(TransferOpportunity)
            .where(TransferOpportunity.fm_save_id == save.id, TransferOpportunity.active.is_(True))
        )
        or 0
    )
    transfer_count = int(
        db.scalar(select(func.count()).select_from(Transfer).where(Transfer.fm_save_id == save.id)) or 0
    )
    reader_ready = bool(
        db.scalar(
            select(func.count())
            .select_from(DataSource)
            .where(
                DataSource.fm_save_id == save.id,
                DataSource.source.in_(("fm27_live_reader", "live_reader")),
            )
        )
        or 0
    )
    active_tasks = _active_tasks(db, save.id) if db_ok else []
    last_updated = _last_updated_at(db, save.id) if db_ok else None

    checks = [
        _check("database", "本地数据库", "ready" if db_ok else "unavailable",
               "已连接本地数据库" if db_ok else "本地数据库暂时不可用"),
        _check("backend", "本地服务", "ready", "本地服务运行中"),
        _check("live_reader", "游戏读取器", "ready" if reader_ready else "unavailable",
               "已通过游戏读取器同步数据" if reader_ready else "未检测到读取器，可先导入已有数据"),
        _check("game", "FM27", "ready" if save.game_build else "unavailable",
               f"已识别游戏版本 {save.game_version}" if save.game_build else "未检测到运行中的 FM27"),
        _check("version", "版本兼容", "ready" if save.game_version else "checking",
               None if save.game_version else "正在确认游戏版本"),
        _migration_check(db) if db_ok else _check("migration", "数据迁移", "unavailable"),
    ]

    if not db_ok:
        status = "unavailable"
    elif player_count == 0:
        status = "needs_attention"
    elif any(item["status"] in {"needs_attention", "unavailable"} for item in checks):
        status = "needs_attention"
    else:
        status = "ready"

    save_status = "尚未导入数据" if player_count == 0 else "已有可用数据"
    return {
        "save": {
            "id": save.id,
            "name": save.name,
            "game_version": save.game_version,
            "status": "ready" if player_count > 0 else "needs_attention",
        },
        "checks": checks,
        "status": status,
        "data": {
            "has_players": player_count > 0,
            "player_count": player_count,
            "club_count": club_count,
            "linked_players": int(health.get("linked") or 0),
            "unlinked_players": int((health.get("states") or {}).get(club_linkage.UNRESOLVED, 0))
            + int((health.get("states") or {}).get(club_linkage.INVALID_REFERENCE, 0)),
            "opportunity_count": opportunity_count,
            "transfer_count": transfer_count,
            "last_updated_at": last_updated,
            "recoverable_tasks": [_readable_task(task) for task in active_tasks],
            "pending_checks": [],
        },
        "summary": {
            "player_count": player_count,
            "club_count": club_count,
            "opportunity_count": opportunity_count,
            "last_updated_at": last_updated,
            "save_status": save_status,
        },
        "actions": [
            {"key": "import", "label": "开始导入", "enabled": player_count == 0},
            {"key": "scan", "label": "重新扫描", "enabled": player_count > 0},
            {"key": "data", "label": "查看数据状态", "enabled": True},
        ],
    }


def data_health(db: Session, save: FmSave) -> dict[str, Any]:
    """统一数据中心视图（只读）。"""
    health = club_linkage.health(db, save.id)
    states = health.get("states") or {}
    missing_source = int(states.get(club_linkage.MISSING_SOURCE_FIELD, 0))
    unresolved = int(states.get(club_linkage.UNRESOLVED, 0))
    invalid = int(states.get(club_linkage.INVALID_REFERENCE, 0))
    player_count = int(health.get("total_players") or 0)
    linked = int(health.get("linked") or 0)

    club_count = int(
        db.scalar(select(func.count()).select_from(Club).where(Club.fm_save_id == save.id)) or 0
    )
    transfers_total = int(
        db.scalar(select(func.count()).select_from(Transfer).where(Transfer.fm_save_id == save.id)) or 0
    )
    transfers_completed = int(
        db.scalar(
            select(func.count())
            .select_from(Transfer)
            .where(Transfer.fm_save_id == save.id, Transfer.status == "completed")
        )
        or 0
    )
    active_opportunities = int(
        db.scalar(
            select(func.count())
            .select_from(TransferOpportunity)
            .where(TransferOpportunity.fm_save_id == save.id, TransferOpportunity.active.is_(True))
        )
        or 0
    )
    confirmed = int(
        db.scalar(
            select(func.count())
            .select_from(TransferOpportunity)
            .where(
                TransferOpportunity.fm_save_id == save.id,
                TransferOpportunity.active.is_(True),
                TransferOpportunity.verified_status == "confirmed",
            )
        )
        or 0
    )
    tasks = _active_tasks(db, save.id)
    latest_task = db.scalar(
        select(BackgroundTask)
        .where(BackgroundTask.fm_save_id == save.id)
        .order_by(BackgroundTask.id.desc())
        .limit(1)
    )

    reasons: list[str] = []
    if player_count == 0:
        level, label = "warn", "待更新"
        reasons.append("尚未导入球员数据，请先导入或扫描")
    else:
        if missing_source:
            reasons.append(f"{missing_source} 名球员的来源数据未提供俱乐部字段")
        if unresolved or invalid:
            reasons.append(f"{unresolved + invalid} 名球员存在待确认或失效的俱乐部引用")
        if reasons:
            level, label = "warn", "部分缺失"
        else:
            level, label = "ok", "正常"

    return {
        "save": {
            "id": save.id,
            "name": save.name,
            "game_date": None,
        },
        "players": {
            "count": player_count,
            "linked": linked,
            "unlinked": unresolved + invalid,
            "missing_source_field": missing_source,
        },
        "clubs": {"count": club_count, "linked_players": linked},
        "transfers": {"count": transfers_total, "completed": transfers_completed},
        "opportunities": {
            "active": active_opportunities,
            "confirmed": confirmed,
            "inferred": max(0, active_opportunities - confirmed),
        },
        "status": {"level": level, "label": label, "reasons": reasons},
        "last_updated_at": _last_updated_at(db, save.id),
        "background": {
            "active": len(tasks),
            "latest": (
                {
                    "task_id": latest_task.task_id,
                    "status": latest_task.status,
                    "message": friendly_message(latest_task.error_code)
                    if latest_task.error_code
                    else "最近一次任务已结束",
                }
                if latest_task is not None
                else None
            ),
        },
        "can_repair": bool(unresolved or invalid),
        "notes": ["无法确认俱乐部归属的球员保持 MISSING_SOURCE_FIELD，不会按姓名猜测绑定"],
    }


def diagnostics(db: Session, save: FmSave) -> dict[str, Any]:
    """只读诊断：可重复调用，不写业务表。"""
    dupe_groups = db.execute(
        select(ImportJob.checksum, func.count())
        .where(ImportJob.fm_save_id == save.id, ImportJob.checksum.is_not(None))
        .group_by(ImportJob.checksum)
        .having(func.count() > 1)
    ).all()
    duplicate_imports = len(dupe_groups)

    valid_club_ids = list(
        db.scalars(select(Club.id).where(Club.fm_save_id == save.id))
    )
    if valid_club_ids:
        orphan_clubs = int(
            db.scalar(
                select(func.count())
                .select_from(PlayerInstance)
                .where(
                    PlayerInstance.fm_save_id == save.id,
                    PlayerInstance.club_id.is_not(None),
                    PlayerInstance.club_id.notin_(valid_club_ids),
                )
            )
            or 0
        )
    else:
        orphan_clubs = int(
            db.scalar(
                select(func.count())
                .select_from(PlayerInstance)
                .where(PlayerInstance.fm_save_id == save.id, PlayerInstance.club_id.is_not(None))
            )
            or 0
        )

    last_scan = db.scalar(
        select(func.max(BackgroundTask.finished_at)).where(
            BackgroundTask.fm_save_id == save.id,
            BackgroundTask.task_type.in_(SCAN_TYPES),
            BackgroundTask.status.in_(("COMPLETED", "PARTIAL")),
        )
    )
    if last_scan is None:
        stale_status, stale_detail = "warn", "还没有完成过转会扫描"
    elif utcnow() - last_scan > timedelta(days=STALE_SCAN_DAYS):
        stale_status, stale_detail = "warn", f"上次扫描已超过 {STALE_SCAN_DAYS} 天"
    else:
        stale_status, stale_detail = "pass", "扫描结果较新"

    failed_tasks = int(
        db.scalar(
            select(func.count())
            .select_from(BackgroundTask)
            .where(BackgroundTask.fm_save_id == save.id, BackgroundTask.status == "FAILED")
        )
        or 0
    )

    checks = [
        {
            "key": "duplicate_imports",
            "label": "重复导入",
            "status": "warn" if duplicate_imports else "pass",
            "detail": f"发现 {duplicate_imports} 组重复导入记录" if duplicate_imports else "未发现重复导入",
            "count": duplicate_imports,
        },
        {
            "key": "orphan_clubs",
            "label": "悬空俱乐部引用",
            "status": "warn" if orphan_clubs else "pass",
            "detail": f"{orphan_clubs} 名球员引用了不存在的俱乐部" if orphan_clubs else "俱乐部引用有效",
            "count": orphan_clubs,
        },
        {
            "key": "stale_scan",
            "label": "扫描新鲜度",
            "status": stale_status,
            "detail": stale_detail,
        },
        {
            "key": "failed_tasks",
            "label": "失败任务",
            "status": "warn" if failed_tasks else "pass",
            "detail": f"{failed_tasks} 个任务上次未完成，可以重试" if failed_tasks else "没有失败任务",
            "count": failed_tasks,
        },
    ]
    summary = {"pass": 0, "warn": 0, "fail": 0}
    for item in checks:
        summary[item["status"]] = summary.get(item["status"], 0) + 1

    return {
        "checks": checks,
        "summary": summary,
        "repairable": list(SAFE_TARGETS),
    }


def repair(db: Session, save: FmSave, targets: list[str] | None = None, dry_run: bool = False) -> dict[str, Any]:
    """只执行安全修复；不安全项返回 skipped 与原因，不删除原始数据。"""
    requested = list(targets or SAFE_TARGETS)
    executed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for target in requested:
        if target == "club_links":
            result = club_linkage.repair(db, save.id, dry_run=dry_run)
            executed.append(
                {
                    "target": "club_links",
                    "scanned": int(result.get("scanned") or 0),
                    "linked": int(result.get("linked") or 0),
                    "failed": int(result.get("failed") or 0),
                }
            )
        elif target in UNSAFE_TARGET_REASONS:
            skipped.append({"target": target, "reason": UNSAFE_TARGET_REASONS[target]})
        else:
            skipped.append({"target": target, "reason": "该修复项需要人工确认，未自动执行"})

    if not dry_run:
        query_cache.clear()

    return {
        "dry_run": dry_run,
        "executed": executed,
        "skipped": skipped,
        "health": data_health(db, save),
        "message": "仅完成检查，未修改任何数据" if dry_run else "已完成可安全修复的项目",
    }
