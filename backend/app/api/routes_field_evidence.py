"""Field evidence capture API (V3.2 SM-061A)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import FieldEvidenceSample, FmSave, PlayerInstance
from ..schemas import FieldEvidenceCaptureBatch
from ..utils import iso, utcnow
from .deps import get_active_save, instance_in_save_or_404

router = APIRouter()


def _resolve_instance(
    db: Session,
    save: FmSave,
    item,
) -> PlayerInstance:
    if item.player_instance_id is not None:
        return instance_in_save_or_404(db, item.player_instance_id, save)
    if item.player_instance_uid:
        instance = db.scalar(
            select(PlayerInstance).where(
                PlayerInstance.fm_save_id == save.id,
                PlayerInstance.save_local_uid == item.player_instance_uid,
            )
        )
        if instance is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "player_not_found", "message": "球员不存在"},
            )
        return instance
    raise HTTPException(
        status_code=422,
        detail={"code": "instance_required", "message": "需要 player_instance_id 或 player_instance_uid"},
    )


@router.post("/field-evidence/captures", status_code=201, summary="上传字段级采样")
def capture_field_evidence(
    body: FieldEvidenceCaptureBatch,
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Persist captured samples; duplicates are idempotent, simulated Verified is rejected."""
    resolved: list[tuple[Any, PlayerInstance]] = []
    seen: set[tuple[int, str, str]] = set()
    for item in body.items:
        if item.simulated and item.validation_status == "Verified":
            raise HTTPException(
                status_code=422,
                detail={"code": "simulated_cannot_be_verified", "message": "模拟样本不能标记为 Verified"},
            )
        instance = _resolve_instance(db, save, item)
        key = (instance.id, item.field_id, item.observed_at.isoformat())
        if key in seen:
            raise HTTPException(
                status_code=422,
                detail={"code": "duplicate_in_batch", "message": "同一批次包含重复采样"},
            )
        seen.add(key)
        resolved.append((item, instance))

    saved = 0
    duplicates = 0
    for item, instance in resolved:
        existing = db.scalar(
            select(FieldEvidenceSample.id).where(
                FieldEvidenceSample.fm_save_id == save.id,
                FieldEvidenceSample.player_instance_id == instance.id,
                FieldEvidenceSample.field_id == item.field_id,
                FieldEvidenceSample.observed_at == item.observed_at,
            )
        )
        if existing is not None:
            duplicates += 1
            continue
        db.add(
            FieldEvidenceSample(
                fm_save_id=save.id,
                player_instance_id=instance.id,
                field_id=item.field_id,
                object_type=item.object_type,
                raw_value=item.raw_value,
                expected_value=item.expected_value,
                game_build=item.game_build,
                plugin_version=item.plugin_version,
                layout_version=item.layout_version,
                game_date=item.game_date,
                observed_at=item.observed_at,
                evidence_source=item.evidence_source,
                validation_status=item.validation_status,
                simulated=item.simulated,
            )
        )
        saved += 1
    db.commit()
    return {"saved": saved, "duplicates": duplicates, "total": len(body.items)}


@router.get("/field-evidence/summary", summary="字段证据采样摘要")
def field_evidence_summary(
    simulated: bool | None = Query(default=None),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Aggregate capture counts by field and status; raw data is never modified."""
    query = select(
        FieldEvidenceSample.field_id,
        FieldEvidenceSample.validation_status,
        FieldEvidenceSample.simulated,
        func.count(),
    ).where(FieldEvidenceSample.fm_save_id == save.id)
    if simulated is not None:
        query = query.where(FieldEvidenceSample.simulated == simulated)
    rows = db.execute(query.group_by(
        FieldEvidenceSample.field_id,
        FieldEvidenceSample.validation_status,
        FieldEvidenceSample.simulated,
    )).all()
    fields: dict[str, dict[str, int]] = {}
    statuses: dict[str, int] = {}
    total = 0
    for field_id, status, is_simulated, count in rows:
        bucket = fields.setdefault(field_id, {"real": 0, "simulated": 0})
        bucket["simulated" if is_simulated else "real"] += int(count)
        statuses[status] = statuses.get(status, 0) + int(count)
        total += int(count)
    return {
        "save_id": save.id,
        "total": total,
        "status_counts": statuses,
        "fields": fields,
        "generated_at": iso(utcnow()),
    }
