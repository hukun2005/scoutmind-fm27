"""转会决策模拟器（SM-017）。

确定性规则，不训练模型、不随机：

1. 竞技能力：CA / 位置属性评分 / 潜力空间；
2. 阵容适配：目标位置现有深度与 CA 排名，签约后排名变化；
3. 位置竞争：同位置人数与平均 CA；
4. 年龄与成长：年龄曲线 + 观测到的成长速率；
5. 工资与预算：总成本（转会费 + 合同期工资）与预算占用；
6. 未来转售：当前估值与 3 年后的保守/基准/乐观估值；
7. 相似交易：同位置已完成交易的 P25/P75 作为合理报价区间；
8. 风险：年龄、合同、数据缺失、预算超限、竞争过度；
9. 替代方案：同位置、预算内、评分接近的球员。

所有输出都带 `assumptions` 与 `data_gaps`：缺失数据不填 0，区间给不出来时明确写 unknown。
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import PlayerInstance, PlayerSnapshot, Transfer
from ..utils import fee_round
from .development import GROWTH_AGE_LIMIT, growth_profile
from .recruitment import candidate_pool, player_score
from .transfers import TransferFilter, fetch_transfers, transfer_price_stats
from .valuation import estimate_value

ALGORITHM_VERSION = "transfer-simulator-1"

#: 情景假设：CA 成长速率相对观测值的倍率与估值倍率。
SCENARIOS = {
    "optimistic": {"growth_factor": 1.35, "value_factor": 1.25, "label": "乐观"},
    "base": {"growth_factor": 1.0, "value_factor": 1.0, "label": "基准"},
    "pessimistic": {"growth_factor": 0.55, "value_factor": 0.75, "label": "悲观"},
}


def _latest(session: Session, instance_id: int) -> PlayerSnapshot | None:
    return session.scalar(
        select(PlayerSnapshot)
        .where(PlayerSnapshot.player_instance_id == instance_id)
        .order_by(PlayerSnapshot.observed_at.desc())
        .limit(1)
    )


def _position_depth(session: Session, save_id: int, slot: str | None, group: str | None) -> dict[str, Any]:
    pool = candidate_pool(session, save_id)
    rows = [
        item
        for item in pool
        if (slot and (item.slot or "").upper() == slot.upper()) or (not slot and group and item.position_group == group)
    ]
    cas = [item.ca for item in rows if item.ca is not None]
    return {
        "count": len(rows),
        "ca_known": len(cas),
        "average_ca": round(sum(cas) / len(cas), 1) if cas else None,
        "top_ca": max(cas) if cas else None,
    }


def _wage_benchmark(session: Session, save_id: int, group: str | None) -> dict[str, Any]:
    """该存档最新工资分布（只用于给建议区间，不做预测）。"""
    rows = session.execute(
        select(PlayerInstance.id, PlayerSnapshot.wage, PlayerSnapshot.observed_at)
        .join(PlayerSnapshot, PlayerSnapshot.player_instance_id == PlayerInstance.id)
        .where(PlayerInstance.fm_save_id == save_id, PlayerSnapshot.wage.is_not(None))
    ).all()
    latest: dict[int, float] = {}
    for instance_id, wage, _observed in rows:
        if wage is not None:
            latest[instance_id] = float(wage)
    wages = sorted(latest.values())
    if not wages:
        return {"available": False, "median": None, "p75": None, "sample": 0}
    median = wages[len(wages) // 2]
    p75 = wages[min(len(wages) - 1, int(len(wages) * 0.75))]
    return {"available": True, "median": median, "p75": p75, "sample": len(wages)}


def _comparable_fees(session: Session, save_id: int, slot: str | None, group: str | None) -> dict[str, Any]:
    stats = transfer_price_stats(session, save_id, TransferFilter())
    if stats["sample_size"] < 5:
        return {"available": False, "reason": f"相似成交样本不足（{stats['sample_size']} 笔）", "sample": stats["sample_size"]}
    return {
        "available": True,
        "p25": stats["p25"],
        "median": stats["median"],
        "p75": stats["p75"],
        "sample": stats["sample_size"],
        "note": "同存档已完成交易的费用分位；未按位置细分" if not slot else "同存档已完成交易的费用分位",
    }


def simulate_transfer(
    session: Session,
    save_id: int,
    instance_id: int,
    *,
    target_position: str | None = None,
    fee: float | None = None,
    wage: float | None = None,
    contract_years: float = 4.0,
    expected_minutes: int | None = None,
    budget: float | None = None,
    transfer_type: str = "permanent",
) -> dict[str, Any]:
    """对一笔引援给出结论、成本、区间、三情景与替代方案。"""
    instance = session.get(PlayerInstance, instance_id)
    if instance is None or instance.fm_save_id != save_id:
        raise ValueError("player instance not found in this save")
    snapshot = _latest(session, instance_id)
    if snapshot is None:
        raise ValueError("player has no snapshot; cannot simulate without observed data")
    player = instance.player
    age = snapshot.age
    ca = snapshot.ca
    pa = snapshot.pa
    slot = (target_position or instance.position or "").upper() or None
    group = _slot_group(slot)

    data_gaps: list[str] = []
    if ca is None:
        data_gaps.append("缺少 CA")
    if pa is None:
        data_gaps.append("缺少 PA")
    if age is None:
        data_gaps.append("缺少年龄")
    if snapshot.market_value is None:
        data_gaps.append("缺少身价")
    if snapshot.wage is None:
        data_gaps.append("缺少工资")

    assumed_fee = fee if fee is not None else (snapshot.market_value or 0)
    assumed_wage = wage if wage is not None else snapshot.wage
    if fee is None and snapshot.market_value is None:
        data_gaps.append("没有报价也没有身价，转会费无法估计")

    wage_cost = (
        fee_round(float(assumed_wage) * 52.0 * contract_years) if assumed_wage is not None else None
    )
    signing_total = fee_round(float(assumed_fee) + (wage_cost or 0.0)) if assumed_fee else None

    depth_before = _position_depth(session, save_id, slot, group)
    rank_before = None
    if ca is not None:
        rank_before = 1 + sum(1 for item in candidate_pool(session, save_id) if (item.slot or "").upper() == (slot or "") and (item.ca or 0) > ca)
    rank_after = rank_before
    depth_after = {
        "count": depth_before["count"] + 1,
        "average_ca": (
            round(((depth_before["average_ca"] or 0) * depth_before["count"] + (ca or 0)) / (depth_before["count"] + 1), 1)
            if depth_before["count"] >= 0 and ca is not None and depth_before["average_ca"] is not None
            else None
        ),
    }

    wage_band = _wage_benchmark(session, save_id, group)
    comparable_fee = _comparable_fees(session, save_id, slot, group)

    valuation = estimate_value(session, instance_id)
    fair_fee = None
    if comparable_fee.get("available"):
        fair_fee = {
            "p25": comparable_fee["p25"],
            "median": comparable_fee["median"],
            "p75": comparable_fee["p75"],
            "verdict": _fee_verdict(assumed_fee, comparable_fee),
        }
    elif valuation.get("value") is not None:
        fair_fee = {
            "p25": fee_round(float(valuation["value"]) * 0.8),
            "median": valuation["value"],
            "p75": fee_round(float(valuation["value"]) * 1.2),
            "verdict": "按估值区间（样本不足，仅供参考）",
        }
    else:
        data_gaps.append("缺少可比成交与估值，无法给出合理报价区间")

    growth = growth_profile(session, instance_id)
    observed_rate = growth.get("rates", {}).get("per_year") if isinstance(growth.get("rates"), dict) else None
    observed_rate = observed_rate if isinstance(observed_rate, (int, float)) else None
    if observed_rate is None:
        data_gaps.append("历史快照不足，成长速率按年龄曲线假设")

    scenarios = _scenarios(age, ca, pa, snapshot.market_value, observed_rate, signing_total)
    budget_check = _budget(assumed_fee, wage_cost, budget)
    risks = _risks(age, ca, pa, assumed_fee, wage_band, depth_before, data_gaps, transfer_type)
    improvement = _improvement(ca, depth_before, rank_before, rank_after, expected_minutes, slot)
    alternatives = _alternatives(session, save_id, instance_id, slot, budget, assumed_fee)

    recommendation = _recommend(improvement, budget_check, risks, fair_fee, assumed_fee, scenarios)
    return {
        "save_id": save_id,
        "instance_id": instance_id,
        "player": {
            "name": player.full_name if player else None,
            "age": age,
            "ca": ca,
            "pa": pa,
            "position": snapshot.position,
            "market_value": snapshot.market_value,
            "wage": snapshot.wage,
            "contract_end": snapshot.contract_end.isoformat() if snapshot.contract_end else None,
        },
        "target": {"slot": slot, "group": group, "transfer_type": transfer_type},
        "cost": {
            "transfer_fee": fee_round(assumed_fee) if assumed_fee else None,
            "contract_years": contract_years,
            "wage": assumed_wage,
            "wage_cost": wage_cost,
            "total": signing_total,
            "currency": "EUR",
            "note": "总成本 = 转会费 + 合同期工资；签字费/经纪人费用未知，不计入",
        },
        "fair_fee": fair_fee,
        "wage_reference": wage_band,
        "squad": {
            "before": depth_before,
            "after": depth_after,
            "rank_before": rank_before,
            "rank_after": rank_after,
            "improvement": improvement,
        },
        "scenarios": scenarios,
        "budget": budget_check,
        "risks": risks,
        "alternatives": alternatives,
        "recommendation": recommendation,
        "assumptions": [
            "转会费与工资取用户输入，未输入时取最新快照身价/工资",
            "合同期工资按 周薪 × 52 × 合同年限 估算",
            "情景成长率 = 观测速率 × 倍率；没有观测时用年龄曲线默认值",
            "估值变化不是现金利润",
        ],
        "data_gaps": sorted(set(data_gaps)),
        "algorithm_version": ALGORITHM_VERSION,
        "generated_at": date.today().isoformat(),
    }


def _slot_group(slot: str | None) -> str | None:
    for group, slots in (("GK", ("GK",)), ("DF", ("CB", "LB", "RB", "LWB", "RWB")), ("MF", ("DM", "CM", "AM", "LM", "RM")), ("FW", ("ST", "LW", "RW"))):
        if slot in slots:
            return group
    return None


def _fee_verdict(fee: float | None, band: dict[str, Any]) -> str:
    if fee is None:
        return "没有报价，无法判断"
    if fee <= band["p25"]:
        return "低于 P25：低于同存档同类成交水平"
    if fee <= band["median"]:
        return "P25–中位数：合理偏低"
    if fee <= band["p75"]:
        return "中位数–P75：合理偏高"
    return "高于 P75：溢价明显"


def _scenarios(
    age: int | None,
    ca: int | None,
    pa: int | None,
    market_value: int | None,
    observed_rate: float | None,
    total_cost: float | None,
) -> dict[str, Any]:
    if ca is None:
        return {"available": False, "reason": "缺少 CA，无法情景预测"}
    base_rate = observed_rate if observed_rate is not None else (3.0 if (age or 30) <= GROWTH_AGE_LIMIT else 0.5)
    room = (pa - ca) if (pa is not None) else None
    result: dict[str, Any] = {"available": True, "observed_rate_per_year": observed_rate, "assumptions": {}}
    for key, config in SCENARIOS.items():
        rate = base_rate * float(config["growth_factor"])
        projected_ca = ca + rate * 3
        if pa is not None:
            projected_ca = min(projected_ca, pa)
        projected_ca = max(projected_ca, ca)
        value = float(market_value) * float(config["value_factor"]) if market_value is not None else None
        result[key] = {
            "label": config["label"],
            "ca_year1": round(ca + rate),
            "ca_year3": round(projected_ca),
            "rate_per_year": round(rate, 2),
            "value_year3": fee_round(value) if value is not None else None,
            "net_vs_cost": fee_round(value - total_cost) if value is not None and total_cost is not None else None,
        }
    result["assumptions"] = {
        "rate": "观测成长速率" if observed_rate is not None else "年龄曲线默认值（≤24 岁 3.0/年，否则 0.5/年）",
        "ceiling": "预测 CA 不超过 PA" if pa is not None else "缺少 PA，不设上限",
        "room_to_pa": room,
        "note": "这些是假设推演，不是承诺；估值变化不等于现金利润",
    }
    return result


def _budget(fee: float | None, wage_cost: float | None, budget: float | None) -> dict[str, Any]:
    if budget is None:
        return {"available": False, "note": "未提供预算，无法判断是否超支"}
    spend = (fee or 0) + (wage_cost or 0)
    return {
        "available": True,
        "budget": budget,
        "estimated_spend": fee_round(spend),
        "remaining": fee_round(budget - spend),
        "within_budget": spend <= budget,
    }


def _risks(
    age: int | None,
    ca: int | None,
    pa: int | None,
    fee: float | None,
    wage_band: dict[str, Any],
    depth: dict[str, Any],
    gaps: list[str],
    transfer_type: str,
) -> list[dict[str, str]]:
    risks: list[dict[str, str]] = []
    if age is not None and age >= 30:
        risks.append({"code": "age", "level": "medium", "message": f"{age} 岁，转售价值与成长空间有限"})
    if pa is not None and ca is not None and pa - ca <= 5:
        risks.append({"code": "ceiling", "level": "low", "message": "已接近潜力上限，成长空间有限"})
    if wage_band.get("p75") and fee is not None and wage_band["p75"] > 0 and fee > wage_band["p75"] * 100:
        risks.append({"code": "fee_vs_wage", "level": "medium", "message": "转会费相对工资水平偏高，回报周期长"})
    if depth.get("count", 0) >= 3:
        risks.append({"code": "competition", "level": "medium", "message": f"该位置已有 {depth['count']} 人，出场时间需要竞争"})
    if transfer_type != "permanent":
        risks.append({"code": "loan", "level": "low", "message": "租借交易不计入长期资产，买断条款需单独确认"})
    for gap in gaps:
        risks.append({"code": "data_gap", "level": "low", "message": gap})
    return risks


def _improvement(
    ca: int | None,
    depth: dict[str, Any],
    rank_before: int | None,
    rank_after: int | None,
    expected_minutes: int | None,
    slot: str | None,
) -> dict[str, Any]:
    if ca is None:
        return {"available": False, "reason": "缺少 CA"}
    average = depth.get("average_ca")
    delta = round(ca - average, 1) if average is not None else None
    return {
        "available": True,
        "ca_vs_position_average": delta,
        "rank_before": rank_before,
        "rank_after": rank_after,
        "already_present": bool(rank_before is not None and rank_after == rank_before),
        "expected_minutes": expected_minutes,
        "note": "排名按同位置 CA 估算；出场时间取决于战术与主教练，不在模型内",
    }


def _alternatives(
    session: Session, save_id: int, instance_id: int, slot: str | None, budget: float | None, fee: float | None
) -> list[dict[str, Any]]:
    pool = candidate_pool(session, save_id)
    ceiling = (fee or 0) * 1.25 if fee else None
    rows = []
    for item in pool:
        if item.instance_id == instance_id:
            continue
        if slot and (item.slot or "").upper() != slot.upper():
            continue
        if ceiling is not None and item.market_value is not None and item.market_value > ceiling:
            continue
        rows.append(item)
    rows.sort(key=lambda item: (-(item.ca or 0), item.instance_id))
    return [
        {
            "instance_id": item.instance_id,
            "name": item.name,
            "age": item.age,
            "ca": item.ca,
            "pa": item.pa,
            "value": item.market_value,
            "reason": "同位置、价格不超过本笔报价 125%，按 CA 排序",
        }
        for item in rows[:3]
    ]


def _recommend(
    improvement: dict[str, Any],
    budget: dict[str, Any],
    risks: list[dict[str, str]],
    fair_fee: dict[str, Any] | None,
    fee: float | None,
    scenarios: dict[str, Any],
) -> dict[str, Any]:
    blockers = [risk for risk in risks if risk["level"] == "high"]
    if not improvement.get("available"):
        verdict = "insufficient_data"
        reason = "缺少 CA，无法评估阵容提升"
    elif budget.get("available") and not budget.get("within_budget"):
        verdict = "not_recommended"
        reason = "按当前报价与合同期工资，总成本超出预算"
    elif fair_fee and fee is not None and fair_fee.get("p75") is not None and fee > fair_fee["p75"] * 1.3:
        verdict = "caution"
        reason = "报价明显高于同存档同类成交 P75，建议压价或选择替代方案"
    elif blockers:
        verdict = "caution"
        reason = "存在高风险项"
    else:
        verdict = "consider"
        reason = "成本、阵容与数据完整度没有硬性阻断，建议进入谈判"
    return {
        "verdict": verdict,
        "reason": reason,
        "base_scenario": scenarios.get("base") if scenarios.get("available") else None,
    }
