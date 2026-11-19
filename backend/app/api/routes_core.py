"""Health, metadata, saves and scan import endpoints."""

from __future__ import annotations

import asyncio

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..ingestion.importer import ImportOutcome, ScanImporter
from ..ingestion.squad_csv import csv_template, import_squad_csv
from ..ingestion.protocol import ProtocolError, ScanPayload
from ..models import Club, DataSource, FmSave, ImportJob, PlayerInstance, PlayerSnapshot, PlayerStatistic, Transfer
from ..schemas import SaveCreate
from ..utils import iso, payload_checksum, utcnow
from .deps import get_active_save, get_current_user
from .routes_adapters import maybe_adapt

# 同一时刻只让有限个导入进入数据库：导入是 CPU + IO 密集型，SQLite 写并发过高会锁表。
_IMPORT_SEMAPHORE = asyncio.Semaphore(settings.max_import_concurrency)
_CHUNK_SIZE = 1024 * 1024


async def _read_body_limited(request: Request) -> bytes:
    """按块读取请求体，一旦超过上限立即返回 413，而不是先读完再判断。"""
    declared = request.headers.get("content-length")
    limit = settings.max_import_bytes
    if declared is not None:
        try:
            declared_bytes = int(declared)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={"code": "invalid_content_length", "message": "Content-Length 不是整数"},
            ) from exc
        if declared_bytes > limit:
            raise HTTPException(
                status_code=413,
                detail={"code": "payload_too_large", "message": f"扫描报文超过 {limit} 字节上限"},
            )

    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            raise HTTPException(
                status_code=413,
                detail={"code": "payload_too_large", "message": f"扫描报文超过 {limit} 字节上限"},
            )
        chunks.append(chunk)
    return b"".join(chunks)


async def _read_upload_limited(upload: Any) -> bytes:
    """分块读取 multipart 文件，超过单字段上限立即 413。"""
    limit = min(settings.max_import_bytes, settings.max_multipart_field_bytes)
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise HTTPException(
                status_code=413,
                detail={"code": "payload_too_large", "message": f"上传文件超过 {limit} 字节上限"},
            )
        chunks.append(chunk)
    return b"".join(chunks)


router = APIRouter()


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
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
    user=Depends(get_current_user),
) -> dict[str, Any]:
    """历史交易独立通道：只导入交易（可带俱乐部），不要求球员快照。

    FM 的转会历史是另一个数据源；它不应该被迫和球员扫描捆在一起，也不应该因为缺少球员数据而无法导入。
    """
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            raise HTTPException(status_code=422, detail={"code": "missing_file", "message": "缺少 file 字段"})
        raw = await upload.read()  # type: ignore[union-attr]
    else:
        raw = await request.body()
    if not raw:
        raise HTTPException(status_code=422, detail={"code": "empty_payload", "message": "交易报文为空"})
    if len(raw) > settings.max_import_bytes:
        raise HTTPException(status_code=413, detail={"code": "payload_too_large", "message": "报文超过大小限制"})
    target = db.get(FmSave, save_id) if save_id else save
    if target is None or target.user_id != user.id:
        raise HTTPException(status_code=404, detail={"code": "save_not_found", "message": "存档不存在"})
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
    outcome = ScanImporter(db).import_payload(target.id, validated, raw)
    return _outcome_payload(outcome)


@router.post("/imports/squad-csv", status_code=201)
async def import_squad_csv_route(
    request: Request,
    save_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
    user=Depends(get_current_user),
) -> dict[str, Any]:
    """导入 FM27 阵容名单（CSV）。低置信度行只报告，不建立归属。"""
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            raise HTTPException(status_code=422, detail={"code": "missing_file", "message": "缺少 file 字段"})
        raw = await upload.read()  # type: ignore[union-attr]
    else:
        raw = await request.body()
    if not raw:
        raise HTTPException(status_code=422, detail={"code": "empty_payload", "message": "CSV 内容为空"})
    if len(raw) > settings.max_import_bytes:
        raise HTTPException(status_code=413, detail={"code": "payload_too_large", "message": "文件超过大小限制"})
    target = db.get(FmSave, save_id) if save_id else save
    if target is None or target.user_id != user.id:
        raise HTTPException(status_code=404, detail={"code": "save_not_found", "message": "存档不存在"})
    try:
        result = import_squad_csv(db, target.id, raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_squad_csv", "message": str(exc)}) from exc
    db.commit()
    return result.payload()


@router.get("/imports/squad-csv/template")
def squad_csv_template() -> dict[str, Any]:
    """可直接填写并上传的阵容 CSV 模板。"""
    return {"filename": "scoutmind-squad.csv", "content": csv_template()}


@router.get("/imports")
def list_imports(
    save_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Import history for the save."""
    target = save_id or save.id
    query = select(ImportJob).where(ImportJob.fm_save_id == target)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(ImportJob.received_at.desc()).limit(limit).offset(offset))
    return {"items": [_job_payload(row) for row in rows], "total": int(total or 0)}


@router.post("/imports/scan", status_code=201)
async def import_scan(
    request: Request,
    save_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
    user=Depends(get_current_user),
) -> dict[str, Any]:
    """Accept a scan payload as JSON, NDJSON or a multipart ``file`` upload and import it idempotently."""
    content_type = request.headers.get("content-type", "")
    raw = b""
    if content_type.startswith("multipart/form-data"):
        form = await request.form(
            max_files=settings.max_multipart_files,
            max_fields=settings.max_multipart_fields,
        )
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            raise HTTPException(status_code=422, detail={"code": "missing_file", "message": "缺少 file 字段"})
        raw = await _read_upload_limited(upload)  # type: ignore[arg-type]
    else:
        raw = await _read_body_limited(request)
    if not raw:
        raise HTTPException(status_code=422, detail={"code": "empty_payload", "message": "扫描报文为空"})
    target_save = db.get(FmSave, save_id) if save_id else save
    if target_save is None or target_save.user_id != user.id:
        raise HTTPException(status_code=404, detail={"code": "save_not_found", "message": "存档不存在"})
    importer = ScanImporter(db)
    # A dropped FMSuperScout dump is converted by the adapter layer, then imported like any other scan.
    adapted = maybe_adapt(raw)
    if adapted is not None:
        payload, report = adapted
        try:
            validated = ScanPayload.model_validate(payload)
        except ValueError as exc:  # pydantic raises ValidationError, a ValueError subclass
            raise ProtocolError(f"FMSuperScout 适配结果不符合扫描协议：{exc}") from exc
        async with _IMPORT_SEMAPHORE:
            outcome = importer.import_payload(target_save.id, validated, raw)
        body = _outcome_payload(outcome)
        body["adapted_by"] = report
        return body
    async with _IMPORT_SEMAPHORE:
        outcome = importer.import_bytes(target_save.id, raw)
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
        "received_at": iso(job.received_at),
        "finished_at": iso(job.finished_at),
        "player_count": job.player_count,
        "transfer_count": job.transfer_count,
        "warnings": json.loads(job.warnings_json or "[]"),
        "coverage": json.loads(job.coverage_json or "{}"),
        "raw_payload_path": job.raw_payload_path,
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
        "snapshots_created": outcome.snapshots_created,
        "snapshots_skipped": outcome.snapshots_skipped,
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

