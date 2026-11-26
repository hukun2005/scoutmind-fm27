"""Player, watchlist and alert endpoints."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analytics.availability import player_status as player_availability_status
from ..analytics.players import PlayerFilter, development, history, list_players, player_profile
from ..db import get_db
from ..models import FmSave, Watchlist
from ..schemas import WatchItemCreate, WatchItemUpdate, WatchlistCreate
from ..services import watchlist as watch_service
from .deps import (
    alert_owned_or_404,
    get_active_save,
    get_current_user,
    instance_in_save_or_404,
    instance_owned_or_404,
    watch_item_owned_or_404,
)

router = APIRouter()

SORTABLE = {"age", "ca", "pa", "market_value", "name", "updated_at"}


@router.get("/players")
def players(
    save_id: int | None = Query(default=None),
    query: str | None = Query(default=None, max_length=128),
    position: str | None = Query(default=None, max_length=16),
    position_group: str | None = Query(default=None, max_length=4),
    min_age: int | None = Query(default=None, ge=10, le=60),
    max_age: int | None = Query(default=None, ge=10, le=60),
    min_ca: int | None = Query(default=None, ge=0, le=400),
    min_pa: int | None = Query(default=None, ge=0, le=400),
    max_value: int | None = Query(default=None, ge=0),
    max_wage: int | None = Query(default=None, ge=0),
    club_id: int | None = Query(default=None),
    watchlist_only: bool = Query(default=False),
    sort: str = Query(default="-updated_at"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Searchable, sortable player list built from each instance's latest snapshot."""
    key = sort.lstrip("-")
    if key not in SORTABLE:
        raise HTTPException(status_code=400, detail={"code": "invalid_sort", "message": f"不支持的排序字段 {sort}"})
    filters = PlayerFilter(
        query=query,
        position=position.upper() if position else None,
        position_group=position_group.upper() if position_group else None,
        min_age=min_age,
        max_age=max_age,
        min_ca=min_ca,
        min_pa=min_pa,
        max_value=max_value,
        max_wage=max_wage,
        club_id=club_id,
        watchlist_only=watchlist_only,
        sort=sort,
    )
    return list_players(db, save_id or save.id, filters, limit=limit, offset=offset)


@router.get("/players/{instance_id}")
def player_detail(
    instance_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
) -> dict[str, Any]:
    """Full profile with attributes, history bounds and tags."""
    instance_owned_or_404(db, instance_id, user)
    try:
        return player_profile(db, instance_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "player_not_found", "message": str(exc)}) from exc


@router.get("/players/{instance_id}/history")
def player_history(
    instance_id: int,
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
) -> dict[str, Any]:
    """Snapshot timeline for growth charts."""
    instance_owned_or_404(db, instance_id, user)
    return history(db, instance_id, from_date, to_date)


@router.get("/players/{instance_id}/status", summary="球员状态时间线（挂牌/伤病/租借）")
def player_status_route(
    instance_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
) -> dict[str, Any]:
    """挂牌、伤病、租借与待生效转会的时间线；缺失项以 data_gaps 说明，不做推断。"""
    instance_owned_or_404(db, instance_id, user)
    try:
        return player_availability_status(db, instance_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "player_not_found", "message": str(exc)}) from exc


@router.get("/players/{instance_id}/development")
def player_development(
    instance_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
) -> dict[str, Any]:
    """Growth deltas with fact / correlation / speculation kept separate."""
    instance_owned_or_404(db, instance_id, user)
    try:
        return development(db, instance_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "player_not_found", "message": str(exc)}) from exc


@router.get("/watchlist")
def get_watchlist(
    save_id: int | None = Query(default=None),
    list_id: int | None = Query(default=None),
    q: str | None = Query(default=None, max_length=64),
    status: str | None = Query(default=None, pattern="^(watching|preparing|paused|done)$"),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Watched players for the save, optionally filtered by list, status or player name."""
    target = save_id or save.id
    items = watch_service.list_items(db, target, list_id=list_id, query=q, status=status)
    lists = watch_service.list_groups(db, save.user_id, target)
    db.commit()
    return {"items": items, "total": len(items), "lists": lists}


@router.get("/watchlist/lists")
def get_watchlist_lists(
    save_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Named watchlists of the save with item counts."""
    items = watch_service.list_groups(db, save.user_id, save_id or save.id)
    db.commit()
    return {"items": items, "total": len(items)}


@router.post("/watchlist/lists", status_code=201)
def create_watchlist(
    body: WatchlistCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Create a named watchlist; names are unique inside one save."""
    try:
        created = watch_service.create_list(db, user.id, save.id, body.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "watchlist_error", "message": str(exc)}) from exc
    db.commit()
    return {"id": created.id, "name": created.name}


@router.post("/watchlist/items", status_code=201)
def add_watch_item(
    body: WatchItemCreate,
    display_name: str | None = Query(default=None, alias="display_name"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Follow a player instance, optionally into a named list with a workflow status."""
    instance_in_save_or_404(db, body.instance_id, save)
    try:
        item = watch_service.add_item(
            db, user.id, save.id, body.instance_id, body.tag, body.note, list_id=body.list_id, status=body.status
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "watchlist_error", "message": str(exc)}) from exc
    db.commit()
    return {
        "id": item.id,
        "instance_id": item.player_instance_id,
        "list_id": item.watchlist_id,
        "status": item.status,
        "tag": item.tag,
        "note": item.note,
    }


@router.patch("/watchlist/items/{item_id}")
def patch_watch_item(
    item_id: int,
    body: WatchItemUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
) -> dict[str, Any]:
    """Update the list, status, tag or note of a watchlist entry."""
    watch_item_owned_or_404(db, item_id, user)
    try:
        item = watch_service.update_item(
            db,
            item_id,
            tag=body.tag,
            note=body.note,
            list_id=body.list_id,
            status=body.status,
            user_id=user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "watchlist_error", "message": str(exc)}) from exc
    db.commit()
    return {
        "id": item.id,
        "instance_id": item.player_instance_id,
        "list_id": item.watchlist_id,
        "status": item.status,
        "tag": item.tag,
        "note": item.note,
    }


@router.delete("/watchlist/items/{item_id}", status_code=204)
def remove_watch_item(
    item_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
) -> None:
    """Stop following a player."""
    watch_item_owned_or_404(db, item_id, user)
    try:
        watch_service.delete_item(db, item_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "watchlist_error", "message": str(exc)}) from exc
    db.commit()


@router.post("/watchlist/refresh")
def refresh_watchlist(
    db: Session = Depends(get_db), user=Depends(get_current_user), save: FmSave = Depends(get_active_save)
) -> dict[str, Any]:
    """Apply automatic watch rules and generate new alerts."""
    result = watch_service.refresh(db, user.id, save.id)
    db.commit()
    return result


@router.get("/alerts")
def alerts(
    save_id: int | None = Query(default=None),
    unread_only: bool = Query(default=False),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Alerts for the save."""
    items = watch_service.list_alerts(db, save_id or save.id, unread_only)
    return {"items": items, "total": len(items)}


@router.post("/alerts/{alert_id}/read", status_code=204)
def read_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
) -> None:
    """Mark one alert read."""
    alert_owned_or_404(db, alert_id, user)
    try:
        watch_service.mark_read(db, alert_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "alert_not_found", "message": str(exc)}) from exc
    db.commit()


def _watchlist_id(db: Session, save_id: int) -> int | None:
    row = db.scalar(select(Watchlist.id).where(Watchlist.fm_save_id == save_id).limit(1))
    return row
