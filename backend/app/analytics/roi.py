"""转会投资回报（SM-016）。

严格区分四种口径，绝不混用：

| 口径 | 含义 | 数据来源 |
| --- | --- | --- |
| cash | 真实现金进出（转会费 + 已支付附加条款 + 租借费） | `transfer_history` + `transfer_fee_components` |
| accounting | 会计成本（现金 + 合同期工资），工资未知时只给下界并标注 | 同上 + 快照工资 |
| valuation | 估值变化（当前身价 − 买入成本），**不是已实现利润** | 最新快照 `market_value` |
| realized | 已实现收益（卖出收入 − 买入现金成本），只对已完成卖出计算 | 后续 completed 卖出交易 |

缺失数据一律 `None` + 说明，不按 0 计算。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import PlayerSnapshot, Transfer, TransferFeeComponent
from ..utils import fee_round

WEEKS_PER_YEAR = 52.0


def _paid_addons(session: Session, transfer: Transfer) -> tuple[float, float, bool]:
    """返回（已支付附加条款，潜在附加条款，是否存在未标注状态的条款）。"""
    paid = 0.0
    potential = 0.0
    uncertain = False
    for component in session.scalars(
        select(TransferFeeComponent).where(TransferFeeComponent.transfer_id == transfer.id)
    ):
        if component.amount is None:
            uncertain = True
            continue
        if component.status in {"paid", "triggered"}:
            paid += float(component.amount)
        else:
            potential += float(component.amount)
    return paid, potential, uncertain


def _latest_snapshot(session: Session, instance_id: int | None) -> PlayerSnapshot | None:
    if instance_id is None:
        return None
    return session.scalar(
        select(PlayerSnapshot)
        .where(PlayerSnapshot.player_instance_id == instance_id)
        .order_by(PlayerSnapshot.observed_at.desc())
        .limit(1)
    )


def transfer_roi(session: Session, transfer_id: int) -> dict[str, Any]:
    """一笔买入交易的现金/会计/估值/已实现四个口径。"""
    transfer = session.get(Transfer, transfer_id)
    if transfer is None:
        raise ValueError("transfer not found")
    if transfer.to_club_id is None:
        raise ValueError("not a purchase transfer")

    paid_addons, potential_addons, addon_uncertain = _paid_addons(session, transfer)
    fee = transfer.base_fee if transfer.base_fee is not None else transfer.effective_fee
    cash_cost: float | None = None
    missing: list[str] = []
    if fee is None:
        missing.append("买入转会费未知")
    else:
        cash_cost = float(fee) + paid_addons

    # 后续卖出：同一实例、日期更晚、completed、且不是同一俱乐部。
    sales = []
    if transfer.player_instance_id is not None:
        sales = [
            row
            for row in session.scalars(
                select(Transfer).where(
                    Transfer.fm_save_id == transfer.fm_save_id,
                    Transfer.player_instance_id == transfer.player_instance_id,
                    Transfer.status == "completed",
                    Transfer.transfer_date > transfer.transfer_date,
                )
            )
            if row.from_club_id == transfer.to_club_id and row.effective_fee is not None
        ]
    sale = sales[0] if sales else None
    sale_paid, sale_potential, _ = _paid_addons(session, sale) if sale is not None else (0.0, 0.0, False)

    realized = None
    if cash_cost is not None and sale is not None and sale.effective_fee is not None:
        realized = fee_round(float(sale.effective_fee) + sale_paid - cash_cost)

    snapshot = _latest_snapshot(session, transfer.player_instance_id)
    valuation = None
    if snapshot is not None and snapshot.market_value is not None and cash_cost is not None:
        valuation = {
            "market_value": snapshot.market_value,
            "observed_at": snapshot.observed_at.isoformat(),
            "delta": fee_round(float(snapshot.market_value) - cash_cost),
            "note": "估值变化不是现金利润；未卖出前不可兑现",
        }
    elif snapshot is None:
        missing.append("没有球员快照，无法估值")

    # 会计成本：现金 + 已知工资 × 合同年限（只有拿到工资才给，否则标下界）。
    accounting = None
    if snapshot is not None and snapshot.wage is not None:
        years = 5.0
        if snapshot.contract_end and transfer.transfer_date:
            years = max((snapshot.contract_end - transfer.transfer_date).days / 365.25, 0.5)
        wage_cost = float(snapshot.wage) * WEEKS_PER_YEAR * years
        accounting = {
            "years": round(years, 2),
            "wage_cost": fee_round(wage_cost),
            "total": fee_round(cash_cost + wage_cost) if cash_cost is not None else None,
            "note": "按最新快照周薪 × 合同剩余年限估算；工资未知时不给总额",
        }
    else:
        missing.append("工资未知，会计成本只能给现金下界")

    return {
        "transfer_id": transfer.id,
        "player_name": transfer.player_name,
        "player_instance_id": transfer.player_instance_id,
        "buy": {
            "date": transfer.transfer_date.isoformat(),
            "status": transfer.status,
            "type": transfer.transfer_type,
            "fee": fee,
            "paid_addons": fee_round(paid_addons),
            "potential_addons": fee_round(potential_addons),
            "cash_cost": fee_round(cash_cost) if cash_cost is not None else None,
            "addon_status_uncertain": addon_uncertain,
        },
        "sale": {
            "available": sale is not None,
            "date": sale.transfer_date.isoformat() if sale else None,
            "fee": sale.effective_fee if sale else None,
            "paid_addons": fee_round(sale_paid) if sale else None,
            "potential_addons": fee_round(sale_potential) if sale else None,
        },
        "cash": {
            "realized_profit": realized,
            "realized_note": None
            if realized is not None
            else "没有找到后续 completed 卖出记录或买入成本未知，已实现收益不可计算",
        },
        "accounting": accounting,
        "valuation": valuation,
        "cost_per_appearance": None,
        "cost_per_goal": None,
        "missing": missing,
        "algorithm_version": "transfer-roi-1",
        "notes": [
            "realized 只包含已完成卖出的现金；未卖出球员没有已实现收益",
            "valuation 是估值变化，不是现金利润",
            "附加条款未触发时只记录为潜在金额，不重复计入",
        ],
    }


def player_investment(session: Session, instance_id: int) -> dict[str, Any]:
    """一名球员在该存档内的全部买入交易汇总（多笔买入时合并现金成本）。"""
    buys = [
        row
        for row in session.scalars(
            select(Transfer).where(
                Transfer.player_instance_id == instance_id,
                Transfer.status == "completed",
                Transfer.to_club_id.is_not(None),
            )
        )
    ]
    if not buys:
        raise ValueError("no completed purchase for this player")
    items = [transfer_roi(session, row.id) for row in buys]
    cash = [item["buy"]["cash_cost"] for item in items]
    total_cash = fee_round(sum(value for value in cash if value is not None)) if any(
        value is not None for value in cash
    ) else None
    return {
        "instance_id": instance_id,
        "purchases": items,
        "total_cash_cost": total_cash,
        "complete": all(value is not None for value in cash),
        "algorithm_version": "transfer-roi-1",
    }
