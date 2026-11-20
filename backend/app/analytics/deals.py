"""Transfer Intelligence V2: cost model, investment score, decision reports and deal review.

Transfer decisions are investment decisions, so this module prices the whole deal instead of the headline fee:

``TotalCost = TransferFee + SigningFee + AgentFee + WageCost + Bonus``

Every component records whether the save observed it or the model assumed it, and a total that is missing components is
labelled a lower bound rather than a full cost. ``InvestmentScore = (ExpectedFutureValue − TotalCost) / TotalCost`` only
runs when both sides are known; otherwise the report says which side is missing.

The transaction taxonomy maps every stored transfer to one accounting treatment so a loan, a loan with an option, an
instalment plan, an add-on clause, an unfinished deal and a cancelled deal are never mixed into price statistics.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ingestion.attributes import position_group, slot_of
from ..models import Club, PlayerInstance, PlayerSnapshot, Transfer
from ..utils import fee_round
from .quantiles import quantile, summarize
from .recruitment import candidate_pool, player_score
from .transfers import TransferFilter, fetch_transfers
from .valuation import estimate_value

DEAL_ALGORITHM_VERSION = "deal-model-1"

#: Weeks per year for a weekly wage, and months per year for a monthly wage.
WAGE_PERIOD_FACTOR: dict[str, float] = {"week": 52.0, "month": 12.0, "year": 1.0}

DEFAULT_CONTRACT_YEARS = 5

#: 不进入价格统计的 transfer_type（与 TRANSACTION_CATEGORIES.counts_in_stats 对应）
NON_STAT_TYPES: tuple[str, ...] = ("loan", "loan_with_option", "free", "end_of_contract", "swap", "youth_promotion")

#: (transfer_type, status) -> accounting treatment. A category only enters price statistics when ``counts_in_stats``.
TRANSACTION_CATEGORIES: dict[str, dict[str, object]] = {
    "completed_permanent": {
        "label": "正式转会",
        "treatment": "记录成交金额与时间，计入成交价格统计",
        "counts_in_stats": True,
    },
    "loan": {
        "label": "租借",
        "treatment": "只记录租借费用与期限，不计入转会费统计",
        "counts_in_stats": False,
    },
    "loan_with_option": {
        "label": "租借附买断",
        "treatment": "租借费用与买断条款分开记录，买断金额在触发前不进统计",
        "counts_in_stats": False,
    },
    "loan_buyout": {
        "label": "租借买断",
        "treatment": "租借期结束按买断条款转为正式转会，计入成交价格统计",
        "counts_in_stats": True,
    },
    "free": {
        "label": "自由转会",
        "treatment": "转会费记为零，保留工资与签字费等实际成本",
        "counts_in_stats": False,
    },
    "clause_release": {
        "label": "解约金买断",
        "treatment": "按已支付金额记录，属于正式转会",
        "counts_in_stats": True,
    },
    "swap": {
        "label": "球员交换",
        "treatment": "双方作价分别记录，缺作价时不得计入选价统计",
        "counts_in_stats": False,
    },
    "youth_promotion": {
        "label": "青训提拔",
        "treatment": "无转会费，只记录工资成本",
        "counts_in_stats": False,
    },
    "pending": {
        "label": "未完成交易",
        "treatment": "记录为未成交，不计入实际支出",
        "counts_in_stats": False,
    },
    "cancelled": {
        "label": "交易取消",
        "treatment": "保留记录，标记取消状态，不进入任何统计",
        "counts_in_stats": False,
    },
    "failed": {
        "label": "交易失败",
        "treatment": "保留记录，标记失败状态，不进入任何统计",
        "counts_in_stats": False,
    },
    "agreed": {
        "label": "已达成未生效",
        "treatment": "双方已达成协议但尚未注册，不计入支出与成交价格统计",
        "counts_in_stats": False,
    },
    "bid_rejected": {
        "label": "报价被拒绝",
        "treatment": "只作为谈判记录，不产生任何成本与成交口径",
        "counts_in_stats": False,
    },
}


def category_of(transfer: Transfer) -> str:
    """Accounting category of one stored transfer."""
    if transfer.status in {"pending", "future", "unknown"}:
        return "pending"
    if transfer.status == "agreed":
        return "agreed"
    if transfer.status == "bid_rejected":
        return "bid_rejected"
    if transfer.status == "cancelled":
        return "cancelled"
    if transfer.status == "failed":
        return "failed"
    if transfer.transfer_type == "loan_buyout":
        return "loan_buyout"
    if transfer.transfer_type == "loan_with_option":
        return "loan_with_option"
    if transfer.transfer_type == "loan":
        return "loan"
    if transfer.transfer_type in {"free", "end_of_contract"}:
        return "free"
    if transfer.transfer_type == "clause_release":
        return "clause_release"
    if transfer.transfer_type == "swap":
        return "swap"
    if transfer.transfer_type == "youth_promotion":
        return "youth_promotion"
    return "completed_permanent"


def classify_transfer(transfer: Transfer) -> dict[str, object]:
    """Category plus the treatment explanation shown on the transfer screen."""
    key = category_of(transfer)
    meta = TRANSACTION_CATEGORIES[key]
    return {
        "key": key,
        "label": meta["label"],
        "treatment": meta["treatment"],
        "counts_in_stats": meta["counts_in_stats"],
    }


def transaction_summary(session: Session, save_id: int) -> dict[str, object]:
    """Every transaction category with its count, known spend and the rules that exclude it from statistics."""
    # 聚合下推到 SQL：GROUP BY (status, transfer_type)，不再把每一行转会加载成 ORM 对象。
    from sqlalchemy import func as sql_func

    buckets: dict[str, dict[str, object]] = {
        key: {
            "key": key,
            "label": meta["label"],
            "treatment": meta["treatment"],
            "count": 0,
            "known_amount": 0.0,
            "known_spend": 0.0,
        }
        for key, meta in TRANSACTION_CATEGORIES.items()
    }
    groups = session.execute(
        select(Transfer.status, Transfer.transfer_type, sql_func.count(), sql_func.sum(Transfer.effective_fee))
        .where(Transfer.fm_save_id == save_id)
        .group_by(Transfer.status, Transfer.transfer_type)
    )
    total = 0
    for status, transfer_type, count, fee_sum in groups:
        key = category_of(Transfer(status=status, transfer_type=transfer_type))
        bucket = buckets[key]
        bucket["count"] = int(bucket["count"]) + int(count)
        total += int(count)
        known = float(fee_sum or 0.0)
        if known and status == "completed":
            bucket["known_amount"] = round(float(bucket["known_amount"]) + known, 2)
        if known and TRANSACTION_CATEGORIES[key]["counts_in_stats"]:
            bucket["known_spend"] = round(float(bucket["known_spend"]) + known, 2)
    rows = None  # 旧实现需要全量行；现在只保留 total 计数
    return {
        "categories": [
            {**buckets[key], "counts_in_stats": TRANSACTION_CATEGORIES[key]["counts_in_stats"]}
            for key in TRANSACTION_CATEGORIES
            if int(buckets[key]["count"]) > 0
        ],
        "total": total,
        "currency": "EUR",
        "algorithm_version": DEAL_ALGORITHM_VERSION,
    }


def deal_cost(
    session: Session,
    transfer: Transfer,
    wage_period: str = "week",
    contract_years: float | None = None,
) -> dict[str, object]:
    """Total cost of one recorded transfer with every component's provenance."""
    components = list(transfer.components)
    by_type: dict[str, float] = {}
    for component in components:
        if component.amount is None:
            continue
        key = component.component_type
        by_type[key] = by_type.get(key, 0.0) + float(component.amount)
    fee = transfer.effective_fee if transfer.effective_fee is not None else transfer.base_fee
    signing = by_type.get("signing_bonus")
    agent = by_type.get("agent_fee")
    addon_paid = sum(
        float(component.amount)
        for component in components
        if component.component_type == "addon"
        and component.amount is not None
        and component.status in {"paid", "triggered"}
    )
    addon_potential = sum(
        float(component.amount)
        for component in components
        if component.component_type == "addon"
        and component.amount is not None
        and component.status not in {"paid", "triggered"}
    )
    loan_fee = by_type.get("loan_fee")
    buy_option = by_type.get("buy_option")
    wage = _wage_of(session, transfer)
    years = contract_years if contract_years is not None else DEFAULT_CONTRACT_YEARS
    factor = WAGE_PERIOD_FACTOR.get(wage_period, WAGE_PERIOD_FACTOR["week"])
    wage_cost = round(float(wage) * factor * float(years), 2) if wage is not None else None
    rows: list[dict[str, object]] = [
        {
            "key": "transfer_fee",
            "label": "转会费",
            "amount": fee_round(fee),
            "status": "observed" if fee is not None else "unavailable",
            "note": "已支付口径（base_fee / 已付与已触发条款）" if fee is not None else "交易没有金额",
        },
        {
            "key": "signing_fee",
            "label": "签字费",
            "amount": fee_round(signing),
            "status": "observed" if signing is not None else "unavailable",
            "note": "来自交易费用条款" if signing is not None else "数据源未提供签字费",
        },
        {
            "key": "agent_fee",
            "label": "经纪人费用",
            "amount": fee_round(agent),
            "status": "observed" if agent is not None else "unavailable",
            "note": "来自交易费用条款" if agent is not None else "数据源未提供经纪人费用",
        },
        {
            "key": "wage_cost",
            "label": "合同期内工资",
            "amount": wage_cost,
            "status": "assumed" if wage_cost is not None else "unavailable",
            "note": (
                f"按 {wage} / {wage_period} × {factor:.0f} × {years} 年估算；工资周期是模型假设"
                if wage_cost is not None
                else "缺少工资数据"
            ),
        },
        {
            "key": "bonus",
            "label": "奖金与附加成本",
            "amount": fee_round(addon_paid) if addon_paid else None,
            "status": "observed" if addon_paid else "unavailable",
            "note": (
                f"已触发奖金 {fee_round(addon_paid)}；另有 {fee_round(addon_potential)} 未触发"
                if addon_paid
                else "没有已触发奖金记录"
            ),
        },
    ]
    if loan_fee:
        rows.append(
            {
                "key": "loan_fee",
                "label": "租借费",
                "amount": fee_round(loan_fee),
                "status": "observed",
                "note": "租借交易的当期费用",
            }
        )
    if buy_option:
        rows.append(
            {
                "key": "buy_option",
                "label": "买断条款",
                "amount": fee_round(buy_option),
                "status": "conditional",
                "note": "条款未触发前不计入成本",
            }
        )
    known = [float(row["amount"]) for row in rows if row["status"] in {"observed", "assumed"} and row["amount"] is not None]
    missing = [str(row["label"]) for row in rows if row["status"] == "unavailable" and row["key"] != "buy_option"]
    total = round(sum(known), 2) if known else None
    return {
        "transfer_id": transfer.id,
        "player_name": transfer.player_name,
        "currency": transfer.currency,
        "components": rows,
        "total_known": total,
        "complete": not missing,
        "missing_components": missing,
        "label": "总成本" if not missing else "已知成本下限",
        "status": classify_transfer(transfer),
        "assumptions": {
            "wage_period": wage_period,
            "contract_years": years,
            "note": "工资周期与合同年限是模型假设，不是存档读数；可在请求中覆盖",
        },
        "algorithm_version": DEAL_ALGORITHM_VERSION,
    }


def prospective_cost(
    session: Session,
    instance_id: int,
    fee: float | None = None,
    wage_period: str = "week",
    contract_years: float | None = None,
) -> dict[str, object]:
    """Cost model for a player the club has not signed yet, using value/fee and current wage."""
    instance = session.get(PlayerInstance, instance_id)
    if instance is None:
        raise ValueError("player instance not found")
    snapshot = session.scalar(
        select(PlayerSnapshot)
        .where(PlayerSnapshot.player_instance_id == instance_id)
        .order_by(PlayerSnapshot.observed_at.desc())
        .limit(1)
    )
    assumed_fee = fee if fee is not None else (snapshot.market_value if snapshot else None)
    wage = snapshot.wage if snapshot else None
    years = contract_years
    if years is None and snapshot is not None and snapshot.contract_end is not None:
        reference = snapshot.game_date or snapshot.observed_at.date()
        years = max(1.0, round(((snapshot.contract_end - reference).days / 365.0), 1))
    factor = WAGE_PERIOD_FACTOR.get(wage_period, WAGE_PERIOD_FACTOR["week"])
    wage_cost = round(float(wage) * factor * float(years or DEFAULT_CONTRACT_YEARS), 2) if wage is not None else None
    rows = [
        {
            "key": "transfer_fee",
            "label": "转会费",
            "amount": fee_round(assumed_fee),
            "status": "assumed",
            "note": "使用报价" if fee is not None else "使用当前身价作为转会费假设",
        },
        {
            "key": "wage_cost",
            "label": "合同期内工资",
            "amount": wage_cost,
            "status": "assumed" if wage_cost is not None else "unavailable",
            "note": f"按 {wage} / {wage_period} × {factor:.0f} × {years or DEFAULT_CONTRACT_YEARS} 年估算",
        },
        {
            "key": "signing_fee",
            "label": "签字费",
            "amount": None,
            "status": "unavailable",
            "note": "未签约球员没有签字费记录",
        },
        {
            "key": "agent_fee",
            "label": "经纪人费用",
            "amount": None,
            "status": "unavailable",
            "note": "未签约球员没有经纪人费用记录",
        },
    ]
    known = [float(row["amount"]) for row in rows if row["status"] == "assumed" and row["amount"] is not None]
    return {
        "instance_id": instance_id,
        "currency": "EUR",
        "components": rows,
        "total_known": round(sum(known), 2) if known else None,
        "complete": False,
        "missing_components": ["签字费", "经纪人费用"],
        "label": "已知成本下限",
        "algorithm_version": DEAL_ALGORITHM_VERSION,
    }


def investment_score(session: Session, instance_id: int, total_cost: float | None) -> dict[str, object]:
    """``(ExpectedFutureValue − TotalCost) / TotalCost`` with an explicit expected-value source."""
    if not total_cost or total_cost <= 0:
        return {
            "available": False,
            "score": None,
            "reason": "缺少总成本，无法计算投资效率",
            "total_cost": total_cost,
        }
    valuation = estimate_value(session, instance_id)
    if valuation.get("insufficient_sample"):
        instance = session.get(PlayerInstance, instance_id)
        snapshot = (
            session.scalar(
                select(PlayerSnapshot)
                .where(PlayerSnapshot.player_instance_id == instance_id)
                .order_by(PlayerSnapshot.observed_at.desc())
                .limit(1)
            )
            if instance is not None
            else None
        )
        market_value = snapshot.market_value if snapshot else None
        if market_value is None:
            return {
                "available": False,
                "score": None,
                "reason": str(valuation.get("warnings", ["没有可比成交，无法估算未来价值"])[0]),
                "total_cost": total_cost,
                "valuation": valuation,
            }
        future_value = float(market_value)
        method = "market_value_fallback"
        note = "可比成交样本不足，改用当前身价作为未来价值；这是假设，不是估值"
    else:
        future_value = float(valuation["mid"] or 0)
        method = "comparable_transfers"
        note = "未来价值来自可比成交估值中位数"
    score = round((future_value - float(total_cost)) / float(total_cost), 4)
    return {
        "available": True,
        "score": score,
        "total_cost": round(float(total_cost), 2),
        "expected_future_value": round(future_value, 2),
        "net_value": round(future_value - float(total_cost), 2),
        "method": method,
        "note": note,
        "valuation": valuation,
        "algorithm_version": DEAL_ALGORITHM_VERSION,
    }


def decision_report(
    session: Session,
    save_id: int,
    instance_id: int,
    fee: float | None = None,
    budget: int | None = None,
    wage_period: str = "week",
    contract_years: float | None = None,
) -> dict[str, object]:
    """The transfer decision report: fit, cost, wage pressure, age, resale and a recommendation."""
    pool = candidate_pool(session, save_id)
    score = player_score(session, save_id, instance_id, pool)
    player = score["player"]
    assert isinstance(player, dict)
    cost = prospective_cost(session, instance_id, fee, wage_period, contract_years)
    total_cost = cost["total_known"]
    investment = investment_score(session, instance_id, float(total_cost) if total_cost else None)
    squad = [item for item in pool if item.club_id == player.get("club_id")]
    squad_wages = sorted(float(item.wage) for item in squad if item.wage is not None)
    wage = player.get("wage")
    wage_median = squad_wages[len(squad_wages) // 2] if squad_wages else None
    wage_pressure = _wage_pressure(float(wage) if wage is not None else None, wage_median)
    age = player.get("age")
    age_risk = _age_risk(age if isinstance(age, int) else None)
    resale = _resale_potential(player, investment)
    fit = next((dimension for dimension in score["dimensions"] if dimension["key"] == "fit"), None)  # type: ignore[index]
    fit_value = float(fit["value"]) if fit and fit["value"] is not None else None
    budget_note = None
    if budget is not None and total_cost is not None and float(total_cost) > float(budget):
        budget_note = f"已知成本 {fee_round(total_cost)} 已超过预算 {fee_round(budget)}"
    verdict, reasons = _verdict(fit_value, wage_pressure, age_risk, investment, budget_note)
    return {
        "player": player,
        "score": score["score"],
        "dimensions": score["dimensions"],
        "cost": cost,
        "investment": investment,
        "rows": [
            {"key": "fit", "label": "球员适配度", "value": _band(fit_value), "raw": fit_value, "basis": "位置模板与战术角色评分"},
            {"key": "cost", "label": "预计转会成本", "value": _band_inverse(float(total_cost) if total_cost else None), "raw": total_cost, "basis": "总成本模型（已知成本下限）"},
            {"key": "wage", "label": "工资压力", "value": wage_pressure["band"], "raw": wage, "basis": wage_pressure["basis"]},
            {"key": "age", "label": "年龄风险", "value": age_risk["band"], "raw": age, "basis": age_risk["basis"]},
            {"key": "injury", "label": "伤病风险", "value": "不可评估", "raw": None, "basis": "数据源未提供伤病记录"},
            {"key": "resale", "label": "转售潜力", "value": resale["band"], "raw": resale["value"], "basis": resale["basis"]},
        ],
        "budget": budget,
        "budget_note": budget_note,
        "recommendation": {"verdict": verdict, "reasons": reasons},
        "data_gaps": _decision_gaps(cost, investment, wage),
        "algorithm_version": DEAL_ALGORITHM_VERSION,
    }


def transfer_review(session: Session, save_id: int, club_id: int | None = None) -> dict[str, object]:
    """Review the managed club's own completed deals against the market and against later value."""
    club = session.get(Club, club_id) if club_id else _own_club(session, save_id)
    if club is None:
        return {"club": None, "items": [], "summary": None, "algorithm_version": DEAL_ALGORITHM_VERSION}
    rows = [
        row
        for row in fetch_transfers(session, save_id, TransferFilter(club_id=club.id, status="all"))
        if row.status == "completed"
    ]
    peers = [
        row
        for row in fetch_transfers(session, save_id, TransferFilter(status="completed"))
        if row.effective_fee is not None
    ]
    items: list[dict[str, object]] = []
    for row in rows:
        direction = "in" if row.to_club_id == club.id else "out"
        comparable = [
            float(other.effective_fee)
            for other in peers
            if other.id != row.id
            and other.effective_fee is not None
            and _comparable(other, row)
        ]
        percentile = None
        if row.effective_fee is not None and len(comparable) >= 5:
            below = sum(1 for value in comparable if value < float(row.effective_fee))
            percentile = round(below / len(comparable), 4)
        snapshot = (
            session.scalar(
                select(PlayerSnapshot)
                .where(PlayerSnapshot.player_instance_id == row.player_instance_id)
                .order_by(PlayerSnapshot.observed_at.desc())
                .limit(1)
            )
            if row.player_instance_id
            else None
        )
        value_delta = (
            (float(snapshot.market_value) - float(row.effective_fee))
            if snapshot is not None and snapshot.market_value is not None and row.effective_fee is not None
            else None
        )
        ca_delta = (
            (float(snapshot.ca) - float(row.player_ca_at_transfer))
            if snapshot is not None
            and snapshot.ca is not None
            and row.player_ca_at_transfer is not None
            else None
        )
        items.append(
            {
                "transfer_id": row.id,
                "direction": direction,
                "player": {
                    "instance_id": row.player_instance_id,
                    "name": row.player_name,
                    "age_at_transfer": row.player_age_at_transfer,
                    "club": (snapshot.club_id if snapshot else None),
                },
                "transfer_date": row.transfer_date.isoformat(),
                "fee": fee_round(row.effective_fee),
                "currency": row.currency,
                "status": classify_transfer(row),
                "fee_percentile": percentile,
                "comparable_sample": len(comparable),
                "ca_delta_since": ca_delta,
                "value_delta_since": fee_round(value_delta),
                "current_value": fee_round(snapshot.market_value) if snapshot else None,
                "verdict": _deal_verdict(direction, percentile, value_delta, ca_delta),
                "evidence": _deal_evidence(percentile, value_delta, ca_delta, len(comparable)),
            }
        )
    items.sort(key=lambda item: str(item["transfer_date"]), reverse=True)
    return {
        "club": {"id": club.id, "name": club.name, "league": club.league},
        "items": items[:60],
        "summary": _review_summary(items),
        "algorithm_version": DEAL_ALGORITHM_VERSION,
        "note": "价值变化用当前身价对比成交价；只有存档提供身价与 CA 时效才成立",
    }


def _review_summary(items: list[dict[str, object]]) -> dict[str, object]:
    deltas = [float(item["value_delta_since"]) for item in items if item["value_delta_since"] is not None]
    profitable = sum(1 for value in deltas if value > 0)
    by_age: dict[str, list[float]] = {}
    for item in items:
        age = item["player"]["age_at_transfer"]  # type: ignore[index]
        if item["value_delta_since"] is None or age is None:
            continue
        band = "≤21" if age <= 21 else "22-25" if age <= 25 else "26-29" if age <= 29 else "30+"
        by_age.setdefault(band, []).append(float(item["value_delta_since"]))
    return {
        "deals": len(items),
        "with_value_delta": len(deltas),
        "profitable": profitable,
        "median_value_delta": fee_round(quantile(deltas, 0.5)) if deltas else None,
        "by_age_band": [
            {
                "band": band,
                "deals": len(values),
                "median_delta": fee_round(quantile(values, 0.5)),
            }
            for band, values in sorted(by_age.items())
        ],
        "note": "只用带身价对比的交易统计；样本少于 3 笔的年龄段不解读",
    }


def _comparable(other: Transfer, row: Transfer) -> bool:
    if other.transfer_type != row.transfer_type:
        return False
    if row.player_age_at_transfer is not None and other.player_age_at_transfer is not None:
        return abs(other.player_age_at_transfer - row.player_age_at_transfer) <= 3
    return True


def _deal_verdict(
    direction: str, percentile: float | None, value_delta: float | None, ca_delta: float | None
) -> str:
    if percentile is not None and value_delta is not None:
        if direction == "in":
            if percentile <= 0.25 and value_delta >= 0:
                return "低价买入且已升值"
            if percentile >= 0.75 and value_delta < 0:
                return "高价买入且已贬值"
            return "价格合理"
        if percentile >= 0.75:
            return "高价卖出"
        if percentile <= 0.25:
            return "低价卖出"
        return "价格合理"
    if ca_delta is not None:
        return "能力提升" if ca_delta > 0 else "能力下降" if ca_delta < 0 else "能力持平"
    return "数据不足"


def _deal_evidence(
    percentile: float | None, value_delta: float | None, ca_delta: float | None, sample: int
) -> list[str]:
    evidence: list[str] = []
    if percentile is not None:
        evidence.append(f"成交价处于同类样本第 {percentile:.0%} 分位（样本 {sample} 笔）")
    else:
        evidence.append(f"同类样本仅 {sample} 笔，未给出分位")
    if value_delta is not None:
        evidence.append(f"当前身价相对成交价变化 {fee_round(value_delta)}")
    if ca_delta is not None:
        evidence.append(f"转会至今 CA 变化 {ca_delta:+.0f}")
    return evidence


def _wage_of(session: Session, transfer: Transfer) -> float | None:
    if transfer.player_instance_id is None:
        return None
    snapshot = session.scalar(
        select(PlayerSnapshot)
        .where(PlayerSnapshot.player_instance_id == transfer.player_instance_id)
        .order_by(PlayerSnapshot.observed_at.desc())
        .limit(1)
    )
    return float(snapshot.wage) if snapshot is not None and snapshot.wage is not None else None


def _wage_pressure(wage: float | None, median: float | None) -> dict[str, object]:
    if wage is None:
        return {"band": "不可评估", "ratio": None, "basis": "缺少工资数据"}
    if median is None or median <= 0:
        return {"band": "未知", "ratio": None, "basis": "缺少同队工资中位数"}
    ratio = wage / median
    band = "低" if ratio <= 1.2 else "中" if ratio <= 2.0 else "高"
    return {"band": band, "ratio": round(ratio, 2), "basis": f"工资是同队中位数的 {ratio:.2f} 倍（中位数 {median:.0f}）"}


def _age_risk(age: int | None) -> dict[str, object]:
    if age is None:
        return {"band": "不可评估", "basis": "缺少年龄数据"}
    if age <= 21:
        return {"band": "低", "basis": f"{age} 岁，处于上升期"}
    if age <= 25:
        return {"band": "低", "basis": f"{age} 岁，进入成熟期"}
    if age <= 28:
        return {"band": "中", "basis": f"{age} 岁，接近巅峰末期"}
    return {"band": "高", "basis": f"{age} 岁，转售窗口有限"}


def _resale_potential(player: dict[str, object], investment: dict[str, object]) -> dict[str, object]:
    age = player.get("age")
    pa = player.get("pa")
    ca = player.get("ca")
    if not isinstance(age, int) or not isinstance(pa, int) or not isinstance(ca, int):
        return {"band": "不可评估", "value": None, "basis": "缺少年龄或 CA/PA"}
    headroom = pa - ca
    if age <= 23 and headroom >= 15:
        band = "高"
    elif age <= 27 and headroom >= 8:
        band = "中"
    else:
        band = "低"
    return {
        "band": band,
        "value": headroom,
        "basis": f"{age} 岁，PA−CA 空间 {headroom}；结合投资效率 {investment.get('score')}",
    }


def _verdict(
    fit: float | None,
    wage_pressure: dict[str, object],
    age_risk: dict[str, object],
    investment: dict[str, object],
    budget_note: str | None,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if fit is not None:
        reasons.append(f"位置适配评分 {fit:.0f}")
    if investment.get("available"):
        reasons.append(f"投资效率 {investment['score']}（净价值 {investment['net_value']}）")
    else:
        reasons.append("投资效率不可计算：" + str(investment.get("reason")))
    reasons.append(f"工资压力 {wage_pressure['band']}，年龄风险 {age_risk['band']}")
    if budget_note:
        reasons.append(budget_note)
    if budget_note:
        return "不建议在当前预算下推进", reasons
    if fit is not None and fit >= 60 and age_risk["band"] in {"低", "中"}:
        return "建议进一步考察", reasons
    if fit is not None and fit < 55:
        return "不建议推进", reasons
    return "需要更多数据后再决定", reasons


def _band(value: float | None) -> str:
    if value is None:
        return "不可评估"
    if value >= 75:
        return "高"
    if value >= 55:
        return "中"
    return "低"


def _band_inverse(value: float | None) -> str:
    if value is None:
        return "不可评估"
    if value <= 20_000_000:
        return "低"
    if value <= 60_000_000:
        return "中"
    return "高"


def _decision_gaps(cost: dict[str, object], investment: dict[str, object], wage: object) -> list[str]:
    gaps = [f"缺少 {name}" for name in cost.get("missing_components", [])]  # type: ignore[union-attr]
    if not investment.get("available"):
        gaps.append(str(investment.get("reason")))
    if wage is None:
        gaps.append("缺少工资数据，无法评估工资压力")
    gaps.append("数据源未提供伤病记录，伤病风险不可评估")
    return gaps


def _own_club(session: Session, save_id: int) -> Club | None:
    return session.scalar(
        select(Club).where(Club.fm_save_id == save_id, Club.is_user_club.is_(True)).order_by(Club.id).limit(1)
    )


def valuation_band(values: list[float]) -> dict[str, object]:
    """Small helper for callers that need quartiles of an already collected fee list."""
    summary = summarize(values)
    return {
        "sample_size": len(values),
        "median": summary["median"],
        "p25": summary["p25"],
        "p75": summary["p75"],
    }


def slot_of_transfer(session: Session, transfer: Transfer) -> str | None:
    """Slot of the player of a transfer, used to group deals by position on the review screen."""
    if transfer.player_instance_id is None:
        return None
    instance = session.get(PlayerInstance, transfer.player_instance_id)
    return slot_of(instance.position) if instance else None


def position_group_of_transfer(session: Session, transfer: Transfer) -> str | None:
    """Position group of the player of a transfer."""
    if transfer.player_instance_id is None:
        return None
    instance = session.get(PlayerInstance, transfer.player_instance_id)
    return position_group(instance.position) if instance else None


def today() -> date:
    """Reference date helper kept here so callers do not each import ``date``."""
    return date.today()
