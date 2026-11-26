"""只读可视化统计：球员价值散点与转会资金流向。"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..analytics.players import latest_snapshot_subquery
from ..analytics.squad import user_club
from ..db import get_db
from ..models import Club, FmSave, Transfer
from .deps import get_active_save

router = APIRouter()

#: 只计入实际成交的状态；其余仅用于 excluded 计数。
EXCLUDED_STATUSES = ("pending", "future", "cancelled", "failed")


@router.get("/visualizations/value-scatter")
def value_scatter(
    save_id: int | None = Query(default=None),
    club_id: int | None = Query(default=None),
    limit: int = Query(default=400, ge=1, le=800),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """年龄 / CA / PA / 身价散点；只返回身价非空的球员，不补 0。"""
    target = save_id or save.id
    base = latest_snapshot_subquery()
    conditions = [base.c.fm_save_id == target]
    if club_id is not None:
        conditions.append(base.c.club_id == club_id)
    total = int(db.scalar(select(func.count()).select_from(base).where(*conditions)) or 0)
    with_value = int(
        db.scalar(select(func.count()).select_from(base).where(*conditions, base.c.market_value.is_not(None))) or 0
    )
    rows = db.execute(
        select(base)
        .where(*conditions, base.c.market_value.is_not(None))
        .order_by(base.c.market_value.desc())
        .limit(limit)
    ).all()
    clubs = {club.id: club for club in db.scalars(select(Club).where(Club.fm_save_id == target))}
    points = [
        {
            "instance_id": int(row.instance_id),
            "name": str(row.full_name),
            "age": row.age,
            "ca": row.ca,
            "pa": row.pa,
            "market_value": row.market_value,
            "club": clubs[row.club_id].name if row.club_id in clubs else None,
            "position": row.position,
        }
        for row in rows
    ]
    return {
        "points": points,
        "total": total,
        "with_value": with_value,
        "returned": len(points),
        "note": "仅包含身价非空的球员；按身价从高到低截断，最多 800 人",
    }


@router.get("/visualizations/transfer-flow")
def transfer_flow(
    save_id: int | None = Query(default=None),
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    club_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """按币种汇总已完成交易的买入、卖出、租借与净支出；未完成状态只计数。"""
    target = save_id or save.id
    club = db.get(Club, club_id) if club_id is not None else user_club(db, target)
    if club is None:
        return {
            "club": None,
            "currencies": [],
            "excluded": {},
            "note": "该存档没有标记「我的俱乐部」，无法计算买入与卖出方向",
        }
    query = select(Transfer).options(selectinload(Transfer.components)).where(Transfer.fm_save_id == target)
    if from_date is not None:
        query = query.where(Transfer.transfer_date >= from_date)
    if to_date is not None:
        query = query.where(Transfer.transfer_date <= to_date)
    rows = list(db.scalars(query))
    buckets: dict[str, dict[str, Any]] = {}
    excluded = {status: 0 for status in EXCLUDED_STATUSES}
    for transfer in rows:
        if transfer.status != "completed":
            if transfer.status in excluded:
                excluded[transfer.status] += 1
            continue
        incoming = transfer.to_club_id == club.id
        outgoing = transfer.from_club_id == club.id
        if not incoming and not outgoing:
            continue
        bucket = buckets.setdefault(
            transfer.currency or "EUR",
            {
                "currency": transfer.currency or "EUR",
                "buy_total": 0.0,
                "sell_total": 0.0,
                "loan_in_fee": 0.0,
                "loan_out_fee": 0.0,
                "counts": {"permanent_buy": 0, "permanent_sell": 0, "loan_in": 0, "loan_out": 0, "free": 0},
                "unknown_fee": 0,
            },
        )
        fee = transfer.effective_fee if transfer.effective_fee is not None else transfer.fee_paid
        if transfer.transfer_type == "loan":
            loan_fee = transfer.loan_fee
            if loan_fee is None:
                # 扫描导入把租借费写成 fee component；不回填业务字段，只在统计时读取。
                component_fees = [
                    float(component.amount)
                    for component in transfer.components
                    if component.component_type == "loan_fee" and component.amount is not None
                ]
                loan_fee = sum(component_fees) if component_fees else None
            if loan_fee is None:
                bucket["unknown_fee"] += 1
            elif incoming:
                bucket["loan_in_fee"] += float(loan_fee)
                bucket["counts"]["loan_in"] += 1
            elif outgoing:
                bucket["loan_out_fee"] += float(loan_fee)
                bucket["counts"]["loan_out"] += 1
            continue
        if transfer.transfer_type in ("free", "end_of_contract"):
            bucket["counts"]["free"] += 1
            continue
        if fee is None:
            bucket["unknown_fee"] += 1
        elif incoming:
            bucket["buy_total"] += float(fee)
            bucket["counts"]["permanent_buy"] += 1
        elif outgoing:
            bucket["sell_total"] += float(fee)
            bucket["counts"]["permanent_sell"] += 1
    currencies = []
    for bucket in buckets.values():
        bucket["net"] = bucket["buy_total"] + bucket["loan_in_fee"] - bucket["sell_total"] - bucket["loan_out_fee"]
        currencies.append(bucket)
    currencies.sort(key=lambda item: abs(item["net"]), reverse=True)
    return {
        "club": {"id": club.id, "name": club.name},
        "currencies": currencies,
        "excluded": excluded,
        "note": "只统计 completed；租借费用单列；附加条款不计入已支付；不同币种不合并",
    }
