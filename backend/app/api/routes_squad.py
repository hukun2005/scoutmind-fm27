"""Squad Intelligence endpoints: squad score, position depth, weight profiles and contracts."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..analytics.squad import (
    DEFAULT_WEIGHTS,
    contract_monitoring,
    ensure_profiles,
    normalise_weights,
    position_depth,
    resolve_weights,
    roster,
    squad_overview,
    succession_plan,
    user_club,
)
from ..db import get_db
from ..models import FmSave, TacticalProfile
from ..schemas import SquadWeights, TacticalProfileUpdate
from ..utils import iso, utcnow
from .deps import get_active_save

router = APIRouter()


@router.get("/squad/overview")
def overview(
    save_id: int | None = Query(default=None),
    profile: str | None = Query(default=None, description="权重模板 key，如 balanced/contender/rebuild"),
    club_id: int | None = Query(default=None),
    coverage: float | None = Query(default=None, ge=0, le=1),
    depth: float | None = Query(default=None, ge=0, le=1),
    age: float | None = Query(default=None, ge=0, le=1),
    fit: float | None = Query(default=None, ge=0, le=1),
    wage: float | None = Query(default=None, ge=0, le=1),
    potential: float | None = Query(default=None, ge=0, le=1),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Squad score with every component, plus depth, age, wage, contract and succession sections."""
    overrides = {
        key: value
        for key, value in (
            ("coverage", coverage),
            ("depth", depth),
            ("age", age),
            ("fit", fit),
            ("wage", wage),
            ("potential", potential),
        )
        if value is not None
    }
    result = squad_overview(db, save_id or save.id, profile_key=profile, overrides=overrides, club_id=club_id)
    db.commit()
    return result


@router.get("/squad/depth")
def depth(
    save_id: int | None = Query(default=None),
    club_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Position depth table only; cheaper than the full overview."""
    target = save_id or save.id
    players = roster(db, target, club_id)
    rows = position_depth(players)
    return {
        "items": rows,
        "total": len(rows),
        "squad_size": len(players),
        "missing_position": sum(int(row["count"]) for row in rows if row["slot"] == "UNKNOWN"),
    }


@router.get("/squad/contracts")
def contracts(
    save_id: int | None = Query(default=None),
    club_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Contract expiry buckets for the managed squad."""
    target = save_id or save.id
    from ..analytics.squad import _reference_date  # noqa: PLC2701 - shared reference-date rule

    players = roster(db, target, club_id)
    return contract_monitoring(players, _reference_date(db, target))


@router.get("/squad/succession")
def succession(
    save_id: int | None = Query(default=None),
    club_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Internal successor or external search profile for each ageing key player."""
    players = roster(db, save_id or save.id, club_id)
    items = succession_plan(players)
    return {"items": items, "total": len(items)}


@router.get("/squad/profiles")
def profiles(
    save_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Weight profiles of the save, with the effective normalised weights."""
    from ..analytics.squad import profile_payload

    rows = ensure_profiles(db, save_id or save.id)
    db.commit()
    items = [profile_payload(row) for row in rows]
    return {"items": items, "total": len(items), "default_weights": DEFAULT_WEIGHTS}


@router.put("/squad/profiles")
def upsert_profile(
    body: TacticalProfileUpdate,
    save_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Create or update one weight profile. Weights are normalised to sum to one."""
    target = save_id or save.id
    ensure_profiles(db, target)
    row = db.query(TacticalProfile).filter_by(fm_save_id=target, key=body.key).one_or_none()
    weights = normalise_weights({**DEFAULT_WEIGHTS, **body.weights.overrides()})
    if row is None:
        row = TacticalProfile(fm_save_id=target, key=body.key)
        db.add(row)
    row.name = body.name
    row.description = body.description
    row.weight_coverage = weights["coverage"]
    row.weight_depth = weights["depth"]
    row.weight_age = weights["age"]
    row.weight_fit = weights["fit"]
    row.weight_wage = weights["wage"]
    row.weight_potential = weights["potential"]
    row.is_default = body.is_default
    if body.is_default:
        for other in db.query(TacticalProfile).filter_by(fm_save_id=target).all():
            if other.key != body.key:
                other.is_default = False
    db.commit()
    db.refresh(row)
    from ..analytics.squad import profile_payload

    return profile_payload(row)


@router.get("/squad/weights")
def weights_preview(
    save_id: int | None = Query(default=None),
    profile: str | None = Query(default=None),
    coverage: float | None = Query(default=None, ge=0, le=1),
    depth: float | None = Query(default=None, ge=0, le=1),
    age: float | None = Query(default=None, ge=0, le=1),
    fit: float | None = Query(default=None, ge=0, le=1),
    wage: float | None = Query(default=None, ge=0, le=1),
    potential: float | None = Query(default=None, ge=0, le=1),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Show the weights a request would use before applying them."""
    overrides = SquadWeights(
        coverage=coverage, depth=depth, age=age, fit=fit, wage=wage, potential=potential
    ).overrides()
    weights, profile_payload = resolve_weights(db, save_id or save.id, profile, overrides)
    db.commit()
    return {"weights": weights, "profile": profile_payload, "resolved_at": iso(utcnow())}


@router.get("/squad/club")
def club(
    save_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """The club treated as the managed squad, so the UI can tell the user whose squad it analyses."""
    target = save_id or save.id
    found = user_club(db, target)
    if found is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "user_club_missing", "message": "该存档没有标记为「我的俱乐部」的球队"},
        )
    return {
        "id": found.id,
        "name": found.name,
        "league": found.league,
        "nation": found.nation,
        "reputation": found.reputation,
    }
