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


KNOWN_ADDON_STATUSES = {"paid", "triggered", "pending", "unpaid", "conditional"}


def _paid_addons(session: Session, transfer: Transfer) -> tuple[float, float, bool]:
    """返回（已支付附加条款，潜在附加条款，现金成本是否不完整）。

    状态未知（NULL/未知字符串）或金额缺失的条款不能被忽略：它们让现金成本变成"下界"，
    因此 `uncertain=True`，已实现收益不会被计算。
    """
    paid = 0.0
    potential = 0.0
    uncertain = False
    for component in session.scalars(
        select(TransferFeeComponent).where(TransferFeeComponent.transfer_id == transfer.id)
    ):
        if component.amount is None:
            uncertain = True
            continue
        status = (component.status or "").lower()
        if status not in KNOWN_ADDON_STATUSES:
            uncertain = True
            continue
        if status in {"paid", "triggered"}:
            paid += float(component.amount)
        else:
            potential += float(component.amount)
    return paid, potential, uncertain


def _snapshot_at_transfer(session: Session, instance_id: int | None, when) -> PlayerSnapshot | None:
    """买入当时（或之前最近一次）的快照：历史工资/合同只能来自这里。"""
    if instance_id is None or when is None:
        return None
    return session.scalar(
        select(PlayerSnapshot)
        .where(PlayerSnapshot.player_instance_id == instance_id, PlayerSnapshot.observed_at <= __import__("datetime").datetime.combine(when, __import__("datetime").time(23, 59)))
        .order_by(PlayerSnapshot.observed_at.desc())
        .limit(1)
    )


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
    is_loan = transfer.transfer_type.startswith("loan")
    cash_cost: float | None = None
    missing: list[str] = []
    if is_loan:
        if transfer.loan_fee is None:
            missing.append("租借费未知，现金成本只能给下界")
        else:
            cash_cost = float(transfer.loan_fee) + paid_addons
    elif fee is None:
        missing.append("买入转会费未知")
    else:
        cash_cost = float(fee) + paid_addons
    cash_cost_complete = cash_cost is not None and not addon_uncertain
    if addon_uncertain:
        missing.append("存在金额或状态未知的附加条款，现金成本只是下界")

    # 后续卖出：同一实例、日期更晚、completed、且不是同一俱乐部。
    sales = []
    if transfer.player_instance_id is not None:
        sales = [
            row
            for row in session.scalars(
                select(Transfer)
                .where(
                    Transfer.fm_save_id == transfer.fm_save_id,
                    Transfer.player_instance_id == transfer.player_instance_id,
                    Transfer.status == "completed",
                    Transfer.transfer_date > transfer.transfer_date,
                    Transfer.transfer_type.in_(("permanent", "loan_buyout", "clause_release", "swap")),
                )
                .order_by(Transfer.transfer_date, Transfer.id)
            )
            if row.from_club_id == transfer.to_club_id and row.effective_fee is not None
        ]
    sale = sales[0] if sales else None
    sale_paid, sale_potential, _ = _paid_addons(session, sale) if sale is not None else (0.0, 0.0, False)

    realized = None
    realized_note = None
    if cash_cost is None:
        realized_note = "买入成本未知，无法计算已实现收益"
    elif not cash_cost_complete:
        realized_note = "现金成本不完整（存在未知附加条款），不能给出确定的已实现收益"
    elif sale is None:
        realized_note = "没有找到之后完成的永久类卖出交易，未实现"
    elif sale.effective_fee is None:
        realized_note = "卖出交易缺少金额，无法计算已实现收益"
    elif sale.currency != transfer.currency:
        realized_note = f"买入币种 {transfer.currency} 与卖出币种 {sale.currency} 不同，未配置汇率时不计算已实现收益"
    else:
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

    # 会计成本：现金 + 买入当时的已知工资 × 买入时合同年限。
    # 当前工资只能作为"现状"展示，绝不能当作历史事实。
    buy_snapshot = _snapshot_at_transfer(session, transfer.player_instance_id, transfer.transfer_date)
    accounting = None
    if buy_snapshot is None:
        missing.append("买入当时没有快照：历史工资/合同未知，会计成本无法计算")
    elif buy_snapshot.wage is None:
        missing.append("买入当时快照没有工资：会计成本只能给现金下界")
    elif buy_snapshot.contract_end is None:
        missing.append("买入当时没有合同到期日：合同年限未知，会计成本无法计算")
    else:
        years = max((buy_snapshot.contract_end - transfer.transfer_date).days / 365.25, 0.0)
        if years <= 0:
            missing.append("买入时合同已到期，合同年限为 0")
        wage_cost = float(buy_snapshot.wage) * WEEKS_PER_YEAR * years
        accounting = {
            "years": round(years, 2),
            "wage_at_transfer": buy_snapshot.wage,
            "wage_cost": fee_round(wage_cost),
            "total": fee_round(cash_cost + wage_cost) if cash_cost is not None else None,
            "observed_at": buy_snapshot.observed_at.isoformat(),
            "note": "按买入时点快照的周薪 × 买入时合同剩余年限；不是当前工资",
        }

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
            "cash_cost_lower_bound": fee_round(
                (float(transfer.loan_fee) if is_loan and transfer.loan_fee is not None else float(fee or 0)) + paid_addons
            )
            if (is_loan and transfer.loan_fee is not None) or fee is not None
            else None,
            "cash_cost_complete": cash_cost_complete,
            "is_loan": is_loan,
            "loan_fee": transfer.loan_fee,
            "wage_contribution": transfer.wage_contribution,
            "wage_contribution_note": "工资分摊是对方承担工资的约定，不是本队现金成本，无法据此抵扣转会费",
            "sell_on_clause_pct": transfer.sell_on_clause_pct,
            "sell_on_note": "二次转会分成只在真实触发并收到款项时才算收入；本接口不把比例折算成收入",
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
            "cash_cost": fee_round(cash_cost) if cash_cost is not None else None,
            "cash_cost_complete": cash_cost_complete,
            "lower_bound_only": cash_cost is not None and not cash_cost_complete,
            "realized_note": realized_note,
        },
        "accounting": accounting,
        "current": {
            "wage": snapshot.wage if snapshot else None,
            "contract_end": snapshot.contract_end.isoformat() if snapshot and snapshot.contract_end else None,
            "note": "当前工资/合同只用于展示现状，不参与历史成本计算",
        },
        "buy_context": {
            "wage": buy_snapshot.wage if buy_snapshot else None,
            "contract_end": buy_snapshot.contract_end.isoformat() if buy_snapshot and buy_snapshot.contract_end else None,
            "observed_at": buy_snapshot.observed_at.isoformat() if buy_snapshot else None,
            "available": buy_snapshot is not None,
        },
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
