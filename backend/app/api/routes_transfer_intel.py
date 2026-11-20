"""俱乐部转会情报与 ROI API（SM-015 / SM-016）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analytics.club_intelligence import club_transfer_intelligence
from ..analytics.roi import player_investment, transfer_roi
from ..db import get_db
from ..models import Club, FmSave, PlayerInstance, Transfer
from .deps import get_active_save, get_current_user

router = APIRouter()


def _owned_save(db: Session, save_id: int | None, save: FmSave, user) -> FmSave:
    if save_id is None:
        return save
    target = db.get(FmSave, save_id)
    if target is None or target.user_id != user.id:
        raise HTTPException(status_code=404, detail={"code": "save_not_found", "message": "存档不存在"})
    return target


@router.get("/clubs/{club_id}/transfer-intelligence", summary="俱乐部转会策略分析")
def club_intelligence(
    club_id: int,
    season: str | None = Query(default=None, max_length=16, pattern=r"^\d{4}/\d{2}$"),
    save_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """只统计 completed；agreed/pending/cancelled 单独计数，缺失金额不给 0。"""
    target = _owned_save(db, save_id, save, user)
    club = db.get(Club, club_id)
    if club is None or club.fm_save_id != target.id:
        raise HTTPException(status_code=404, detail={"code": "club_not_found", "message": "俱乐部不存在"})
    try:
        return club_transfer_intelligence(db, target.id, club_id, season=season)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "no_transfers", "message": str(exc)}) from exc


@router.get("/transfers/{transfer_id}/roi", summary="单笔买入的现金/会计/估值/已实现收益")
def roi(
    transfer_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
) -> dict[str, Any]:
    transfer = db.get(Transfer, transfer_id)
    if transfer is None:
        raise HTTPException(status_code=404, detail={"code": "transfer_not_found", "message": "交易不存在"})
    save = db.get(FmSave, transfer.fm_save_id)
    if save is None or save.user_id != user.id:
        raise HTTPException(status_code=404, detail={"code": "transfer_not_found", "message": "交易不存在"})
    try:
        return transfer_roi(db, transfer_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "roi_unavailable", "message": str(exc)}) from exc


@router.get("/players/{instance_id}/investment", summary="一名球员的全部买入投资")
def investment(
    instance_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
) -> dict[str, Any]:

    instance = db.get(PlayerInstance, instance_id)
    if instance is None:
        raise HTTPException(status_code=404, detail={"code": "player_not_found", "message": "球员不存在"})
    save = db.get(FmSave, instance.fm_save_id)
    if save is None or save.user_id != user.id:
        raise HTTPException(status_code=404, detail={"code": "player_not_found", "message": "球员不存在"})
    try:
        return player_investment(db, instance_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "investment_unavailable", "message": str(exc)}) from exc
