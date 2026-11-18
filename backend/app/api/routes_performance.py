"""Performance Analytics endpoints: per-position output, trend and ability comparison."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..analytics.performance import POSITION_METRICS, performance_board, performance_profile
from ..db import get_db
from ..models import FmSave
from .deps import get_active_save

router = APIRouter()


@router.get("/performance/metrics")
def metrics() -> dict[str, Any]:
    """The metrics tracked per position group, so the UI explains what is measured."""
    return {
        "position_metrics": POSITION_METRICS,
        "note": "缺失字段在界面上显示为「数据缺失」，不会用 0 代替",
    }


@router.get("/performance/board")
def board(
    save_id: int | None = Query(default=None),
    slot: str | None = Query(default=None),
    min_minutes: int = Query(default=300, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Players with season statistics, ranked by output percentile inside their position group."""
    return performance_board(db, save_id or save.id, slot=slot, min_minutes=min_minutes, limit=limit)


@router.get("/performance/player/{instance_id}")
def player(instance_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """One player's output, trend and ability-versus-output comparison."""
    try:
        return performance_profile(db, instance_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "player_not_found", "message": str(exc)}) from exc
