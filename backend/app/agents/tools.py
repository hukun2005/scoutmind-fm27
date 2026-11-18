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
    "search_players",
    "get_player_profile",
    "get_player_history",
    "find_similar_transfers",
    "get_transfer_price_stats",
    "get_club_transfer_profile",
    "estimate_transfer_value",
    "simulate_transfer_offer",
    "analyze_own_club_deal",
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
