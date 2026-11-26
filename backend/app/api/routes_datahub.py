"""V3.3.0 data hub endpoints: one status panel and one import entry point.

The old import endpoints stay untouched; this router is additive. A user only needs two actions:
"同步游戏数据" (an upload in the desktop build) and "导入数据" (this endpoint).
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..datahub import AutomaticDataImportEngine
from ..datahub.audit import list_repairs, repair_summary
from ..datahub.detection import SUPPORTED_MAJOR, DetectionError
from ..datahub.game_detection import detect_game
from ..db import get_db
from ..ingestion.importer import ImportCancelled, ImportInProgressError, OperationConflict, OperationRejected
from ..ingestion.protocol import ProtocolError
from ..models import (
    Club,
    FmSave,
    IdentityConflict,
    ImportJob,
    PlayerInstance,
    PlayerSnapshot,
    ReaderCompatibility,
    SaveIdentity,
    SaveIdentityConflict,
    Transfer,
    UnresolvedPlayerCandidate,
)
from ..services.write_safety import WriteRejected
from .deps import get_active_save, get_current_user
from .routes_core import _import_failure, _raise_write_rejected, _require_write_fence
from .uploads import read_request_payload, upload_slot

router = APIRouter()


def _count(db: Session, model, *conditions) -> int:
    query = select(func.count()).select_from(model)
    for condition in conditions:
        query = query.where(condition)
    return int(db.scalar(query) or 0)


def _latest_identity(db: Session, save_id: int) -> SaveIdentity | None:
    return db.scalar(
        select(SaveIdentity)
        .where(SaveIdentity.fm_save_id == save_id)
        .order_by(SaveIdentity.last_seen_at.desc(), SaveIdentity.id.desc())
        .limit(1)
    )


def _compatibility(db: Session, version: str | None) -> dict[str, Any]:
    """Best-effort compatibility statement from the reader registry.

    ``unknown`` is deliberate: an unverified build must not be presented as supported or unsupported.
    """
    if not version:
        return {"status": "unknown", "message": "未能读取游戏版本，导入前请先运行一次读取器 probe"}
    major_minor = ".".join(version.split(".")[:2])
    rows = list(db.scalars(select(ReaderCompatibility)))
    if not rows:
        return {"status": "unknown", "message": "本机没有兼容性记录"}
    verified = [
        row for row in rows
        if row.status == "verified" and (row.plugin_version or "").startswith(major_minor)
    ]
    if verified:
        return {"status": "supported", "message": "", "plugin_version": verified[0].plugin_version}
    candidates = [row for row in rows if (row.plugin_version or "").startswith(major_minor)]
    if candidates:
        return {
            "status": "unknown",
            "message": "当前版本只有候选兼容记录，导入前请先确认读取器版本",
            "plugin_version": candidates[0].plugin_version,
        }
    return {
        "status": "unsupported",
        "message": "当前 FM27 版本暂不支持同步，请等待兼容性更新",
    }


@router.get("/data-hub/status", summary="数据中心状态（游戏连接 / 存档 / 记录数 / 健康）")
def data_hub_status(
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
    user=Depends(get_current_user),
) -> dict[str, Any]:
    """Everything the three data-center panels need, from real database queries only."""
    game_raw = detect_game()
    version = game_raw.version
    if version is None:
        identity = _latest_identity(db, save.id)
        version = None if identity is None else identity.game_build
    compatibility = _compatibility(db, version)

    identity = _latest_identity(db, save.id)
    identity_status = identity.identity_status if identity is not None else "unknown"
    open_conflicts = _count(
        db,
        SaveIdentityConflict,
        SaveIdentityConflict.fm_save_id == save.id,
        SaveIdentityConflict.status == "open",
    )
    recognized = identity_status == "verified" and open_conflicts == 0
    can_sync = (
        game_raw.running
        and compatibility["status"] != "unsupported"
        and open_conflicts == 0
    )
    if not game_raw.running and game_raw.detected:
        save_message = "请先启动 Football Manager 27"
    elif compatibility["status"] == "unsupported":
        save_message = compatibility["message"]
    elif open_conflicts:
        save_message = "存档身份存在冲突，请先在「存档身份」页确认后再写入"
    elif identity_status != "verified":
        save_message = "存档身份待确认；可以同步，但系统会保留写入审计"
    else:
        save_message = ""

    last_job = db.scalar(
        select(ImportJob)
        .where(ImportJob.fm_save_id == save.id)
        .order_by(ImportJob.received_at.desc(), ImportJob.id.desc())
        .limit(1)
    )
    records = {
        "players": _count(db, PlayerInstance, PlayerInstance.fm_save_id == save.id),
        "clubs": _count(db, Club, Club.fm_save_id == save.id),
        "transfers": _count(db, Transfer, Transfer.fm_save_id == save.id),
        "snapshots": _count(
            db,
            PlayerSnapshot,
            PlayerSnapshot.player_instance_id.in_(
                select(PlayerInstance.id).where(PlayerInstance.fm_save_id == save.id)
            ),
        ),
    }
    unresolved = _count(
        db,
        UnresolvedPlayerCandidate,
        UnresolvedPlayerCandidate.fm_save_id == save.id,
        UnresolvedPlayerCandidate.status == "pending",
    )
    identity_conflicts = _count(
        db,
        IdentityConflict,
        IdentityConflict.fm_save_id == save.id,
        IdentityConflict.status == "open",
    )
    repair_counts = repair_summary(db, save.id)
    pending_total = unresolved + identity_conflicts + repair_counts.get("pending_review", 0)

    issues: list[str] = []
    if last_job is not None and last_job.status in {"failed", "rejected", "partial"}:
        issues.append(f"最近一次导入状态为 {last_job.status}")
    if unresolved:
        issues.append(f"{unresolved} 名球员待确认身份")
    if identity_conflicts:
        issues.append(f"{identity_conflicts} 个身份冲突待人工确认")
    if repair_counts.get("pending_review"):
        issues.append(f"{repair_counts['pending_review']} 条记录被隔离，需要人工确认")
    if records["players"] == 0:
        health_status = "empty"
    elif issues:
        health_status = "attention"
    else:
        health_status = "ok"

    last_sync = None
    if last_job is not None:
        last_sync = {
            "job_id": last_job.id,
            "status": last_job.status,
            "source": last_job.source,
            "received_at": _iso(last_job.received_at),
            "finished_at": _iso(last_job.finished_at),
            "players": last_job.player_count,
            "transfers": last_job.transfer_count,
        }

    return {
        "game": {
            **game_raw.payload(),
            "compatibility": compatibility["status"],
            "compatibility_message": compatibility.get("message", ""),
        },
        "save": {
            "id": save.id,
            "name": save.name,
            "recognized": recognized,
            "identity_status": identity_status,
            "can_sync": can_sync,
            "message": save_message,
        },
        "records": records,
        "last_sync": last_sync,
        "health": {"status": health_status, "issues": issues},
        "needs_confirmation": {
            "unresolved_players": unresolved,
            "identity_conflicts": identity_conflicts,
            "quarantined_rows": repair_counts.get("pending_review", 0),
            "total": pending_total,
        },
        "repairs": repair_counts,
    }


@router.get("/data-hub/capabilities", summary="自动识别支持的来源与格式")
def data_hub_capabilities() -> dict[str, Any]:
    """What the automatic engine accepts. No internal table or field names are exposed."""
    return {
        "schema_major": SUPPORTED_MAJOR,
        "sources": [
            {"id": "fm27_live_reader", "label": "FM27 实时读取"},
            {"id": "fmsuperscout", "label": "FMSuperScout 导出"},
            {"id": "manual", "label": "手动数据文件"},
        ],
        "formats": [
            {"id": "json", "label": "JSON 扫描报文"},
            {"id": "ndjson", "label": "NDJSON 扫描报文"},
            {"id": "fmscout_dump", "label": "FMSuperScout 导出文件"},
        ],
        "auto_detection": True,
        "repair_levels": [1, 2, 3],
    }


@router.post("/data-hub/import", status_code=201, summary="一键导入（自动识别 / 校验 / 修复 / 去重 / 验证）")
async def data_hub_import(
    request: Request,
    save_id: int | None = Query(default=None),
    save_identity_id: int | None = Query(default=None),
    save_session_id: int | None = Query(default=None),
    operation_id: str | None = Query(default=None, max_length=64),
    dry_run: bool = Query(default=False),
    filename: str | None = Query(default=None, max_length=255),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
    user=Depends(get_current_user),
) -> dict[str, Any]:
    """The single import entry point.

    ``dry_run=true`` performs detection, repair and validation but writes nothing; the desktop UI uses it for the
    pre-flight check behind the progress bar.
    """
    raw = await read_request_payload(request, what="数据文件")
    if not raw:
        raise HTTPException(status_code=422, detail={"code": "empty_payload", "message": "文件内容为空"})

    target = db.get(FmSave, save_id) if save_id else save
    if target is None or target.user_id != user.id:
        raise HTTPException(status_code=404, detail={"code": "save_not_found", "message": "存档不存在"})

    fence = None
    imported_identity_id = None
    imported_session_id = None
    if not dry_run:
        context, fence = _require_write_fence(
            db,
            target,
            identity_id=save_identity_id,
            session_id=save_session_id,
            operation_id=operation_id,
            endpoint="data-hub/import",
        )
        imported_identity_id = context.identity_id if context else None
        imported_session_id = context.session_id if context else None

    engine = AutomaticDataImportEngine(db)
    try:
        async with upload_slot():
            report = await asyncio.to_thread(
                engine.run,
                target.id,
                raw,
                identity_id=imported_identity_id,
                session_id=imported_session_id,
                fence=fence,
                operation_id=operation_id,
                dry_run=dry_run,
                filename=filename,
            )
    except DetectionError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": exc.message}) from exc
    except ProtocolError as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_payload", "message": str(exc)}) from exc
    except ImportInProgressError as busy:
        raise HTTPException(
            status_code=409,
            detail={"code": "import_in_progress", "message": "同一份数据正在导入中，请稍后重试", "job_id": busy.job.id},
        ) from busy
    except WriteRejected as rejection:
        _raise_write_rejected(db, target, rejection, operation_id=operation_id)
    except (ImportCancelled, OperationConflict, OperationRejected) as exc:
        raise _import_failure(exc) from exc
    if report.status == "BLOCKED":
        message = report.detection.message or (report.warnings[0] if report.warnings else "数据无法导入")
        raise HTTPException(
            status_code=422,
            detail={"code": report.detection.code or "invalid_payload", "message": message},
        )
    return report.payload()


@router.get("/data-hub/repairs", summary="按导入批次查询自动修复与隔离审计")
def data_hub_repairs(
    import_job_id: int | None = Query(default=None),
    decision: str | None = Query(default=None, pattern="^(repaired|quarantined)$"),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
    user=Depends(get_current_user),
) -> dict[str, Any]:
    """Developer diagnostics: which rule touched which row, before/after values, and what was quarantined."""
    if import_job_id is not None:
        job = db.get(ImportJob, import_job_id)
        if job is None or job.fm_save_id != save.id:
            raise HTTPException(status_code=404, detail={"code": "import_not_found", "message": "导入批次不存在"})
    return list_repairs(
        db,
        save.id,
        import_job_id=import_job_id,
        decision=decision,
        limit=limit,
        offset=offset,
    )


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
