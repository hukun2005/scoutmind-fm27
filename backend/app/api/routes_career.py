"""球员职业轨迹 API（SM-014）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analytics.career import player_career
from ..db import get_db
from ..models import FmSave
from .deps import get_current_user

router = APIRouter()


@router.get("/players/{instance_id}/career", summary="球员职业轨迹（跨存档，按全局身份）")
def career(
    instance_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
) -> dict[str, Any]:
    """跨该用户的全部存档返回轨迹；不属于该用户的存档不参与。"""
    save_ids = set(db.scalars(select(FmSave.id).where(FmSave.user_id == user.id)))
    if not save_ids:
        raise HTTPException(status_code=404, detail={"code": "player_not_found", "message": "球员不存在"})
    try:
        return player_career(db, instance_id, allowed_save_ids=save_ids)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "player_not_found", "message": str(exc)}) from exc
