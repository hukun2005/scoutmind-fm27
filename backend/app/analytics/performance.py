"""Performance Analytics: per-position output, trend and the ability-versus-output comparison.

Three deliberately separate readings:

* **Output** — per-90 rates of the metrics that matter for the player's position, benchmarked against the same
  position group inside the save. A metric the scanner does not provide stays missing instead of becoming zero.
* **Trend** — season-over-season change when more than one period is stored. Match-level windows (last 5, last 10)
  are reported unavailable unless the source stores per-match rows; the response says so instead of inventing them.
* **Ability versus output** — CA percentile against output percentile inside the position group, which is what
  separates "good attributes" from "good performances".
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ingestion.attributes import SLOT_NAMES_ZH, position_group, slot_of
from ..models import Club, Player, PlayerInstance, PlayerStatistic
from .players import latest_snapshot_subquery
from .recruitment import MIN_PERCENTILE_PEERS

ALGORITHM_VERSION = "performance-1"

#: Metrics that matter per position group, in display order. ``higher_is_better`` drives the percentile direction.
POSITION_METRICS: dict[str, tuple[dict[str, object], ...]] = {
    "FW": (
        {"key": "goals", "label": "进球", "per90": True, "higher_is_better": True},
        {"key": "shots_on_target", "label": "射正", "per90": True, "higher_is_better": True},
        {"key": "xg", "label": "预期进球", "per90": True, "higher_is_better": True},
        {"key": "assists", "label": "助攻", "per90": True, "higher_is_better": True},
    ),
    "MF": (
        {"key": "assists", "label": "助攻", "per90": True, "higher_is_better": True},
        {"key": "key_passes", "label": "关键传球", "per90": True, "higher_is_better": True},
        {"key": "tackles", "label": "抢断", "per90": True, "higher_is_better": True},
        {"key": "passes_completed", "label": "成功传球", "per90": True, "higher_is_better": True},
    ),
    "DF": (
        {"key": "tackles", "label": "抢断", "per90": True, "higher_is_better": True},
        {"key": "interceptions", "label": "拦截", "per90": True, "higher_is_better": True},
        {"key": "clearances", "label": "解围", "per90": True, "higher_is_better": True},
        {"key": "aerials_won", "label": "争顶成功", "per90": True, "higher_is_better": True},
    ),
    "GK": (
        {"key": "saves", "label": "扑救", "per90": True, "higher_is_better": True},
        {"key": "conceded", "label": "失球", "per90": True, "higher_is_better": False},
        {"key": "clean_sheets", "label": "零封", "per90": False, "higher_is_better": True},
    ),
}

TREND_WINDOWS = ("last5", "last10", "season")


def performance_profile(session: Session, instance_id: int) -> dict[str, object]:
    """Output, trend and ability comparison for one player."""
    instance = session.get(PlayerInstance, instance_id)
    if instance is None:
        raise ValueError("player instance not found")
    player = session.get(Player, instance.player_id)
    rows = list(
        session.scalars(
            select(PlayerStatistic)
            .where(PlayerStatistic.player_instance_id == instance_id, PlayerStatistic.scope == "season")
            .order_by(PlayerStatistic.period.asc())
        )
    )
    latest_row = rows[-1] if rows else None
    group = position_group(instance.position)
    payload: dict[str, object] = {
        "player": {
            "instance_id": instance.id,
            "name": player.full_name if player else f"#{instance.player_id}",
            "position": instance.position,
            "slot": slot_of(instance.position),
            "slot_name": SLOT_NAMES_ZH.get(slot_of(instance.position) or ""),
            "position_group": group,
            "club_id": instance.club_id,
            "club": session.get(Club, instance.club_id).name if instance.club_id and session.get(Club, instance.club_id) else None,
        },
        "periods": [
            {
                "period": row.period,
                "competition": row.competition,
                "appearances": row.appearances,
                "minutes_played": row.minutes_played,
                "source": row.source,
            }
            for row in rows
        ],
        "season": None,
        "trend": {"available": False, "windows": [], "reason": ""},
        "ability_vs_output": {"available": False, "reason": ""},
        "metrics": [],
        "data_gaps": [],
        "algorithm_version": ALGORITHM_VERSION,
    }
    if latest_row is None:
        payload["data_gaps"] = ["该球员没有任何赛季统计，表现分析不可用"]
        payload["trend"]["reason"] = "没有统计周期"  # type: ignore[index]
        payload["ability_vs_output"]["reason"] = "没有统计周期"  # type: ignore[index]
        return payload
    metrics = _metrics(session, instance.fm_save_id, latest_row, group)
    payload["season"] = {
        "period": latest_row.period,
        "competition": latest_row.competition,
        "appearances": latest_row.appearances,
        "minutes_played": latest_row.minutes_played,
        "goals": latest_row.goals,
        "assists": latest_row.assists,
        "xg": latest_row.xg,
        "source": latest_row.source,
    }
    payload["metrics"] = metrics
    payload["trend"] = _trend(rows, group)
    payload["ability_vs_output"] = _ability_vs_output(session, instance.fm_save_id, instance_id, latest_row, group, metrics)
    gaps: list[str] = []
    if latest_row.minutes_played is None:
        gaps.append("缺少出场时间，无法换算每 90 分钟数据")
    for metric in metrics:
        if metric["per90"] is None and metric["total"] is not None:
            gaps.append(f"{metric['label']} 只有累计值，缺少出场时间")
    if not payload["trend"]["available"]:  # type: ignore[index]
        gaps.append(str(payload["trend"]["reason"]))  # type: ignore[index]
    payload["data_gaps"] = gaps
    return payload


def performance_board(
    session: Session,
    save_id: int,
    slot: str | None = None,
    min_minutes: int = 300,
    limit: int = 50,
) -> dict[str, object]:
    """Every player with season statistics ranked by output percentile inside its position group."""
    base = latest_snapshot_subquery()
    rows = session.execute(select(base).where(base.c.fm_save_id == save_id)).all()
    stats = {
        row.player_instance_id: row
        for row in session.scalars(
            select(PlayerStatistic)
            .where(PlayerStatistic.scope == "season")
            .order_by(PlayerStatistic.observed_at.desc())
        )
    }
    entries: list[dict[str, object]] = []
    for row in rows:
        if slot and slot_of(row.position) != slot:
            continue
        statistic = stats.get(int(row.instance_id))
        if statistic is None:
            continue
        group = position_group(row.position)
        metrics = _metrics(session, save_id, statistic, group)
        entries.append(
            {
                "instance_id": int(row.instance_id),
                "name": row.full_name,
                "age": row.age,
                "position": row.position,
                "slot": slot_of(row.position),
                "slot_name": SLOT_NAMES_ZH.get(slot_of(row.position) or ""),
                "position_group": group,
                "club": session.get(Club, row.club_id).name if row.club_id else None,
                "ca": row.ca,
                "minutes_played": statistic.minutes_played,
                "period": statistic.period,
                "metrics": metrics,
                "output_percentile": _output_percentile(metrics),
                "ability_percentile": None,
                "verdict": _verdict(metrics),
            }
        )
    # Ability percentiles need the whole group, which is only known after every entry was collected.
    by_group: dict[str, list[float]] = {}
    for entry in entries:
        if entry["ca"] is not None:
            by_group.setdefault(str(entry["position_group"]), []).append(float(entry["ca"]))
    for entry in entries:
        values = sorted(by_group.get(str(entry["position_group"]), []))
        if len(values) >= MIN_PERCENTILE_PEERS and entry["ca"] is not None:
            entry["ability_percentile"] = round(_percentile(values, float(entry["ca"])), 4)
        entry["verdict"] = _verdict(entry["metrics"], entry["ability_percentile"], entry["output_percentile"])
    filtered = [entry for entry in entries if (entry["minutes_played"] or 0) >= min_minutes]
    filtered.sort(key=lambda item: -(float(item["output_percentile"] or 0)))
    return {
        "items": filtered[:limit],
        "total": len(filtered),
        "excluded_below_minutes": len(entries) - len(filtered),
        "min_minutes": min_minutes,
        "slot": slot,
        "algorithm_version": ALGORITHM_VERSION,
        "note": "百分位在存档内同位置球员之间计算；样本不足时不给排名",
    }


def _metrics(session: Session, save_id: int, row: PlayerStatistic, group: str | None) -> list[dict[str, object]]:
    specs = POSITION_METRICS.get(group or "", ())
    minutes = row.minutes_played
    peers = _peer_values(session, save_id, group, [str(spec["key"]) for spec in specs])
    metrics: list[dict[str, object]] = []
    for spec in specs:
        key = str(spec["key"])
        total = getattr(row, key, None)
        per90 = round(float(total) * 90 / float(minutes), 3) if total is not None and minutes else None
        values = peers.get(key, [])
        percentile = (
            round(_percentile(values, float(per90)), 4)
            if per90 is not None and len(values) >= MIN_PERCENTILE_PEERS
            else None
        )
        if not bool(spec["higher_is_better"]) and percentile is not None:
            percentile = round(1 - percentile, 4)
        metrics.append(
            {
                "key": key,
                "label": spec["label"],
                "total": total,
                "per90": per90 if bool(spec["per90"]) else None,
                "percentile": percentile,
                "peer_sample": len(values),
                "higher_is_better": bool(spec["higher_is_better"]),
                "available": total is not None,
            }
        )
    return metrics


def _peer_values(
    session: Session, save_id: int, group: str | None, keys: list[str]
) -> dict[str, list[float]]:
    """Per-90 values of every same-position player in the save, used as the percentile sample."""
    base = latest_snapshot_subquery()
    rows = session.execute(select(base).where(base.c.fm_save_id == save_id)).all()
    instances = {int(row.instance_id): row for row in rows if position_group(row.position) == group}
    if not instances:
        return {}
    statistics = session.scalars(
        select(PlayerStatistic)
        .where(PlayerStatistic.scope == "season", PlayerStatistic.player_instance_id.in_(instances.keys()))
        .order_by(PlayerStatistic.observed_at.desc())
    )
    seen: set[int] = set()
    result: dict[str, list[float]] = {key: [] for key in keys}
    for row in statistics:
        if row.player_instance_id in seen or not row.minutes_played:
            continue
        seen.add(row.player_instance_id)
        for key in keys:
            value = getattr(row, key, None)
            if value is not None:
                result[key].append(float(value) * 90 / float(row.minutes_played))
    return {key: sorted(values) for key, values in result.items()}


def _trend(rows: list[PlayerStatistic], group: str | None) -> dict[str, object]:
    """Season-over-season change; match windows stay unavailable without per-match rows."""
    if len(rows) < 2:
        return {
            "available": False,
            "windows": [],
            "reason": "只有 1 个统计周期，无法给出趋势；需要多赛季或逐场统计",
            "season_over_season": None,
        }
    current, previous = rows[-1], rows[-2]
    changes: list[dict[str, object]] = []
    for spec in POSITION_METRICS.get(group or "", ()):
        key = str(spec["key"])
        before = getattr(previous, key, None)
        after = getattr(current, key, None)
        changes.append(
            {
                "key": key,
                "label": spec["label"],
                "previous": before,
                "current": after,
                "delta": (int(after) - int(before)) if before is not None and after is not None else None,
            }
        )
    return {
        "available": True,
        "windows": ["season"],
        "unavailable_windows": {
            "last5": "需要逐场统计，数据源未提供",
            "last10": "需要逐场统计，数据源未提供",
        },
        "season_over_season": {
            "previous_period": previous.period,
            "current_period": current.period,
            "changes": changes,
        },
        "reason": "",
    }


def _ability_vs_output(
    session: Session,
    save_id: int,
    instance_id: int,
    row: PlayerStatistic,
    group: str | None,
    metrics: list[dict[str, object]],
) -> dict[str, object]:
    base = latest_snapshot_subquery()
    peers = session.execute(select(base).where(base.c.fm_save_id == save_id)).all()
    cas = sorted(float(peer.ca) for peer in peers if peer.ca is not None and position_group(peer.position) == group)
    target = next((float(peer.ca) for peer in peers if int(peer.instance_id) == instance_id and peer.ca is not None), None)
    output = _output_percentile(metrics)
    if target is None or len(cas) < MIN_PERCENTILE_PEERS:
        return {
            "available": False,
            "reason": "缺少 CA 或同位置样本不足，无法比较能力与表现",
            "ability_percentile": None,
            "output_percentile": output,
        }
    ability = round(_percentile(cas, target), 4)
    if output is None:
        return {
            "available": False,
            "reason": "统计样本不足，无法比较能力与表现",
            "ability_percentile": ability,
            "output_percentile": None,
        }
    gap = round(output - ability, 4)
    return {
        "available": True,
        "ability_percentile": ability,
        "output_percentile": output,
        "gap": gap,
        "verdict": _gap_verdict(gap),
        "evidence": [
            f"CA {target:.0f} 在同位置处于第 {ability:.0%} 分位",
            f"综合产出在同位置处于第 {output:.0%} 分位",
            f"两者相差 {gap:+.0%}",
        ],
        "reason": "",
    }


def _output_percentile(metrics: list[dict[str, object]]) -> float | None:
    values = [float(metric["percentile"]) for metric in metrics if metric["percentile"] is not None]
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _verdict(metrics: list[dict[str, object]], ability: object = None, output: object = None) -> str:
    if output is None:
        return "数据不足"
    assert isinstance(output, (int, float))
    if ability is None:
        return "仅表现可用"
    assert isinstance(ability, (int, float))
    gap = float(output) - float(ability)
    if gap >= 0.15:
        return "表现超出能力"
    if gap <= -0.15:
        return "表现低于能力"
    return "表现与能力相符"


def _gap_verdict(gap: float) -> str:
    if gap >= 0.15:
        return "表现优于属性预期"
    if gap <= -0.15:
        return "属性强于表现，需要检查战术适配与使用方式"
    return "表现与属性基本相符"


def _percentile(sorted_values: list[float], value: float) -> float:
    if not sorted_values:
        return 0.0
    below = sum(1 for item in sorted_values if item < value)
    equal = sum(1 for item in sorted_values if item == value)
    return (below + 0.5 * equal) / len(sorted_values)
