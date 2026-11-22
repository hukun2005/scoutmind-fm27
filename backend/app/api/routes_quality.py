"""Data-quality rule API (V3.2 SM-066A)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import FmSave, ImportJob, PlayerObservationCanonical
from ..quality.dedup import build_canonicals, canonical_summary
from ..quality.rules import rule_catalog, run_quality_rules
from .deps import get_active_save

router = APIRouter()


@router.get("/data-quality/rules", summary="数据质量规则目录")
def quality_rules() -> dict[str, Any]:
    """Return the deterministic rule catalog (read-only)."""
    rules = rule_catalog()
    return {"items": rules, "total": len(rules)}


@router.get("/data-quality/report", summary="数据质量规则报告")
def quality_report(
    import_job_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Run the rule engine for the save (or one import job); never mutates data."""
    if import_job_id is not None:
        job = db.get(ImportJob, import_job_id)
        if job is None or job.fm_save_id != save.id:
            raise HTTPException(status_code=404, detail={"code": "import_not_found", "message": "导入批次不存在"})
    return run_quality_rules(db, save.id, import_job_id=import_job_id)


@router.get("/data-quality/canonical/summary", summary="同日观测 canonical 摘要")
def canonical_summary_route(
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Read-only counts for canonical/duplicate governance."""
    return canonical_summary(db, save.id)


@router.post("/data-quality/canonical/scan", summary="评估同日重复/冲突并生成 canonical")
def canonical_scan(
    dry_run: bool = Query(default=True, description="默认只预览；显式 false 才写 canonical 表"),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Never deletes raw snapshots; conflicting groups stay needs_review."""
    return build_canonicals(db, save.id, dry_run=dry_run)


@router.get("/data-quality/canonical", summary="查看 canonical 决策")
def canonical_list(
    status: str | None = Query(default=None, pattern="^(resolved|needs_review)$"),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    query = select(PlayerObservationCanonical).where(PlayerObservationCanonical.fm_save_id == save.id)
    if status:
        query = query.where(PlayerObservationCanonical.status == status)
    rows = list(db.scalars(query.order_by(PlayerObservationCanonical.id).limit(limit)))
    return {
        "items": [
            {
                "id": row.id,
                "player_instance_id": row.player_instance_id,
                "game_date": row.game_date.isoformat(),
                "canonical_snapshot_id": row.canonical_snapshot_id,
                "status": row.status,
                "conflict": row.conflict,
                "snapshot_count": row.snapshot_count,
                "distinct_content_count": row.distinct_content_count,
                "reason": row.reason,
            }
            for row in rows
        ],
        "total": len(rows),
    }
