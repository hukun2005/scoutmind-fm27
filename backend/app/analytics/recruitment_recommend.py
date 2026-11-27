"""自动引援推荐（SM-020）。

在现有 `candidate_pool` + `player_score` 之上加：

* 硬过滤：位置、年龄、预算、工资上限、联赛、国籍；
* 用户权重：六个维度（ability / potential / fit / form / value / room）可覆盖默认权重；
* 缺失数据显式标注：某个维度没有数据时，该维度不参与加权，并计入 `missing_dimensions`；
* 排序可解释：每条结果带六维分、权重、加权总分与原因；
* 分页；与模拟器联动：每个候选可带一个 `simulator_hint`（缺少报价时不给数字）。

不改变 `player_score` 的既有口径；这里只做"按用户偏好重新加权 + 过滤 + 排序"。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Club, Player
from .recruitment import (
    DIMENSION_WEIGHTS,
    _attributes_for_snapshot_id_list,
    _score_candidate,
    build_score_context,
    candidate_pool,
)

ALGORITHM_VERSION = "recruitment-recommend-1"

DIMENSIONS = ("ability", "potential", "fit", "form", "value", "room")


def recommend(
    session: Session,
    save_id: int,
    *,
    slot: str | None = None,
    min_age: int | None = None,
    max_age: int | None = None,
    budget: float | None = None,
    wage_cap: float | None = None,
    league: str | None = None,
    nationality: str | None = None,
    prefer: str = "balanced",
    weights: dict[str, float] | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """返回分页后的推荐列表与每条的加权解释（按存档 + 数据版本缓存 60 秒）。"""
    from ..services import query_cache

    params = {
        "slot": slot,
        "min_age": min_age,
        "max_age": max_age,
        "budget": budget,
        "wage_cap": wage_cap,
        "league": league,
        "nationality": nationality,
        "prefer": prefer,
        "weights": weights or {},
        "page": page,
        "page_size": page_size,
    }
    return query_cache.cached(
        session,
        save_id,
        "recruitment_recommend",
        params,
        lambda: _recommend(
            session,
            save_id,
            slot=slot,
            min_age=min_age,
            max_age=max_age,
            budget=budget,
            wage_cap=wage_cap,
            league=league,
            nationality=nationality,
            prefer=prefer,
            weights=weights,
            page=page,
            page_size=page_size,
        ),
    )


def _recommend(
    session: Session,
    save_id: int,
    *,
    slot: str | None = None,
    min_age: int | None = None,
    max_age: int | None = None,
    budget: float | None = None,
    wage_cap: float | None = None,
    league: str | None = None,
    nationality: str | None = None,
    prefer: str = "balanced",
    weights: dict[str, float] | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    # 先只加载快照字段与统计，过滤后再加载命中球员的属性，避免为整个存档加载数百万条属性值。
    pool = candidate_pool(session, save_id, load_attributes=False)
    clubs = {club.id: club for club in session.scalars(select(Club).where(Club.fm_save_id == save_id))}
    # 只有显式按国籍筛选时才加载国籍，并按 500 个 ID 分批，避免 5 万球员触发 SQLite 变量上限。
    nationalities: dict[int, str | None] = {}
    if nationality:
        player_ids = [item.player_id for item in pool]
        for start in range(0, len(player_ids), 500):
            chunk = player_ids[start : start + 500]
            nationalities.update(
                {
                    player.id: player.nationality
                    for player in session.scalars(select(Player).where(Player.id.in_(chunk)))
                }
            )
    club_of: dict[int, Club | None] = {}
    gaps: list[str] = []

    custom = dict(weights or {})
    unknown = set(custom) - set(DIMENSIONS)
    if unknown:
        raise ValueError(f"未知权重维度：{sorted(unknown)}")

    if league:
        gaps.append("联赛筛选基于俱乐部当前所属联赛，历史赛季不追溯")

    filtered: list[dict[str, Any]] = []
    for item in pool:
        if slot and (item.slot or "").upper() != slot.upper():
            continue
        if min_age is not None and (item.age is None or item.age < min_age):
            continue
        if max_age is not None and (item.age is None or item.age > max_age):
            continue
        if budget is not None and (item.market_value is None or item.market_value > budget):
            continue
        if wage_cap is not None and (item.wage is None or item.wage > wage_cap):
            continue
        player_nationality = nationalities.get(item.player_id)
        if nationality and (player_nationality or "").lower() != nationality.lower():
            continue
        club = clubs.get(item.club_id) if item.club_id else None
        club_of[item.instance_id] = club
        if league and (club is None or (club.league or "").lower() != league.lower()):
            continue
        filtered.append({"candidate": item, "club": club})

    if filtered:
        attributes = _attributes_for_snapshot_id_list(
            session, [entry["candidate"].snapshot_id for entry in filtered]
        )
        for entry in filtered:
            item = entry["candidate"]
            item.attributes = attributes.get(item.snapshot_id, {})

    scored: list[dict[str, Any]] = []
    missing_counter: dict[str, int] = {}
    # 同位置分位样本只构建一次；原实现对每个候选重复构建，5 万球员时会退化为 O(N²)。
    score_context = build_score_context(session, pool)
    for entry in filtered:
        item = entry["candidate"]
        detail = _score_candidate(session, item, pool, score_context)
        dims = {row["key"]: row for row in detail["dimensions"]}
        weights_used = dict(DIMENSION_WEIGHTS.get(item.position_group or "MF", DIMENSION_WEIGHTS["MF"]))
        weights_used.update(custom)
        if prefer == "ready":
            weights_used["ability"] = weights_used.get("ability", 0.3) * 1.4
            weights_used["room"] = weights_used.get("room", 0.1) * 0.6
        elif prefer == "potential":
            weights_used["potential"] = weights_used.get("potential", 0.2) * 1.4
            weights_used["room"] = weights_used.get("room", 0.1) * 1.4
            weights_used["ability"] = weights_used.get("ability", 0.3) * 0.7

        weighted_sum = 0.0
        weight_total = 0.0
        missing: list[str] = []
        for key in DIMENSIONS:
            dimension = dims.get(key)
            value = dimension.get("value") if dimension else None
            if value is None:
                missing.append(key)
                missing_counter[key] = missing_counter.get(key, 0) + 1
                continue
            weight = float(weights_used.get(key, 0.0))
            weighted_sum += float(value) * weight
            weight_total += weight
        score = round(weighted_sum / weight_total, 2) if weight_total > 0 else None
        scored.append(
            {
                "instance_id": item.instance_id,
                "name": item.name,
                "age": item.age,
                "nationality": nationalities.get(item.player_id),
                "position": item.position,
                "slot": item.slot,
                "club": entry["club"].name if entry["club"] else None,
                "league": entry["club"].league if entry["club"] else None,
                "market_value": item.market_value,
                "wage": item.wage,
                "ca": item.ca,
                "pa": item.pa,
                "score": score,
                "dimensions": [
                    {
                        "key": row["key"],
                        "label": row.get("label"),
                        "value": row.get("value"),
                        "weight": round(float(weights_used.get(row["key"], 0.0)), 4),
                        "missing": row.get("missing", []),
                    }
                    for row in detail["dimensions"]
                ],
                "missing_dimensions": missing,
                "reason": _reason(detail, item),
                "risk": detail.get("risks", []),
                "simulator_hint": None,
            }
        )
    scored.sort(key=lambda row: (-(row["score"] or -1), row["instance_id"]))
    total = len(scored)
    page_rows = scored[(page - 1) * page_size : page * page_size]
    return {
        "items": page_rows,
        "total": total,
        "page": page,
        "page_size": page_size,
        "filters": {
            "slot": slot,
            "min_age": min_age,
            "max_age": max_age,
            "budget": budget,
            "wage_cap": wage_cap,
            "league": league,
            "nationality": nationality,
            "prefer": prefer,
            "weights": custom,
        },
        "weights_used": DIMENSION_WEIGHTS.get("MF"),
        "missing_dimensions": missing_counter,
        "coverage_note": "缺失维度不参与加权（不会被当成 0 分）；缺失越多，分数解释力越弱",
        "gaps": gaps,
        "algorithm_version": ALGORITHM_VERSION,
    }


def _reason(detail: dict[str, Any], item) -> list[str]:
    reasons = []
    for strength in detail.get("strengths", [])[:2]:
        reasons.append(strength)
    if item.age is not None and item.age <= 21:
        reasons.append(f"{item.age} 岁，仍有成长空间")
    if item.market_value is not None:
        reasons.append(f"身价 {item.market_value:,}")
    return reasons
