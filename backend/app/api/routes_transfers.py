"""Transfer Intelligence and club endpoints."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..analytics.transfers import (
    TransferFilter,
    club_transfer_profile,
    fetch_transfers,
    serialize_transfer,
    similar_transfers,
    transfer_price_stats,
)
from ..analytics.valuation import estimate_value
from ..db import get_db
from ..models import Club, FmSave, PlayerValuation
from ..utils import utcnow
from .deps import get_active_save

router = APIRouter()


def _filters(
    status: str,
    transfer_type: str | None,
    from_date: date | None,
    to_date: date | None,
    club_id: int | None,
    position_group: str | None,
    league: str | None,
    min_fee: float | None,
    max_fee: float | None,
    min_age: int | None,
    max_age: int | None,
    min_ca: int | None,
    max_ca: int | None,
) -> TransferFilter:
    return TransferFilter(
        status=status,
        transfer_type=transfer_type,
        from_date=from_date,
        to_date=to_date,
        club_id=club_id,
        position_group=position_group.upper() if position_group else None,
        league=league,
        min_fee=min_fee,
        max_fee=max_fee,
        min_age=min_age,
        max_age=max_age,
        min_ca=min_ca,
        max_ca=max_ca,
    )


@router.get("/transfers")
def list_transfers(
    save_id: int | None = Query(default=None),
    status: str = Query(default="completed"),
    transfer_type: str | None = Query(default=None),
    from_date: date | None = Query(default=None, alias="from_date"),
    to_date: date | None = Query(default=None, alias="to_date"),
    club_id: int | None = Query(default=None),
    position_group: str | None = Query(default=None),
    league: str | None = Query(default=None),
    min_fee: float | None = Query(default=None, ge=0),
    max_fee: float | None = Query(default=None, ge=0),
    min_age: int | None = Query(default=None),
    max_age: int | None = Query(default=None),
    min_ca: int | None = Query(default=None),
    max_ca: int | None = Query(default=None),
    sort: str = Query(default="-transfer_date"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Completed (or all) transfers with their fee components."""
    filters = _filters(
        status, transfer_type, from_date, to_date, club_id, position_group, league, min_fee, max_fee, min_age, max_age,
        min_ca, max_ca,
    )
    target_save = save_id or save.id
    all_rows = fetch_transfers(db, target_save, filters)
    total = len(all_rows)
    rows = all_rows[offset : offset + limit]
    clubs = {club.id: club for club in db.scalars(select(Club).where(Club.fm_save_id == target_save))}
    items = [serialize_transfer(row, clubs) for row in rows]
    priced = [row for row in all_rows if row.effective_fee is not None]
    total_rows = max(total, 1)
    return {
        "items": items,
        "total": total,
        "coverage": {
            "effective_fee": round(len(priced) / total_rows, 4),
            "transfer_date": 1.0,
            "ca_at_transfer": round(
                sum(1 for row in all_rows if row.player_ca_at_transfer is not None) / total_rows, 4
            ),
            "contract_remaining_months": round(
                sum(1 for row in all_rows if row.contract_remaining_months is not None) / total_rows, 4
            ),
        },
    }


@router.get("/transfers/stats")
def transfer_stats(
    save_id: int | None = Query(default=None),
    position_group: str | None = Query(default=None),
    min_age: int | None = Query(default=None),
    max_age: int | None = Query(default=None),
    min_ca: int | None = Query(default=None),
    max_ca: int | None = Query(default=None),
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    club_id: int | None = Query(default=None),
    league: str | None = Query(default=None),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Median/quartile statistics for completed transfers."""
    filters = _filters(
        "completed", None, from_date, to_date, club_id, position_group, league, None, None, min_age, max_age, min_ca,
        max_ca,
    )
    return transfer_price_stats(db, save_id or save.id, filters)


@router.get("/transfers/similar")
def transfers_similar(
    instance_id: int = Query(...),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Weighted comparable transfers for one player."""
    try:
        outcome = similar_transfers(db, instance_id, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "similar_unavailable", "message": str(exc)}) from exc
    return {
        "target": outcome.target,
        "items": outcome.items,
        "effective_weights": outcome.effective_weights,
        "missing_fields": outcome.missing_fields,
        "data_gaps": outcome.data_gaps,
        "sample_size": outcome.sample_size,
    }


@router.get("/transfers/valuation")
def transfers_valuation(instance_id: int = Query(...), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Comparable-transfer valuation range, stored for audit."""
    result = estimate_value(db, instance_id)
    db.add(
        PlayerValuation(
            player_instance_id=instance_id,
            as_of=utcnow(),
            method=str(result["method"]),
            algorithm_version=str(result["algorithm_version"]),
            low=result["low"] if isinstance(result["low"], (int, float)) else None,
            mid=result["mid"] if isinstance(result["mid"], (int, float)) else None,
            high=result["high"] if isinstance(result["high"], (int, float)) else None,
            sample_size=int(result["sample_size"]),
            confidence=str(result["confidence"]),
            insufficient_sample=bool(result["insufficient_sample"]),
            evidence_json=__import__("json").dumps(result["basis"], ensure_ascii=False),
        )
    )
    db.commit()
    return result


@router.get("/clubs")
def list_clubs(
    save_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Clubs of the save with their reputation and league."""
    target_save = save_id or save.id
    rows = list(db.scalars(select(Club).where(Club.fm_save_id == target_save).order_by(Club.name)))
    return {
        "items": [
            {
                "id": club.id,
                "uid": club.uid,
                "name": club.name,
                "nation": club.nation,
                "league": club.league,
                "reputation": club.reputation,
                "is_user_club": club.is_user_club,
            }
            for club in rows
        ],
        "total": len(rows),
    }


@router.get("/clubs/{club_id}/transfer-profile")
def club_profile(club_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Buy/sell behaviour of one club."""
    try:
        return club_transfer_profile(db, club_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "club_not_found", "message": str(exc)}) from exc


