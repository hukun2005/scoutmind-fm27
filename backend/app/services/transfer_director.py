"""V3.3.2-05 AI Transfer Director 的确定性服务层。

只做三件事：

1. 把真实可读的数据聚合成「交易上下文」（合同、可用性、租借、历史转会、条款、估值）。
2. 用确定性规则生成买入/出售报价（不编造金额，未知保持 None）。
3. 记录用户真实谈判并做复盘。

AI 只负责解释这里的输出，不参与金额计算。所有读写都以 ``fm_save_id`` 隔离。
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..analytics.players import latest_snapshot
from ..analytics.transfers import serialize_transfer
from ..analytics.valuation import estimate_value
from ..models import (
    Club,
    IdentityConflict,
    ImportJob,
    LoanRecord,
    NegotiationEvent,
    PlayerAvailability,
    PlayerInstance,
    PlayerSnapshot,
    Transfer,
    TransferFeedback,
    TransferFeeComponent,
    TransferNegotiation,
    TransferOffer,
    TransferStatusHistory,
)
from ..utils import fee_round, iso, utcnow

OFFER_VERSION = "transfer-offer-1"
LOAN_OFFER_VERSION = "transfer-loan-offer-1"
REVIEW_VERSION = "negotiation-review-1"

#: V3.3.2-07：币种未知时的存储占位符；序列化时映射回 null，绝不擅自换算。
UNKNOWN_CURRENCY = "UNKNOWN"
ADJUSTMENT_MIN_CASES = 3
ADJUSTMENT_BOUNDS = (0.85, 1.15)
FEEDBACK_OUTCOMES = ("completed", "rejected", "cancelled", "negotiating", "unknown")

PURCHASE_TYPES = ("conservative", "competitive", "fast_close")
SALE_TYPES = ("quick_sale", "fair_sale", "max_value")
LOAN_TYPES = ("low_cost_loan", "development_loan", "loan_to_buy")
NEGOTIATION_STATUSES = (
    "DRAFT",
    "PROPOSED",
    "SUBMITTED",
    "COUNTERED",
    "ACCEPTED",
    "REJECTED",
    "WITHDRAWN",
    "COMPLETED",
    "CANCELLED",
)
EVENT_TYPES = (
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
)

#: 一次事件会把谈判推进到的状态；None 表示该事件不改变状态。
STATUS_BY_EVENT: dict[str, str | None] = {
    "draft_created": None,
    "offer_generated": "PROPOSED",
    "offer_submitted": "SUBMITTED",
    "counter_received": "COUNTERED",
    "offer_revised": "SUBMITTED",
    "accepted": "ACCEPTED",
    "rejected": "REJECTED",
    "withdrawn": "WITHDRAWN",
    "completed": "COMPLETED",
    "cancelled": "CANCELLED",
    "note": None,
}

#: 计入谈判轮次的用户侧动作。
ROUND_EVENTS = {"offer_submitted", "offer_revised", "counter_received", "accepted", "rejected", "withdrawn", "completed"}

TERMINAL_STATUSES = {"ACCEPTED", "REJECTED", "WITHDRAWN", "COMPLETED", "CANCELLED"}

#: 周薪超过该值时提示异常（真实库存在 3,413,698 这类异常值）。
WAGE_SANITY_LIMIT = 500_000

MISSING_CONTRACT_HINTS = {
    "wage": "当前数据源未提供周薪",
    "contract_end": "当前数据源未提供合同到期日",
    "market_value": "当前数据源未提供身价",
}


def _months_between(start: date, end: date) -> int:
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return months


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _annual_wage(weekly: float | None) -> float | None:
    return fee_round(weekly * 52) if weekly is not None else None


def save_currency(db: Session, save_id: int) -> dict[str, Any]:
    """当前存档的报价币种。

    只信任导入历史转会明确记录的 ``currency_original``；``Transfer.currency`` 的默认值
    EUR 不是证据。无法识别时返回未知，绝不换算。
    """
    row = db.scalar(
        select(Transfer)
        .where(Transfer.fm_save_id == save_id, Transfer.currency_original.is_not(None))
        .order_by(Transfer.transfer_date.desc(), Transfer.id.desc())
        .limit(1)
    )
    code = (row.currency_original or "").strip().upper() if row is not None else ""
    if code:
        return {
            "currency": code,
            "known": True,
            "source": "transfer_history",
            "note": None,
        }
    return {
        "currency": None,
        "known": False,
        "source": None,
        "note": "货币单位未知",
    }


def _currency_fields(info: dict[str, Any]) -> dict[str, Any]:
    return {
        "currency": info["currency"],
        "currency_known": info["known"],
        "currency_source": info["source"],
        "currency_note": info["note"],
    }


def strategy_adjustment(
    db: Session, save_id: int, instance: PlayerInstance, base_amount: float | None
) -> dict[str, Any]:
    """历史案例对基础报价的确定性调整层。

    只有"相似度达标、可用于统计、有真实成交金额"的案例达到 3 个才调整；倍数夹紧在
    ``[0.85, 1.15]``，并完整保留调整前/后的数值与引用案例。
    """
    from . import transfer_strategy as strategy

    empty = {
        "applied": False,
        "multiplier": 1.0,
        "before": fee_round(base_amount),
        "after": fee_round(base_amount),
        "sample_size": 0,
        "confidence": strategy.confidence_tier(0),
        "case_ids": [],
        "basis": "没有相似成交案例，沿用原有确定性规则",
    }
    if base_amount is None or base_amount <= 0:
        return empty
    try:
        similar = strategy.similar_cases(db, save_id, instance.id, limit=20)["items"]
    except ValueError:
        similar = []
    usable = [
        case
        for case in similar
        if case.get("usable_for_stats")
        and float(case.get("match_pct") or 0) >= strategy.SIMILARITY_THRESHOLD
        and case.get("actual_fee") is not None
    ]
    if len(usable) < ADJUSTMENT_MIN_CASES:
        return {
            **empty,
            "sample_size": len(usable),
            "confidence": strategy.confidence_tier(len(usable)),
            "case_ids": [str(case["case_id"]) for case in usable[:5]],
            "basis": f"相似成交案例只有 {len(usable)} 个，低于最低样本 {ADJUSTMENT_MIN_CASES}，未调整报价",
        }

    fees = sorted(float(case["actual_fee"]) for case in usable)
    middle = len(fees) // 2
    median = fees[middle] if len(fees) % 2 else (fees[middle - 1] + fees[middle]) / 2
    raw = median / float(base_amount)
    multiplier = round(_clamp(raw, *ADJUSTMENT_BOUNDS), 4)
    applied = abs(multiplier - 1.0) >= 0.0001
    return {
        "applied": applied,
        "multiplier": multiplier if applied else 1.0,
        "before": fee_round(base_amount),
        "after": fee_round(base_amount * (multiplier if applied else 1.0)),
        "sample_size": len(usable),
        "confidence": strategy.confidence_tier(len(usable)),
        "case_ids": [str(case["case_id"]) for case in usable[:5]],
        "basis": "相似成交案例成交金额中位数与当前估值的比值（倍数限制在 0.85–1.15）"
        if applied
        else "相似案例中位成交金额与当前估值一致，无需调整",
    }


def _contract(db: Session, instance: PlayerInstance, snapshot: PlayerSnapshot | None) -> dict[str, Any]:
    availability = latest_availability(db, instance.id)
    reference = (snapshot.game_date if snapshot is not None and snapshot.game_date else None) or date.today()
    remaining = None
    if snapshot is not None and snapshot.contract_end:
        remaining = _months_between(reference, snapshot.contract_end)
    missing = [key for key, value in (("wage", snapshot.wage if snapshot else None),
                                      ("contract_end", snapshot.contract_end if snapshot else None)) if value is None]
    warnings: list[str] = []
    if snapshot is not None and snapshot.wage is not None and snapshot.wage > WAGE_SANITY_LIMIT:
        warnings.append("工资数值显著高于常见周薪，可能是单位或解析异常，请以游戏内合同页为准")
    return {
        "club_id": (snapshot.club_id if snapshot is not None else None) or instance.club_id,
        "contract_end": iso(snapshot.contract_end) if snapshot is not None else None,
        "contract_start": None,
        "wage": snapshot.wage if snapshot is not None else None,
        "wage_period": "week",
        "annual_wage": _annual_wage(snapshot.wage if snapshot is not None else None),
        "remaining_months": remaining,
        "contract_status": "unknown" if remaining is None else ("expiring" if remaining <= 6 else "active"),
        "contract_type": None,
        "release_clause": None,
        "observed_at": iso(snapshot.observed_at) if snapshot is not None else None,
        "source": snapshot.source if snapshot is not None else None,
        "confidence": (snapshot.data_completeness if snapshot is not None else None),
        "listed": availability.listed if availability else None,
        "loan_listed": availability.loan_listed if availability else None,
        "not_for_sale": availability.not_for_sale if availability else None,
        "missing_fields": missing,
        "warnings": warnings + [MISSING_CONTRACT_HINTS[key] for key in missing],
    }


def latest_availability(db: Session, instance_id: int) -> PlayerAvailability | None:
    return db.scalar(
        select(PlayerAvailability)
        .where(PlayerAvailability.player_instance_id == instance_id)
        .order_by(PlayerAvailability.observed_at.desc(), PlayerAvailability.id.desc())
        .limit(1)
    )


def latest_loan(db: Session, instance_id: int) -> LoanRecord | None:
    return db.scalar(
        select(LoanRecord)
        .where(LoanRecord.player_instance_id == instance_id)
        .order_by(LoanRecord.observed_at.desc(), LoanRecord.id.desc())
        .limit(1)
    )


def _loan_payload(loan: LoanRecord | None) -> dict[str, Any]:
    if loan is None:
        return {
            "available": False,
            "note": "当前数据源没有该球员的租借记录；未获取不等于没有条款",
            "missing_fields": ["loan_terms", "buy_option", "buy_obligation", "loan_fee"],
        }
    return {
        "available": True,
        "parent_club_id": loan.parent_club_id,
        "parent_club_name": loan.parent_club_name,
        "loan_club_id": loan.loan_club_id,
        "loan_club_name": loan.loan_club_name,
        "start_date": iso(loan.start_date),
        "end_date": iso(loan.end_date),
        "has_option": loan.has_option,
        "has_obligation": loan.has_obligation,
        "loan_fee": loan.loan_fee,
        "wage_contribution_amount": loan.wage_contribution_amount,
        "wage_contribution_pct": loan.wage_contribution_pct,
        "buy_option_fee": loan.buy_option_fee,
        "buy_obligation_fee": loan.buy_obligation_fee,
        "option_status": loan.option_status,
        "status": loan.status,
        "source": loan.source,
        "confidence": loan.confidence,
        "observed_at": iso(loan.observed_at),
    }


def _transfer_rows(db: Session, save_id: int, instance_id: int, limit: int = 20) -> list[dict[str, Any]]:
    clubs = {club.id: club for club in db.scalars(select(Club).where(Club.fm_save_id == save_id))}
    rows = list(
        db.scalars(
            select(Transfer)
            .where(Transfer.fm_save_id == save_id, Transfer.player_instance_id == instance_id)
            .order_by(Transfer.transfer_date.desc(), Transfer.id.desc())
            .limit(limit)
        )
    )
    return [serialize_transfer(row, clubs) for row in rows]


def _clauses(db: Session, save_id: int, instance_id: int) -> list[dict[str, Any]]:
    rows = db.execute(
        select(TransferFeeComponent, Transfer)
        .join(Transfer, Transfer.id == TransferFeeComponent.transfer_id)
        .where(Transfer.fm_save_id == save_id, Transfer.player_instance_id == instance_id)
        .order_by(Transfer.transfer_date.desc(), TransferFeeComponent.id.asc())
    ).all()
    items: list[dict[str, Any]] = []
    for component, transfer in rows:
        items.append(
            {
                "clause_id": component.id,
                "transfer_id": transfer.id,
                "clause_type": component.component_type,
                "clause_value": component.amount,
                "currency": transfer.currency,
                "trigger_condition": component.condition,
                "payment_schedule": component.payment_schedule,
                "clause_status": component.status,
                "due_date": iso(component.due_date),
                "source": component.source or transfer.source,
                "confidence": component.confidence if component.confidence is not None else transfer.confidence,
            }
        )
    return items


def valuation_summary(db: Session, instance_id: int) -> dict[str, Any]:
    """确定性估值；样本不足时明确拒绝给区间。"""
    result = estimate_value(db, instance_id)
    return {
        "low": result.get("low"),
        "mid": result.get("mid"),
        "high": result.get("high"),
        "sample_size": result.get("sample_size"),
        "confidence": result.get("confidence"),
        "insufficient_sample": result.get("insufficient_sample"),
        "method": result.get("method"),
        "algorithm_version": result.get("algorithm_version"),
        "warnings": result.get("warnings") or [],
    }


def player_transfer_context(db: Session, instance: PlayerInstance) -> dict[str, Any]:
    """一名球员的交易上下文：合同、可用性、租借、历史、条款、估值。"""
    snapshot = latest_snapshot(db, instance.id)
    player = db.get(PlayerInstance, instance.id)
    if player is None:
        raise ValueError("player instance not found")
    availability = latest_availability(db, instance.id)
    loan = latest_loan(db, instance.id)
    contract = _contract(db, instance, snapshot)
    history = _transfer_rows(db, instance.fm_save_id, instance.id)
    clauses = _clauses(db, instance.fm_save_id, instance.id)
    valuation = valuation_summary(db, instance.id)
    missing: list[str] = list(contract["missing_fields"])
    if not history:
        missing.append("transfer_history")
    if not clauses:
        missing.append("transfer_clauses")
    if not loan:
        missing.append("loan_terms")
    missing.append("transfer_budget")
    return {
        "instance_id": instance.id,
        "save_id": instance.fm_save_id,
        "player": {
            "name": player.player.full_name if player.player is not None else None,
            "club_id": contract["club_id"],
            "position": snapshot.position if snapshot is not None else instance.position,
            "age": snapshot.age if snapshot is not None else None,
            "ca": snapshot.ca if snapshot is not None else None,
            "pa": snapshot.pa if snapshot is not None else None,
            "market_value": snapshot.market_value if snapshot is not None else None,
            "height_cm": snapshot.height_cm if snapshot is not None else None,
            "foot": snapshot.foot if snapshot is not None else None,
        },
        "contract": contract,
        "availability": {
            "listed": availability.listed if availability else None,
            "loan_listed": availability.loan_listed if availability else None,
            "not_for_sale": availability.not_for_sale if availability else None,
            "set_for_release": availability.set_for_release if availability else None,
            "agreed_to_club_id": availability.agreed_to_club_id if availability else None,
            "agreed_transfer_date": iso(availability.agreed_transfer_date) if availability else None,
            "observed_at": iso(availability.observed_at) if availability else None,
        },
        "loan": _loan_payload(loan),
        "transfer_history": history,
        "clauses": clauses,
        "valuation": valuation,
        "missing_fields": sorted(set(missing)),
        "sources": {
            "contract": contract["source"],
            "availability": availability.source if availability else None,
            "transfers": sorted({item.get("source") for item in history if item.get("source")}),
            "clauses": sorted({item["source"] for item in clauses if item.get("source")}),
        },
    }


def _club_name(db: Session, club_id: int | None) -> str | None:
    if club_id is None:
        return None
    club = db.get(Club, club_id)
    return club.name if club else None


def enrich_context(db: Session, context: dict[str, Any]) -> dict[str, Any]:
    """补上俱乐部名，前端不需要再查一次。"""
    club_id = (context.get("contract") or {}).get("club_id")
    context["player"]["club_name"] = _club_name(db, club_id)
    return context


def _factor_bundle(db: Session, instance: PlayerInstance, snapshot: PlayerSnapshot | None,
                   contract: dict[str, Any]) -> dict[str, Any]:
    remaining = contract.get("remaining_months")
    if remaining is None:
        contract_factor, contract_note = 1.0, "缺少合同剩余时间，未做合同调整"
    elif remaining < 6:
        contract_factor, contract_note = 0.75, "合同剩余不足 6 个月，买方压价 25%"
    elif remaining < 12:
        contract_factor, contract_note = 0.88, "合同剩余不足 12 个月，买方压价 12%"
    elif remaining >= 36:
        contract_factor, contract_note = 1.05, "合同剩余 36 个月以上，卖方溢价 5%"
    else:
        contract_factor, contract_note = 1.0, None

    age = snapshot.age if snapshot is not None else None
    if age is None:
        age_factor, age_note = 1.0, "缺少年龄，未做年龄调整"
    elif age <= 21:
        age_factor, age_note = 1.10, "21 岁及以下，潜力溢价 10%"
    elif age <= 27:
        age_factor, age_note = 1.0, None
    elif age <= 30:
        age_factor, age_note = 0.90, "28–30 岁，折价 10%"
    elif age <= 33:
        age_factor, age_note = 0.78, "31–33 岁，折价 22%"
    else:
        age_factor, age_note = 0.62, "34 岁以上，折价 38%"

    ca = snapshot.ca if snapshot is not None else None
    if ca is None:
        ca_factor, ca_note = 1.0, "缺少能力值，未做能力调整"
    else:
        ca_factor = _clamp(1 + (ca - 140) * 0.005, 0.7, 1.4)
        ca_note = f"以 CA 140 为基准，每点 ±0.5%（当前 {ca}）" if ca != 140 else None

    listed = contract.get("listed")
    not_for_sale = contract.get("not_for_sale")
    if listed is True:
        availability_factor, availability_note = 0.90, "球员已挂牌，卖方议价空间下降 10%"
    elif not_for_sale is True:
        availability_factor, availability_note = 1.15, "球员被标记为非卖品，需要溢价 15%"
    else:
        availability_factor, availability_note = 1.0, "挂牌状态未知，未做议价调整"

    notes = [note for note in (contract_note, age_note, ca_note, availability_note) if note]
    return {
        "contract_factor": contract_factor,
        "age_factor": round(age_factor, 4),
        "ca_factor": round(ca_factor, 4),
        "availability_factor": availability_factor,
        "combined_multiplier": round(contract_factor * age_factor * ca_factor * availability_factor, 4),
        "notes": notes,
    }


def _base_value(db: Session, instance: PlayerInstance, snapshot: PlayerSnapshot | None) -> dict[str, Any]:
    valuation = valuation_summary(db, instance.id)
    market_value = snapshot.market_value if snapshot is not None else None
    if valuation["mid"] is not None:
        return {
            "basis": "comparable_transfers",
            "base": float(valuation["mid"]),
            "currency": None,
            "sample_size": valuation["sample_size"],
            "confidence": valuation["confidence"],
            "valuation": valuation,
            "warnings": list(valuation["warnings"]),
        }
    if market_value is not None and market_value > 0:
        return {
            "basis": "market_value_only",
            "base": float(market_value),
            "currency": None,
            "sample_size": 0,
            "confidence": "low",
            "valuation": valuation,
            "warnings": [
                "可比成交样本不足，以下方案仅以当前身价为基准；身价不是成交价",
                *valuation["warnings"],
            ],
        }
    return {
        "basis": "unavailable",
        "base": None,
        "currency": None,
        "sample_size": 0,
        "confidence": "none",
        "valuation": valuation,
        "warnings": ["既没有可比成交，也没有身价；无法生成可靠报价，不编造金额"],
    }


def _offer(
    *,
    offer_type: str,
    base: float,
    committed_multiplier: float,
    immediate_share: float,
    addons_share: float,
    sell_on_pct: float | None,
    wage_impact: float | None,
    risk_level: str,
    rationale: dict[str, Any],
    currency: str | None = None,
    currency_known: bool = False,
) -> dict[str, Any]:
    committed = base * committed_multiplier
    addons = committed * addons_share
    installments = committed * (1 - immediate_share)
    return {
        "offer_type": offer_type,
        "currency": currency,
        "currency_known": currency_known,
        "base_fee": fee_round(committed),
        "immediate_payment": fee_round(committed * immediate_share),
        "installments_total": fee_round(installments) if installments else None,
        "addons_potential": fee_round(addons) if addons else None,
        "total_committed": fee_round(committed),
        "potential_total": fee_round(committed + addons),
        "sell_on_pct": sell_on_pct,
        "wage_impact": wage_impact,
        "risk_level": risk_level,
        "rationale": rationale,
        "algorithm_version": OFFER_VERSION,
    }


def generate_purchase_offers(
    db: Session, instance: PlayerInstance, budget: float | None = None
) -> dict[str, Any]:
    snapshot = latest_snapshot(db, instance.id)
    contract = _contract(db, instance, snapshot)
    factors = _factor_bundle(db, instance, snapshot, contract)
    base_info = _base_value(db, instance, snapshot)
    currency = save_currency(db, instance.fm_save_id)
    missing = list(contract["missing_fields"]) + ["transfer_budget"]
    warnings = list(base_info["warnings"])
    if not currency["known"]:
        warnings.append("当前存档货币单位未知，金额只保留数值，未做任何币种换算")

    if budget is None:
        warnings.append("当前未获取可靠预算数据，报价方案不包含预算可行性保证")
        budget_status = "unknown"
        budget_note = "预算状态未知，无法确认该报价符合俱乐部财政条件。"
    else:
        budget_status = None
        budget_note = None

    if base_info["base"] is None:
        return {
            "instance_id": instance.id,
            "direction": "purchase",
            **_currency_fields(currency),
            "available": False,
            "offers": [],
            "factors": factors,
            "basis": base_info,
            "budget": {"provided": budget is not None, "value": budget},
            "budget_status": budget_status or "provided",
            "budget_note": budget_note,
            "strategy_adjustment": strategy_adjustment(db, instance.fm_save_id, instance, None),
            "warnings": warnings,
            "missing_fields": sorted(set(missing)),
            "algorithm_version": OFFER_VERSION,
        }

    adjusted = base_info["base"] * factors["combined_multiplier"]
    adjustment = strategy_adjustment(db, instance.fm_save_id, instance, adjusted)
    if adjustment["applied"]:
        adjusted = adjusted * float(adjustment["multiplier"])
    annual_wage = contract["annual_wage"]
    rationale_common = {
        "basis": base_info["basis"],
        "base": fee_round(base_info["base"]),
        "adjusted_base": fee_round(adjusted),
        "factors": factors,
        "valuation": base_info["valuation"],
        "missing_fields": sorted(set(missing)),
    }
    offers = [
        _offer(
            offer_type="conservative",
            base=adjusted,
            committed_multiplier=0.85,
            immediate_share=1.0,
            addons_share=0.0,
            sell_on_pct=None,
            wage_impact=annual_wage,
            risk_level="low",
            currency=currency["currency"],
            currency_known=currency["known"],
            rationale={
                **rationale_common,
                "reason": "一次性付清、低于估值 15%，先试探卖方底线；成交概率最低",
                "payment_plan": "签约时支付全部固定费用",
            },
        ),
        _offer(
            offer_type="competitive",
            base=adjusted,
            committed_multiplier=1.0,
            immediate_share=0.6,
            addons_share=0.05,
            sell_on_pct=None,
            wage_impact=annual_wage,
            risk_level="medium",
            currency=currency["currency"],
            currency_known=currency["known"],
            rationale={
                **rationale_common,
                "reason": "固定费用贴近估值，60% 首付 + 40% 分期，另留 5% 浮动条款",
                "payment_plan": "首付 60%，余款按合同分期；浮动费用按出场条件触发",
            },
        ),
        _offer(
            offer_type="fast_close",
            base=adjusted,
            committed_multiplier=1.18,
            immediate_share=1.0,
            addons_share=0.05,
            sell_on_pct=None,
            wage_impact=annual_wage,
            risk_level="high",
            currency=currency["currency"],
            currency_known=currency["known"],
            rationale={
                **rationale_common,
                "reason": "溢价 18% 并全额首付，用于必须拿下的目标；成本最高",
                "payment_plan": "签约时全额支付，另 5% 浮动条款",
            },
        ),
    ]
    for offer in offers:
        if budget is not None and offer["immediate_payment"] is not None and offer["immediate_payment"] > budget:
            offer["budget_feasible"] = False
            offer["rationale"]["budget_note"] = "立即支付超过当前可用预算，需要调整分期或降低报价"
        else:
            offer["budget_feasible"] = None if budget is None else True
        before_total = (
            fee_round(float(offer["total_committed"]) / float(adjustment["multiplier"]))
            if adjustment["applied"] and adjustment["multiplier"]
            else offer["total_committed"]
        )
        offer["strategy_adjustment"] = {
            "applied": adjustment["applied"],
            "multiplier": adjustment["multiplier"],
            "before": before_total,
            "after": offer["total_committed"],
            "case_ids": adjustment["case_ids"],
        }
        offer["rationale"]["case_ids"] = adjustment["case_ids"]

    if budget is not None:
        if any(offer["budget_feasible"] is False for offer in offers):
            budget_status = "insufficient"
            budget_note = "存在即时支付超过预算的方案，需要调整分期或降低报价"
        else:
            budget_status = "provided"
            budget_note = None
    return {
        "instance_id": instance.id,
        "direction": "purchase",
        **_currency_fields(currency),
        "available": True,
        "offers": offers,
        "factors": factors,
        "basis": {
            "kind": base_info["basis"],
            "base": fee_round(base_info["base"]),
            "sample_size": base_info["sample_size"],
            "confidence": base_info["confidence"],
        },
        "budget": {"provided": budget is not None, "value": budget},
        "budget_status": budget_status,
        "budget_note": budget_note,
        "strategy_adjustment": adjustment,
        "warnings": warnings,
        "missing_fields": sorted(set(missing)),
        "algorithm_version": OFFER_VERSION,
    }


def _position_depth(db: Session, save_id: int, club_id: int | None, position: str | None) -> int | None:
    if club_id is None or not position:
        return None
    query = (
        select(func.count())
        .select_from(PlayerInstance)
        .join(PlayerSnapshot, PlayerSnapshot.id == PlayerInstance.latest_snapshot_id)
        .where(
            PlayerInstance.fm_save_id == save_id,
            PlayerInstance.club_id == club_id,
            PlayerSnapshot.position == position,
        )
    )
    return int(db.scalar(query) or 0)


def generate_sale_offers(db: Session, instance: PlayerInstance) -> dict[str, Any]:
    snapshot = latest_snapshot(db, instance.id)
    contract = _contract(db, instance, snapshot)
    factors = _factor_bundle(db, instance, snapshot, contract)
    base_info = _base_value(db, instance, snapshot)
    currency = save_currency(db, instance.fm_save_id)
    missing = list(contract["missing_fields"]) + ["other_club_offers"]
    warnings = list(base_info["warnings"])
    if not currency["known"]:
        warnings.append("当前存档货币单位未知，金额只保留数值，未做任何币种换算")
    depth = _position_depth(db, instance.fm_save_id, instance.club_id,
                            snapshot.position if snapshot is not None else instance.position)
    squad_impact = {
        "position": snapshot.position if snapshot is not None else instance.position,
        "same_position_peers": depth,
        "squad_gap_risk": None if depth is None else ("high" if depth <= 1 else "medium" if depth <= 2 else "low"),
        "wage_release": contract["annual_wage"],
        "note": "同位置人数来自当前存档最新快照；人数为 1 时出售会直接造成位置缺口",
    }
    if base_info["base"] is None:
        return {
            "instance_id": instance.id,
            "direction": "sale",
            **_currency_fields(currency),
            "available": False,
            "offers": [],
            "factors": factors,
            "basis": base_info,
            "squad_impact": squad_impact,
            "strategy_adjustment": strategy_adjustment(db, instance.fm_save_id, instance, None),
            "warnings": warnings,
            "missing_fields": sorted(set(missing)),
            "algorithm_version": OFFER_VERSION,
        }

    adjusted = base_info["base"] * factors["combined_multiplier"]
    adjustment = strategy_adjustment(db, instance.fm_save_id, instance, adjusted)
    if adjustment["applied"]:
        adjusted = adjusted * float(adjustment["multiplier"])
    rationale_common = {
        "basis": base_info["basis"],
        "base": fee_round(base_info["base"]),
        "adjusted_base": fee_round(adjusted),
        "factors": factors,
        "valuation": base_info["valuation"],
        "missing_fields": sorted(set(missing)),
    }
    offers = [
        _offer(
            offer_type="quick_sale",
            base=adjusted,
            committed_multiplier=0.85,
            immediate_share=1.0,
            addons_share=0.0,
            sell_on_pct=None,
            wage_impact=(-contract["annual_wage"] if contract["annual_wage"] else None),
            risk_level="low",
            currency=currency["currency"],
            currency_known=currency["known"],
            rationale={
                **rationale_common,
                "reason": "低于估值 15% 快速成交，优先释放工资与名额",
                "payment_plan": "一次性收款",
            },
        ),
        _offer(
            offer_type="fair_sale",
            base=adjusted,
            committed_multiplier=1.0,
            immediate_share=0.7,
            addons_share=0.05,
            sell_on_pct=None,
            wage_impact=(-contract["annual_wage"] if contract["annual_wage"] else None),
            risk_level="medium",
            currency=currency["currency"],
            currency_known=currency["known"],
            rationale={
                **rationale_common,
                "reason": "固定费用贴近估值，70% 即时收款，另 5% 浮动",
                "payment_plan": "70% 即时，30% 分期",
            },
        ),
        _offer(
            offer_type="max_value",
            base=adjusted,
            committed_multiplier=1.15,
            immediate_share=0.5,
            addons_share=0.10,
            sell_on_pct=10.0,
            wage_impact=(-contract["annual_wage"] if contract["annual_wage"] else None),
            risk_level="high",
            currency=currency["currency"],
            currency_known=currency["known"],
            rationale={
                **rationale_common,
                "reason": "溢价 15% 并附加 10% 二次转会分成，等待时间与失败概率更高",
                "payment_plan": "50% 即时，50% 分期，附加二转分成",
            },
        ),
    ]
    for offer in offers:
        offer["strategy_adjustment"] = {
            "applied": adjustment["applied"],
            "multiplier": adjustment["multiplier"],
            "before": offer["total_committed"],
            "after": offer["total_committed"],
            "case_ids": adjustment["case_ids"],
        }
        offer["rationale"]["case_ids"] = adjustment["case_ids"]
    return {
        "instance_id": instance.id,
        "direction": "sale",
        **_currency_fields(currency),
        "available": True,
        "offers": offers,
        "factors": factors,
        "basis": {
            "kind": base_info["basis"],
            "base": fee_round(base_info["base"]),
            "sample_size": base_info["sample_size"],
            "confidence": base_info["confidence"],
        },
        "squad_impact": squad_impact,
        "strategy_adjustment": adjustment,
        "warnings": warnings,
        "missing_fields": sorted(set(missing)),
        "algorithm_version": OFFER_VERSION,
    }


def generate_loan_offers(db: Session, instance: PlayerInstance) -> dict[str, Any]:
    """V3.3.2-05-05：三套租借方案（低成本 / 发展型 / 租借后买断）。

    金额全部由确定性规则从估值推导；未知估值不生成金额。租借费、工资承担与买断费
    都是"建议条款"，不是当前合同事实。
    """
    snapshot = latest_snapshot(db, instance.id)
    contract = _contract(db, instance, snapshot)
    factors = _factor_bundle(db, instance, snapshot, contract)
    base_info = _base_value(db, instance, snapshot)
    currency = save_currency(db, instance.fm_save_id)
    availability = latest_availability(db, instance.id)
    missing = list(contract["missing_fields"]) + ["loan_terms", "transfer_budget"]
    warnings = list(base_info["warnings"])
    if not currency["known"]:
        warnings.append("当前存档货币单位未知，金额只保留数值，未做任何币种换算")
    if availability is None or availability.loan_listed is not True:
        warnings.append("游戏内未标记可租借，报价可能被拒绝")
    if latest_loan(db, instance.id) is not None:
        warnings.append("该球员已存在租借关系，先确认原租借是否结束")
    warnings.append("当前未获取可靠预算数据，租借方案不包含预算可行性保证")

    if base_info["base"] is None:
        return {
            "instance_id": instance.id,
            "direction": "loan",
            **_currency_fields(currency),
            "available": False,
            "offers": [],
            "factors": factors,
            "basis": base_info,
            "strategy_adjustment": strategy_adjustment(db, instance.fm_save_id, instance, None),
            "warnings": warnings,
            "missing_fields": sorted(set(missing)),
            "algorithm_version": LOAN_OFFER_VERSION,
        }

    adjusted = base_info["base"] * factors["combined_multiplier"]
    adjustment = strategy_adjustment(db, instance.fm_save_id, instance, adjusted)
    if adjustment["applied"]:
        adjusted = adjusted * float(adjustment["multiplier"])
    annual_wage = contract["annual_wage"]
    loan_months = 12
    rationale_common = {
        "basis": base_info["basis"],
        "base": fee_round(base_info["base"]),
        "adjusted_base": fee_round(adjusted),
        "factors": factors,
        "valuation": base_info["valuation"],
        "missing_fields": sorted(set(missing)),
        "loan_months": loan_months,
        "note": "租借费、工资承担与买断费均为 AI 建议条款，不是当前合同已有条款",
        "case_ids": adjustment["case_ids"],
    }

    def _loan_offer(offer_type: str, fee_pct: float, wage_pct: float, option_fee: float | None,
                    obligation_fee: float | None, risk: str, reason: str) -> dict[str, Any]:
        loan_fee = adjusted * fee_pct
        buy_fee = option_fee if option_fee is not None else obligation_fee
        return {
            "offer_type": offer_type,
            "currency": currency["currency"],
            "currency_known": currency["known"],
            "base_fee": fee_round(loan_fee),
            "immediate_payment": fee_round(loan_fee),
            "installments_total": None,
            "addons_potential": None,
            "total_committed": fee_round(loan_fee),
            "potential_total": fee_round(loan_fee + (buy_fee or 0)),
            "sell_on_pct": None,
            "wage_impact": fee_round(annual_wage * wage_pct / 100) if annual_wage is not None else None,
            "loan_fee": fee_round(loan_fee),
            "wage_contribution_pct": wage_pct,
            "buy_option_fee": fee_round(option_fee) if option_fee is not None else None,
            "buy_obligation_fee": fee_round(obligation_fee) if obligation_fee is not None else None,
            "loan_months": loan_months,
            "risk_level": risk,
            "rationale": {**rationale_common, "reason": reason},
            "algorithm_version": LOAN_OFFER_VERSION,
        }

    offers = [
        _loan_offer(
            "low_cost_loan", 0.01, 30, None, None, "low",
            "只承担 1% 租借费与 30% 工资，成本最低，适合轮换与短租试探",
        ),
        _loan_offer(
            "development_loan", 0.03, 50, adjusted * 0.95, None, "medium",
            "承担 3% 租借费与 50% 工资，并保留 95% 估值的买断选择权，适合年轻球员发展",
        ),
        _loan_offer(
            "loan_to_buy", 0.05, 70, None, adjusted, "high",
            "承担 5% 租借费与 70% 工资，附带等值强制买断，适合确定要长期留下的目标",
        ),
    ]
    for offer in offers:
        offer["strategy_adjustment"] = {
            "applied": adjustment["applied"],
            "multiplier": adjustment["multiplier"],
            "before": offer["total_committed"],
            "after": offer["total_committed"],
            "case_ids": adjustment["case_ids"],
        }
    return {
        "instance_id": instance.id,
        "direction": "loan",
        **_currency_fields(currency),
        "available": True,
        "offers": offers,
        "factors": factors,
        "basis": {
            "kind": base_info["basis"],
            "base": fee_round(base_info["base"]),
            "sample_size": base_info["sample_size"],
            "confidence": base_info["confidence"],
        },
        "loan_listed": availability.loan_listed if availability is not None else None,
        "strategy_adjustment": adjustment,
        "warnings": warnings,
        "missing_fields": sorted(set(missing)),
        "algorithm_version": LOAN_OFFER_VERSION,
    }


def save_offer(db: Session, save_id: int, instance_id: int, direction: str, payload: dict[str, Any]) -> TransferOffer:
    offer = TransferOffer(
        fm_save_id=save_id,
        player_instance_id=instance_id,
        direction=direction,
        offer_type=str(payload.get("offer_type") or "custom"),
        base_fee=payload.get("base_fee"),
        immediate_payment=payload.get("immediate_payment"),
        installments_total=payload.get("installments_total"),
        addons_potential=payload.get("addons_potential"),
        total_committed=payload.get("total_committed"),
        potential_total=payload.get("potential_total"),
        sell_on_pct=payload.get("sell_on_pct"),
        currency=(str(payload.get("currency") or UNKNOWN_CURRENCY).strip()[:8] or UNKNOWN_CURRENCY),
        wage_impact=payload.get("wage_impact"),
        loan_fee=payload.get("loan_fee"),
        wage_contribution_pct=payload.get("wage_contribution_pct"),
        buy_option_fee=payload.get("buy_option_fee"),
        buy_obligation_fee=payload.get("buy_obligation_fee"),
        loan_months=payload.get("loan_months"),
        risk_level=str(payload.get("risk_level") or "medium"),
        rationale_json=json.dumps(payload.get("rationale") or {}, ensure_ascii=False),
        algorithm_version=str(payload.get("algorithm_version") or OFFER_VERSION),
        status=str(payload.get("status") or "saved"),
        source=str(payload.get("source") or "user_confirmed"),
        created_by=str(payload.get("created_by") or "user"),
    )
    db.add(offer)
    db.commit()
    db.refresh(offer)
    return offer


def serialize_offer(offer: TransferOffer) -> dict[str, Any]:
    currency_known = bool(offer.currency) and offer.currency != UNKNOWN_CURRENCY
    return {
        "offer_id": offer.id,
        "instance_id": offer.player_instance_id,
        "direction": offer.direction,
        "offer_type": offer.offer_type,
        "base_fee": offer.base_fee,
        "immediate_payment": offer.immediate_payment,
        "installments_total": offer.installments_total,
        "addons_potential": offer.addons_potential,
        "total_committed": offer.total_committed,
        "potential_total": offer.potential_total,
        "sell_on_pct": offer.sell_on_pct,
        "currency": offer.currency if currency_known else None,
        "currency_known": currency_known,
        "currency_note": None if currency_known else "货币单位未知",
        "wage_impact": offer.wage_impact,
        "loan_fee": offer.loan_fee,
        "wage_contribution_pct": offer.wage_contribution_pct,
        "buy_option_fee": offer.buy_option_fee,
        "buy_obligation_fee": offer.buy_obligation_fee,
        "loan_months": offer.loan_months,
        "risk_level": offer.risk_level,
        "rationale": _loads(offer.rationale_json),
        "algorithm_version": offer.algorithm_version,
        "status": offer.status,
        "source": offer.source,
        "created_by": offer.created_by,
        "created_at": iso(offer.created_at),
    }


def _loads(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def list_offers(db: Session, save_id: int, instance_id: int | None = None, direction: str | None = None,
                limit: int = 50) -> list[TransferOffer]:
    query = select(TransferOffer).where(TransferOffer.fm_save_id == save_id)
    if instance_id is not None:
        query = query.where(TransferOffer.player_instance_id == instance_id)
    if direction is not None:
        query = query.where(TransferOffer.direction == direction)
    return list(db.scalars(query.order_by(TransferOffer.created_at.desc(), TransferOffer.id.desc()).limit(limit)))


def create_negotiation(
    db: Session,
    *,
    save_id: int,
    instance_id: int,
    direction: str,
    offer_id: int | None = None,
    initial_ask: float | None = None,
    note: str | None = None,
) -> TransferNegotiation:
    negotiation = TransferNegotiation(
        fm_save_id=save_id,
        player_instance_id=instance_id,
        offer_id=offer_id,
        direction=direction,
        status="DRAFT",
        initial_ask=initial_ask,
        currency="EUR",
        source="user_confirmed",
    )
    db.add(negotiation)
    db.flush()
    db.add(
        NegotiationEvent(
            negotiation_id=negotiation.id,
            fm_save_id=save_id,
            event_type="draft_created",
            amount=initial_ask,
            event_data_json=json.dumps({"note": note} if note else {}, ensure_ascii=False),
            source="user_confirmed",
            occurred_at=utcnow(),
        )
    )
    db.commit()
    db.refresh(negotiation)
    return negotiation


def _event_exists(db: Session, negotiation_id: int, event_type: str, occurred_at: datetime,
                  amount: float | None, payload: str) -> NegotiationEvent | None:
    return db.scalar(
        select(NegotiationEvent).where(
            NegotiationEvent.negotiation_id == negotiation_id,
            NegotiationEvent.event_type == event_type,
            NegotiationEvent.occurred_at == occurred_at,
            NegotiationEvent.amount == amount if amount is not None else NegotiationEvent.amount.is_(None),
            NegotiationEvent.event_data_json == payload,
        ).limit(1)
    )


def append_event(
    db: Session,
    negotiation: TransferNegotiation,
    *,
    event_type: str,
    amount: float | None = None,
    data: dict[str, Any] | None = None,
    occurred_at: datetime | None = None,
    source: str = "user_confirmed",
) -> tuple[NegotiationEvent, bool]:
    """追加谈判事件；完全相同的事件不重复写入。"""
    if event_type not in EVENT_TYPES:
        raise ValueError(f"不支持的事件类型 {event_type}")
    when = occurred_at or utcnow()
    payload = json.dumps(data or {}, ensure_ascii=False, sort_keys=True)
    existing = _event_exists(db, negotiation.id, event_type, when, amount, payload)
    if existing is not None:
        return existing, True
    event = NegotiationEvent(
        negotiation_id=negotiation.id,
        fm_save_id=negotiation.fm_save_id,
        event_type=event_type,
        amount=amount,
        event_data_json=payload,
        source=source,
        occurred_at=when,
    )
    db.add(event)
    new_status = STATUS_BY_EVENT[event_type]
    if new_status is not None:
        negotiation.status = new_status
    if event_type in ROUND_EVENTS:
        negotiation.round_count = int(negotiation.round_count or 0) + 1
    if amount is not None:
        if event_type == "counter_received":
            negotiation.counter_offer = amount
        elif event_type in {"offer_submitted", "offer_revised"}:
            negotiation.user_offer = amount
        elif event_type == "completed":
            negotiation.final_fee = amount
    if event_type == "completed":
        negotiation.completed_at = when
    if event_type == "rejected" and data and data.get("reason"):
        negotiation.reject_reason = str(data["reason"])[:256]
    if event_type in {"completed", "accepted"} and data and data.get("terms"):
        negotiation.final_terms_json = json.dumps(data["terms"], ensure_ascii=False)
    db.commit()
    db.refresh(event)
    db.refresh(negotiation)
    return event, False


def serialize_negotiation(negotiation: TransferNegotiation, events: list[NegotiationEvent] | None = None) -> dict[str, Any]:
    payload = {
        "negotiation_id": negotiation.id,
        "instance_id": negotiation.player_instance_id,
        "offer_id": negotiation.offer_id,
        "direction": negotiation.direction,
        "status": negotiation.status,
        "round_count": negotiation.round_count,
        "initial_ask": negotiation.initial_ask,
        "user_offer": negotiation.user_offer,
        "counter_offer": negotiation.counter_offer,
        "final_fee": negotiation.final_fee,
        "currency": negotiation.currency,
        "final_terms": _loads(negotiation.final_terms_json),
        "reject_reason": negotiation.reject_reason,
        "source": negotiation.source,
        "created_at": iso(negotiation.created_at),
        "completed_at": iso(negotiation.completed_at),
    }
    if events is not None:
        payload["events"] = [
            {
                "event_id": event.id,
                "event_type": event.event_type,
                "amount": event.amount,
                "data": _loads(event.event_data_json),
                "source": event.source,
                "occurred_at": iso(event.occurred_at),
            }
            for event in events
        ]
    return payload


def negotiation_events(db: Session, negotiation_id: int) -> list[NegotiationEvent]:
    return list(
        db.scalars(
            select(NegotiationEvent)
            .where(NegotiationEvent.negotiation_id == negotiation_id)
            .order_by(NegotiationEvent.occurred_at.asc(), NegotiationEvent.id.asc())
        )
    )


def review_negotiation(db: Session, negotiation: TransferNegotiation) -> dict[str, Any]:
    events = negotiation_events(db, negotiation.id)
    valuation = valuation_summary(db, negotiation.player_instance_id)
    initial_offer = negotiation.initial_ask
    if initial_offer is None:
        first = next((event for event in events if event.amount is not None and event.event_type in
                      {"offer_generated", "offer_submitted", "draft_created"}), None)
        initial_offer = first.amount if first is not None else None
    final_fee = negotiation.final_fee
    delta = None
    delta_pct = None
    if initial_offer is not None and final_fee is not None:
        delta = fee_round(final_fee - initial_offer)
        if initial_offer:
            delta_pct = round((final_fee - initial_offer) / initial_offer * 100, 1)

    completed_samples = db.scalar(
        select(func.count()).select_from(TransferNegotiation).where(
            TransferNegotiation.fm_save_id == negotiation.fm_save_id,
            TransferNegotiation.status.in_(("COMPLETED", "ACCEPTED")),
        )
    ) or 0

    outcome = {
        "COMPLETED": "成交",
        "ACCEPTED": "对方接受，等待游戏内完成",
        "REJECTED": "被拒绝",
        "WITHDRAWN": "已撤回",
        "CANCELLED": "已取消",
    }.get(negotiation.status, "进行中")

    warnings: list[str] = []
    if completed_samples < 5:
        warnings.append("当前历史谈判样本不足，暂不形成可靠规律")

    return {
        "negotiation_id": negotiation.id,
        "instance_id": negotiation.player_instance_id,
        "direction": negotiation.direction,
        "status": negotiation.status,
        "outcome": outcome,
        "initial_valuation": {
            "low": valuation["low"],
            "mid": valuation["mid"],
            "high": valuation["high"],
            "confidence": valuation["confidence"],
            "insufficient_sample": valuation["insufficient_sample"],
        },
        "initial_offer": initial_offer,
        "final_fee": final_fee,
        "delta": delta,
        "delta_pct": delta_pct,
        "round_count": negotiation.round_count,
        "counter_offer": negotiation.counter_offer,
        "reject_reason": negotiation.reject_reason,
        "final_terms": _loads(negotiation.final_terms_json),
        "completed_samples_in_save": int(completed_samples),
        "warnings": warnings,
        "algorithm_version": REVIEW_VERSION,
    }


def club_transfer_summary(db: Session, save_id: int, club_id: int) -> dict[str, Any]:
    """用户俱乐部的买入/卖出/租借/自由/未来/取消汇总；金额按币种分开，不混算。"""
    incoming = list(db.scalars(select(Transfer).where(Transfer.fm_save_id == save_id, Transfer.to_club_id == club_id)))
    outgoing = list(db.scalars(select(Transfer).where(Transfer.fm_save_id == save_id, Transfer.from_club_id == club_id)))

    def bucket(rows: list[Transfer]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in rows:
            key = row.transfer_type or "unknown"
            counts[key] = counts.get(key, 0) + 1
        return counts

    def cash(rows: list[Transfer]) -> dict[str, float]:
        totals: dict[str, float] = {}
        for row in rows:
            if row.status != "completed":
                continue
            amount = row.effective_fee if row.effective_fee is not None else row.base_fee
            if amount is None:
                continue
            totals[row.currency] = round(totals.get(row.currency, 0.0) + float(amount), 2)
        return totals

    completed = [row for row in incoming if row.status == "completed"]
    return {
        "club_id": club_id,
        "club_name": _club_name(db, club_id),
        "purchases": len(incoming),
        "sales": len(outgoing),
        "incoming_by_type": bucket(incoming),
        "outgoing_by_type": bucket(outgoing),
        "completed_incoming": len(completed),
        "completed_outgoing": len([row for row in outgoing if row.status == "completed"]),
        "cash_in_by_currency": cash(outgoing),
        "cash_out_by_currency": cash(incoming),
        "agreed": len([row for row in incoming + outgoing if row.status == "agreed"]),
        "pending": len([row for row in incoming + outgoing if row.status in {"pending", "future"}]),
        "cancelled": len([row for row in incoming + outgoing if row.status in {"cancelled", "failed"}]),
        "warning": None if (incoming or outgoing) else "当前存档没有该俱乐部的转会记录；导入历史转会文件后才有数据",
    }


def overview(db: Session, save_id: int, user_club_id: int | None) -> dict[str, Any]:
    latest = (
        select(PlayerInstance.id, PlayerSnapshot.wage, PlayerSnapshot.contract_end, PlayerSnapshot.observed_at)
        .join(PlayerSnapshot, PlayerSnapshot.id == PlayerInstance.latest_snapshot_id)
        .where(PlayerInstance.fm_save_id == save_id)
        .subquery()
    )
    players = int(db.scalar(select(func.count()).select_from(latest)) or 0)
    with_wage = int(db.scalar(select(func.count()).select_from(latest).where(latest.c.wage.is_not(None))) or 0)
    with_contract = int(db.scalar(select(func.count()).select_from(latest).where(latest.c.contract_end.is_not(None))) or 0)
    transfer_count = int(db.scalar(select(func.count()).select_from(Transfer).where(Transfer.fm_save_id == save_id)) or 0)
    loan_count = int(db.scalar(select(func.count()).select_from(LoanRecord).where(LoanRecord.fm_save_id == save_id)) or 0)
    clause_count = int(
        db.scalar(
            select(func.count())
            .select_from(TransferFeeComponent)
            .join(Transfer, Transfer.id == TransferFeeComponent.transfer_id)
            .where(Transfer.fm_save_id == save_id)
        ) or 0
    )
    last_sync = db.scalar(
        select(func.max(ImportJob.finished_at)).where(ImportJob.fm_save_id == save_id, ImportJob.finished_at.is_not(None))
    )
    conflicts = int(
        db.scalar(
            select(func.count()).select_from(IdentityConflict).where(
                IdentityConflict.fm_save_id == save_id, IdentityConflict.status == "open"
            )
        ) or 0
    )
    negotiation_counts = {
        status: int(count)
        for status, count in db.execute(
            select(TransferNegotiation.status, func.count())
            .where(TransferNegotiation.fm_save_id == save_id)
            .group_by(TransferNegotiation.status)
        ).all()
    }
    offers = int(db.scalar(select(func.count()).select_from(TransferOffer).where(TransferOffer.fm_save_id == save_id)) or 0)
    recent_cutoff = date.today() - timedelta(days=30)
    recent = int(
        db.scalar(
            select(func.count()).select_from(Transfer).where(
                Transfer.fm_save_id == save_id, Transfer.transfer_date >= recent_cutoff
            )
        ) or 0
    )
    unknown_fields = players - with_contract + players - with_wage
    message = f"当前存档有 {players} 名球员，其中 {with_contract} 名有合同到期日；转会记录 {transfer_count} 条。"
    if transfer_count == 0:
        message += " 当前数据源不提供历史转会，导入 CSV/JSON 后才能分析成交价格。"
    return {
        "save_id": save_id,
        "user_club_id": user_club_id,
        "player_count": players,
        "players_with_wage": with_wage,
        "players_with_contract": with_contract,
        "unknown_contract_fields": unknown_fields,
        "transfer_count": transfer_count,
        "recent_transfers_30d": recent,
        "loan_count": loan_count,
        "clause_count": clause_count,
        "identity_conflicts": conflicts,
        "last_sync_at": iso(last_sync),
        "offers": offers,
        "negotiations": negotiation_counts,
        "negotiations_total": sum(negotiation_counts.values()),
        "capabilities": {
            "auto_transfer_history": False,
            "auto_contract": with_contract > 0,
            "auto_loan_terms": loan_count > 0,
            "auto_budget": False,
        },
        "message": message,
    }


# ---------------------------------------------------------------------------
# V3.3.2-07 B-08 谈判反馈与持续学习
# ---------------------------------------------------------------------------

FEEDBACK_MESSAGES = {
    "completed": "已记录真实成交，将用于后续报价参考",
    "rejected": "已记录谈判结果，被拒绝的报价不计入成交统计",
    "cancelled": "已记录取消结果，不计入成交统计",
    "negotiating": "已记录为谈判中，尚未计入成交统计",
    "unknown": "已记录结果未知，不计入成交统计",
}


def _feedback_key(
    save_id: int,
    instance_id: int,
    direction: str,
    outcome: str,
    amount: float | None,
    note: str | None,
) -> str:
    raw = f"{save_id}|{instance_id}|{direction}|{outcome}|{'' if amount is None else f'{amount:.2f}'}|{note or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _feedback_result(
    db: Session,
    save_id: int,
    feedback: TransferFeedback,
    *,
    duplicate: bool,
    learning_updated: bool,
) -> dict[str, Any]:
    from . import transfer_strategy as strategy

    return {
        "duplicate": duplicate,
        "feedback_id": feedback.id,
        "outcome": feedback.outcome,
        "learning_updated": learning_updated,
        "data_version": strategy.data_version(db, save_id),
        "message": "该反馈已记录，不重复计入统计"
        if duplicate
        else FEEDBACK_MESSAGES.get(feedback.outcome, "已记录反馈"),
    }


def record_feedback(
    db: Session,
    *,
    save_id: int,
    instance_id: int,
    direction: str,
    outcome: str,
    amount: float | None = None,
    offer_id: int | None = None,
    negotiation_id: int | None = None,
    note: str | None = None,
    source: str = "user_confirmed",
) -> dict[str, Any]:
    """记录用户确认的谈判结果。

    * 只有 ``completed`` + 有效金额才派生 ``TransferNegotiation(status=COMPLETED)`` 成交案例；
    * 相同反馈由 ``dedupe_key`` 唯一约束兜底，不重复计入统计；
    * 写入后清空查询缓存，学习数据版本随之变化。
    """
    from . import query_cache

    if outcome not in FEEDBACK_OUTCOMES:
        raise ValueError("不支持的反馈结果")
    if outcome == "completed" and (amount is None or float(amount) <= 0):
        raise ValueError("真实成交必须提供有效金额")

    key = _feedback_key(save_id, instance_id, direction, outcome, amount, note)
    existing = db.scalar(select(TransferFeedback).where(TransferFeedback.dedupe_key == key))
    if existing is not None:
        return _feedback_result(db, save_id, existing, duplicate=True, learning_updated=False)

    negotiation: TransferNegotiation | None = None
    if negotiation_id is not None:
        negotiation = db.get(TransferNegotiation, negotiation_id)
        if negotiation is None or negotiation.fm_save_id != save_id:
            raise ValueError("谈判记录不存在")
    if offer_id is not None:
        offer = db.get(TransferOffer, offer_id)
        if offer is None or offer.fm_save_id != save_id:
            raise ValueError("报价方案不存在")

    feedback = TransferFeedback(
        fm_save_id=save_id,
        player_instance_id=instance_id,
        direction=direction,
        outcome=outcome,
        amount=amount,
        offer_id=offer_id,
        negotiation_id=negotiation_id,
        note=note,
        source=source,
        dedupe_key=key,
    )
    db.add(feedback)
    learning_updated = False
    if outcome == "completed":
        if negotiation is None:
            currency = save_currency(db, save_id)
            negotiation = TransferNegotiation(
                fm_save_id=save_id,
                player_instance_id=instance_id,
                offer_id=offer_id,
                direction=direction,
                status="COMPLETED",
                round_count=1,
                initial_ask=amount,
                final_fee=amount,
                currency=currency["currency"] or UNKNOWN_CURRENCY,
                completed_at=utcnow(),
                source=source,
            )
            db.add(negotiation)
            db.flush()
        else:
            negotiation.status = "COMPLETED"
            negotiation.final_fee = amount
            negotiation.completed_at = utcnow()
        feedback.negotiation_id = negotiation.id
        learning_updated = True
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(TransferFeedback).where(TransferFeedback.dedupe_key == key))
        if existing is None:
            raise
        return _feedback_result(db, save_id, existing, duplicate=True, learning_updated=False)
    db.refresh(feedback)
    query_cache.clear()
    return _feedback_result(db, save_id, feedback, duplicate=False, learning_updated=learning_updated)
