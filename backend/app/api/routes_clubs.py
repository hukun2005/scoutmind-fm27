"""Club endpoints: search, provenance and the operator's managed club."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..clubs import SOURCE_LABELS, ClubResolver
from ..db import get_db
from ..models import FmSave
from .deps import get_active_save

router = APIRouter()


class UserClubRequest(BaseModel):
    """Body of the managed-club selection."""

    club_id: int


@router.get("/clubs/search")
def search_clubs(
    query: str | None = Query(default=None, description="按俱乐部名称模糊搜索"),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """俱乐部列表，带来源与可信度；用于手动指定主执教俱乐部。"""
    items = ClubResolver(db, save.id).search(query=query, limit=limit)
    return {"items": items, "total": len(items), "source_labels": SOURCE_LABELS}


@router.get("/saves/{save_id}/user-club")
def get_user_club(save_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """当前主执教俱乐部及其来源。"""
    resolver = ClubResolver(db, save_id)
    club = resolver.user_club()
    if club is None:
        return {"club": None, "source": None, "source_label": None, "confidence": None, "assignment_source": None}
    save = db.get(FmSave, save_id)
    return {
        "assignment_source": save.user_club_source if save is not None else None,
        "club": {
            "id": club.id,
            "name": club.name,
            "league": club.league,
            "nation": club.nation,
            "reputation": club.reputation,
        },
        "source": club.source,
        "source_label": SOURCE_LABELS.get(club.source or "", club.source),
        "confidence": club.confidence,
    }


@router.put("/saves/{save_id}/user-club")
def set_user_club(save_id: int, body: UserClubRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    """指定主执教俱乐部。只改存档指针，**不移动任何球员**。"""
    resolver = ClubResolver(db, save_id)
    try:
        club = resolver.set_user_club(body.club_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "club_not_found", "message": str(exc)}) from exc
    db.commit()
    return {
        "club": {"id": club.id, "name": club.name, "league": club.league, "nation": club.nation},
        "source": "manual",
        "source_label": SOURCE_LABELS["manual"],
        "confidence": 1.0,
        "assignment_source": "manual",
        "note": "手动指定只影响阵容分析的本队判定，不会修改球员所属俱乐部",
    }


@router.delete("/saves/{save_id}/user-club")
def clear_user_club(save_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """清除主执教俱乐部；阵容分析会回到"无法确定本队"的状态。"""
    ClubResolver(db, save_id).clear_user_club()
    db.commit()
    return {"club": None}
