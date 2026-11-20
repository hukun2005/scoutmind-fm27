"""第三阶段 API：转会模拟、成长预测、自动引援推荐（SM-017 / SM-019 / SM-020）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analytics.forecast import backtest, forecast_player
from ..analytics.recruitment_recommend import recommend
from ..analytics.simulator import simulate_transfer
from ..db import get_db
from ..models import FmSave, PlayerInstance
from .deps import get_active_save, get_current_user

router = APIRouter()


class SimulateRequest(BaseModel):
    """一笔引援的输入；未提供 fee/wage 时用最新快照的身价/工资。"""

    save_id: int | None = None
    instance_id: int
    target_position: str | None = Field(default=None, max_length=8)
    fee: float | None = Field(default=None, ge=0)
    wage: float | None = Field(default=None, ge=0)
    contract_years: float = Field(default=4.0, gt=0, le=8)
    expected_minutes: int | None = Field(default=None, ge=0, le=6000)
    budget: float | None = Field(default=None, ge=0)
    transfer_type: str = Field(
        default="permanent",
        pattern="^(permanent|loan|loan_with_option|free_transfer)$",
    )


class RecommendRequest(BaseModel):
    """自动引援筛选与权重。"""

    save_id: int | None = None
    slot: str | None = Field(default=None, max_length=8)
    min_age: int | None = Field(default=None, ge=10, le=60)
    max_age: int | None = Field(default=None, ge=10, le=60)
    budget: float | None = Field(default=None, ge=0)
    wage_cap: float | None = Field(default=None, ge=0)
    league: str | None = Field(default=None, max_length=128)
    nationality: str | None = Field(default=None, max_length=64)
    prefer: str = Field(default="balanced", pattern="^(balanced|ready|potential)$")
    weights: dict[str, float] | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


def _owned_save(db: Session, save_id: int | None, save: FmSave, user) -> FmSave:
    if save_id is None:
        return save
    target = db.get(FmSave, save_id)
    if target is None or target.user_id != user.id:
        raise HTTPException(status_code=404, detail={"code": "save_not_found", "message": "存档不存在"})
    return target


def _instance_of(db: Session, instance_id: int, save_id: int) -> PlayerInstance:
    instance = db.get(PlayerInstance, instance_id)
    if instance is None or instance.fm_save_id != save_id:
        raise HTTPException(status_code=404, detail={"code": "player_not_found", "message": "球员不存在"})
    return instance


@router.post("/transfers/simulate", summary="转会决策模拟（确定性）")
def simulate(
    body: SimulateRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    target = _owned_save(db, body.save_id, save, user)
    _instance_of(db, body.instance_id, target.id)
    try:
        return simulate_transfer(
            db,
            target.id,
            body.instance_id,
            target_position=body.target_position,
            fee=body.fee,
            wage=body.wage,
            contract_years=body.contract_years,
            expected_minutes=body.expected_minutes,
            budget=body.budget,
            transfer_type=body.transfer_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "simulation_unavailable", "message": str(exc)}) from exc


@router.get("/players/{instance_id}/forecast", summary="球员成长预测（可解释统计基线）")
def forecast(
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
        return forecast_player(db, instance_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "forecast_unavailable", "message": str(exc)}) from exc


@router.get("/development/forecast-backtest", summary="成长预测回测（MAE/RMSE/区间覆盖率）")
def forecast_backtest(
    save_id: int | None = Query(default=None),
    min_snapshots: int = Query(default=3, ge=2, le=10),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    target = _owned_save(db, save_id, save, user)
    return backtest(db, target.id, min_snapshots=min_snapshots)


@router.post("/recruitment/recommend", summary="自动引援推荐（可自定义权重）")
def recommend_players(
    body: RecommendRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    target = _owned_save(db, body.save_id, save, user)
    try:
        return recommend(
            db,
            target.id,
            slot=body.slot,
            min_age=body.min_age,
            max_age=body.max_age,
            budget=body.budget,
            wage_cap=body.wage_cap,
            league=body.league,
            nationality=body.nationality,
            prefer=body.prefer,
            weights=body.weights,
            page=body.page,
            page_size=body.page_size,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "recommendation_failed", "message": str(exc)}) from exc
