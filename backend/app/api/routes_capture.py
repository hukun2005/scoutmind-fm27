"""Automatic capture run API (V3.2.2 SM-067)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import CaptureRun, FmSave, ImportJob
from ..schemas import CaptureRunIn, CaptureRunUpdate
from ..utils import iso
from .deps import get_active_save
from ..services.write_safety import WriteRejected, acquire_write_fence, resolve_write_context

router = APIRouter()


def _assert_capture_fence(db: Session, fence) -> None:
    """采集元数据同样受代次保护：切换已提交时拒绝写入，避免切换后补记旧采集。"""
    if fence is None:
        return
    try:
        fence.assert_current(db)
    except WriteRejected as rejection:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "code": rejection.code,
                "message": rejection.message,
                "save_id": rejection.save_id,
                "generation": rejection.generation,
            },
        ) from rejection

STATUSES = {
    "idle", "monitoring", "date_detected", "scan_queued", "scanning", "importing",
    "completed", "retry_pending", "failed", "cancelled", "paused",
}

DATE_SOURCES = {"game_memory", "reader_date_probe", "upstream_dump", "manual", "unknown"}
DATE_CONFIDENCES = {"verified", "inferred", "unverified", "unknown"}
DATE_READ_STATUSES = {"detected", "unavailable", "unsupported_build", "layout_unverified", "regressed", "unknown"}


def _provenance(body: CaptureRunIn, latest_date) -> tuple[str, str, str]:
    """Resolve date provenance without ever promoting an unverified date.

    A verified date must name its source; a date earlier than the newest recorded one is kept but
    marked ``regressed`` so a save switch or a misread field cannot silently move the timeline back.
    """
    for value, allowed, code in (
        (body.date_source, DATE_SOURCES, "invalid_date_source"),
        (body.date_confidence, DATE_CONFIDENCES, "invalid_date_confidence"),
        (body.date_read_status, DATE_READ_STATUSES, "invalid_date_read_status"),
    ):
        if value is not None and value not in allowed:
            raise HTTPException(status_code=422, detail={"code": code, "message": f"不允许的取值：{value}"})

    if body.game_date is None:
        return (
            body.date_source or "unknown",
            body.date_confidence or "unknown",
            body.date_read_status or "unavailable",
        )

    source = body.date_source or "unknown"
    confidence = body.date_confidence or "unverified"
    read_status = body.date_read_status or "detected"
    if confidence == "verified" and source == "unknown":
        raise HTTPException(
            status_code=422,
            detail={"code": "verified_date_without_source", "message": "verified 日期必须说明来源"},
        )
    if latest_date is not None and body.game_date < latest_date:
        read_status = "regressed"
        confidence = "unverified" if confidence in {"verified", "inferred"} else confidence
    return source, confidence, read_status


def _payload(row: CaptureRun) -> dict[str, Any]:
    return {
        "id": row.id,
        "save_id": row.fm_save_id,
        "game_date": row.game_date.isoformat() if row.game_date else None,
        "reader_version": row.reader_version,
        "game_build": row.game_build,
        "scan_scope": row.scan_scope,
        "status": row.status,
        "attempt_count": row.attempt_count,
        "max_attempts": row.max_attempts,
        "next_retry_at": iso(row.next_retry_at),
        "scan_id": row.scan_id,
        "import_job_id": row.import_job_id,
        "supplemental": row.supplemental,
        "revision": row.revision,
        "observed_at": iso(row.observed_at),
        "started_at": iso(row.started_at),
        "finished_at": iso(row.finished_at),
        "error_code": row.error_code,
        "error_message": row.error_message,
        "date_source": row.date_source,
        "date_confidence": row.date_confidence,
        "date_read_status": row.date_read_status,
        "save_identity_id": row.save_identity_id,
        "save_session_id": row.save_session_id,
        "metadata": json.loads(row.metadata_json or "{}"),
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


@router.get("/captures", summary="自动采集记录")
def list_captures(
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    query = select(CaptureRun).where(CaptureRun.fm_save_id == save.id)
    if status:
        query = query.where(CaptureRun.status == status)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(CaptureRun.updated_at.desc(), CaptureRun.id.desc()).offset(offset).limit(limit))
    return {"items": [_payload(row) for row in rows], "total": int(total), "limit": limit, "offset": offset}


@router.get("/captures/summary", summary="自动采集摘要")
def capture_summary(db: Session = Depends(get_db), save: FmSave = Depends(get_active_save)) -> dict[str, Any]:
    rows = db.execute(
        select(CaptureRun.status, func.count()).where(CaptureRun.fm_save_id == save.id).group_by(CaptureRun.status)
    ).all()
    counts = {status: int(count) for status, count in rows}
    latest = db.scalar(
        select(CaptureRun).where(CaptureRun.fm_save_id == save.id).order_by(CaptureRun.updated_at.desc()).limit(1)
    )
    return {
        "save_id": save.id,
        "counts": counts,
        "total": sum(counts.values()),
        "latest": _payload(latest) if latest else None,
    }


@router.post("/captures", status_code=201, summary="登记自动采集尝试")
def register_capture(
    body: CaptureRunIn,
    save_identity_id: int | None = Query(default=None),
    save_session_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    if body.status not in STATUSES:
        raise HTTPException(status_code=422, detail={"code": "invalid_status", "message": "未知采集状态"})
    context = resolve_write_context(
        db, save, identity_id=save_identity_id, session_id=save_session_id
    )
    fence = acquire_write_fence(db, context) if context is not None else None
    if body.import_job_id is not None:
        job = db.get(ImportJob, body.import_job_id)
        if job is None or job.fm_save_id != save.id:
            raise HTTPException(status_code=404, detail={"code": "import_not_found", "message": "导入批次不存在"})
    existing = db.scalar(
        select(CaptureRun).where(
            CaptureRun.fm_save_id == save.id,
            CaptureRun.game_date == body.game_date,
            CaptureRun.reader_version == body.reader_version,
            CaptureRun.scan_scope == body.scan_scope,
            CaptureRun.revision == body.revision,
        )
    )
    row = existing or CaptureRun(
        fm_save_id=save.id,
        game_date=body.game_date,
        reader_version=body.reader_version,
        game_build=body.game_build,
        scan_scope=body.scan_scope,
        revision=body.revision,
        supplemental=body.supplemental or body.revision > 0,
    )
    row.game_build = body.game_build or row.game_build
    row.status = body.status
    if context is not None:
        row.save_identity_id = context.identity_id or row.save_identity_id
        row.save_session_id = context.session_id or row.save_session_id
    row.scan_id = body.scan_id or row.scan_id
    row.import_job_id = body.import_job_id or row.import_job_id
    row.error_code = body.error_code
    row.error_message = body.error_message
    latest_date = db.scalar(
        select(CaptureRun.game_date)
        .where(
            CaptureRun.fm_save_id == save.id,
            CaptureRun.game_date.is_not(None),
            CaptureRun.id != (existing.id if existing is not None else 0),
        )
        .order_by(CaptureRun.game_date.desc())
        .limit(1)
    )
    row.date_source, row.date_confidence, row.date_read_status = _provenance(body, latest_date)
    row.metadata_json = json.dumps(body.metadata or {}, ensure_ascii=False)
    if body.status == "scanning" and row.started_at is None:
        row.started_at = datetime.now(timezone.utc).replace(tzinfo=None)
    if body.status in {"completed", "failed", "cancelled"}:
        row.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
    if existing is None:
        db.add(row)
    _assert_capture_fence(db, fence)
    db.commit()
    db.refresh(row)
    return _payload(row)


@router.patch("/captures/{capture_id}", summary="更新自动采集状态")
def update_capture(
    capture_id: int,
    body: CaptureRunUpdate,
    save_identity_id: int | None = Query(default=None),
    save_session_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    row = db.get(CaptureRun, capture_id)
    if row is None or row.fm_save_id != save.id:
        raise HTTPException(status_code=404, detail={"code": "capture_not_found", "message": "采集记录不存在"})
    # V3.2.7.2：声明了身份/会话时，更新采集状态同样要做存档上下文校验，
    # 否则采集记录可在会话失效后被“补记”为完成。
    context = resolve_write_context(
        db, save, identity_id=save_identity_id, session_id=save_session_id
    )
    fence = acquire_write_fence(db, context) if context is not None else None
    if context is not None and context.identity_id is not None:
        if row.save_identity_id is not None and row.save_identity_id != context.identity_id:
            raise HTTPException(
                status_code=409,
                detail={"code": "save_context_mismatch", "message": "采集记录归属于其他存档身份"},
            )
        row.save_identity_id = context.identity_id
    if context is not None and context.session_id is not None:
        if row.save_session_id is not None and row.save_session_id != context.session_id:
            raise HTTPException(
                status_code=409,
                detail={"code": "save_context_mismatch", "message": "采集记录归属于其他会话"},
            )
        row.save_session_id = context.session_id
    if body.status is not None:
        if body.status not in STATUSES:
            raise HTTPException(status_code=422, detail={"code": "invalid_status", "message": "未知采集状态"})
        row.status = body.status
        if body.status == "scanning" and row.started_at is None:
            row.started_at = datetime.now(timezone.utc).replace(tzinfo=None)
        if body.status in {"completed", "failed", "cancelled"}:
            row.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
    if body.attempt_count is not None:
        row.attempt_count = body.attempt_count
    if body.next_retry_at is not None:
        row.next_retry_at = body.next_retry_at
    if body.scan_id is not None:
        row.scan_id = body.scan_id
    if body.import_job_id is not None:
        job = db.get(ImportJob, body.import_job_id)
        if job is None or job.fm_save_id != save.id:
            raise HTTPException(status_code=404, detail={"code": "import_not_found", "message": "导入批次不存在"})
        row.import_job_id = body.import_job_id
    row.error_code = body.error_code
    row.error_message = body.error_message
    _assert_capture_fence(db, fence)
    db.commit()
    db.refresh(row)
    return _payload(row)
