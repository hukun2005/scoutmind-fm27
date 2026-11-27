"""Squad Intelligence: position depth, the six-component squad score and planning signals.

The module answers the questions the squad screen is built on: where the squad is thin, which positions need
reinforcing, who is declining, who can be sold, which academy players are ready, and who replaces a key player.

Every component of the squad score is normalised to 0-100 and returns its own evidence list. A component whose inputs
the save does not contain is reported as unavailable and its weight is redistributed, so a squad is never scored on
data that does not exist. ``SquadScore = 0.25C + 0.20D + 0.15A + 0.15T + 0.15W + 0.10P`` is the baseline formula;
``tactical_profiles`` stores user-adjustable variants and one request may override the weights explicitly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..clubs import ClubResolver
from ..ingestion.attributes import (
    SLOT_IMPORTANCE,
    SLOT_NAMES_ZH,
    SLOT_REQUIREMENT,
    SQUAD_SLOTS,
    position_group,
    slot_of,
)
from ..models import (
    Club,
    PlayerAttribute,
    PlayerAttributeValue,
    PlayerInstance,
    PlayerSnapshot,
    SquadAssignment,
    TacticalProfile,
)
from ..utils import iso, utcnow
from .players import latest_snapshot_subquery
from .scoring import attribute_names, best_role_score

ALGORITHM_VERSION = "squad-score-1"

#: The product baseline: ``SquadScore = 0.25C + 0.20D + 0.15A + 0.15T + 0.15W + 0.10P``.
DEFAULT_WEIGHTS: dict[str, float] = {
    "coverage": 0.25,
    "depth": 0.20,
    "age": 0.15,
    "fit": 0.15,
    "wage": 0.15,
    "potential": 0.10,
}

COMPONENT_LABELS: dict[str, str] = {
    "coverage": "位置覆盖（C）",
    "depth": "阵容深度（D）",
    "age": "年龄结构（A）",
    "fit": "战术适配（T）",
    "wage": "工资结构（W）",
    "potential": "潜力储备（P）",
}

PROFILE_PRESETS: tuple[dict[str, object], ...] = (
    {
        "key": "balanced",
        "name": "均衡评估",
        "description": "产品基线权重：覆盖与深度优先，六个维度全部参与。",
        "weights": DEFAULT_WEIGHTS,
        "is_default": True,
    },
    {
        "key": "contender",
        "name": "争冠阵容",
        "description": "即战力优先：位置覆盖、深度与战术适配权重更高。",
        "weights": {"coverage": 0.30, "depth": 0.25, "age": 0.10, "fit": 0.20, "wage": 0.10, "potential": 0.05},
        "is_default": False,
    },
    {
        "key": "rebuild",
        "name": "重建期",
        "description": "换血优先：潜力储备与年龄结构权重更高，容忍即战力缺口。",
        "weights": {"coverage": 0.15, "depth": 0.15, "age": 0.20, "fit": 0.10, "wage": 0.10, "potential": 0.30},
        "is_default": False,
    },
    {
        "key": "survival",
        "name": "保级/升班",
        "description": "先堵漏洞：覆盖与深度合计 65%，潜力只作参考。",
        "weights": {"coverage": 0.35, "depth": 0.30, "age": 0.10, "fit": 0.15, "wage": 0.05, "potential": 0.05},
        "is_default": False,
    },
    {
        "key": "youth",
        "name": "青训建队",
        "description": "长期资产优先：潜力储备与年龄结构合计 55%。",
        "weights": {"coverage": 0.15, "depth": 0.15, "age": 0.25, "fit": 0.10, "wage": 0.05, "potential": 0.30},
        "is_default": False,
    },
)

AGE_BUCKETS: tuple[tuple[str, int, int], ...] = (
    ("17-20", 17, 20),
    ("21-24", 21, 24),
    ("25-28", 25, 28),
    ("29-31", 29, 31),
    ("32+", 32, 99),
)

#: Share of a healthy squad the baseline expects inside each age bucket.
IDEAL_AGE_SHARE: dict[str, float] = {"17-20": 0.22, "21-24": 0.30, "25-28": 0.28, "29-31": 0.15, "32+": 0.05}

#: Ability window inside which a backup still counts as first-team quality.
DEPTH_QUALITY_WINDOW = 30.0


@dataclass
class RosterPlayer:
    """One squad member flattened from its newest snapshot, with the attributes used by fit scoring."""

    instance_id: int
    name: str
    position: str | None
    slot: str | None
    position_group: str | None
    age: int | None
    ca: int | None
    pa: int | None
    market_value: int | None
    wage: int | None
    contract_end: date | None
    minutes_played: int | None
    appearances: int | None
    attributes: dict[str, float] = field(default_factory=dict)
    fit: dict[str, object] | None = None

    def payload(self) -> dict[str, object]:
        """Row shown in depth and succession tables."""
        return {
            "instance_id": self.instance_id,
            "name": self.name,
            "position": self.position,
            "slot": self.slot,
            "position_group": self.position_group,
            "age": self.age,
            "ca": self.ca,
            "pa": self.pa,
            "market_value": self.market_value,
            "wage": self.wage,
            "contract_end": self.contract_end.isoformat() if self.contract_end else None,
            "minutes_played": self.minutes_played,
            "appearances": self.appearances,
            "fit_score": self.fit["score"] if self.fit else None,
            "fit_role": self.fit["role_name"] if self.fit else None,
        }


# -- weight profiles --------------------------------------------------------------------------------------------


def ensure_profiles(session: Session, save_id: int) -> list[TacticalProfile]:
    """Seed the preset weight profiles of one save; existing rows are never rewritten."""
    existing = {
        row.key: row for row in session.scalars(select(TacticalProfile).where(TacticalProfile.fm_save_id == save_id))
    }
    created = False
    for preset in PROFILE_PRESETS:
        key = str(preset["key"])
        if key in existing:
            continue
        weights = preset["weights"]
        assert isinstance(weights, dict)
        existing[key] = TacticalProfile(
            fm_save_id=save_id,
            key=key,
            name=str(preset["name"]),
            description=str(preset["description"]),
            weight_coverage=float(weights["coverage"]),
            weight_depth=float(weights["depth"]),
            weight_age=float(weights["age"]),
            weight_fit=float(weights["fit"]),
            weight_wage=float(weights["wage"]),
            weight_potential=float(weights["potential"]),
            is_default=bool(preset["is_default"]),
        )
        session.add(existing[key])
        created = True
    if created:
        session.flush()
    return [existing[key] for key in sorted(existing)]


def weights_of(row: TacticalProfile) -> dict[str, float]:
    """Weights of a stored profile, normalised to sum to one."""
    return normalise_weights(
        {
            "coverage": row.weight_coverage,
            "depth": row.weight_depth,
            "age": row.weight_age,
            "fit": row.weight_fit,
            "wage": row.weight_wage,
            "potential": row.weight_potential,
        }
    )


def normalise_weights(raw: dict[str, float]) -> dict[str, float]:
    """Clamp negative weights to zero and rescale so the six components sum to exactly one."""
    cleaned = {key: max(0.0, float(value)) for key, value in raw.items() if key in DEFAULT_WEIGHTS}
    for key in DEFAULT_WEIGHTS:
        cleaned.setdefault(key, 0.0)
    total = sum(cleaned.values())
    if total <= 0:
        return dict(DEFAULT_WEIGHTS)
    scaled = {key: round(value / total, 4) for key, value in cleaned.items()}
    # Rounding to four decimals leaves a residual; move it onto the largest weight so the sum stays exact.
    residual = round(1.0 - sum(scaled.values()), 4)
    if residual:
        largest = max(scaled, key=lambda key: scaled[key])
        scaled[largest] = round(scaled[largest] + residual, 4)
    return scaled


def profile_payload(row: TacticalProfile) -> dict[str, object]:
    """Serialise one stored profile, including its normalised weights."""
    return {
        "key": row.key,
        "name": row.name,
        "description": row.description,
        "is_default": row.is_default,
        "weights": weights_of(row),
    }


def resolve_weights(
    session: Session,
    save_id: int,
    profile_key: str | None = None,
    overrides: dict[str, float] | None = None,
) -> tuple[dict[str, float], dict[str, object]]:
    """Pick the weights for one request: explicit overrides, else a named profile, else the save default."""
    profiles = ensure_profiles(session, save_id)
    by_key = {row.key: row for row in profiles}
    chosen = by_key.get(profile_key) if profile_key else None
    if chosen is None:
        chosen = next((row for row in profiles if row.is_default), profiles[0] if profiles else None)
    weights = weights_of(chosen) if chosen is not None else dict(DEFAULT_WEIGHTS)
    if overrides:
        weights = normalise_weights({**weights, **overrides})
    payload: dict[str, object] = (
        profile_payload(chosen) if chosen is not None else {"key": "custom", "name": "自定义权重"}
    )
    payload["weights"] = weights
    payload["overridden"] = bool(overrides)
    return weights, payload


# -- roster -----------------------------------------------------------------------------------------------------


def user_club(session: Session, save_id: int) -> Club | None:
    """The club the operator manages inside one save.

    ``fm_saves.user_club_id`` is the single source of truth (set by the operator or by a payload that declares it);
    ``clubs.is_user_club`` remains as a derived flag for older data.
    """
    return ClubResolver(session, save_id).user_club()


def roster(session: Session, save_id: int, club_id: int | None = None) -> list[RosterPlayer]:
    """Squad members of the managed club from their newest snapshot, best ability first."""
    club = session.get(Club, club_id) if club_id is not None else user_club(session, save_id)
    if club is None:
        return []
    base = latest_snapshot_subquery()
    rows = session.execute(select(base).where(base.c.fm_save_id == save_id, base.c.club_id == club.id)).all()
    readings = _attributes_by_snapshot(session, [int(row.snapshot_id) for row in rows if row.snapshot_id])
    names = attribute_names(session)
    players: list[RosterPlayer] = []
    for row in rows:
        player = RosterPlayer(
            instance_id=int(row.instance_id),
            name=str(row.full_name),
            position=row.position,
            slot=slot_of(row.position),
            position_group=position_group(row.position),
            age=row.age,
            ca=row.ca,
            pa=row.pa,
            market_value=row.market_value,
            wage=row.wage,
            contract_end=row.contract_end,
            minutes_played=row.minutes_played,
            appearances=row.appearances,
            attributes=readings.get(int(row.snapshot_id), {}) if row.snapshot_id else {},
        )
        if player.attributes:
            player.fit = best_role_score(session, player.instance_id, player.attributes, names, player.position_group)
        players.append(player)
    players.sort(key=lambda item: (item.ca is None, -(item.ca or 0)))
    return players


# -- public sections ---------------------------------------------------------------------------------------------


def squad_overview(
    session: Session,
    save_id: int,
    profile_key: str | None = None,
    overrides: dict[str, float] | None = None,
    club_id: int | None = None,
) -> dict[str, object]:
    """Everything the squad screen shows: components, weighted score, depth, age, wage, contracts and planning.

    V3.3.2：整份统计按 ``(save_id, data_revision, profile, overrides, club_id)`` 缓存 60 秒；
    导入或战术模板变化会改变数据版本，立即失效。
    """
    from ..services import query_cache

    params = {"profile": profile_key, "overrides": overrides or {}, "club": club_id}
    return query_cache.cached(
        session,
        save_id,
        "squad_overview",
        params,
        lambda: _squad_overview(session, save_id, profile_key, overrides, club_id),
    )


def _squad_overview(
    session: Session,
    save_id: int,
    profile_key: str | None = None,
    overrides: dict[str, float] | None = None,
    club_id: int | None = None,
) -> dict[str, object]:
    club = session.get(Club, club_id) if club_id is not None else user_club(session, save_id)
    if club is None:
        return {
            "save_id": save_id,
            "club": None,
            "squad_size": 0,
            "score": None,
            "profile": {"key": "balanced", "name": "均衡评估", "weights": dict(DEFAULT_WEIGHTS), "overridden": False},
            "components": [],
            "depth": [],
            "age_structure": {"average_age": None, "median_age": None, "buckets": [], "missing": ["没有阵容数据"]},
            "wage_structure": {"total": None, "median": None, "top_earners": [], "missing": ["没有阵容数据"]},
            "contracts": {"buckets": {}, "at_risk_count": 0, "at_risk_names": [], "missing": ["没有阵容数据"]},
            "weakness": [],
            "succession": [],
            "composition": squad_composition(session, save_id, None),
            "algorithm_version": ALGORITHM_VERSION,
            "data_gaps": ["该存档没有标记为「我的俱乐部」的球队，无法分析阵容"],
            "computed_at": iso(utcnow()),
        }
    players = roster(session, save_id, club.id)
    weights, profile = resolve_weights(session, save_id, profile_key, overrides)
    depth_rows = position_depth(players)
    components = [
        _coverage_component(depth_rows),
        _depth_component(depth_rows),
        _age_component(players),
        _fit_component(players),
        _wage_component(players),
        _potential_component(players),
    ]
    for component in components:
        component["weight"] = weights[str(component["key"])]
    available = [item for item in components if item["value"] is not None]
    weight_sum = sum(float(item["weight"]) for item in available)
    score = (
        round(sum(float(item["value"]) * float(item["weight"]) for item in available) / weight_sum, 2)
        if weight_sum > 0
        else None
    )
    gaps: list[str] = []
    if not players:
        gaps.append("阵容为空：该俱乐部没有任何球员快照")
    for component in components:
        if component["value"] is None:
            gaps.extend(str(item) for item in component["missing"])
    return {
        "save_id": save_id,
        "club": {"id": club.id, "name": club.name, "league": club.league, "nation": club.nation},
        "squad_size": len(players),
        "score": score,
        "profile": profile,
        "components": components,
        "depth": depth_rows,
        "age_structure": age_structure(players),
        "wage_structure": wage_structure(players),
        "contracts": contract_monitoring(players, _reference_date(session, save_id)),
        "weakness": squad_weakness(depth_rows),
        "succession": succession_plan(players),
        "composition": squad_composition(session, save_id, club),
        "algorithm_version": ALGORITHM_VERSION,
        "data_gaps": gaps,
        "computed_at": iso(utcnow()),
    }


# -- composition ------------------------------------------------------------------------------------------------


def squad_composition(session: Session, save_id: int, club: Club | None) -> dict[str, object]:
    """Squad composition from imported assignments: senior / reserve / youth / loaned out / loaned in / unknown.

    The source of truth is ``squad_assignments`` (CSV or manual). When nothing was imported the answer is
    "unavailable", not "everyone is senior": FMSuperScout does not report squad tiers (see the field coverage report).
    """
    if club is None:
        return {
            "available": False,
            "source": None,
            "buckets": {},
            "counts": {},
            "missing": ["没有本队，无法统计阵容构成"],
        }
    rows = list(
        session.scalars(
            select(SquadAssignment)
            .where(SquadAssignment.fm_save_id == save_id)
            .order_by(SquadAssignment.observed_at)
        )
    )
    if not rows:
        return {
            "available": False,
            "source": None,
            "buckets": {},
            "counts": {},
            "missing": [
                "没有导入阵容名单：数据源不提供一线队/预备队/青年队与租借状态，"
                "请导入阵容 CSV 或手动指定",
            ],
        }
    latest: dict[int, SquadAssignment] = {}
    for row in rows:
        latest[row.player_instance_id] = row  # 后写覆盖前写：同一来源以最新观测为准
    buckets: dict[str, list[dict[str, object]]] = {
        "senior": [],
        "reserve": [],
        "youth": [],
        "loaned_out": [],
        "loaned_in": [],
        "unknown": [],
    }
    for assignment in latest.values():
        instance = session.get(PlayerInstance, assignment.player_instance_id)
        name = instance.player.full_name if instance is not None and instance.player is not None else None
        entry = {
            "instance_id": assignment.player_instance_id,
            "name": name,
            "club": session.get(Club, assignment.club_id).name if assignment.club_id else assignment.club_name_raw,
            "squad_type": assignment.squad_type,
            "loan_status": assignment.loan_status,
            "confidence": assignment.confidence,
            "source": assignment.source,
        }
        if assignment.loan_status == "loaned_out":
            buckets["loaned_out"].append(entry)
        elif assignment.loan_status == "loaned_in":
            buckets["loaned_in"].append(entry)
        elif assignment.squad_type in ("senior", "reserve", "youth"):
            buckets[assignment.squad_type].append(entry)
        else:
            buckets["unknown"].append(entry)
    counts = {key: len(value) for key, value in buckets.items()}
    gaps: list[str] = []
    if counts["unknown"]:
        gaps.append(f"{counts['unknown']} 名球员的阵容类别无法确认（显示为未知，不按自由球员处理）")
    unassigned = session.scalar(
        select(func.count())
        .select_from(PlayerSnapshot)
        .join(PlayerInstance, PlayerInstance.id == PlayerSnapshot.player_instance_id)
        .where(PlayerInstance.fm_save_id == save_id, PlayerSnapshot.club_id == club.id)
    )
    assigned_ids = set(latest)
    covered = sum(1 for item in buckets.values() for entry in item if entry["instance_id"] in assigned_ids)
    missing_on_squad = max(0, int(unassigned or 0) - covered)
    if missing_on_squad:
        gaps.append(f"本队 {missing_on_squad} 名球员不在阵容名单里，梯队归属未知")
    return {
        "available": True,
        "source": latest[next(iter(latest))].source if latest else None,
        "buckets": buckets,
        "counts": counts,
        "gaps": gaps,
    }


def position_depth(players: list[RosterPlayer]) -> list[dict[str, object]]:
    """Depth table: how many players each slot has, how good the backup is, and what to do about it."""
    by_slot: dict[str, list[RosterPlayer]] = {slot: [] for slot in SQUAD_SLOTS}
    unknown: list[RosterPlayer] = []
    for player in players:
        if player.slot is None:
            unknown.append(player)
            continue
        by_slot[player.slot].append(player)
    rows: list[dict[str, object]] = []
    for slot in SQUAD_SLOTS:
        members = sorted(by_slot[slot], key=lambda item: (item.ca is None, -(item.ca or 0)))
        required = SLOT_REQUIREMENT[slot]
        count = len(members)
        depth = _depth_quality(members)
        status, suggestion = _slot_verdict(slot, count, depth, required)
        rows.append(
            {
                "slot": slot,
                "slot_name": SLOT_NAMES_ZH[slot],
                "count": count,
                "required": required,
                "importance": SLOT_IMPORTANCE[slot],
                "coverage": round(min(count / required, 1.0), 4),
                "depth_quality": round(depth, 4),
                "status": status,
                "suggestion": suggestion,
                "players": [player.payload() for player in members],
            }
        )
    if unknown:
        rows.append(
            {
                "slot": "UNKNOWN",
                "slot_name": "位置未知",
                "count": len(unknown),
                "required": 0,
                "importance": 0.0,
                "coverage": 0.0,
                "depth_quality": 0.0,
                "status": "未知",
                "suggestion": "数据源未提供可用位置代码，无法纳入位置深度分析",
                "players": [player.payload() for player in unknown],
            }
        )
    return rows


def age_structure(players: list[RosterPlayer]) -> dict[str, object]:
    """Age distribution with average and median age, plus the players inside each bucket."""
    ages = [player.age for player in players if player.age is not None]
    shares = _age_shares(ages) if ages else {bucket: 0.0 for bucket, *_ in AGE_BUCKETS}
    buckets = []
    for bucket, low, high in AGE_BUCKETS:
        members = [player for player in players if player.age is not None and low <= player.age <= high]
        buckets.append(
            {
                "bucket": bucket,
                "count": len(members),
                "share": round(shares[bucket], 4),
                "ideal_share": IDEAL_AGE_SHARE[bucket],
                "players": [player.name for player in members],
            }
        )
    return {
        "average_age": round(sum(ages) / len(ages), 1) if ages else None,
        "median_age": _median([float(age) for age in ages]) if ages else None,
        "buckets": buckets,
        "missing": [] if ages else ["缺少年龄数据"],
    }


def wage_structure(players: list[RosterPlayer]) -> dict[str, object]:
    """Wage totals, concentration and the highest earners with their minutes."""
    paid = [player for player in players if player.wage is not None]
    if not paid:
        return {
            "total": None,
            "median": None,
            "max": None,
            "top3_share": None,
            "earners": 0,
            "top_earners": [],
            "missing": ["缺少工资数据"],
        }
    wages = sorted((float(player.wage or 0) for player in paid), reverse=True)
    total = sum(wages)
    return {
        "total": int(total),
        "median": _median(wages),
        "max": int(wages[0]),
        "top3_share": round(sum(wages[:3]) / total, 4) if total else None,
        "earners": len(paid),
        "missing_players": len(players) - len(paid),
        "top_earners": [
            {
                "instance_id": player.instance_id,
                "name": player.name,
                "wage": player.wage,
                "minutes_played": player.minutes_played,
                "age": player.age,
                "ca": player.ca,
            }
            for player in sorted(paid, key=lambda item: -(item.wage or 0))[:8]
        ],
        "missing": [],
    }


def contract_monitoring(players: list[RosterPlayer], today: date) -> dict[str, object]:
    """Contract expiry buckets so an expiring squad can be planned before it leaves for free."""
    buckets: dict[str, list[dict[str, object]]] = {
        "expired": [],
        "6m": [],
        "12m": [],
        "24m": [],
        "later": [],
        "unknown": [],
    }
    for player in players:
        entry = {
            "instance_id": player.instance_id,
            "name": player.name,
            "contract_end": player.contract_end.isoformat() if player.contract_end else None,
            "age": player.age,
            "ca": player.ca,
            "pa": player.pa,
            "wage": player.wage,
            "market_value": player.market_value,
        }
        if player.contract_end is None:
            buckets["unknown"].append(entry)
            continue
        months = _months_between(today, player.contract_end)
        if months < 0:
            buckets["expired"].append(entry)
        elif months <= 6:
            buckets["6m"].append(entry)
        elif months <= 12:
            buckets["12m"].append(entry)
        elif months <= 24:
            buckets["24m"].append(entry)
        else:
            buckets["later"].append(entry)
    at_risk = buckets["expired"] + buckets["6m"]
    return {
        "today": today.isoformat(),
        "buckets": buckets,
        "at_risk_count": len(at_risk),
        "at_risk_names": [str(entry["name"]) for entry in at_risk],
        "missing": [f"{len(buckets['unknown'])} 名球员缺少合同到期日"] if buckets["unknown"] else [],
    }


def squad_weakness(depth_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Slots ranked from weakest to strongest, each with the evidence and a concrete recommendation."""
    candidates: list[dict[str, object]] = []
    for row in depth_rows:
        if row["slot"] not in SQUAD_SLOTS:
            continue
        score = (float(row["coverage"]) * 0.6 + float(row["depth_quality"]) * 0.4) * float(row["importance"])
        candidates.append(
            {
                "slot": row["slot"],
                "slot_name": row["slot_name"],
                "severity": round((1 - score) * 100, 1),
                "count": row["count"],
                "required": row["required"],
                "status": row["status"],
                "suggestion": row["suggestion"],
                "evidence": [
                    f"该位置 {row['count']} 人，最低要求 {row['required']} 人",
                    f"覆盖率 {float(row['coverage']) * 100:.0f}%，替补质量 {float(row['depth_quality']) * 100:.0f}%",
                ],
            }
        )
    candidates.sort(key=lambda item: -float(item["severity"]))
    return candidates[:4]


def succession_plan(players: list[RosterPlayer]) -> list[dict[str, object]]:
    """For each ageing key player, name the internal successor or the external profile to search for."""
    ranked = [player for player in players if player.ca is not None]
    key_players = [player for player in ranked if (player.age or 0) >= 29][:6]
    plan: list[dict[str, object]] = []
    for player in key_players:
        successors = [
            candidate
            for candidate in players
            if candidate.slot == player.slot
            and candidate.instance_id != player.instance_id
            and (candidate.age or 99) <= (player.age or 99) - 3
        ]
        successors.sort(key=lambda item: -(item.pa or item.ca or 0))
        ready = [
            candidate
            for candidate in successors
            if (candidate.ca or 0) >= (player.ca or 0) - 15 or (candidate.pa or 0) >= (player.ca or 0)
        ]
        plan.append(
            {
                "player": player.payload(),
                "internal_options": [candidate.payload() for candidate in successors[:3]],
                "ready_now": [candidate.payload() for candidate in ready[:2]],
                "external_profile": _external_profile(player),
                "verdict": "内部有可用接班" if ready else ("内部有培养对象" if successors else "内部无同位置年轻球员"),
                "evidence": [
                    f"{player.name} 现年 {player.age} 岁，CA {player.ca}",
                    f"同位置年轻 {len(successors)} 人，其中 {len(ready)} 人能力或潜力已接近主力水平",
                ],
            }
        )
    return plan


# -- components -------------------------------------------------------------------------------------------------


def _coverage_component(depth_rows: list[dict[str, object]]) -> dict[str, object]:
    slots = [row for row in depth_rows if row["slot"] in SQUAD_SLOTS]
    total_importance = sum(SLOT_IMPORTANCE[str(row["slot"])] for row in slots) or 1.0
    value = sum(float(row["coverage"]) * SLOT_IMPORTANCE[str(row["slot"])] for row in slots) / total_importance
    missing = [str(row["slot_name"]) for row in slots if int(row["count"]) == 0]
    return {
        "key": "coverage",
        "label": COMPONENT_LABELS["coverage"],
        "value": round(value * 100, 2),
        "evidence": [
            f"{len(slots) - len(missing)}/{len(slots)} 个位置有人可用",
            f"按位置重要性加权后覆盖率 {value * 100:.0f}%",
        ],
        "missing": [f"{name} 无人可用" for name in missing],
        "available": True,
    }


def _depth_component(depth_rows: list[dict[str, object]]) -> dict[str, object]:
    slots = [row for row in depth_rows if row["slot"] in SQUAD_SLOTS]
    total_importance = sum(SLOT_IMPORTANCE[str(row["slot"])] for row in slots) or 1.0
    value = sum(float(row["depth_quality"]) * SLOT_IMPORTANCE[str(row["slot"])] for row in slots) / total_importance
    thin = [str(row["slot_name"]) for row in slots if int(row["count"]) < int(row["required"])]
    return {
        "key": "depth",
        "label": COMPONENT_LABELS["depth"],
        "value": round(value * 100, 2),
        "evidence": [
            f"{len(slots) - len(thin)}/{len(slots)} 个位置达到最低人数要求",
            "每个位置用第二人选与首选的差距衡量替补质量",
        ],
        "missing": [f"{name} 人数低于要求" for name in thin],
        "available": True,
    }


def _age_component(players: list[RosterPlayer]) -> dict[str, object]:
    ages = [player.age for player in players if player.age is not None]
    if not ages:
        return {
            "key": "age",
            "label": COMPONENT_LABELS["age"],
            "value": None,
            "evidence": [],
            "missing": ["存档缺少球员年龄/出生日期，无法评估年龄结构"],
            "available": False,
        }
    shares = _age_shares(ages)
    distance = 0.5 * sum(abs(shares[bucket] - IDEAL_AGE_SHARE[bucket]) for bucket, *_ in AGE_BUCKETS)
    value = max(0.0, 1.0 - distance)
    return {
        "key": "age",
        "label": COMPONENT_LABELS["age"],
        "value": round(value * 100, 2),
        "evidence": [
            f"平均年龄 {sum(ages) / len(ages):.1f} 岁（样本 {len(ages)}）",
            "实际分布 " + "、".join(f"{bucket} {shares[bucket]:.0%}" for bucket, *_ in AGE_BUCKETS),
        ],
        "missing": [],
        "available": True,
    }


def _fit_component(players: list[RosterPlayer]) -> dict[str, object]:
    scored = [player for player in players if player.fit is not None]
    if not scored:
        return {
            "key": "fit",
            "label": COMPONENT_LABELS["fit"],
            "value": None,
            "evidence": [],
            "missing": ["属性覆盖率不足，无法计算战术适配"],
            "available": False,
        }
    values = [float(player.fit["score"]) for player in scored if player.fit is not None]
    value = sum(values) / len(values)
    return {
        "key": "fit",
        "label": COMPONENT_LABELS["fit"],
        "value": round(value, 2),
        "evidence": [
            f"{len(scored)}/{len(players)} 名球员可计算角色评分",
            f"全队最佳角色评分均值 {value:.0f}",
        ],
        "missing": [f"{len(players) - len(scored)} 名球员属性不足，未参与适配评估"]
        if len(scored) < len(players)
        else [],
        "available": True,
    }


def _wage_component(players: list[RosterPlayer]) -> dict[str, object]:
    wages = sorted((player.wage for player in players if player.wage is not None), reverse=True)
    if not wages:
        return {
            "key": "wage",
            "label": COMPONENT_LABELS["wage"],
            "value": None,
            "evidence": [],
            "missing": ["存档缺少工资字段，无法评估工资结构"],
            "available": False,
        }
    total = float(sum(wages))
    top3_share = sum(float(value) for value in wages[:3]) / total if total else 0.0
    median_wage = _median([float(value) for value in wages])
    evidence = [f"工资总额 {int(total)}，前 3 名占 {top3_share:.0%}"]
    penalties = 0.0
    if top3_share > 0.45:
        penalties += (top3_share - 0.45) * 220
        evidence.append("工资高度集中在少数球员，阵容调整空间受限")
    minutes = [float(player.minutes_played) for player in players if player.minutes_played is not None]
    if minutes:
        median_minutes = _median(minutes)
        idle = [
            player
            for player in players
            if player.wage is not None
            and player.minutes_played is not None
            and float(player.wage) > median_wage
            and float(player.minutes_played) < median_minutes
        ]
        if idle:
            penalties += min(30.0, len(idle) / len(players) * 120)
            evidence.append(f"{len(idle)} 名球员工资高于中位数但出场时间低于中位数")
    return {
        "key": "wage",
        "label": COMPONENT_LABELS["wage"],
        "value": round(max(0.0, 100.0 - penalties), 2),
        "evidence": evidence,
        "missing": [],
        "available": True,
    }


def _potential_component(players: list[RosterPlayer]) -> dict[str, object]:
    young = [player for player in players if player.age is not None and player.age <= 23 and player.pa is not None]
    if not young:
        return {
            "key": "potential",
            "label": COMPONENT_LABELS["potential"],
            "value": None,
            "evidence": [],
            "missing": ["没有可评估的 U23 潜力数据（需要年龄与 PA）"],
            "available": False,
        }
    headroom = [float((player.pa or 0) - (player.ca or 0)) for player in young if player.ca is not None]
    mean_headroom = sum(headroom) / len(headroom) if headroom else 0.0
    expected = max(3.0, 0.25 * len(players))
    share = min(1.0, len(young) / expected)
    room = min(1.0, mean_headroom / 25.0)
    value = (0.5 * share + 0.5 * room) * 100
    return {
        "key": "potential",
        "label": COMPONENT_LABELS["potential"],
        "value": round(value, 2),
        "evidence": [
            f"U23 球员 {len(young)} 人（基线期望 {expected:.0f} 人）",
            f"其中可计算 PA−CA 空间的 {len(headroom)} 人，平均空间 {mean_headroom:.1f}",
        ],
        "missing": [],
        "available": True,
    }


# -- helpers ----------------------------------------------------------------------------------------------------


def _depth_quality(members: list[RosterPlayer]) -> float:
    """0-1 quality of a slot's backup: full marks when the second choice is close to the first."""
    if not members:
        return 0.0
    if len(members) == 1:
        return 0.4
    best = members[0].ca
    second = members[1].ca
    if best is None or second is None:
        return 0.5
    ratio = max(0.0, min(1.0, (float(second) - (float(best) - DEPTH_QUALITY_WINDOW)) / DEPTH_QUALITY_WINDOW))
    return 0.4 + 0.6 * ratio


def _slot_verdict(slot: str, count: int, depth: float, required: int) -> tuple[str, str]:
    """Status label and the action the squad screen shows for one slot."""
    name = SLOT_NAMES_ZH[slot]
    if count == 0:
        return "空缺", f"立即引援：{name}无人可用"
    if count < required:
        return ("危险" if count * 2 <= required else "一般"), f"优先引援：需要至少 {required - count} 名{name}"
    if depth < 0.5:
        return "一般", f"寻找替补：{name}替补与主力差距过大"
    if count > required + 2:
        return "拥挤", f"考虑出售或外租：{name}人员过剩"
    return "良好", f"暂无补强需求：{name}人数与质量达标"


def _external_profile(player: RosterPlayer) -> dict[str, object]:
    """Search profile for an external replacement, derived from the outgoing player's strongest attributes."""
    top = sorted(player.attributes.items(), key=lambda item: -item[1])[:4] if player.attributes else []
    return {
        "slot": player.slot,
        "slot_name": SLOT_NAMES_ZH.get(player.slot or ""),
        "age_max": max((player.age or 30) - 6, 18),
        "ca_floor": max((player.ca or 100) - 15, 60),
        "pa_floor": player.ca,
        "key_attributes": [{"key": key, "value": value} for key, value in top],
        "note": "按接班人条件在 Recruitment Engine 中检索；属性权重来自离队球员的强项，不是官方评分公式",
    }


def _age_shares(ages: list[int]) -> dict[str, float]:
    total = len(ages) or 1
    return {
        bucket: sum(1 for age in ages if low <= age <= high) / total for bucket, low, high in AGE_BUCKETS
    }


def _months_between(today: date, target: date) -> int:
    return (target.year - today.year) * 12 + (target.month - today.month)


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (float(ordered[middle - 1]) + float(ordered[middle])) / 2


def _reference_date(session: Session, save_id: int) -> date:
    """Reference date for contract buckets: the newest game date of the save, else today."""
    newest = session.scalar(
        select(func.max(PlayerSnapshot.game_date))
        .join(PlayerInstance, PlayerInstance.id == PlayerSnapshot.player_instance_id)
        .where(PlayerInstance.fm_save_id == save_id, PlayerSnapshot.game_date.is_not(None))
    )
    return newest or date.today()


def _attributes_by_snapshot(session: Session, snapshot_ids: list[int]) -> dict[int, dict[str, float]]:
    if not snapshot_ids:
        return {}
    rows = session.execute(
        select(PlayerAttributeValue.player_snapshot_id, PlayerAttribute.key, PlayerAttributeValue.value)
        .join(PlayerAttribute, PlayerAttribute.id == PlayerAttributeValue.attribute_id)
        .where(PlayerAttributeValue.player_snapshot_id.in_(snapshot_ids))
    ).all()
    result: dict[int, dict[str, float]] = {}
    for snapshot_id, key, value in rows:
        result.setdefault(int(snapshot_id), {})[str(key)] = float(value)
    return result


def squad_json(payload: dict[str, object]) -> str:
    """Canonical JSON used when a squad result is stored inside a report row."""
    return json.dumps(payload, ensure_ascii=False, default=str)
