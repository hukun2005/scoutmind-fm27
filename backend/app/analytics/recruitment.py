"""Recruitment Engine: position-aware player scoring, hidden-value discovery and shortlists.

The engine answers "who fits this squad, this budget and this plan", not "who has the highest ability". It has three
layers:

1. **Position attribute templates** turn one attribute reading into a 0-100 score for a concrete position. The
   weights are an explicit starting model to be calibrated against real save data, not an official in-game formula.
2. **Six-dimensional player score** ``PlayerScore = w1·A + w2·P + w3·T + w4·F + w5·V + w6·R`` (current ability,
   potential, tactical fit, form, value, development room) with per-position weights. A dimension the save cannot
   support is reported unavailable and its weight is redistributed, so a missing expected-goals column can never
   silently become a zero.
3. **Hidden-value rules** search the market for cheap upside and say explicitly which rules could not be evaluated
   because the data source does not expose the needed field.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ingestion.attributes import SLOT_NAMES_ZH, slot_of
from ..models import (
    Club,
    PlayerAttribute,
    PlayerAttributeValue,
    PlayerInstance,
    PlayerStatistic,
    RecruitmentShortlist,
    RecruitmentShortlistItem,
    Transfer,
)
from ..utils import iso, utcnow
from .players import latest_snapshot_subquery
from .scoring import score_attributes

ALGORITHM_VERSION = "player-score-1"

#: Position attribute templates. Every template sums to 1.0; missing attributes shrink coverage instead of scoring 0.
POSITION_TEMPLATES: dict[str, dict[str, float]] = {
    "ST": {
        "finishing": 0.20,
        "off_the_ball": 0.15,
        "pace": 0.15,
        "anticipation": 0.10,
        "dribbling": 0.10,
        "first_touch": 0.10,
        "strength": 0.10,
        "decisions": 0.10,
    },
    "AMC": {
        "vision": 0.18,
        "passing": 0.16,
        "technique": 0.15,
        "dribbling": 0.13,
        "decisions": 0.12,
        "first_touch": 0.10,
        "off_the_ball": 0.09,
        "long_shots": 0.07,
    },
    "AML": {
        "dribbling": 0.18,
        "acceleration": 0.15,
        "pace": 0.15,
        "crossing": 0.12,
        "technique": 0.10,
        "off_the_ball": 0.10,
        "finishing": 0.10,
        "agility": 0.10,
    },
    "MC": {
        "passing": 0.18,
        "vision": 0.15,
        "technique": 0.12,
        "decisions": 0.12,
        "teamwork": 0.10,
        "stamina": 0.10,
        "first_touch": 0.09,
        "composure": 0.08,
        "off_the_ball": 0.06,
    },
    "DM": {
        "tackling": 0.18,
        "positioning": 0.15,
        "passing": 0.14,
        "anticipation": 0.12,
        "teamwork": 0.10,
        "stamina": 0.10,
        "composure": 0.09,
        "strength": 0.07,
        "marking": 0.05,
    },
    "DC": {
        "tackling": 0.16,
        "marking": 0.14,
        "positioning": 0.14,
        "heading": 0.11,
        "strength": 0.10,
        "composure": 0.10,
        "anticipation": 0.09,
        "pace": 0.08,
        "jumping": 0.08,
    },
    "DL": {
        "crossing": 0.15,
        "stamina": 0.14,
        "pace": 0.13,
        "tackling": 0.12,
        "positioning": 0.10,
        "teamwork": 0.10,
        "work_rate": 0.10,
        "acceleration": 0.09,
        "passing": 0.07,
    },
    "GK": {
        "reflexes": 0.18,
        "handling": 0.16,
        "one_on_ones": 0.14,
        "aerial_reach": 0.12,
        "command_of_area": 0.10,
        "communication": 0.08,
        "kicking": 0.08,
        "rushing_out": 0.07,
        "positioning": 0.07,
    },
}
POSITION_TEMPLATES["STC"] = POSITION_TEMPLATES["ST"]
POSITION_TEMPLATES["AMR"] = POSITION_TEMPLATES["AML"]
POSITION_TEMPLATES["ML"] = POSITION_TEMPLATES["AML"]
POSITION_TEMPLATES["MR"] = POSITION_TEMPLATES["AML"]
POSITION_TEMPLATES["WBL"] = POSITION_TEMPLATES["DL"]
POSITION_TEMPLATES["DR"] = POSITION_TEMPLATES["DL"]
POSITION_TEMPLATES["WBR"] = POSITION_TEMPLATES["DL"]

#: Six-dimension weights per position group; ``F`` (form) needs statistics and ``V`` (value) needs market peers.
DIMENSION_WEIGHTS: dict[str, dict[str, float]] = {
    "GK": {"ability": 0.30, "potential": 0.15, "fit": 0.20, "form": 0.15, "value": 0.15, "room": 0.05},
    "DF": {"ability": 0.28, "potential": 0.17, "fit": 0.20, "form": 0.15, "value": 0.15, "room": 0.05},
    "MF": {"ability": 0.25, "potential": 0.20, "fit": 0.20, "form": 0.15, "value": 0.15, "room": 0.05},
    "FW": {"ability": 0.26, "potential": 0.20, "fit": 0.18, "form": 0.16, "value": 0.15, "room": 0.05},
}

DIMENSION_LABELS: dict[str, str] = {
    "ability": "当前能力（A）",
    "potential": "潜力（P）",
    "fit": "战术适配（T）",
    "form": "比赛表现（F）",
    "value": "转会价值（V）",
    "room": "发展空间（R）",
}

#: Minimum peers of the same position group before a percentile can be computed.
MIN_PERCENTILE_PEERS = 5

#: Hidden-value rules and the scan field each one needs.
HIDDEN_VALUE_RULES: tuple[dict[str, object], ...] = (
    {
        "key": "contract_expiring",
        "label": "合同即将到期",
        "requires": ("contract_end",),
        "description": "12 个月内合同到期，可用较低转会费或自由身签下",
    },
    {
        "key": "transfer_listed",
        "label": "被俱乐部挂牌",
        "requires": ("transfer_listed",),
        "description": "挂牌球员通常低于市场价，但当前数据源没有该字段",
    },
    {
        "key": "bench_young_talent",
        "label": "强队缺少出场机会的年轻人",
        "requires": ("club_reputation", "minutes_played", "age"),
        "description": "高声誉俱乐部里出场时间很少的 U23 球员，估值通常被压低",
    },
    {
        "key": "lower_league_standout",
        "label": "低级别联赛突出球员",
        "requires": ("club_league", "ca"),
        "description": "联赛级别低于本队但能力已接近本队主力的球员",
    },
    {
        "key": "cheap_and_fits",
        "label": "身价低但战术契合",
        "requires": ("market_value", "attributes", "age"),
        "description": "同类球员中身价偏低、同时位置适配评分较高的球员",
    },
    {
        "key": "high_potential_low_wage",
        "label": "高潜力低工资年轻人",
        "requires": ("pa", "ca", "wage", "age"),
        "description": "潜力空间大、工资低于同龄人，长期投入产出比高",
    },
    {
        "key": "loan_possible",
        "label": "可通过租借获得",
        "requires": ("loan_status",),
        "description": "租借状态当前数据源没有该字段",
    },
)


@dataclass
class Candidate:
    """One player flattened for scoring, with the peer statistics the percentiles need."""

    instance_id: int
    player_id: int
    name: str
    age: int | None
    position: str | None
    slot: str | None
    position_group: str | None
    ca: int | None
    pa: int | None
    market_value: int | None
    wage: int | None
    contract_end: date | None
    minutes_played: int | None
    appearances: int | None
    club_id: int | None
    club_name: str | None
    club_league: str | None
    club_reputation: int | None
    attributes: dict[str, float]
    statistics: dict[str, float | None]


# -- pool -------------------------------------------------------------------------------------------------------


def candidate_pool(session: Session, save_id: int) -> list[Candidate]:
    """Every player of one save with its newest snapshot, attributes and newest season statistics."""
    base = latest_snapshot_subquery()
    club_ids = {row.id: row for row in session.scalars(select(Club).where(Club.fm_save_id == save_id))}
    rows = session.execute(select(base).where(base.c.fm_save_id == save_id)).all()
    readings = _attributes_by_snapshot(session, [int(row.snapshot_id) for row in rows if row.snapshot_id])
    stats = _statistics_by_instance(session, [int(row.instance_id) for row in rows])
    pool: list[Candidate] = []
    for row in rows:
        club = club_ids.get(row.club_id) if row.club_id else None
        pool.append(
            Candidate(
                instance_id=int(row.instance_id),
                player_id=int(row.player_id),
                name=str(row.full_name),
                age=row.age,
                position=row.position,
                slot=slot_of(row.position),
                position_group=_group_of(row.position),
                ca=row.ca,
                pa=row.pa,
                market_value=row.market_value,
                wage=row.wage,
                contract_end=row.contract_end,
                minutes_played=row.minutes_played,
                appearances=row.appearances,
                club_id=row.club_id,
                club_name=club.name if club else None,
                club_league=club.league if club else None,
                club_reputation=club.reputation if club else None,
                attributes=readings.get(int(row.snapshot_id), {}) if row.snapshot_id else {},
                statistics=stats.get(int(row.instance_id), {}),
            )
        )
    return pool


def player_score(
    session: Session,
    save_id: int,
    instance_id: int,
    pool: list[Candidate] | None = None,
) -> dict[str, object]:
    """Six-dimensional score for one player with the evidence behind every dimension."""
    pool = pool if pool is not None else candidate_pool(session, save_id)
    target = next((item for item in pool if item.instance_id == instance_id), None)
    if target is None:
        raise ValueError("player instance not found in this save")
    return _score_candidate(session, target, pool)


def compare_players(session: Session, save_id: int, instance_ids: list[int]) -> dict[str, object]:
    """Score several players with the same weights so the comparison is apples to apples."""
    pool = candidate_pool(session, save_id)
    items = [_score_candidate(session, item, pool) for item in pool if item.instance_id in set(instance_ids)]
    items.sort(key=lambda row: -(row["score"] or 0))
    shared = _shared_dimensions(items)
    return {
        "items": items,
        "compared": len(items),
        "shared_dimensions": shared,
        "algorithm_version": ALGORITHM_VERSION,
        "note": "所有球员使用同一套位置权重与同一份同位置样本，因此可以直接比较总分",
    }


def search_recruitment(
    session: Session,
    save_id: int,
    slot: str | None = None,
    min_age: int | None = None,
    max_age: int | None = None,
    max_value: int | None = None,
    max_wage: int | None = None,
    min_score: float | None = None,
    exclude_own_club: bool = True,
    limit: int = 25,
) -> dict[str, object]:
    """Rank candidates for a slot with the six-dimensional score applied inside each position group."""
    pool = candidate_pool(session, save_id)
    own_club = _own_club_id(session, save_id)
    scored: list[dict[str, object]] = []
    for item in pool:
        if slot and item.slot != slot:
            continue
        if exclude_own_club and own_club is not None and item.club_id == own_club:
            continue
        if min_age is not None and (item.age is None or item.age < min_age):
            continue
        if max_age is not None and (item.age is None or item.age > max_age):
            continue
        if max_value is not None and (item.market_value is None or item.market_value > max_value):
            continue
        if max_wage is not None and (item.wage is None or item.wage > max_wage):
            continue
        result = _score_candidate(session, item, pool)
        if min_score is not None and (result["score"] is None or float(result["score"]) < min_score):
            continue
        scored.append(result)
    scored.sort(key=lambda row: -(row["score"] or 0))
    return {
        "items": scored[:limit],
        "total": len(scored),
        "algorithm_version": ALGORITHM_VERSION,
        "criteria": {
            "slot": slot,
            "min_age": min_age,
            "max_age": max_age,
            "max_value": max_value,
            "max_wage": max_wage,
            "min_score": min_score,
            "exclude_own_club": exclude_own_club,
        },
        "data_gaps": _pool_gaps(scored),
    }


def hidden_value(
    session: Session,
    save_id: int,
    slot: str | None = None,
    limit: int = 15,
) -> dict[str, object]:
    """Run every hidden-value rule the save can support and report the rules it cannot."""
    pool = candidate_pool(session, save_id)
    own_club = _own_club_id(session, save_id)
    squad = [item for item in pool if own_club is not None and item.club_id == own_club]
    squad_ca = _median([float(item.ca) for item in squad if item.ca is not None])
    user_league_rank = _league_rank(_own_league(session, save_id))
    peers_value = _value_percentiles(pool)
    hits: list[dict[str, object]] = []
    evaluated: list[dict[str, object]] = []
    unavailable: list[dict[str, object]] = []

    for rule in HIDDEN_VALUE_RULES:
        key = str(rule["key"])
        requires = tuple(str(field) for field in rule["requires"])  # type: ignore[index]
        missing = [field for field in requires if not _field_available(field, pool)]
        if missing:
            unavailable.append(
                {
                    "key": key,
                    "label": rule["label"],
                    "missing_fields": missing,
                    "description": rule["description"],
                }
            )
            continue
        evaluated.append({"key": key, "label": rule["label"]})
        for item in pool:
            if slot and item.slot != slot:
                continue
            if own_club is not None and item.club_id == own_club:
                continue
            hit = _apply_rule(key, item, squad_ca, user_league_rank, peers_value)
            if hit is not None:
                hits.append(hit)

    hits.sort(key=lambda row: -float(row["signal"]))
    return {
        "items": hits[:limit],
        "total": len(hits),
        "rules": {
            "evaluated": evaluated,
            "unavailable": unavailable,
        },
        "method": "每条规则输出命中理由与数据依据；未提供字段的规则只列出不猜测",
        "algorithm_version": ALGORITHM_VERSION,
    }


def build_shortlist(
    session: Session,
    save_id: int,
    name: str,
    slot: str | None = None,
    role_key: str | None = None,
    budget: int | None = None,
    min_age: int | None = None,
    max_age: int | None = None,
    limit: int = 10,
    persist: bool = True,
) -> dict[str, object]:
    """Generate a shortlist: scored candidates with reasons, cost estimate and risk factors."""
    result = search_recruitment(
        session,
        save_id,
        slot=slot,
        min_age=min_age,
        max_age=max_age,
        max_value=budget,
        limit=limit,
    )
    entries: list[dict[str, object]] = []
    for index, item in enumerate(result["items"], start=1):
        entries.append(
            {
                "rank": index,
                "player": item["player"],
                "score": item["score"],
                "dimensions": item["dimensions"],
                "strengths": item["strengths"],
                "risks": item["risks"],
                "cost_estimate": item["cost_estimate"],
                "reason": _reason(item),
            }
        )
    payload: dict[str, object] = {
        "name": name,
        "slot": slot,
        "role_key": role_key,
        "budget": budget,
        "items": entries,
        "criteria": result["criteria"],
        "data_gaps": result["data_gaps"],
        "algorithm_version": ALGORITHM_VERSION,
        "generated_at": iso(utcnow()),
    }
    if persist and entries:
        shortlist = RecruitmentShortlist(
            fm_save_id=save_id,
            name=name,
            position_code=slot,
            role_key=role_key,
            budget=budget,
            criteria_json=json.dumps(
                {
                    "slot": slot,
                    "role_key": role_key,
                    "min_age": min_age,
                    "max_age": max_age,
                    "limit": limit,
                },
                ensure_ascii=False,
            ),
        )
        session.add(shortlist)
        session.flush()
        for entry in entries:
            session.add(
                RecruitmentShortlistItem(
                    shortlist_id=shortlist.id,
                    player_instance_id=int(entry["player"]["instance_id"]),
                    rank=int(entry["rank"]),
                    score=float(entry["score"]) if entry["score"] is not None else None,
                    payload_json=json.dumps(entry, ensure_ascii=False, default=str),
                )
            )
        payload["shortlist_id"] = shortlist.id
    return payload


def list_shortlists(session: Session, save_id: int) -> list[dict[str, object]]:
    """Stored shortlists of one save with their candidate counts."""
    rows = session.scalars(
        select(RecruitmentShortlist)
        .where(RecruitmentShortlist.fm_save_id == save_id)
        .order_by(RecruitmentShortlist.created_at.desc())
    )
    return [
        {
            "id": row.id,
            "name": row.name,
            "slot": row.position_code,
            "role_key": row.role_key,
            "budget": row.budget,
            "candidates": len(row.items),
            "created_at": iso(row.created_at),
            "criteria": _json(row.criteria_json, {}),
        }
        for row in rows
    ]


def shortlist_detail(session: Session, shortlist_id: int) -> dict[str, object]:
    """Stored shortlist with every stored candidate payload."""
    row = session.get(RecruitmentShortlist, shortlist_id)
    if row is None:
        raise ValueError("shortlist not found")
    return {
        "id": row.id,
        "name": row.name,
        "slot": row.position_code,
        "role_key": row.role_key,
        "budget": row.budget,
        "created_at": iso(row.created_at),
        "criteria": _json(row.criteria_json, {}),
        "items": [
            _json(item.payload_json, {})
            for item in sorted(row.items, key=lambda entry: entry.rank)
        ],
    }


# -- scoring ----------------------------------------------------------------------------------------------------


def _score_candidate(session: Session, target: Candidate, pool: list[Candidate]) -> dict[str, object]:
    group = target.position_group or "MF"
    weights = DIMENSION_WEIGHTS.get(group, DIMENSION_WEIGHTS["MF"])
    names = _attribute_names(session)
    template = POSITION_TEMPLATES.get((target.position or "").upper())
    if template is None:
        template = POSITION_TEMPLATES.get(str(target.slot or ""), {})
    attribute_result = (
        score_attributes(target.attributes, template, names) if template and target.attributes else None
    )
    dimensions = [
        _ability_dimension(target, attribute_result),
        _potential_dimension(target),
        _fit_dimension(target, attribute_result),
        _form_dimension(target, pool),
        _value_dimension(target, pool),
        _room_dimension(target),
    ]
    for dimension in dimensions:
        dimension["weight"] = weights[str(dimension["key"])]
    available = [item for item in dimensions if item["value"] is not None]
    weight_sum = sum(float(item["weight"]) for item in available)
    score = (
        round(sum(float(item["value"]) * float(item["weight"]) for item in available) / weight_sum, 2)
        if weight_sum > 0
        else None
    )
    strengths = _strengths(attribute_result)
    return {
        "player": _player_payload(target),
        "score": score,
        "dimensions": dimensions,
        "position_template": {
            "position": target.position,
            "weights": template,
            "attribute_score": attribute_result["score"] if attribute_result else None,
            "coverage": attribute_result["coverage"] if attribute_result else None,
        },
        "strengths": strengths,
        "risks": _risks(target, score),
        "cost_estimate": {
            "market_value": target.market_value,
            "wage": target.wage,
            "contract_end": target.contract_end.isoformat() if target.contract_end else None,
            "currency": "EUR",
            "basis": "当前存档身价；不是报价预测",
        },
        "algorithm_version": ALGORITHM_VERSION,
        "weights": weights,
    }


def _ability_dimension(target: Candidate, attribute_result: dict[str, object] | None) -> dict[str, object]:
    if target.ca is not None:
        return {
            "key": "ability",
            "label": DIMENSION_LABELS["ability"],
            "value": round(min(100.0, float(target.ca) / 200 * 100), 2),
            "source": "CA",
            "evidence": f"CA {target.ca}，按 0-200 能力标度换算",
            "missing": [],
        }
    if attribute_result is not None:
        return {
            "key": "ability",
            "label": DIMENSION_LABELS["ability"],
            "value": attribute_result["score"],
            "source": "attributes",
            "evidence": f"缺少 CA，用位置属性评分 {attribute_result['score']} 代替（覆盖 {float(attribute_result['coverage']):.0%}）",
            "missing": ["缺少 CA 字段"],
        }
    return {
        "key": "ability",
        "label": DIMENSION_LABELS["ability"],
        "value": None,
        "source": None,
        "evidence": "",
        "missing": ["缺少 CA 与属性数据，无法评估当前能力"],
    }


def _potential_dimension(target: Candidate) -> dict[str, object]:
    if target.pa is None:
        return {
            "key": "potential",
            "label": DIMENSION_LABELS["potential"],
            "value": None,
            "source": None,
            "evidence": "",
            "missing": ["缺少 PA，无法评估潜力"],
        }
    return {
        "key": "potential",
        "label": DIMENSION_LABELS["potential"],
        "value": round(min(100.0, float(target.pa) / 200 * 100), 2),
        "source": "PA",
        "evidence": f"PA {target.pa}，按 0-200 能力标度换算",
        "missing": [],
    }


def _fit_dimension(target: Candidate, attribute_result: dict[str, object] | None) -> dict[str, object]:
    if attribute_result is None:
        return {
            "key": "fit",
            "label": DIMENSION_LABELS["fit"],
            "value": None,
            "source": None,
            "evidence": "",
            "missing": ["缺少位置属性，无法计算战术适配"],
        }
    coverage = float(attribute_result["coverage"])
    return {
        "key": "fit",
        "label": DIMENSION_LABELS["fit"],
        "value": attribute_result["score"],
        "source": "position_template",
        "evidence": f"按 {target.position or target.slot or '未知'} 位置模板加权，属性覆盖 {coverage:.0%}",
        "missing": ["属性覆盖率低于 70%，适配分数参考价值有限"] if coverage < 0.7 else [],
    }


def _form_dimension(target: Candidate, pool: list[Candidate]) -> dict[str, object]:
    stats = target.statistics
    minutes = stats.get("minutes_played") or target.minutes_played
    if not stats or not minutes or minutes <= 0:
        return {
            "key": "form",
            "label": DIMENSION_LABELS["form"],
            "value": None,
            "source": None,
            "evidence": "",
            "missing": ["缺少赛季统计或出场时间，无法评估比赛表现"],
        }
    metric = _form_metric(target, stats, float(minutes))
    if metric is None:
        return {
            "key": "form",
            "label": DIMENSION_LABELS["form"],
            "value": None,
            "source": None,
            "evidence": "",
            "missing": ["该位置的统计指标缺失，无法评估比赛表现"],
        }
    peers = [
        _form_metric(item, item.statistics, float(item.statistics.get("minutes_played") or item.minutes_played or 0))
        for item in pool
        if item.position_group == target.position_group
        and item.statistics
        and (item.statistics.get("minutes_played") or item.minutes_played or 0) > 0
    ]
    peer_values = sorted(float(value) for value in peers if value is not None)
    if len(peer_values) < MIN_PERCENTILE_PEERS:
        return {
            "key": "form",
            "label": DIMENSION_LABELS["form"],
            "value": None,
            "source": "percentile",
            "evidence": f"同位置仅有 {len(peer_values)} 份可用统计，低于 {MIN_PERCENTILE_PEERS} 份门槛",
            "missing": ["同位置统计样本不足，拒绝给出表现评分"],
        }
    percentile = _percentile(peer_values, float(metric))
    return {
        "key": "form",
        "label": DIMENSION_LABELS["form"],
        "value": round(percentile * 100, 2),
        "source": "percentile",
        "evidence": f"{_form_metric_label(target.position_group)} 每 90 分钟 {float(metric):.2f}，高于同位置 {percentile:.0%} 的球员（样本 {len(peer_values)}）",
        "missing": [],
    }


def _value_dimension(target: Candidate, pool: list[Candidate]) -> dict[str, object]:
    percentiles = _value_percentiles(pool)
    entry = percentiles.get(target.instance_id)
    if entry is None:
        return {
            "key": "value",
            "label": DIMENSION_LABELS["value"],
            "value": None,
            "source": None,
            "evidence": "",
            "missing": ["同位置同年龄段的身价样本不足，无法评估性价比"],
        }
    return {
        "key": "value",
        "label": DIMENSION_LABELS["value"],
        "value": round((1 - float(entry)) * 100, 2),
        "source": "percentile",
        "evidence": f"身价在同位置同年龄段中处于第 {float(entry):.0%} 分位（分位越低代表越便宜）",
        "missing": [],
    }


def _room_dimension(target: Candidate) -> dict[str, object]:
    if target.ca is None or target.pa is None:
        return {
            "key": "room",
            "label": DIMENSION_LABELS["room"],
            "value": None,
            "source": None,
            "evidence": "",
            "missing": ["缺少 CA/PA，无法评估发展空间"],
        }
    headroom = max(0.0, float(target.pa) - float(target.ca))
    age = target.age if target.age is not None else 27
    age_factor = max(0.2, min(1.0, (30 - age) / 12))
    value = min(100.0, headroom / 30 * 100) * age_factor
    return {
        "key": "room",
        "label": DIMENSION_LABELS["room"],
        "value": round(value, 2),
        "source": "ca_pa_age",
        "evidence": f"PA−CA 空间 {headroom:.0f}，年龄 {age} 岁，年龄系数 {age_factor:.2f}",
        "missing": [],
    }


def _form_metric(target: Candidate, stats: dict[str, float | None], minutes: float) -> float | None:
    """Per-90 attacking or defensive output chosen for the position group."""
    per90 = minutes / 90.0
    group = target.position_group
    if group == "FW":
        goals = stats.get("goals")
        assists = stats.get("assists")
        if goals is None and assists is None:
            return None
        return ((goals or 0) + (assists or 0)) / per90
    if group == "MF":
        key_passes = stats.get("key_passes")
        tackles = stats.get("tackles")
        if key_passes is None and tackles is None:
            return None
        return ((key_passes or 0) + (tackles or 0)) / per90
    if group == "DF":
        tackles = stats.get("tackles")
        interceptions = stats.get("interceptions")
        if tackles is None and interceptions is None:
            return None
        return ((tackles or 0) + (interceptions or 0)) / per90
    saves = stats.get("saves")
    conceded = stats.get("conceded")
    if saves is None:
        return None
    return saves / per90 - (conceded or 0) / per90 * 0.5


def _form_metric_label(group: str | None) -> str:
    return {
        "FW": "进球+助攻",
        "MF": "关键传球+抢断",
        "DF": "抢断+拦截",
        "GK": "扑救净值",
    }.get(group or "", "综合产出")


def _value_percentiles(pool: list[Candidate]) -> dict[int, float]:
    """Value percentile inside position group and age band; cheaper players score lower percentiles."""
    groups: dict[tuple[str, int], list[tuple[int, int]]] = {}
    for item in pool:
        if item.market_value is None or item.age is None:
            continue
        band = item.age // 3
        groups.setdefault((item.position_group or "UNKNOWN", band), []).append((item.instance_id, item.market_value))
    result: dict[int, float] = {}
    for members in groups.values():
        if len(members) < MIN_PERCENTILE_PEERS:
            continue
        values = sorted(value for _, value in members)
        for instance_id, value in members:
            result[instance_id] = _percentile([float(item) for item in values], float(value))
    return result


# -- hidden value rules -----------------------------------------------------------------------------------------


def _apply_rule(
    key: str,
    item: Candidate,
    squad_ca: float,
    user_league_rank: int,
    value_percentiles: dict[int, float],
) -> dict[str, object] | None:
    if key == "contract_expiring":
        if item.contract_end is None:
            return None
        months = _months_until(item.contract_end)
        if months is None or months > 12:
            return None
        return _hit(item, key, 80 - months, [f"合同 {months} 个月后到期（{item.contract_end.isoformat()}）"])
    if key == "bench_young_talent":
        if item.age is None or item.minutes_played is None or item.club_reputation is None:
            return None
        if item.age > 23 or item.club_reputation < 7000 or item.minutes_played > 900:
            return None
        return _hit(
            item,
            key,
            65,
            [
                f"{item.club_name or '母队'} 声誉 {item.club_reputation}",
                f"{item.age} 岁只有 {item.minutes_played} 分钟出场时间",
            ],
        )
    if key == "lower_league_standout":
        rank = _league_rank(item.club_league)
        if rank is None or user_league_rank is None or rank <= user_league_rank:
            return None
        if squad_ca <= 0 or item.ca is None or float(item.ca) < squad_ca - 10:
            return None
        return _hit(
            item,
            key,
            70,
            [f"{item.club_league} 级别低于本队", f"CA {item.ca} 已接近本队中位数 {squad_ca:.0f}"],
        )
    if key == "cheap_and_fits":
        percentile = value_percentiles.get(item.instance_id)
        if percentile is None or percentile > 0.35 or not item.attributes:
            return None
        template = POSITION_TEMPLATES.get((item.position or "").upper())
        if not template:
            return None
        fit = score_attributes(item.attributes, template, {})
        if float(fit["score"]) < 65:
            return None
        return _hit(
            item,
            key,
            75,
            [
                f"身价处于同位置第 {percentile:.0%} 分位",
                f"{item.position or ''} 位置适配评分 {fit['score']}",
            ],
        )
    if key == "high_potential_low_wage":
        if item.age is None or item.pa is None or item.ca is None or item.wage is None:
            return None
        if item.age > 21 or item.pa - item.ca < 20:
            return None
        return _hit(
            item,
            key,
            72,
            [f"{item.age} 岁，PA−CA 空间 {item.pa - item.ca}", f"工资 {item.wage}"],
        )
    return None


def _hit(item: Candidate, key: str, signal: float, evidence: list[str]) -> dict[str, object]:
    label = next((str(rule["label"]) for rule in HIDDEN_VALUE_RULES if rule["key"] == key), key)
    return {
        "rule": key,
        "rule_label": label,
        "signal": round(signal, 2),
        "player": _player_payload(item),
        "evidence": evidence,
        "cost_estimate": {
            "market_value": item.market_value,
            "wage": item.wage,
            "contract_end": item.contract_end.isoformat() if item.contract_end else None,
        },
    }


# -- payload helpers --------------------------------------------------------------------------------------------


def _player_payload(item: Candidate) -> dict[str, object]:
    return {
        "instance_id": item.instance_id,
        "player_id": item.player_id,
        "name": item.name,
        "age": item.age,
        "position": item.position,
        "slot": item.slot,
        "slot_name": SLOT_NAMES_ZH.get(item.slot or ""),
        "position_group": item.position_group,
        "ca": item.ca,
        "pa": item.pa,
        "market_value": item.market_value,
        "wage": item.wage,
        "contract_end": item.contract_end.isoformat() if item.contract_end else None,
        "club_id": item.club_id,
        "club": item.club_name,
        "league": item.club_league,
        "minutes_played": item.minutes_played,
        "appearances": item.appearances,
    }


def _strengths(attribute_result: dict[str, object] | None) -> list[str]:
    if attribute_result is None:
        return []
    return list(attribute_result["strengths"])  # type: ignore[arg-type]


def _risks(target: Candidate, score: float | None) -> list[str]:
    risks: list[str] = []
    if target.contract_end is not None:
        months = _months_until(target.contract_end)
        if months is not None and months <= 6:
            risks.append(f"合同仅剩 {months} 个月，续约与转会费都存在不确定性")
    if target.age is None:
        risks.append("缺少年龄数据，无法判断成长窗口")
    elif target.age >= 30:
        risks.append(f"年龄 {target.age} 岁，转售价值随年龄快速下降")
    if target.ca is None and target.pa is None:
        risks.append("缺少 CA/PA，评分只覆盖部分维度")
    if score is not None and score < 55:
        risks.append("综合评分偏低，只适合作为低成本补充")
    return risks


def _reason(item: dict[str, object]) -> str:
    player = item["player"]
    assert isinstance(player, dict)
    strengths = item["strengths"]
    strength_text = "、".join(str(value) for value in strengths[:2]) if isinstance(strengths, list) else ""
    return (
        f"{player['name']}（{player.get('age') or '年龄未知'} 岁，{player.get('club') or '自由身'}）"
        f"综合评分 {item['score']}，强项：{strength_text or '—'}"
    )


def _shared_dimensions(items: list[dict[str, object]]) -> list[str]:
    """Dimensions that every compared player could be scored on."""
    if not items:
        return []
    keys: set[str] | None = None
    for item in items:
        dimensions = item["dimensions"]
        available = {str(d["key"]) for d in dimensions if d["value"] is not None}  # type: ignore[index]
        keys = available if keys is None else keys & available
    return sorted(keys or [])


def _pool_gaps(items: list[dict[str, object]]) -> list[str]:
    gaps: set[str] = set()
    for item in items:
        for dimension in item["dimensions"]:  # type: ignore[index]
            for missing in dimension["missing"]:
                gaps.add(str(missing))
    return sorted(gaps)


def _field_available(field: str, pool: list[Candidate]) -> bool:
    if field == "transfer_listed" or field == "loan_status":
        return False
    checks = {
        "contract_end": lambda item: item.contract_end is not None,
        "club_reputation": lambda item: item.club_reputation is not None,
        "minutes_played": lambda item: item.minutes_played is not None,
        "age": lambda item: item.age is not None,
        "club_league": lambda item: item.club_league is not None,
        "ca": lambda item: item.ca is not None,
        "market_value": lambda item: item.market_value is not None,
        "attributes": lambda item: bool(item.attributes),
        "pa": lambda item: item.pa is not None,
        "wage": lambda item: item.wage is not None,
    }
    check = checks.get(field)
    return bool(pool) and check is not None and any(check(item) for item in pool)


def _own_club_id(session: Session, save_id: int) -> int | None:
    club = session.scalar(
        select(Club).where(Club.fm_save_id == save_id, Club.is_user_club.is_(True)).order_by(Club.id).limit(1)
    )
    return club.id if club else None


def _own_league(session: Session, save_id: int) -> str | None:
    club_id = _own_club_id(session, save_id)
    if club_id is None:
        return None
    club = session.get(Club, club_id)
    return club.league if club else None


LEAGUE_RANK = {"Premier Division": 3, "Championship": 2, "League One": 1}


def _league_rank(league: str | None) -> int | None:
    return LEAGUE_RANK.get(league or "")


def _months_until(target: date) -> int | None:
    today = date.today()
    return (target.year - today.year) * 12 + (target.month - today.month)


def _percentile(sorted_values: list[float], value: float) -> float:
    """Share of the sample strictly below ``value``; ties count as half so a median lands at 0.5."""
    if not sorted_values:
        return 0.0
    below = sum(1 for item in sorted_values if item < value)
    equal = sum(1 for item in sorted_values if item == value)
    return (below + 0.5 * equal) / len(sorted_values)


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    return (
        float(ordered[middle])
        if len(ordered) % 2
        else (float(ordered[middle - 1]) + float(ordered[middle])) / 2
    )


def _group_of(position: str | None) -> str | None:
    from ..ingestion.attributes import position_group

    return position_group(position)


def _attribute_names(session: Session) -> dict[str, str]:
    return {row.key: row.name_zh for row in session.scalars(select(PlayerAttribute))}


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


def _statistics_by_instance(session: Session, instance_ids: list[int]) -> dict[int, dict[str, float | None]]:
    if not instance_ids:
        return {}
    rows = session.scalars(
        select(PlayerStatistic)
        .where(
            PlayerStatistic.player_instance_id.in_(instance_ids),
            PlayerStatistic.scope == "season",
        )
        .order_by(PlayerStatistic.observed_at.desc())
    )
    result: dict[int, dict[str, float | None]] = {}
    for row in rows:
        if row.player_instance_id in result:
            continue
        result[row.player_instance_id] = {
            "period": row.period,
            "appearances": row.appearances,
            "minutes_played": row.minutes_played,
            "goals": row.goals,
            "assists": row.assists,
            "shots": row.shots,
            "shots_on_target": row.shots_on_target,
            "xg": row.xg,
            "key_passes": row.key_passes,
            "passes_attempted": row.passes_attempted,
            "passes_completed": row.passes_completed,
            "dribbles": row.dribbles,
            "tackles": row.tackles,
            "interceptions": row.interceptions,
            "clearances": row.clearances,
            "aerials_won": row.aerials_won,
            "saves": row.saves,
            "conceded": row.conceded,
            "clean_sheets": row.clean_sheets,
        }
    return result


def _json(text: str, fallback: object) -> object:
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return fallback


def transfer_cost_benchmark(session: Session, instance_id: int) -> dict[str, object]:
    """Comparable completed-transfer fees for one player's age and ability band."""
    instance = session.get(PlayerInstance, instance_id)
    if instance is None:
        raise ValueError("player instance not found")
    rows = session.scalars(
        select(Transfer).where(
            Transfer.fm_save_id == instance.fm_save_id,
            Transfer.status == "completed",
            Transfer.effective_fee.is_not(None),
        )
    )
    fees = [float(row.effective_fee) for row in rows if row.effective_fee]
    return {
        "sample_size": len(fees),
        "median": _median(fees) if fees else None,
        "currency": "EUR",
        "method": "全存档已完成交易的有效费用中位数；不是该球员的报价",
    }
