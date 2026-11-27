"""Health, metadata, saves and scan import endpoints."""

from __future__ import annotations

import asyncio

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..analytics.longitudinal import quality_summary
from ..ingestion import cancellation
from ..ingestion.importer import (
    ImportCancelled,
    ImportInProgressError,
    ImportOutcome,
    OperationConflict,
    OperationRejected,
    ScanImporter,
)
from ..ingestion.squad_csv import csv_template, import_squad_csv
from ..ingestion.protocol import ProtocolError, ScanPayload
from ..models import Club, DataSource, FmSave, ImportJob, ImportRow, PlayerInstance, PlayerSnapshot, PlayerStatistic, SaveIdentity, Transfer
from ..schemas import SaveCreate, SaveResolveIn
from ..services.save_identity import record_audit
from ..services.write_safety import (
    WriteRejected,
    acquire_write_fence,
    record_legacy_write,
    record_rejection,
    resolve_write_context,
)
from ..utils import iso, payload_checksum, utcnow
from .deps import get_active_save, get_current_user
from .routes_adapters import maybe_adapt
from .uploads import import_slot, read_request_payload, upload_slot

# 导入写库限流统一由 uploads.import_slot() 提供（按事件循环惰性创建，避免跨循环复用）。


router = APIRouter()


def _trigger_online_learning(db: Session, save_id: int) -> None:
    """导入成功后按存档触发增量学习；已有活跃任务时复用，失败不影响导入结果。"""
    if not settings.learning_auto_start:
        return
    from ..services import background_scan

    try:
        background_scan.create_task(
            db, save_id, background_scan.TRANSFER_LEARNING, created_by="auto"
        )
    except Exception:  # noqa: BLE001 - 学习触发失败不能破坏已完成的导入
        db.rollback()


def _require_write_fence(
    db: Session,
    save: FmSave,
    *,
    identity_id: int | None,
    session_id: int | None,
    operation_id: str | None = None,
    endpoint: str = "import",
):
    """统一写入入口：返回 (上下文, 门票)。历史存档（无 gate 且未声明上下文）返回 (None, None)。"""
    context = resolve_write_context(
        db,
        save,
        identity_id=identity_id,
        session_id=session_id,
        operation_id=operation_id,
    )
    if context is None:
        # 旧客户端兼容路径：显式写审计，便于后续收紧为强制上下文。
        record_legacy_write(db, save_id=save.id, operation_id=operation_id, endpoint=endpoint)
        return None, None
    return context, acquire_write_fence(db, context)


def _raise_write_rejected(
    db: Session,
    save: FmSave,
    rejection: WriteRejected,
    *,
    operation_id: str | None,
) -> None:
    try:
        record_rejection(
            db,
            save_id=save.id,
            session_id=rejection.session_id,
            identity_id=None,
            capture_id=None,
            code=rejection.code,
            message=rejection.message,
            generation=rejection.generation,
            operation_id=operation_id,
        )
        db.commit()
    except Exception:  # 审计失败不能掩盖真正的拒绝结果
        db.rollback()
    raise HTTPException(
        status_code=409,
        detail={
            "code": rejection.code,
            "message": rejection.message,
            "save_id": save.id,
            "generation": rejection.generation,
        },
    ) from rejection


@router.get("/meta/bootstrap")
def bootstrap(db: Session = Depends(get_db), user=Depends(get_current_user)) -> dict[str, Any]:
    """Everything the SPA needs on first load: saves, sources, counts and capabilities."""
    saves = list(db.scalars(select(FmSave).where(FmSave.user_id == user.id).order_by(FmSave.created_at)))
    active = next((save for save in saves if save.is_active), saves[0] if saves else None)
    sources = list(db.scalars(select(DataSource).where(DataSource.fm_save_id == active.id))) if active else []
    warnings: list[str] = []
    if not settings.api_token:
        warnings.append("未配置 SCOUTMIND_API_TOKEN，本地 API 仅应在 127.0.0.1 上监听")
    return {
        "product": settings.app_name,
        "version": settings.version,
        "demo_mode": any(source.source == "synthetic_fixture" for source in sources),
        "auth_required": bool(settings.api_token),
        "active_save_id": active.id if active else None,
        "saves": [_save_payload(save, db) for save in saves],
        "data_sources": [
            {"source": source.source, "records": source.record_count, "last_seen_at": iso(source.last_seen_at)}
            for source in sources
        ],
        "capabilities": {
            "live_reader": any(source.source == "fm27_live_reader" for source in sources),
            "save_parser": any(source.source == "fm_save_parser" for source in sources),
            "fmscout_adapter": True,
            "fmscout_data": any(source.source == "fmsuperscout" for source in sources),
            "agent_llm": bool(settings.agent_llm_enabled),
            "watchlist": True,
            "transfer_intelligence": True,
            "squad_intelligence": True,
            "recruitment_engine": True,
            "player_development": True,
            "performance_analytics": True,
            "statistics": bool(
                active
                and db.scalar(
                    select(func.count())
                    .select_from(PlayerStatistic)
                    .join(PlayerInstance, PlayerInstance.id == PlayerStatistic.player_instance_id)
                    .where(PlayerInstance.fm_save_id == active.id)
                )
            )
            if active
            else False,
        },
        "warnings": warnings,
    }


@router.get("/saves")
def list_saves(db: Session = Depends(get_db), user=Depends(get_current_user)) -> dict[str, Any]:
    """Every save of the local user with its record counts."""
    saves = list(db.scalars(select(FmSave).where(FmSave.user_id == user.id).order_by(FmSave.created_at)))
    return {"items": [_save_payload(save, db) for save in saves], "total": len(saves)}


@router.post("/saves", status_code=201)
def create_save(body: SaveCreate, db: Session = Depends(get_db), user=Depends(get_current_user)) -> dict[str, Any]:
    """Create a save and make it active."""
    for existing in db.scalars(select(FmSave).where(FmSave.user_id == user.id)):
        existing.is_active = False
    save = FmSave(
        user_id=user.id,
        name=body.name,
        game_version=body.game_version,
        game_build=body.game_build,
        is_active=True,
    )
    db.add(save)
    db.commit()
    return _save_payload(save, db)


@router.post("/saves/resolve")
def resolve_save(body: SaveResolveIn, db: Session = Depends(get_db), user=Depends(get_current_user)) -> dict[str, Any]:
    """Find the save that owns ``fingerprint``; create and activate one when it is unseen.

    Agent 用它把「读取器识别出的存档文件指纹」映射到后端存档，避免切换存档时把两个存档的数据
    混进同一个 ``fm_save``（V3.2.7.5 D-01）。
    """
    fingerprint = body.fingerprint.strip()
    if not fingerprint.startswith("si:v1:"):
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_fingerprint", "message": "存档指纹必须以 si:v1: 开头"},
        )
    identity = db.scalar(
        select(SaveIdentity)
        .where(
            SaveIdentity.identity_fingerprint == fingerprint,
            SaveIdentity.fm_save_id.is_not(None),
        )
        .order_by(SaveIdentity.last_seen_at.desc())
        .limit(1)
    )
    save = db.get(FmSave, identity.fm_save_id) if identity is not None else None
    created = False
    if save is None or save.user_id != user.id:
        suffix = fingerprint.rsplit(":", 1)[-1][:8] or "unknown"
        for existing in db.scalars(select(FmSave).where(FmSave.user_id == user.id)):
            existing.is_active = False
        save = FmSave(user_id=user.id, name=body.name or f"FM27 存档 {suffix}", is_active=True)
        db.add(save)
        db.flush()
        # 先登记一条 unknown 身份，保证同一指纹再次解析时能找回这个存档；
        # Agent 随后注册正式身份会更新同一行，而不是新建。
        db.add(
            SaveIdentity(
                fm_save_id=save.id,
                identity_fingerprint=fingerprint,
                identity_status="unknown",
                identity_confidence="none",
                identity_kind="save_file",
            )
        )
        db.commit()
        created = True
    elif not save.is_active:
        for existing in db.scalars(select(FmSave).where(FmSave.user_id == user.id, FmSave.id != save.id)):
            existing.is_active = False
        save.is_active = True
        db.commit()
    return {"save": _save_payload(save, db), "created": created, "save_id": save.id}


@router.get("/saves/{save_id}/summary")
def save_summary(save_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)) -> dict[str, Any]:
    """Coverage summary of one save."""
    save = db.get(FmSave, save_id)
    if save is None or save.user_id != user.id:
        raise HTTPException(status_code=404, detail={"code": "save_not_found", "message": "存档不存在"})
    last = db.scalar(
        select(ImportJob).where(ImportJob.fm_save_id == save_id).order_by(ImportJob.received_at.desc()).limit(1)
    )
    return {
        "save": _save_payload(save, db),
        "coverage": {
            "players": db.scalar(select(func.count()).select_from(PlayerInstance).where(PlayerInstance.fm_save_id == save_id)),
            "snapshots": db.scalar(
                select(func.count())
                .select_from(PlayerSnapshot)
                .join(PlayerInstance, PlayerInstance.id == PlayerSnapshot.player_instance_id)
                .where(PlayerInstance.fm_save_id == save_id)
            ),
            "transfers": db.scalar(select(func.count()).select_from(Transfer).where(Transfer.fm_save_id == save_id)),
            "clubs": db.scalar(select(func.count()).select_from(Club).where(Club.fm_save_id == save_id)),
        },
        "last_import": _job_payload(last) if last else None,
    }


@router.post("/imports/transfers", status_code=201, summary="历史交易独立导入")
async def import_transfers(
    request: Request,
    save_id: int | None = Query(default=None),
    save_identity_id: int | None = Query(default=None),
    save_session_id: int | None = Query(default=None),
    operation_id: str | None = Query(default=None, max_length=64),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
    user=Depends(get_current_user),
) -> dict[str, Any]:
    """历史交易独立通道：只导入交易（可带俱乐部），不要求球员快照。

    FM 的转会历史是另一个数据源；它不应该被迫和球员扫描捆在一起，也不应该因为缺少球员数据而无法导入。
    """
    raw = await read_request_payload(request, what="交易报文")
    if not raw:
        raise HTTPException(status_code=422, detail={"code": "empty_payload", "message": "交易报文为空"})
    target = db.get(FmSave, save_id) if save_id else save
    if target is None or target.user_id != user.id:
        raise HTTPException(status_code=404, detail={"code": "save_not_found", "message": "存档不存在"})
    context, fence = _require_write_fence(
        db,
        target,
        identity_id=save_identity_id,
        session_id=save_session_id,
        operation_id=operation_id,
        endpoint="imports/transfers",
    )
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"交易报文不是有效 JSON：{exc}") from exc
    if not isinstance(document, dict) or not document.get("transfers"):
        raise HTTPException(
            status_code=422,
            detail={"code": "no_transfers", "message": "报文里没有 transfers 数组；球员扫描请走 /imports/scan"},
        )
    document.setdefault("scan", {"scan_id": f"transfers-{payload_checksum(raw)}"})
    if isinstance(document["scan"], dict):
        document["scan"].setdefault("observed_at", utcnow().isoformat())
        document["scan"].setdefault("scan_id", f"transfers-{payload_checksum(raw)}")
    try:
        validated = ScanPayload.model_validate(document)
    except ValueError as exc:
        raise ProtocolError(f"交易报文不符合协议：{exc}") from exc
    try:
        outcome = ScanImporter(db).import_payload(
            target.id,
            validated,
            raw,
            identity_id=context.identity_id if context else None,
            session_id=context.session_id if context else None,
            fence=fence,
            operation_id=operation_id,
        )
    except WriteRejected as rejection:
        _raise_write_rejected(db, target, rejection, operation_id=operation_id)
    except (ImportCancelled, OperationConflict, OperationRejected) as exc:
        raise _import_failure(exc) from exc
    _trigger_online_learning(db, target.id)
    return _outcome_payload(outcome)


@router.post("/imports/squad-csv", status_code=201)
async def import_squad_csv_route(
    request: Request,
    save_id: int | None = Query(default=None),
    save_identity_id: int | None = Query(default=None),
    save_session_id: int | None = Query(default=None),
    operation_id: str | None = Query(default=None, max_length=64),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
    user=Depends(get_current_user),
) -> dict[str, Any]:
    """导入 FM27 阵容名单（CSV）。低置信度行只报告，不建立归属。"""
    raw = await read_request_payload(request, what="阵容 CSV")
    if not raw:
        raise HTTPException(status_code=422, detail={"code": "empty_payload", "message": "CSV 内容为空"})
    if len(raw) > settings.max_import_bytes:
        raise HTTPException(status_code=413, detail={"code": "payload_too_large", "message": "文件超过大小限制"})
    target = db.get(FmSave, save_id) if save_id else save
    if target is None or target.user_id != user.id:
        raise HTTPException(status_code=404, detail={"code": "save_not_found", "message": "存档不存在"})
    _context, fence = _require_write_fence(
        db,
        target,
        identity_id=save_identity_id,
        session_id=save_session_id,
        operation_id=operation_id,
        endpoint="imports/squad-csv",
    )
    try:
        result = import_squad_csv(db, target.id, raw)
        if fence is not None:
            fence.assert_current(db)
    except WriteRejected as rejection:
        db.rollback()
        _raise_write_rejected(db, target, rejection, operation_id=operation_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_squad_csv", "message": str(exc)}) from exc
    db.commit()
    return result.payload()


@router.get("/imports/squad-csv/template")
def squad_csv_template() -> dict[str, Any]:
    """可直接填写并上传的阵容 CSV 模板。"""
    return {"filename": "scoutmind-squad.csv", "content": csv_template()}


@router.get("/data-quality/summary", summary="导入后数据质量摘要")
def data_quality_summary(
    import_job_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """每次导入后的质量摘要：数量、独立日期、覆盖率、重复与来源。"""
    if import_job_id is not None:
        job = db.get(ImportJob, import_job_id)
        if job is None or job.fm_save_id != save.id:
            raise HTTPException(status_code=404, detail={"code": "import_not_found", "message": "导入批次不存在"})
    return quality_summary(db, save.id, import_job_id)


@router.get("/imports")
def list_imports(
    save_id: int | None = Query(default=None),
    scan_id: str | None = Query(default=None, max_length=64),
    status: str | None = Query(default=None, max_length=16),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Import history for the save, optionally narrowed to one scan or one status.

    The Agent uses this to verify whether a timed-out upload actually finished server-side instead of
    assuming failure and re-uploading.
    """
    target = save.id
    if save_id is not None and save_id != save.id:
        target_save = db.get(FmSave, save_id)
        if target_save is None or target_save.user_id != save.user_id:
            raise HTTPException(status_code=404, detail={"code": "save_not_found", "message": "存档不存在"})
        target = target_save.id
    query = select(ImportJob).where(ImportJob.fm_save_id == target)
    if scan_id:
        query = query.where(ImportJob.scan_id == scan_id)
    if status:
        query = query.where(ImportJob.status == status)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(ImportJob.received_at.desc(), ImportJob.id.desc()).limit(limit).offset(offset))
    return {"items": [_job_payload(row) for row in rows], "total": int(total or 0)}


@router.get("/imports/{job_id}")
def get_import(
    job_id: int,
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """One import job: status, counts and the rejected-row codes needed to explain a failure."""
    job = db.get(ImportJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail={"code": "import_not_found", "message": "导入批次不存在"})
    owner = db.get(FmSave, job.fm_save_id)
    if owner is None or owner.user_id != save.user_id:
        raise HTTPException(status_code=404, detail={"code": "import_not_found", "message": "导入批次不存在"})
    rejected = db.execute(
        select(ImportRow.code, ImportRow.entity, func.count())
        .where(ImportRow.import_job_id == job.id, ImportRow.entity != "scan")
        .group_by(ImportRow.code, ImportRow.entity)
        .order_by(ImportRow.code)
    ).all()
    return {
        **_job_payload(job),
        "rejected_rows": int(sum(row[2] for row in rejected)),
        "rejected_codes": [
            {"code": code, "entity": entity, "count": int(count)} for code, entity, count in rejected
        ],
        "retryable": job.status in {"failed", "partial", "running"},
        "cancellable": job.status in {"queued", "running", "cancel_requested"},
    }


@router.post("/imports/{job_id}/cancel")
def cancel_import(
    job_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
) -> dict[str, Any]:
    """请求取消一个排队中或运行中的导入任务（幂等）。

    语义：
    * ``queued`` → 直接原子落 ``cancelled``（尚未被 Worker 领取，无需等待检查点）；
    * ``running`` → ``cancel_requested``，Worker 在下一个安全检查点回滚并落 ``cancelled``；
    * 已是 ``cancelled`` → 原样返回（幂等，不重复写审计）；
    * 已 ``succeeded/partial/failed/rejected`` → 409，已提交的事务不可撤销。
    """
    job = db.get(ImportJob, job_id)
    owner = db.get(FmSave, job.fm_save_id) if job is not None else None
    if job is None or owner is None or owner.user_id != user.id:
        raise HTTPException(status_code=404, detail={"code": "import_not_found", "message": "导入批次不存在"})

    if job.status == "cancelled":
        return {**_job_payload(job), "cancel_requested": False, "already_cancelled": True}
    if job.status not in {"queued", "running", "cancel_requested"}:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "import_not_cancellable",
                "message": f"任务已结束（{job.status}），已提交的导入不可撤销",
                "job_id": job.id,
                "status": job.status,
            },
        )

    previous_status = job.status
    now = utcnow()
    cancelled_directly = False
    if previous_status == "queued":
        # 排队任务尚未被 Worker 领取：直接原子地落到 cancelled，不依赖进程内事件。
        result = db.execute(
            update(ImportJob)
            .where(ImportJob.id == job.id, ImportJob.status == "queued")
            .values(status="cancelled", cancel_requested_at=now, cancelled_at=now)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount == 1:
            cancelled_directly = True
            record_audit(
                db,
                save_id=job.fm_save_id,
                identity_id=job.save_identity_id,
                session_id=job.save_session_id,
                event_type="worker_cancel_requested",
                old_status="queued",
                new_status="cancel_requested",
                evidence_summary={"job_id": job.id, "scan_id": job.scan_id, "operation_id": job.operation_id, "direct": True},
                reason="user_cancel",
                actor="user",
            )
            record_audit(
                db,
                save_id=job.fm_save_id,
                identity_id=job.save_identity_id,
                session_id=job.save_session_id,
                event_type="worker_cancelled",
                old_status="cancel_requested",
                new_status="cancelled",
                evidence_summary={"job_id": job.id, "scan_id": job.scan_id, "operation_id": job.operation_id, "direct": True},
                reason="user_cancel",
                actor="user",
            )

    if not cancelled_directly:
        result = db.execute(
            update(ImportJob)
            .where(ImportJob.id == job.id, ImportJob.status.in_(("queued", "running")))
            .values(status="cancel_requested", cancel_requested_at=now)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount == 1:
            cancellation.request_cancel(job.id)
            record_audit(
                db,
                save_id=job.fm_save_id,
                identity_id=job.save_identity_id,
                session_id=job.save_session_id,
                event_type="worker_cancel_requested",
                old_status=previous_status,
                new_status="cancel_requested",
                evidence_summary={
                    "job_id": job.id,
                    "scan_id": job.scan_id,
                    "operation_id": job.operation_id,
                    "generation": job.save_generation,
                    "attempt_count": job.attempt_count,
                },
                reason="user_cancel",
                actor="user",
            )
    db.commit()
    db.expire_all()
    job = db.get(ImportJob, job.id)
    if job is None:  # 理论不可达：同一事务内刚更新过
        raise HTTPException(status_code=404, detail={"code": "import_not_found", "message": "导入批次不存在"})
    if job.status not in {"queued", "running", "cancel_requested", "cancelled"}:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "import_not_cancellable",
                "message": f"任务在取消请求到达前已结束（{job.status}），已提交的导入不可撤销",
                "job_id": job.id,
                "status": job.status,
            },
        )
    return {
        **_job_payload(job),
        "cancel_requested": job.status in {"cancel_requested", "queued", "running"},
        "already_cancelled": job.status == "cancelled",
    }


def _import_failure(exc: Exception, job_id_hint: int | None = None) -> HTTPException:
    """把导入器的取消/冲突/拒绝异常翻译成稳定的 409 响应。"""
    if isinstance(exc, ImportCancelled):
        return HTTPException(
            status_code=409,
            detail={
                "code": "import_cancelled",
                "message": "导入已在提交前取消，未写入任何业务数据",
                "job_id": exc.job.id,
                "status": exc.job.status,
            },
        )
    if isinstance(exc, OperationRejected):
        return HTTPException(
            status_code=409,
            detail={
                "code": "operation_rejected",
                "message": "该 operation_id 曾因写入安全策略被拒绝，不能自动重放；请重新识别存档并生成新的 operation_id",
                "job_id": exc.job.id,
                "rejected_reason": exc.job.rejected_reason,
                "status": exc.job.status,
            },
        )
    if isinstance(exc, OperationConflict):
        return HTTPException(
            status_code=409,
            detail={
                "code": exc.code,
                "message": exc.message,
                "job_id": exc.job.id,
                "status": exc.job.status,
            },
        )
    return HTTPException(
        status_code=409,
        detail={"code": "import_failed", "message": str(exc), "job_id": job_id_hint},
    )


@router.post("/imports/scan", status_code=201)
async def import_scan(
    request: Request,
    save_id: int | None = Query(default=None),
    save_identity_id: int | None = Query(default=None),
    save_session_id: int | None = Query(default=None),
    operation_id: str | None = Query(default=None, max_length=64),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
    user=Depends(get_current_user),
) -> dict[str, Any]:
    """Accept a scan payload as JSON, NDJSON or a multipart ``file`` upload and import it idempotently."""
    raw = await read_request_payload(request, what="扫描报文")
    if not raw:
        raise HTTPException(status_code=422, detail={"code": "empty_payload", "message": "扫描报文为空"})
    target_save = db.get(FmSave, save_id) if save_id else save
    if target_save is None or target_save.user_id != user.id:
        raise HTTPException(status_code=404, detail={"code": "save_not_found", "message": "存档不存在"})
    context, fence = _require_write_fence(
        db,
        target_save,
        identity_id=save_identity_id,
        session_id=save_session_id,
        operation_id=operation_id,
        endpoint="imports/scan",
    )
    imported_identity_id = context.identity_id if context else None
    imported_session_id = context.session_id if context else None
    importer = ScanImporter(db)
    # A dropped FMSuperScout dump is converted by the adapter layer, then imported like any other scan.
    # Both steps are CPU/IO heavy for a 44k-player scan: run them off the event loop so /health and
    # GET /imports keep answering while the import is in progress.
    adapted = await asyncio.to_thread(maybe_adapt, raw)
    if adapted is not None:
        payload, report = adapted
        try:
            validated = ScanPayload.model_validate(payload)
        except ValueError as exc:  # pydantic raises ValidationError, a ValueError subclass
            raise ProtocolError(f"FMSuperScout 适配结果不符合扫描协议：{exc}") from exc
        async with upload_slot(), import_slot():
            try:
                outcome = await asyncio.to_thread(
                    importer.import_payload,
                    target_save.id,
                    validated,
                    raw,
                    identity_id=imported_identity_id,
                    session_id=imported_session_id,
                    fence=fence,
                    operation_id=operation_id,
                )
            except ImportInProgressError as busy:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "import_in_progress",
                        "message": "同一扫描正在导入中，请稍后重试",
                        "job_id": busy.job.id,
                    },
                ) from busy
            except WriteRejected as rejection:
                _raise_write_rejected(db, target_save, rejection, operation_id=operation_id)
            except (ImportCancelled, OperationConflict, OperationRejected) as exc:
                raise _import_failure(exc) from exc
        body = _outcome_payload(outcome)
        body["adapted_by"] = report
        _trigger_online_learning(db, target_save.id)
        return body
    async with upload_slot(), import_slot():
        try:
            outcome = await asyncio.to_thread(
                importer.import_bytes,
                target_save.id,
                raw,
                identity_id=imported_identity_id,
                session_id=imported_session_id,
                fence=fence,
                operation_id=operation_id,
            )
        except ImportInProgressError as busy:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "import_in_progress",
                    "message": "同一扫描正在导入中，请稍后重试",
                    "job_id": busy.job.id,
                },
            ) from busy
        except WriteRejected as rejection:
            _raise_write_rejected(db, target_save, rejection, operation_id=operation_id)
        except (ImportCancelled, OperationConflict, OperationRejected) as exc:
            raise _import_failure(exc) from exc
    _trigger_online_learning(db, target_save.id)
    return _outcome_payload(outcome)


def _save_payload(save: FmSave, db: Session) -> dict[str, Any]:
    counts = db.execute(
        select(
            func.count(PlayerInstance.id),
        ).where(PlayerInstance.fm_save_id == save.id)
    ).scalar()
    snapshots = db.scalar(
        select(func.count())
        .select_from(PlayerSnapshot)
        .join(PlayerInstance, PlayerInstance.id == PlayerSnapshot.player_instance_id)
        .where(PlayerInstance.fm_save_id == save.id)
    )
    transfers = db.scalar(select(func.count()).select_from(Transfer).where(Transfer.fm_save_id == save.id))
    last_import = db.scalar(
        select(ImportJob).where(ImportJob.fm_save_id == save.id).order_by(ImportJob.received_at.desc()).limit(1)
    )
    return {
        "id": save.id,
        "name": save.name,
        "game_version": save.game_version,
        "game_build": save.game_build,
        "created_at": iso(save.created_at),
        "is_active": save.is_active,
        "player_count": int(counts or 0),
        "snapshot_count": int(snapshots or 0),
        "transfer_count": int(transfers or 0),
        "last_import_at": iso(last_import.received_at) if last_import else None,
    }


def _job_payload(job: ImportJob | None) -> dict[str, Any] | None:
    if job is None:
        return None
    return {
        "id": job.id,
        "save_id": job.fm_save_id,
        "scan_id": job.scan_id,
        "source": job.source,
        "status": job.status,
        "schema_version": job.schema_version,
        "reader_version": job.reader_version,
        "game_build": job.game_build,
        "checksum": job.checksum,
        "received_at": iso(job.received_at),
        "finished_at": iso(job.finished_at),
        "player_count": job.player_count,
        "transfer_count": job.transfer_count,
        "warnings": json.loads(job.warnings_json or "[]"),
        "coverage": json.loads(job.coverage_json or "{}"),
        "raw_payload_path": job.raw_payload_path,
        "save_identity_id": job.save_identity_id,
        "save_session_id": job.save_session_id,
        "operation_id": job.operation_id,
        "save_generation": job.save_generation,
        "rejected_reason": job.rejected_reason,
        "attempt_count": job.attempt_count,
        "cancel_requested_at": iso(job.cancel_requested_at),
        "cancelled_at": iso(job.cancelled_at),
        "cancellable": job.status in {"queued", "running"},
        "retryable": job.status in {"failed", "partial"},
    }


def _outcome_payload(outcome: ImportOutcome) -> dict[str, Any]:
    return {
        "job_id": outcome.job_id,
        "status": outcome.status,
        "duplicate": outcome.duplicate,
        "scan_id": outcome.scan_id,
        "save_id": outcome.save_id,
        "players_created": outcome.players_created,
        "players_updated": outcome.players_updated,
        "instances_matched": outcome.instances_matched,
        "players_imported": outcome.players_imported,
        "snapshots_created": outcome.snapshots_created,
        "snapshots_skipped": outcome.snapshots_skipped,
        "unresolved_created": outcome.unresolved_created,
        "unresolved_observations_created": outcome.unresolved_observations_created,
        "unresolved_observations_skipped": outcome.unresolved_observations_skipped,
        "unresolved_candidates_matched": outcome.unresolved_candidates_matched,
        "rows_skipped": outcome.rows_skipped,
        "canonical_candidates_created": outcome.canonical_candidates_created,
        "transfers_created": outcome.transfers_created,
        "transfers_updated": outcome.transfers_updated,
        "transfers_skipped": outcome.transfers_skipped,
        "statistics_created": outcome.statistics_created,
        "statistics_updated": outcome.statistics_updated,
        "rows_rejected": outcome.rows_rejected,
        "warnings": outcome.warnings,
        "errors": outcome.errors,
        "coverage": outcome.coverage,
    }

