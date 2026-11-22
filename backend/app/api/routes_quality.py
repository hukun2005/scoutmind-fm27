"""Data-quality rule API (V3.2 SM-066A)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import FmSave, ImportJob
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
