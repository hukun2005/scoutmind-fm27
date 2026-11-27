"""Deterministic tools the decision assistant may call.

Every number that reaches an answer must come from one of these functions. They wrap the analytics layer and return
plain JSON-serialisable data plus a one-line summary that is shown in the UI's tool-call log.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from ..analytics.players import PlayerFilter, history, list_players, player_profile
from ..analytics.scoring import evaluate_player
from ..analytics.transfers import (
    TransferFilter,
    club_transfer_profile,
    fetch_transfers,
    similar_transfers,
    transfer_price_stats,
)
from ..analytics.valuation import estimate_value


@dataclass
class ToolCall:
    """One executed tool call, recorded for the UI and for regression tests."""

    name: str
    arguments: dict[str, object]
    result: dict[str, object]
    summary: str
    warnings: list[str] = field(default_factory=list)

    def payload(self) -> dict[str, object]:
        """Serialize the call for ``agent_messages.tool_calls_json``."""
        return {
            "name": self.name,
            "arguments": self.arguments,
            "result_summary": self.summary,
            "warnings": self.warnings,
        }


def search_players(session: Session, save_id: int, filters: dict[str, object] | None = None, limit: int = 20) -> ToolCall:
    """``search_players`` — filter the player database by position, age, ability, value and club."""
    data = filters or {}
    player_filter = PlayerFilter(
        query=_str(data.get("query")),
        position=_str(data.get("position")),
        position_group=_str(data.get("position_group")),
        min_age=_int(data.get("min_age")),
        max_age=_int(data.get("max_age")),
        min_ca=_int(data.get("min_ca")),
        min_pa=_int(data.get("min_pa")),
        max_value=_int(data.get("max_value")),
        max_wage=_int(data.get("max_wage")),
        club_id=_int(data.get("club_id")),
        watchlist_only=bool(data.get("watchlist_only", False)),
        sort=_str(data.get("sort")) or "-ca",
    )
    result = list_players(session, save_id, player_filter, limit=limit, offset=0)
    return ToolCall(
        "search_players",
        {**data, "limit": limit},
        result,  # type: ignore[arg-type]
        f"命中 {result['total']} 名球员，返回前 {len(result['items'])} 条",
    )


def get_player_profile(session: Session, instance_id: int) -> ToolCall:
    """``get_player_profile`` — the current profile, data completeness and watchlist tags."""
    profile = player_profile(session, instance_id)
    summary = profile["summary"]
    return ToolCall(
        "get_player_profile",
        {"instance_id": instance_id},
        profile,  # type: ignore[arg-type]
        f"{summary.get('name')}：CA {summary.get('ca')} / PA {summary.get('pa')}，完整度 {summary.get('data_completeness')}",
    )


def get_player_history(session: Session, instance_id: int, from_date: date | None = None, to_date: date | None = None) -> ToolCall:
    """``get_player_history`` — snapshot timeline used for growth curves."""
    data = history(session, instance_id, from_date, to_date)
    return ToolCall(
        "get_player_history",
        {"instance_id": instance_id, "from": from_date.isoformat() if from_date else None, "to": to_date.isoformat() if to_date else None},
        data,  # type: ignore[arg-type]
        f"{len(data['points'])} 个历史快照",
    )


def find_similar_transfers(session: Session, instance_id: int, limit: int = 20) -> ToolCall:
    """``find_similar_transfers`` — weighted comparable completed transfers."""
    outcome = similar_transfers(session, instance_id, limit=limit)
    result = {
        "target": outcome.target,
        "items": outcome.items,
        "effective_weights": outcome.effective_weights,
        "missing_fields": outcome.missing_fields,
        "data_gaps": outcome.data_gaps,
        "sample_size": outcome.sample_size,
    }
    return ToolCall(
        "find_similar_transfers",
        {"instance_id": instance_id, "limit": limit},
        result,
        f"找到 {outcome.sample_size} 笔相似成交",
        warnings=list(outcome.data_gaps),
    )


def get_transfer_price_stats(session: Session, save_id: int, criteria: dict[str, object] | None = None) -> ToolCall:
    """``get_transfer_price_stats`` — median/quartiles with coverage and exclusions."""
    data = criteria or {}
    filters = TransferFilter(
        position_group=_str(data.get("position_group")),
        min_age=_int(data.get("min_age")),
        max_age=_int(data.get("max_age")),
        min_ca=_int(data.get("min_ca")),
        max_ca=_int(data.get("max_ca")),
        from_date=_date(data.get("from_date")),
        to_date=_date(data.get("to_date")),
        league=_str(data.get("league")),
    )
    stats = transfer_price_stats(session, save_id, filters)
    summary = (
        f"{stats['sample_size']} 笔成交，中位数 {_money(stats['median'])}"
        if stats["sample_size"]
        else "没有满足条件的成交样本"
    )
    return ToolCall(
        "get_transfer_price_stats",
        {**data},
        stats,
        str(summary),
        warnings=list(stats.get("warnings", [])),
    )


def get_club_transfer_profile(session: Session, club_id: int) -> ToolCall:
    """``get_club_transfer_profile`` — buy/sell behaviour of one club."""
    profile = club_transfer_profile(session, club_id)
    bought = profile["bought"]
    sold = profile["sold"]
    return ToolCall(
        "get_club_transfer_profile",
        {"club_id": club_id},
        profile,
        f"{profile['name']}：买入 {bought['count']} 笔 / 卖出 {sold['count']} 笔",
        warnings=list(profile.get("warnings", [])),
    )


def estimate_transfer_value(session: Session, instance_id: int) -> ToolCall:
    """``estimate_transfer_value`` — comparable-transfer valuation range."""
    result = estimate_value(session, instance_id)
    if result["insufficient_sample"]:
        summary = f"样本仅 {result['sample_size']} 笔，拒绝给出精确估值"
    else:
        summary = f"估值区间 {_money(result['low'])} – {_money(result['high'])}（样本 {result['sample_size']}）"
    return ToolCall(
        "estimate_transfer_value",
        {"instance_id": instance_id},
        result,
        summary,
        warnings=list(result.get("warnings", [])),
    )


def simulate_transfer_offer(
    session: Session, instance_id: int, budget: float | None = None, installments: int = 3
) -> ToolCall:
    """``simulate_transfer_offer`` — opening bid, target price and walk-away price from the valuation range.

    The simulation only rearranges the valuation numbers; it never invents a market price when the sample is small.
    """
    valuation = estimate_value(session, instance_id)
    if valuation["insufficient_sample"]:
        return ToolCall(
            "simulate_transfer_offer",
            {"instance_id": instance_id, "budget": budget, "installments": installments},
            {"instance_id": instance_id, "insufficient_sample": True, "valuation": valuation},
            "估值样本不足，拒绝给出报价建议",
            warnings=list(valuation.get("warnings", [])),
        )
    low = float(valuation["low"] or 0)
    mid = float(valuation["mid"] or 0)
    high = float(valuation["high"] or 0)
    opening = round(mid * 0.85, 2)
    walk_away = high
    warnings: list[str] = []
    if budget is not None and budget < mid:
        warnings.append("预算低于估值中位数，可能需要分期或出售球员腾出空间")
        walk_away = min(high, budget)
    schedule = [round(opening / max(installments, 1), 2) for _ in range(max(installments, 1))]
    result = {
        "instance_id": instance_id,
        "currency": valuation["currency"],
        "opening_bid": opening,
        "target_price": mid,
        "walk_away_price": walk_away,
        "budget": budget,
        "installments": installments,
        "installment_schedule": schedule,
        "valuation": valuation,
        "sample_size": valuation["sample_size"],
        "insufficient_sample": False,
    }
    return ToolCall(
        "simulate_transfer_offer",
        {"instance_id": instance_id, "budget": budget, "installments": installments},
        result,
        f"首报 {_money(opening)}，目标 {_money(mid)}，上限 {_money(walk_away)}",
        warnings=warnings,
    )


def analyze_own_club_deal(session: Session, transfer_id: int) -> ToolCall:
    """``analyze_own_club_deal`` — review one completed transfer against the market for its age and role."""
    transfer = next((row for row in fetch_transfers(session, _save_of_transfer(session, transfer_id), TransferFilter(status="all")) if row.id == transfer_id), None)
    if transfer is None:
        raise ValueError("transfer not found")
    if transfer.effective_fee is None:
        return ToolCall(
            "analyze_own_club_deal",
            {"transfer_id": transfer_id},
            {"transfer_id": transfer_id, "insufficient_data": True},
            "该交易没有金额，无法复盘",
            warnings=["成交金额缺失"],
        )
    filters = TransferFilter(
        position_group=None,
        min_age=max((transfer.player_age_at_transfer or 18) - 2, 14),
        max_age=(transfer.player_age_at_transfer or 18) + 2,
        min_ca=max((transfer.player_ca_at_transfer or 100) - 20, 0),
        max_ca=(transfer.player_ca_at_transfer or 100) + 20,
        from_date=date(transfer.transfer_date.year - 2, 1, 1),
    )
    stats = transfer_price_stats(session, transfer.fm_save_id, filters)
    values = [
        row.effective_fee
        for row in fetch_transfers(session, transfer.fm_save_id, filters)
        if row.effective_fee is not None and row.id != transfer.id
    ]
    cheaper = sum(1 for value in values if value is not None and value < float(transfer.effective_fee))
    percentile = round(cheaper / len(values), 4) if values else None
    result = {
        "transfer_id": transfer.id,
        "player_name": transfer.player_name,
        "effective_fee": transfer.effective_fee,
        "market_median": stats["median"],
        "market_p25": stats["p25"],
        "market_p75": stats["p75"],
        "comparables": stats["sample_size"],
        "fee_percentile": percentile,
        "verdict": _verdict(percentile),
        "stats": stats,
    }
    return ToolCall(
        "analyze_own_club_deal",
        {"transfer_id": transfer_id},
        result,
        f"{transfer.player_name} 成交 {_money(transfer.effective_fee)}，处于同类样本第 {percentile:.0%} 分位"
        if percentile is not None
        else f"{transfer.player_name} 成交 {_money(transfer.effective_fee)}，缺少同类样本",
        warnings=list(stats.get("warnings", [])),
    )


def evaluate_role(session: Session, instance_id: int, role_key: str) -> ToolCall:
    """Extra tool used by the scouting screen: role score with component breakdown."""
    result = evaluate_player(session, instance_id, role_key)
    return ToolCall(
        "evaluate_role",
        {"instance_id": instance_id, "role_key": role_key},
        result,  # type: ignore[arg-type]
        f"{result['role_name']} 评分 {result['score']}（覆盖 {result['coverage']:.0%}）",
    )


TOOL_NAMES = (
    "get_squad_overview",
    "get_player_profile",
    "search_players",
    "evaluate_player",
    "compare_players",
    "analyze_position_depth",
    "find_transfer_targets",
    "analyze_transfer_history",
    "get_player_growth_history",
    "generate_recruitment_report",
    "get_player_history",
    "find_similar_transfers",
    "get_transfer_price_stats",
    "get_club_transfer_profile",
    "estimate_transfer_value",
    "simulate_transfer_offer",
    "analyze_own_club_deal",
    "evaluate_role",
    "get_player_contract",
    "get_player_transfer_history",
    "get_club_transfer_history",
    "get_transfer_clauses",
    "get_club_financial_context",
    "calculate_transfer_valuation",
    "generate_purchase_offers",
    "generate_sale_offers",
    "record_negotiation_event",
    "review_negotiation",
)


def get_squad_overview(session: Session, save_id: int, profile: str | None = None) -> ToolCall:
    """``get_squad_overview`` — squad score, depth, contracts and planning signals for the managed club."""
    from ..analytics.squad import squad_overview

    result = squad_overview(session, save_id, profile_key=profile)
    club = result.get("club")
    score = result.get("score")
    return ToolCall(
        "get_squad_overview",
        {"save_id": save_id, "profile": profile},
        result,  # type: ignore[arg-type]
        f"{club['name'] if club else '无俱乐部'}：阵容评分 {score if score is not None else '—'}，"
        f"阵容人数 {result.get('squad_size')}",
        warnings=[str(item) for item in result.get("data_gaps", [])],  # type: ignore[union-attr]
    )


def analyze_position_depth(session: Session, save_id: int) -> ToolCall:
    """``analyze_position_depth`` — per-slot depth with the ranked weaknesses."""
    from ..analytics.squad import position_depth, roster, squad_weakness

    players = roster(session, save_id)
    depth = position_depth(players)
    weakness = squad_weakness(depth)
    return ToolCall(
        "analyze_position_depth",
        {"save_id": save_id},
        {"depth": depth, "weakness": weakness, "squad_size": len(players)},
        f"最薄弱位置：{weakness[0]['slot_name']}（缺口评分 {weakness[0]['severity']}）" if weakness else "没有位置数据",
    )


def evaluate_player(session: Session, save_id: int, instance_id: int) -> ToolCall:
    """``evaluate_player`` — six-dimensional player score with strengths, risks and cost estimate."""
    from ..analytics.recruitment import player_score

    result = player_score(session, save_id, instance_id)
    player = result["player"]
    assert isinstance(player, dict)
    return ToolCall(
        "evaluate_player",
        {"save_id": save_id, "instance_id": instance_id},
        result,
        f"{player['name']}：综合评分 {result['score']}，强项 {', '.join(str(item) for item in result['strengths'][:2]) or '—'}",
    )


def compare_players(session: Session, save_id: int, instance_ids: list[int]) -> ToolCall:
    """``compare_players`` — score several players with identical weights."""
    from ..analytics.recruitment import compare_players as compare

    result = compare(session, save_id, instance_ids)
    return ToolCall(
        "compare_players",
        {"save_id": save_id, "instance_ids": instance_ids},
        result,
        f"比较 {result['compared']} 名球员，可比维度 {len(result['shared_dimensions'])} 项",
    )


def find_transfer_targets(
    session: Session,
    save_id: int,
    slot: str | None = None,
    min_age: int | None = None,
    max_age: int | None = None,
    max_value: int | None = None,
    limit: int = 10,
) -> ToolCall:
    """``find_transfer_targets`` — ranked candidates for one slot within budget and age limits."""
    from ..analytics.recruitment import search_recruitment

    result = search_recruitment(
        session,
        save_id,
        slot=slot,
        min_age=min_age,
        max_age=max_age,
        max_value=max_value,
        limit=limit,
    )
    return ToolCall(
        "find_transfer_targets",
        {"save_id": save_id, "slot": slot, "min_age": min_age, "max_age": max_age, "max_value": max_value},
        result,
        f"{result['total']} 名候选，返回前 {len(result['items'])} 名",
        warnings=[str(item) for item in result.get("data_gaps", [])][:5],  # type: ignore[union-attr]
    )


def analyze_transfer_history(session: Session, save_id: int, club_id: int | None = None) -> ToolCall:
    """``analyze_transfer_history`` — own-club deal review plus the transaction taxonomy summary."""
    from ..analytics.deals import transaction_summary, transfer_review

    review = transfer_review(session, save_id, club_id)
    summary = transaction_summary(session, save_id)
    result = {"review": review, "categories": summary}
    club = review.get("club")
    deals = review.get("summary")
    detail = f"{deals['deals']} 笔交易，其中 {deals['profitable']} 笔已升值" if isinstance(deals, dict) else "没有可复盘的交易"
    return ToolCall(
        "analyze_transfer_history",
        {"save_id": save_id, "club_id": club_id},
        result,
        f"{club['name'] if club else '本队'}：{detail}",
    )


def get_player_growth_history(session: Session, instance_id: int) -> ToolCall:
    """``get_player_growth_history`` — growth timeline, rate, advice and outlook band."""
    from ..analytics.development import growth_profile

    result = growth_profile(session, instance_id)
    player = result["player"]
    assert isinstance(player, dict)
    outlook = result["outlook"]
    assert isinstance(outlook, dict)
    return ToolCall(
        "get_player_growth_history",
        {"instance_id": instance_id},
        result,
        f"{player['name']}：{len(result['points'])} 个快照，月均成长 {result['rates']['overall_per_month']}，"  # type: ignore[index]
        f"潜力判断「{outlook['label']}」",
        warnings=[str(item) for item in result.get("data_gaps", [])],  # type: ignore[union-attr]
    )


def generate_recruitment_report(
    session: Session,
    save_id: int,
    slot: str | None = None,
    budget: int | None = None,
    limit: int = 5,
) -> ToolCall:
    """``generate_recruitment_report`` — shortlist with reasons, cost and risks for one slot."""
    from ..analytics.recruitment import build_shortlist

    result = build_shortlist(
        session,
        save_id,
        name=f"{slot or '全位置'}引援方案",
        slot=slot,
        budget=budget,
        limit=limit,
        persist=False,
    )
    top = result["items"][0] if result["items"] else None
    return ToolCall(
        "generate_recruitment_report",
        {"save_id": save_id, "slot": slot, "budget": budget},
        result,
        f"生成 {len(result['items'])} 名候选" + (f"，首选 {top['player']['name']}（{top['score']}）" if top else ""),
        warnings=[str(item) for item in result.get("data_gaps", [])][:5],  # type: ignore[union-attr]
    )


def _verdict(percentile: float | None) -> str:
    if percentile is None:
        return "unknown"
    if percentile <= 0.25:
        return "低价买入"
    if percentile >= 0.75:
        return "高价买入"
    return "价格合理"


def _save_of_transfer(session: Session, transfer_id: int) -> int:
    from ..models import Transfer

    transfer = session.get(Transfer, transfer_id)
    if transfer is None:
        raise ValueError("transfer not found")
    return transfer.fm_save_id


def _str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def _date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _money(value: object) -> str:
    if value is None:
        return "—"
    amount = float(value)
    if abs(amount) >= 100_000_000:
        return f"{amount / 100_000_000:.2f} 亿"
    if abs(amount) >= 10_000:
        return f"{amount / 10_000:.0f} 万"
    return f"{amount:.0f}"


# ---------------------------------------------------------------------------
# V3.3.2-05 AI Transfer Director 工具
#
# 这些工具只调用 services.transfer_director 的确定性计算；AI 不生成金额。
# 所有工具在入口校验球员/谈判属于传入 save_id，越权直接抛 ValueError。
# ---------------------------------------------------------------------------

def _director():
    from ..services import transfer_director

    return transfer_director


def _instance_in_save(session: Session, save_id: int, instance_id: int):
    from ..models import PlayerInstance

    instance = session.get(PlayerInstance, instance_id)
    if instance is None or instance.fm_save_id != save_id:
        raise ValueError("球员不存在或不属于当前存档")
    return instance


def get_player_contract(session: Session, save_id: int, instance_id: int) -> ToolCall:
    """``get_player_contract`` — 真实合同字段；缺失字段明确列为 unknown。"""
    director = _director()
    instance = _instance_in_save(session, save_id, instance_id)
    context = director.player_transfer_context(session, instance)
    contract = context["contract"]
    summary = (
        f"周薪 {_money(contract['wage'])}，合同到期 {contract['contract_end'] or '未知'}，"
        f"剩余 {contract['remaining_months'] if contract['remaining_months'] is not None else '未知'} 个月"
    )
    return ToolCall(
        name="get_player_contract",
        arguments={"instance_id": instance_id},
        result=contract,
        summary=summary,
        warnings=list(contract.get("warnings") or []),
    )


def get_player_transfer_history(session: Session, save_id: int, instance_id: int, limit: int = 20) -> ToolCall:
    """``get_player_transfer_history`` — 该球员在当前存档的历史转会。"""
    director = _director()
    instance = _instance_in_save(session, save_id, instance_id)
    rows = director._transfer_rows(session, save_id, instance.id, limit=limit)
    warnings = [] if rows else ["当前存档没有该球员的转会记录；没有记录不代表没有发生过转会"]
    return ToolCall(
        name="get_player_transfer_history",
        arguments={"instance_id": instance_id, "limit": limit},
        result={"items": rows, "total": len(rows)},
        summary=f"找到 {len(rows)} 笔转会记录",
        warnings=warnings,
    )


def get_club_transfer_history(session: Session, save_id: int, club_id: int) -> ToolCall:
    """``get_club_transfer_history`` — 俱乐部买卖/租借/未来/取消汇总。"""
    director = _director()
    summary_data = director.club_transfer_summary(session, save_id, club_id)
    return ToolCall(
        name="get_club_transfer_history",
        arguments={"club_id": club_id},
        result=summary_data,
        summary=f"买入 {summary_data['purchases']} 笔、卖出 {summary_data['sales']} 笔",
        warnings=[summary_data["warning"]] if summary_data.get("warning") else [],
    )


def get_transfer_clauses(session: Session, save_id: int, instance_id: int) -> ToolCall:
    """``get_transfer_clauses`` — 已导入/已确认的分期、浮动、二转、买断条款。"""
    director = _director()
    instance = _instance_in_save(session, save_id, instance_id)
    clauses = director._clauses(session, save_id, instance.id)
    warnings = [] if clauses else ["当前没有可验证的条款记录；未知条款不等于没有条款"]
    return ToolCall(
        name="get_transfer_clauses",
        arguments={"instance_id": instance_id},
        result={"items": clauses, "total": len(clauses)},
        summary=f"找到 {len(clauses)} 条条款",
        warnings=warnings,
    )


def get_club_financial_context(session: Session, save_id: int) -> ToolCall:
    """``get_club_financial_context`` — 预算来源不存在时明确返回不可用。"""
    from ..models import FmSave

    save = session.get(FmSave, save_id)
    return ToolCall(
        name="get_club_financial_context",
        arguments={},
        result={
            "available": False,
            "user_club_id": save.user_club_id if save else None,
            "transfer_budget": None,
            "wage_budget": None,
            "reason": "当前数据源不提供转会预算与工资预算；不要假设预算数字",
        },
        summary="未获取可靠预算数据",
        warnings=["当前未获取可靠预算数据，报价方案不包含预算可行性保证"],
    )


def calculate_transfer_valuation(session: Session, save_id: int, instance_id: int) -> ToolCall:
    """``calculate_transfer_valuation`` — 复用确定性估值；样本不足拒绝给区间。"""
    director = _director()
    _instance_in_save(session, save_id, instance_id)
    valuation = director.valuation_summary(session, instance_id)
    if valuation["insufficient_sample"]:
        summary = f"可比成交仅 {valuation['sample_size']} 笔，拒绝给出估值区间"
    else:
        summary = f"估值 {_money(valuation['low'])} – {_money(valuation['high'])}（{valuation['confidence']}）"
    return ToolCall(
        name="calculate_transfer_valuation",
        arguments={"instance_id": instance_id},
        result=valuation,
        summary=summary,
        warnings=list(valuation.get("warnings") or []),
    )


def generate_purchase_offers(
    session: Session, save_id: int, instance_id: int, budget: float | None = None
) -> ToolCall:
    """``generate_purchase_offers`` — 三套买入方案（确定性）。"""
    director = _director()
    instance = _instance_in_save(session, save_id, instance_id)
    result = director.generate_purchase_offers(session, instance, budget=budget)
    types = "、".join(offer["offer_type"] for offer in result["offers"]) or "无"
    return ToolCall(
        name="generate_purchase_offers",
        arguments={"instance_id": instance_id, "budget": budget},
        result=result,
        summary=f"生成 {len(result['offers'])} 套买入方案（{types}）",
        warnings=list(result.get("warnings") or []),
    )


def generate_sale_offers(session: Session, save_id: int, instance_id: int) -> ToolCall:
    """``generate_sale_offers`` — 三套出售方案与阵容/工资影响。"""
    director = _director()
    instance = _instance_in_save(session, save_id, instance_id)
    result = director.generate_sale_offers(session, instance)
    return ToolCall(
        name="generate_sale_offers",
        arguments={"instance_id": instance_id},
        result=result,
        summary=f"生成 {len(result['offers'])} 套出售方案",
        warnings=list(result.get("warnings") or []),
    )


def record_negotiation_event(
    session: Session,
    save_id: int,
    negotiation_id: int,
    event_type: str,
    amount: float | None = None,
    data: dict[str, object] | None = None,
) -> ToolCall:
    """``record_negotiation_event`` — 只记录用户真实谈判，不提交游戏内报价。"""
    from ..models import TransferNegotiation

    director = _director()
    negotiation = session.get(TransferNegotiation, negotiation_id)
    if negotiation is None or negotiation.fm_save_id != save_id:
        raise ValueError("谈判记录不存在或不属于当前存档")
    try:
        event, duplicate = director.append_event(
            session, negotiation, event_type=event_type, amount=amount, data=dict(data or {})
        )
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    return ToolCall(
        name="record_negotiation_event",
        arguments={"negotiation_id": negotiation_id, "event_type": event_type, "amount": amount},
        result={
            "event_id": event.id,
            "duplicate": duplicate,
            "negotiation_status": negotiation.status,
        },
        summary=f"已记录 {event_type}，当前状态 {negotiation.status}",
        warnings=[],
    )


def review_negotiation(session: Session, save_id: int, negotiation_id: int) -> ToolCall:
    """``review_negotiation`` — 复盘已完成谈判。"""
    from ..models import TransferNegotiation

    director = _director()
    negotiation = session.get(TransferNegotiation, negotiation_id)
    if negotiation is None or negotiation.fm_save_id != save_id:
        raise ValueError("谈判记录不存在或不属于当前存档")
    review = director.review_negotiation(session, negotiation)
    return ToolCall(
        name="review_negotiation",
        arguments={"negotiation_id": negotiation_id},
        result=review,
        summary=f"{review['outcome']}，{review['round_count']} 轮",
        warnings=list(review.get("warnings") or []),
    )
