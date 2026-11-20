"""Recruitment Engine endpoints: scored search, hidden value, comparison and shortlists."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..analytics.recruitment import (
    DIMENSION_WEIGHTS,
    POSITION_TEMPLATES,
    build_shortlist,
    compare_players,
    hidden_value,
    list_shortlists,
    player_score,
    search_recruitment,
    shortlist_detail,
)
from ..db import get_db
from ..models import FmSave
from ..schemas import CompareRequest, RecruitmentSearchRequest, ShortlistRequest
from .deps import get_active_save, instance_in_save_or_404, shortlist_in_save_or_404

router = APIRouter()


@router.get("/recruitment/model")
def model() -> dict[str, Any]:
    """The position templates and six-dimension weights the engine currently uses."""
    return {
        "position_templates": POSITION_TEMPLATES,
        "dimension_weights": DIMENSION_WEIGHTS,
        "note": "属性权重是初始模型，需结合 FM27 实际字段与角色职责校准，不是官方评分公式",
    }


@router.post("/recruitment/search")
def search(
    body: RecruitmentSearchRequest,
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Rank candidates for a slot with the six-dimensional score."""
    return search_recruitment(
        db,
        body.save_id or save.id,
        slot=body.slot,
        min_age=body.min_age,
        max_age=body.max_age,
        max_value=body.max_value,
        max_wage=body.max_wage,
        min_score=body.min_score,
        exclude_own_club=body.exclude_own_club,
        limit=body.limit,
    )


@router.get("/recruitment/player/{instance_id}")
def player(
    instance_id: int,
    save_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Full scout report for one player: score, dimensions, strengths, risks and cost."""
    instance_in_save_or_404(db, instance_id, save)
    try:
        return player_score(db, save.id, instance_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "player_not_found", "message": str(exc)}) from exc


@router.post("/recruitment/compare")
def compare(
    body: CompareRequest,
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Compare up to five players with identical weights."""
    return compare_players(db, body.save_id or save.id, body.instance_ids)


@router.get("/recruitment/hidden-value")
def hidden(
    save_id: int | None = Query(default=None),
    slot: str | None = Query(default=None),
    limit: int = Query(default=15, ge=1, le=100),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Cheap-upside candidates plus the rules that could not be evaluated."""
    return hidden_value(db, save_id or save.id, slot=slot, limit=limit)


@router.get("/recruitment/shortlists")
def shortlists(
    save_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Stored shortlists of the save."""
    items = list_shortlists(db, save_id or save.id)
    return {"items": items, "total": len(items)}


@router.get("/recruitment/shortlists/{shortlist_id}")
def shortlist(
    shortlist_id: int,
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """One stored shortlist with its ranked candidates; only the owning save may read it."""
    shortlist_in_save_or_404(db, shortlist_id, save)
    try:
        return shortlist_detail(db, shortlist_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "shortlist_not_found", "message": str(exc)}) from exc


@router.post("/recruitment/shortlists", status_code=201)
def create_shortlist(
    body: ShortlistRequest,
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Generate a shortlist and store it with its candidates."""
    result = build_shortlist(
        db,
        body.save_id or save.id,
        name=body.name,
        slot=body.slot,
        role_key=body.role_key,
        budget=body.budget,
        min_age=body.min_age,
        max_age=body.max_age,
        limit=body.limit,
        persist=body.persist,
    )
    db.commit()
    return result
