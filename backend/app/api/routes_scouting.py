"""Scouting endpoints: role templates, explainable role scores and ranking."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analytics.players import PlayerFilter, list_players
from ..analytics.scoring import evaluate_player, list_roles
from ..db import get_db
from ..models import FmSave
from ..schemas import EvaluateRequest, ScoutingSearchRequest
from .deps import get_active_save, get_current_user, owned_save_or_404

router = APIRouter()


@router.get("/scouting/roles")
def roles(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Role templates with their attribute weights and version."""
    items = list_roles(db)
    db.commit()
    return {"items": items, "total": len(items)}


@router.post("/scouting/evaluate")
def evaluate(body: EvaluateRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Score one player against one role, returning the component breakdown."""
    try:
        result = evaluate_player(db, body.instance_id, body.role_key)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "role_or_player_not_found", "message": str(exc)}) from exc
    db.commit()
    return result


@router.post("/scouting/search")
def search(
    body: ScoutingSearchRequest,
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Rank players by role score, with coverage shown for every candidate."""
    role = next((item for item in list_roles(db) if item["key"] == body.role_key), None)
    if body.role_key and role is None:
        raise HTTPException(status_code=404, detail={"code": "role_not_found", "message": "战术角色不存在"})
    position_group = body.position_group or (str(role["position_group"]) if role else None)
    filters = PlayerFilter(
        query=body.query,
        position=body.position.upper() if body.position else None,
        position_group=position_group,
        min_age=body.min_age,
        max_age=body.max_age,
        min_ca=body.min_ca,
        min_pa=body.min_pa,
        max_value=body.max_value,
        max_wage=body.max_wage,
        club_id=body.club_id,
        sort="-ca",
    )
    target = owned_save_or_404(db, body.save_id, user) if body.save_id is not None else save
    result = list_players(db, target.id, filters, limit=body.limit, offset=0)
    candidates: list[dict[str, Any]] = []
    for item in result["items"]:
        entry: dict[str, Any] = {"player": item, "role_key": body.role_key, "score": None, "coverage": None}
        if body.role_key:
            scored = evaluate_player(db, int(item["instance_id"]), body.role_key)
            entry.update({"score": scored["score"], "coverage": scored["coverage"]})
        candidates.append(entry)
    candidates.sort(key=lambda entry: (entry["score"] is None, -(entry["score"] or 0)))
    db.commit()
    return {"items": candidates, "total": result["total"], "role_key": body.role_key, "coverage": result["coverage"]}


@router.get("/scouting/rank")
def rank(
    instance_id: int = Query(...),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Show every role score for one player, which is what the profile screen displays."""
    roles_list = list_roles(db)
    scores = []
    for role in roles_list:
        try:
            scores.append(evaluate_player(db, instance_id, str(role["key"])))
        except ValueError:
            continue
    db.commit()
    scores.sort(key=lambda item: float(item["score"]), reverse=True)
    return {"instance_id": instance_id, "items": scores}
