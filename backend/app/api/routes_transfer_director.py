"""V3.3.2-05 AI Transfer Director API。

所有端点都以当前存档为作用域；``save_id`` 只接受服务端校验过的存档，
球员实例、报价与谈判都必须属于该存档，越权统一 404。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import FmSave, PlayerInstance, TransferNegotiation, TransferOffer
from ..services import transfer_director as director
from ..services import transfer_radar as radar
from ..services import transfer_strategy as strategy
from .deps import get_active_save, instance_in_save_or_404

router = APIRouter()


class PurchaseOfferRequest(BaseModel):
    budget: float | None = Field(default=None, ge=0)


class SaveOfferRequest(BaseModel):
    direction: Literal["purchase", "sale", "loan"]
    offer_type: str = Field(min_length=1, max_length=32)
    base_fee: float | None = Field(default=None, ge=0)
    immediate_payment: float | None = Field(default=None, ge=0)
    installments_total: float | None = Field(default=None, ge=0)
    addons_potential: float | None = Field(default=None, ge=0)
    total_committed: float | None = Field(default=None, ge=0)
    potential_total: float | None = Field(default=None, ge=0)
    sell_on_pct: float | None = Field(default=None, ge=0, le=100)
    currency: str = Field(default="EUR", max_length=8)
    wage_impact: float | None = None
    loan_fee: float | None = Field(default=None, ge=0)
    wage_contribution_pct: float | None = Field(default=None, ge=0, le=100)
    buy_option_fee: float | None = Field(default=None, ge=0)
    buy_obligation_fee: float | None = Field(default=None, ge=0)
    loan_months: int | None = Field(default=None, ge=1, le=36)
    risk_level: Literal["low", "medium", "high"] = "medium"
    rationale: dict[str, Any] = Field(default_factory=dict)


class CreateNegotiationRequest(BaseModel):
    instance_id: int = Field(gt=0)
    direction: Literal["purchase", "sale", "loan"]
    offer_id: int | None = Field(default=None, gt=0)
    initial_ask: float | None = Field(default=None, ge=0)
    note: str | None = Field(default=None, max_length=256)


class AppendEventRequest(BaseModel):
    event_type: Literal[
        "draft_created",
        "offer_generated",
        "offer_submitted",
        "counter_received",
        "offer_revised",
        "accepted",
        "rejected",
        "withdrawn",
        "completed",
        "cancelled",
        "note",
    ]
    amount: float | None = Field(default=None, ge=0)
    data: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime | None = None
    source: Literal["user_confirmed", "local_import"] = "user_confirmed"


def _negotiation_or_404(db: Session, save: FmSave, negotiation_id: int) -> TransferNegotiation:
    negotiation = db.get(TransferNegotiation, negotiation_id)
    if negotiation is None or negotiation.fm_save_id != save.id:
        raise HTTPException(status_code=404, detail={"code": "negotiation_not_found", "message": "谈判记录不存在"})
    return negotiation


@router.get("/transfer-director/overview", summary="AI 转会总监：同步状态与能力")
def overview(
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    return director.overview(db, save.id, save.user_club_id)


@router.get("/transfer-director/opportunities", summary="转会机会雷达：分页列表")
def opportunities(
    opportunity_type: Literal[
        "listed", "loan_listed", "release_listed", "contract_expiring", "ai_inferred"
    ] | None = Query(default=None, alias="type"),
    club_id: int | None = Query(default=None, gt=0),
    position: str | None = Query(default=None, max_length=32),
    age_min: int | None = Query(default=None, ge=10, le=60),
    age_max: int | None = Query(default=None, ge=10, le=60),
    group: Literal["strong", "watch", "loan", "long_term", "not_recommended"] | None = Query(default=None),
    search: str | None = Query(default=None, max_length=64),
    sort: Literal["score", "contract", "age", "value", "newest"] = Query(default="score"),
    limit: int = Query(default=30, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    if age_min is not None and age_max is not None and age_min > age_max:
        raise HTTPException(status_code=400, detail={"code": "invalid_age_range", "message": "年龄下限不能大于上限"})
    try:
        return radar.list_opportunities(
            db,
            save.id,
            opportunity_type=opportunity_type,
            club_id=club_id,
            position=position,
            age_min=age_min,
            age_max=age_max,
            group=group,
            search=search,
            sort=sort,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_filter", "message": str(exc)}) from exc


@router.get("/transfer-director/opportunities/summary", summary="转会机会雷达：顶部统计与能力说明")
def opportunities_summary(
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    return radar.summary(db, save.id)


@router.post("/transfer-director/opportunities/refresh", summary="重新扫描全部可读球员并记录变化")
def refresh_opportunities(
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    return radar.scan(db, save.id)


@router.get("/transfer-director/opportunities/{instance_id}", summary="单个球员的全部机会与交易上下文")
def opportunity_detail(
    instance_id: int,
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    instance = instance_in_save_or_404(db, instance_id, save)
    payload = radar.player_opportunities(db, save.id, instance_id)
    context = director.enrich_context(db, director.player_transfer_context(db, instance))
    return {"opportunity": payload, "context": context}


@router.get("/transfer-director/opportunity-events", summary="机会状态变化历史")
def opportunity_events(
    instance_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    return radar.list_events(db, save.id, instance_id=instance_id, limit=limit, offset=offset)


@router.get("/transfer-director/alerts", summary="转会机会提醒")
def transfer_alerts(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    return radar.list_alerts(db, save.id, unread_only=unread_only, limit=limit)


@router.post("/transfer-director/alerts/{alert_id}/read", summary="标记提醒已读")
def read_transfer_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    try:
        return radar.mark_alert_read(db, save.id, alert_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "alert_not_found", "message": "提醒不存在"}) from exc


@router.get("/transfer-director/strategy-cases", summary="历史成交策略案例列表")
def strategy_cases(
    transfer_type: Literal["permanent", "loan", "free"] | None = Query(default=None),
    case_origin: Literal["imported", "demo", "negotiation"] | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    return strategy.list_cases(
        db, save.id, transfer_type=transfer_type, case_origin=case_origin, limit=limit, offset=offset
    )


@router.get("/transfer-director/strategy-cases/similar/{instance_id}", summary="相似成交案例匹配")
def similar_strategy_cases(
    instance_id: int,
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    instance_in_save_or_404(db, instance_id, save)
    return strategy.similar_cases(db, save.id, instance_id, limit=limit)


@router.get("/transfer-director/strategy-insights", summary="成交策略归纳（带样本量与案例引用）")
def strategy_insights(
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    return strategy.insights(db, save.id)


@router.get("/transfer-director/player/{instance_id}", summary="AI 交易分析：合同/条款/历史/估值")
def player_analysis(
    instance_id: int,
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    instance = instance_in_save_or_404(db, instance_id, save)
    context = director.enrich_context(db, director.player_transfer_context(db, instance))
    context["purchase_preview"] = director.generate_purchase_offers(db, instance)
    context["sale_preview"] = director.generate_sale_offers(db, instance)
    context["loan_preview"] = director.generate_loan_offers(db, instance)
    return context


@router.post("/transfer-director/player/{instance_id}/purchase-offers", summary="生成三套买入方案")
def purchase_offers(
    instance_id: int,
    payload: PurchaseOfferRequest | None = None,
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    instance = instance_in_save_or_404(db, instance_id, save)
    return director.generate_purchase_offers(db, instance, budget=payload.budget if payload else None)


@router.post("/transfer-director/player/{instance_id}/sale-offers", summary="生成三套出售方案")
def sale_offers(
    instance_id: int,
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    instance = instance_in_save_or_404(db, instance_id, save)
    return director.generate_sale_offers(db, instance)


@router.post("/transfer-director/player/{instance_id}/loan-offers", summary="生成三套租借方案")
def loan_offers(
    instance_id: int,
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    instance = instance_in_save_or_404(db, instance_id, save)
    return director.generate_loan_offers(db, instance)


@router.post("/transfer-director/offers/loan", summary="生成三套租借方案（工作台入口）")
def loan_offers_workspace(
    instance_id: int = Query(..., gt=0),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    instance = instance_in_save_or_404(db, instance_id, save)
    return director.generate_loan_offers(db, instance)


@router.get("/transfer-director/offers/{offer_id}", summary="报价详情")
def offer_detail(
    offer_id: int,
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    offer = db.get(TransferOffer, offer_id)
    if offer is None or offer.fm_save_id != save.id:
        raise HTTPException(status_code=404, detail={"code": "offer_not_found", "message": "报价方案不存在"})
    return director.serialize_offer(offer)


@router.get("/transfer-director/offers", summary="报价方案列表")
def offers(
    instance_id: int | None = Query(default=None, gt=0),
    direction: Literal["purchase", "sale", "loan"] | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    rows = director.list_offers(db, save.id, instance_id=instance_id, direction=direction, limit=limit)
    return {"items": [director.serialize_offer(row) for row in rows], "total": len(rows)}


@router.post("/transfer-director/offers", status_code=201, summary="保存报价草稿")
def save_offer(
    payload: SaveOfferRequest,
    instance_id: int = Query(..., gt=0),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    instance_in_save_or_404(db, instance_id, save)
    offer: TransferOffer = director.save_offer(
        db, save.id, instance_id, payload.direction, payload.model_dump()
    )
    return director.serialize_offer(offer)


@router.get("/transfer-director/negotiations", summary="谈判记录列表")
def negotiations(
    instance_id: int | None = Query(default=None, gt=0),
    status: str | None = Query(default=None, max_length=16),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    query = select(TransferNegotiation).where(TransferNegotiation.fm_save_id == save.id)
    if instance_id is not None:
        query = query.where(TransferNegotiation.player_instance_id == instance_id)
    if status is not None:
        if status not in director.NEGOTIATION_STATUSES:
            raise HTTPException(status_code=400, detail={"code": "invalid_status", "message": "不支持的谈判状态"})
        query = query.where(TransferNegotiation.status == status)
    rows = list(db.scalars(query.order_by(TransferNegotiation.created_at.desc()).limit(limit)))
    return {"items": [director.serialize_negotiation(row) for row in rows], "total": len(rows)}


@router.post("/transfer-director/negotiations", status_code=201, summary="创建谈判记录")
def create_negotiation(
    payload: CreateNegotiationRequest,
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    instance_in_save_or_404(db, payload.instance_id, save)
    if payload.offer_id is not None:
        offer = db.get(TransferOffer, payload.offer_id)
        if offer is None or offer.fm_save_id != save.id:
            raise HTTPException(status_code=404, detail={"code": "offer_not_found", "message": "报价方案不存在"})
    negotiation = director.create_negotiation(
        db,
        save_id=save.id,
        instance_id=payload.instance_id,
        direction=payload.direction,
        offer_id=payload.offer_id,
        initial_ask=payload.initial_ask,
        note=payload.note,
    )
    return director.serialize_negotiation(negotiation, director.negotiation_events(db, negotiation.id))


@router.get("/transfer-director/negotiations/{negotiation_id}", summary="谈判详情与事件")
def negotiation_detail(
    negotiation_id: int,
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    negotiation = _negotiation_or_404(db, save, negotiation_id)
    return director.serialize_negotiation(negotiation, director.negotiation_events(db, negotiation.id))


@router.post("/transfer-director/negotiations/{negotiation_id}/events", status_code=201, summary="记录谈判事件")
def append_event(
    negotiation_id: int,
    payload: AppendEventRequest,
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    negotiation = _negotiation_or_404(db, save, negotiation_id)
    if negotiation.status in director.TERMINAL_STATUSES and payload.event_type not in {"note"}:
        raise HTTPException(
            status_code=409,
            detail={"code": "negotiation_finished", "message": "该谈判已结束，只能追加备注"},
        )
    event, duplicate = director.append_event(
        db,
        negotiation,
        event_type=payload.event_type,
        amount=payload.amount,
        data=payload.data,
        occurred_at=payload.occurred_at,
        source=payload.source,
    )
    return {
        "duplicate": duplicate,
        "event": {
            "event_id": event.id,
            "event_type": event.event_type,
            "amount": event.amount,
            "data": director._loads(event.event_data_json),
            "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
        },
        "negotiation": director.serialize_negotiation(negotiation),
    }


@router.get("/transfer-director/negotiations/{negotiation_id}/review", summary="谈判复盘")
def review(
    negotiation_id: int,
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    negotiation = _negotiation_or_404(db, save, negotiation_id)
    return director.review_negotiation(db, negotiation)


@router.get("/transfer-director/club-summary", summary="我的俱乐部买卖与租借汇总")
def club_summary(
    club_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    target = club_id or save.user_club_id
    if target is None:
        raise HTTPException(
            status_code=422,
            detail={"code": "user_club_missing", "message": "当前存档还没有识别出执教俱乐部"},
        )
    return director.club_transfer_summary(db, save.id, target)
