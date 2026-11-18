"""Player Development endpoints: growth timeline, advice, outlook and the development board."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..analytics.development import development_board, growth_profile
from ..db import get_db
from ..models import FmSave
from .deps import get_active_save

router = APIRouter()


@router.get("/development/board")
def board(
    save_id: int | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=200),
    min_age: int | None = Query(default=23, ge=10, le=60),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Players with at least two snapshots, ordered by growth rate."""
    return development_board(db, save_id or save.id, limit=limit, min_age=min_age)


@router.get("/development/player/{instance_id}")
def player(instance_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Growth timeline, rate, advice and outlook for one player."""
    try:
        return growth_profile(db, instance_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "player_not_found", "message": str(exc)}) from exc
