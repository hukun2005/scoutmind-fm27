"""Player Development: growth tracking, development advice and potential outlook.

The module never claims to predict a player's future CA. It reports three separate things:

* **Growth facts** — the CA/value/minutes change between observed snapshots, with the interval that produced it.
* **Growth rate** — ``(CA_t − CA_t−1) / Δmonths`` for each observed interval and for the whole window.
* **Outlook** — a probability band derived from the observed rate, the remaining PA−CA room and the player's age.
  The band is a heuristic projection with an explicit uncertainty window; it is labelled as an estimate, and the
  response states the inputs and the sample size behind it.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ingestion.attributes import SLOT_NAMES_ZH, position_group, slot_of
from ..models import Club, Player, PlayerAttribute, PlayerAttributeValue, PlayerInstance, PlayerSnapshot
from ..utils import iso
from .recruitment import POSITION_TEMPLATES
from .scoring import score_attributes

ALGORITHM_VERSION = "development-1"

#: A player is expected to grow until this age; the projection only extrapolates inside this window.
GROWTH_AGE_LIMIT = 24

#: Minimum months between two snapshots before a rate is reported.
MIN_INTERVAL_MONTHS = 1

#: Uncertainty applied to the projected ability, wider when the observed window is short.
PROJECTION_UNCERTAINTY = 0.25

OUTLOOK_BANDS = (
    ("on_track", "大概率达到潜力区间", 0.95),
    ("close", "可能接近潜力区间", 0.85),
    ("gap", "与潜力区间有差距", 0.7),
    ("stalled", "停滞风险高", 0.0),
)


def growth_profile(session: Session, instance_id: int, context: dict[str, object] | None = None) -> dict[str, object]:
    """Growth timeline, rate, advice and outlook for one player."""
    instance = session.get(PlayerInstance, instance_id)
    if instance is None:
        raise ValueError("player instance not found")
    player = session.get(Player, instance.player_id)
    snapshots = list(
        session.scalars(
            select(PlayerSnapshot)
            .where(PlayerSnapshot.player_instance_id == instance_id)
            .order_by(PlayerSnapshot.observed_at.asc())
        )
    )
    positions = _positions(session, instance_id)
    points = _timeline(session, snapshots)
    rates = _rates(points)
    if not snapshots:
        return {
            "player": _player_payload(instance, player, None),
            "points": [],
            "rates": {"intervals": [], "overall_per_month": None, "recent_per_month": None, "classification": "unknown"},
            "advice": [
                {
                    "action": "等待数据",
                    "reason": "该球员还没有任何快照，无法分析成长",
                    "confidence": "none",
                    "evidence": ["快照数为 0"],
                }
            ],
            "outlook": {"band": "unknown", "label": "数据不足", "rationale": "没有快照", "probability": None},
            "data_gaps": ["没有快照数据"],
            "algorithm_version": ALGORITHM_VERSION,
        }
    latest = snapshots[-1]
    advice = _advice(points, rates, latest, context or {})
    outlook = _outlook(points, rates, latest)
    player_payload = _player_payload(instance, player, positions)
    player_payload.update(
        {
            "age": latest.age,
            "ca": latest.ca,
            "pa": latest.pa,
            "market_value": latest.market_value,
            "club_id": latest.club_id,
        }
    )
    gaps: list[str] = []
    if all(snapshot.minutes_played is None for snapshot in snapshots):
        gaps.append("出场时间缺失，无法判断比赛负荷对成长的影响")
    if all(snapshot.pa is None for snapshot in snapshots):
        gaps.append("PA 缺失，潜力区间无法对比")
    if len(snapshots) < 2:
        gaps.append("只有 1 个快照，无法计算成长速率")
    return {
        "player": player_payload,
        "points": points,
        "rates": rates,
        "advice": advice,
        "outlook": outlook,
        "data_gaps": gaps,
        "algorithm_version": ALGORITHM_VERSION,
    }


def development_board(
    session: Session, save_id: int, limit: int = 50, min_age: int | None = 23
) -> dict[str, object]:
    """All tracked players with at least two snapshots, ordered by growth rate."""
    from .squad import user_club

    club = user_club(session, save_id)
    context = _squad_context(session, club.id if club else None, save_id)
    rows: list[dict[str, object]] = []
    instances = session.execute(
        select(PlayerSnapshot.player_instance_id, PlayerSnapshot.age, PlayerSnapshot.ca, PlayerSnapshot.pa)
        .join(PlayerInstance, PlayerInstance.id == PlayerSnapshot.player_instance_id)
        .where(PlayerInstance.fm_save_id == save_id)
        .order_by(PlayerSnapshot.observed_at.desc())
    ).all()
    seen: set[int] = set()
    for instance_id, age, ca, pa in instances:
        if instance_id in seen:
            continue
        seen.add(instance_id)
        if min_age is not None and (age is None or age > min_age):
            continue
        profile = growth_profile(session, int(instance_id), context)
        points = profile["points"]
        if len(points) < 2:  # type: ignore[arg-type]
            continue
        rates = profile["rates"]
        assert isinstance(rates, dict)
        rows.append(
            {
                "player": profile["player"],
                "overall_per_month": rates["overall_per_month"],
                "recent_per_month": rates["recent_per_month"],
                "classification": rates["classification"],
                "ca_delta": _delta(points[0]["ca"], points[-1]["ca"]),  # type: ignore[index]
                "outlook": profile["outlook"],
                "advice_top": (profile["advice"] or [{}])[0],  # type: ignore[index]
            }
        )
    rows.sort(key=lambda row: -(float(row["overall_per_month"] or 0)))
    return {
        "items": rows[:limit],
        "total": len(rows),
        "min_age": min_age,
        "algorithm_version": ALGORITHM_VERSION,
        "note": "只统计至少有两个快照的球员；没有速率就没有成长结论",
    }


def _timeline(session: Session, snapshots: list[PlayerSnapshot]) -> list[dict[str, object]]:
    points: list[dict[str, object]] = []
    for index, snapshot in enumerate(snapshots):
        previous = snapshots[index - 1] if index else None
        points.append(
            {
                "snapshot_id": snapshot.id,
                "date": (snapshot.game_date or snapshot.observed_at.date()).isoformat(),
                "observed_at": iso(snapshot.observed_at),
                "age": snapshot.age,
                "ca": snapshot.ca,
                "pa": snapshot.pa,
                "market_value": snapshot.market_value,
                "wage": snapshot.wage,
                "minutes_played": snapshot.minutes_played,
                "appearances": snapshot.appearances,
                "goal_contributions": _goal_contributions(snapshot),
                "ca_delta": _delta(previous.ca, snapshot.ca) if previous else None,
                "value_delta": _delta(previous.market_value, snapshot.market_value) if previous else None,
                "minutes_delta": _delta(previous.minutes_played, snapshot.minutes_played) if previous else None,
                "change_label": _change_label(previous, snapshot) if previous else "初始记录",
            }
        )
    return points


def _rates(points: list[dict[str, object]]) -> dict[str, object]:
    intervals: list[dict[str, object]] = []
    for previous, current in zip(points, points[1:]):
        months = _months_between(str(previous["date"]), str(current["date"]))
        delta = current["ca_delta"]
        intervals.append(
            {
                "from": previous["date"],
                "to": current["date"],
                "months": months,
                "ca_delta": delta,
                "per_month": round(float(delta) / months, 4)
                if months is not None and months >= MIN_INTERVAL_MONTHS and delta is not None
                else None,
            }
        )
    valid = [interval for interval in intervals if interval["per_month"] is not None]
    overall = round(sum(float(item["per_month"]) for item in valid) / len(valid), 4) if valid else None
    recent = float(valid[-1]["per_month"]) if valid else None
    return {
        "intervals": intervals,
        "overall_per_month": overall,
        "recent_per_month": recent,
        "classification": _classify(overall),
        "formula": "GrowthRate = (CA_t − CA_t−1) / Δ月",
        "sample_size": len(valid),
    }


def _advice(
    points: list[dict[str, object]],
    rates: dict[str, object],
    latest: PlayerSnapshot,
    context: dict[str, object],
) -> list[dict[str, object]]:
    advice: list[dict[str, object]] = []
    age = latest.age
    ca = latest.ca
    pa = latest.pa
    minutes = latest.minutes_played
    overall = rates.get("overall_per_month")
    squad_median = context.get("squad_median_ca")
    slot_best = context.get("slot_best_ca")

    if age is not None and age <= 21 and minutes is not None and minutes < 900:
        advice.append(
            {
                "action": "考虑外租获取出场时间",
                "reason": "年轻且出场时间不足，缺乏比赛锻炼会拖慢成长",
                "confidence": "medium",
                "evidence": [f"{age} 岁，本赛季出场 {minutes} 分钟"],
            }
        )
    if minutes is not None and minutes >= 1500 and ca is not None and slot_best and float(ca) >= float(slot_best) - 10:
        advice.append(
            {
                "action": "保留在一线队",
                "reason": "出场时间充足且能力已接近该位置主力",
                "confidence": "high",
                "evidence": [f"出场 {minutes} 分钟", f"CA {ca}，同位置最高 {slot_best}"],
            }
        )
    if overall is not None and float(overall) > 0 and minutes is not None and minutes < 1200:
        advice.append(
            {
                "action": "增加比赛时间",
                "reason": "能力在增长但比赛负荷偏低，增加出场有助于兑现潜力",
                "confidence": "medium",
                "evidence": [f"月均成长 {overall}", f"出场 {minutes} 分钟"],
            }
        )
    if _stagnant(points) and age is not None and age <= 23:
        advice.append(
            {
                "action": "排查发展停滞",
                "reason": "多个快照之间能力没有变化",
                "confidence": "medium",
                "evidence": [f"最近 {len(points)} 个快照 CA 未变化"],
            }
        )
    if age is not None and age >= 29 and overall is not None and float(overall) < 0:
        advice.append(
            {
                "action": "评估出售或降低使用强度",
                "reason": "年龄进入下降区间且能力已开始下滑",
                "confidence": "high",
                "evidence": [f"{age} 岁", f"月均成长 {overall}"],
            }
        )
    if age is not None and age >= 30 and pa is not None and ca is not None and pa - ca <= 2:
        advice.append(
            {
                "action": "规划接班",
                "reason": "潜力空间已用尽，需要提前寻找替代者",
                "confidence": "high",
                "evidence": [f"PA−CA 仅 {pa - ca}"],
            }
        )
    position_hint = context.get("position_hint")
    if isinstance(position_hint, dict) and position_hint.get("better_position"):
        advice.append(
            {
                "action": f"尝试改打 {position_hint['better_position']}",
                "reason": "按当前属性组合，另一个位置的模板评分明显更高",
                "confidence": "low",
                "evidence": [str(position_hint.get("evidence") or "")],
            }
        )
    if not advice:
        advice.append(
            {
                "action": "保持现状",
                "reason": "现有数据没有触发任何调整信号",
                "confidence": "low",
                "evidence": ["成长速率、出场时间与年龄均处于常规区间"],
            }
        )
    return advice


def _outlook(points: list[dict[str, object]], rates: dict[str, object], latest: PlayerSnapshot) -> dict[str, object]:
    """Projected ability band with an explicit uncertainty window, never a single predicted CA."""
    ca = latest.ca
    pa = latest.pa
    age = latest.age
    overall = rates.get("overall_per_month")
    if ca is None or pa is None or age is None or overall is None:
        return {
            "band": "unknown",
            "label": "数据不足",
            "probability": None,
            "projected_low": None,
            "projected_high": None,
            "rationale": "需要 CA、PA、年龄与至少两个快照才能给出区间",
            "inputs": {"ca": ca, "pa": pa, "age": age, "rate_per_month": overall},
        }
    months = max(0, (GROWTH_AGE_LIMIT - age) * 12)
    rate = float(overall)
    decay = 0.6
    projected = float(ca) + rate * months * decay
    low = round(projected * (1 - PROJECTION_UNCERTAINTY), 1)
    high = round(min(float(pa), projected * (1 + PROJECTION_UNCERTAINTY)), 1)
    ratio = projected / float(pa) if pa else 0.0
    band, label, _ = next(
        ((key, band_label, threshold) for key, band_label, threshold in OUTLOOK_BANDS if ratio >= threshold),
        ("stalled", "停滞风险高", 0.0),
    )
    probability = round(max(0.0, min(1.0, ratio)), 2)
    return {
        "band": band,
        "label": label,
        "probability": probability,
        "projected_low": low,
        "projected_high": high,
        "projected_center": round(projected, 1),
        "horizon_age": GROWTH_AGE_LIMIT,
        "rationale": (
            f"按最近 {months} 个月观测、月均 {rate:+.2f} CA、{age} 岁到 {GROWTH_AGE_LIMIT} 岁线性外推并施加"
            f" {decay:.0%} 衰减；区间为外推值的 ±{PROJECTION_UNCERTAINTY:.0%}。这是等级与区间，不是精确 CA 预测"
        ),
        "inputs": {
            "ca": ca,
            "pa": pa,
            "age": age,
            "rate_per_month": rate,
            "snapshots": len(points),
        },
        "missing": [],
    }


def _squad_context(session: Session, club_id: int | None, save_id: int) -> dict[str, object]:
    """Median CA and best CA per slot of the managed club, used by the advice rules."""
    if club_id is None:
        return {}
    from .players import latest_snapshot_subquery

    base = latest_snapshot_subquery()
    rows = session.execute(select(base).where(base.c.fm_save_id == save_id, base.c.club_id == club_id)).all()
    values = [float(row.ca) for row in rows if row.ca is not None]
    if not values:
        return {}
    ordered = sorted(values)
    median = ordered[len(ordered) // 2] if len(ordered) % 2 else (ordered[len(ordered) // 2 - 1] + ordered[len(ordered) // 2]) / 2
    best_by_slot: dict[str, float] = {}
    for row in rows:
        if row.ca is None:
            continue
        slot = slot_of(row.position)
        if slot and float(row.ca) > best_by_slot.get(slot, 0.0):
            best_by_slot[slot] = float(row.ca)
    return {"squad_median_ca": median, "slot_best_by_slot": best_by_slot, "club_id": club_id}


def _positions(session: Session, instance_id: int) -> dict[str, object]:
    """Best-scoring position template for a player, used as a position-change hint."""
    snapshot = session.scalar(
        select(PlayerSnapshot)
        .where(PlayerSnapshot.player_instance_id == instance_id)
        .order_by(PlayerSnapshot.observed_at.desc())
        .limit(1)
    )
    if snapshot is None:
        return {}
    readings = {
        key: float(value)
        for key, value in session.execute(
            select(PlayerAttribute.key, PlayerAttributeValue.value)
            .join(PlayerAttribute, PlayerAttribute.id == PlayerAttributeValue.attribute_id)
            .where(PlayerAttributeValue.player_snapshot_id == snapshot.id)
        ).all()
    }
    if not readings:
        return {}
    names = {row.key: row.name_zh for row in session.scalars(select(PlayerAttribute))}
    current = (snapshot.position or "").upper()
    best_key = None
    best_score = None
    for key in ("GK", "DC", "DL", "DM", "MC", "AMC", "AML", "ST"):
        template = POSITION_TEMPLATES.get(key)
        if not template:
            continue
        result = score_attributes(readings, template, names)
        if float(result["coverage"]) < 0.5:
            continue
        if best_score is None or float(result["score"]) > best_score:
            best_key = key
            best_score = float(result["score"])
    current_template = POSITION_TEMPLATES.get(current)
    current_score = float(score_attributes(readings, current_template, names)["score"]) if current_template else None
    hint: dict[str, object] = {"best_position": best_key, "best_score": best_score, "current_score": current_score}
    if (
        best_key is not None
        and best_score is not None
        and current_score is not None
        and best_key != current
        and best_score - current_score >= 8
    ):
        hint["better_position"] = best_key
        hint["evidence"] = f"{best_key} 模板评分 {best_score:.0f}，当前 {current} 仅 {current_score:.0f}"
    return hint


def _player_payload(instance: PlayerInstance, player: Player | None, positions: dict[str, object] | None) -> dict[str, object]:
    return {
        "instance_id": instance.id,
        "name": player.full_name if player else f"#{instance.player_id}",
        "position": instance.position,
        "slot": slot_of(instance.position),
        "slot_name": SLOT_NAMES_ZH.get(slot_of(instance.position) or ""),
        "position_group": position_group(instance.position),
        "positions": positions or {},
    }


def _change_label(previous: PlayerSnapshot, current: PlayerSnapshot) -> str:
    if previous.ca is not None and current.ca is not None and current.ca > previous.ca:
        return "能力提升"
    if previous.ca is not None and current.ca is not None and current.ca < previous.ca:
        return "能力下降"
    if previous.market_value is not None and current.market_value is not None and current.market_value != previous.market_value:
        return "身价变化"
    if previous.minutes_played is not None and current.minutes_played is not None and current.minutes_played > previous.minutes_played:
        return "比赛经验增加"
    return "无显著变化"


def _classify(overall: float | None) -> str:
    if overall is None:
        return "unknown"
    if overall >= 1.0:
        return "fast"
    if overall >= 0.3:
        return "steady"
    if overall > -0.3:
        return "flat"
    return "declining"


def _stagnant(points: list[dict[str, object]]) -> bool:
    ca_values = [point["ca"] for point in points if point["ca"] is not None]
    if len(ca_values) < 3:
        return False
    months = _months_between(str(points[0]["date"]), str(points[-1]["date"]))
    return len(set(ca_values[-3:])) == 1 and months is not None and months >= 8


def _goal_contributions(snapshot: PlayerSnapshot) -> int | None:
    goals = snapshot.goals
    assists = snapshot.assists
    if goals is None and assists is None:
        return None
    return (goals or 0) + (assists or 0)


def _months_between(start: str, end: str) -> int | None:
    try:
        start_date = date.fromisoformat(start[:10])
        end_date = date.fromisoformat(end[:10])
    except ValueError:
        return None
    return (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month)


def _delta(before: object, after: object) -> int | None:
    if before is None or after is None:
        return None
    return int(after) - int(before)  # type: ignore[call-overload]
