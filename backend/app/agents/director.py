"""AI 足球总监（V3.3.2）：把阵容、引援、关注、球员档案与成长整合为一个可解释的分析入口。

约束：

* 所有数字来自本地数据库与既有业务服务（``squad`` / ``recruitment_recommend`` / ``watchlist``）；
* 不重新实现评分或阵容规则，只做编排、排序与解释；
* 事实、规则计算、推测和缺失数据分开呈现；
* 没有可靠数据时明确说明，不用 0 或虚构值填充；
* 不自动修改球员、关注或转会状态。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..analytics.players import coverage_for_save
from ..analytics.recruitment_recommend import recommend
from ..analytics.squad import (
    _reference_date,
    contract_monitoring,
    roster,
    squad_overview,
    user_club,
)
from ..models import (
    FmSave,
    PlayerInstance,
    PlayerSnapshot,
    PlayerStatistic,
    Transfer,
    Watchlist,
    WatchlistItem,
)
from ..services import watchlist as watch_service
from ..utils import iso, utcnow
from . import service as agent_service

DISCLAIMERS = [
    "结论是本地数据分析，不包含游戏内未提供的训练、伤病与战术指令。",
]

INTENT_LABELS = {
    "gaps": "阵容补强",
    "development": "球员培养",
    "sell": "出售与外租",
    "plan": "引援计划",
    "watchlist": "关注名单",
    "age": "年龄结构",
    "squad": "阵容概览",
    "general": "综合问答",
}


def classify(question: str) -> str:
    """把自然语言问题映射到确定性分析入口；顺序保证更具体的意图优先。"""
    text = (question or "").strip().lower()
    if any(word in text for word in ("出售", "卖出", "卖掉", "外租", "租出", "清理")):
        return "sell"
    if any(word in text for word in ("引援计划", "转会计划", "下一阶段", "预算计划", "制定计划")):
        return "plan"
    if "引援" in text and any(word in text for word in ("目标", "寻找", "推荐", "候选")):
        return "plan"
    if "年龄结构" in text or "年龄分布" in text:
        return "age"
    if "关注名单" in text or "关注球员" in text or ("关注" in text and "名单" in text):
        return "watchlist"
    if any(word in text for word in ("培养", "年轻球员", "潜力", "成长", "u23", "新星")):
        return "development"
    if any(word in text for word in ("补强", "缺口", "最需要", "短板", "弱点", "风险")):
        return "gaps"
    if any(word in text for word in ("阵容", "球队现状", "球队情况")):
        return "squad"
    return "general"


def context(session: Session, save_id: int) -> dict[str, Any]:
    """当前存档的工作台上下文：俱乐部、数据时间与完整度、各模块规模。"""
    save = session.get(FmSave, save_id)
    club = user_club(session, save_id)
    coverage = coverage_for_save(session, save_id)
    player_count = int(
        session.scalar(
            select(func.count()).select_from(PlayerInstance).where(PlayerInstance.fm_save_id == save_id)
        )
        or 0
    )
    snapshot_count = int(
        session.scalar(
            select(func.count())
            .select_from(PlayerSnapshot)
            .join(PlayerInstance, PlayerInstance.id == PlayerSnapshot.player_instance_id)
            .where(PlayerInstance.fm_save_id == save_id)
        )
        or 0
    )
    transfer_count = int(
        session.scalar(select(func.count()).select_from(Transfer).where(Transfer.fm_save_id == save_id)) or 0
    )
    statistic_count = int(
        session.scalar(
            select(func.count())
            .select_from(PlayerStatistic)
            .join(PlayerInstance, PlayerInstance.id == PlayerStatistic.player_instance_id)
            .where(PlayerInstance.fm_save_id == save_id)
        )
        or 0
    )
    watch_count = int(
        session.scalar(
            select(func.count())
            .select_from(WatchlistItem)
            .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
            .where(Watchlist.fm_save_id == save_id)
        )
        or 0
    )
    last_observed = session.scalar(
        select(func.max(PlayerSnapshot.observed_at))
        .select_from(PlayerSnapshot)
        .join(PlayerInstance, PlayerInstance.id == PlayerSnapshot.player_instance_id)
        .where(PlayerInstance.fm_save_id == save_id)
    )
    gaps: list[str] = []
    if club is None:
        gaps.append("该存档没有标记为「我的俱乐部」的球队，阵容类分析不可用")
    if player_count == 0:
        gaps.append("当前存档没有球员数据，请先在数据中心导入扫描")
    if coverage.get("ca", 0) == 0 and coverage.get("pa", 0) == 0:
        gaps.append("能力字段（CA/PA）全部缺失")
    if coverage.get("market_value", 0) == 0:
        gaps.append("身价字段缺失，经济分析不可用")
    if transfer_count == 0:
        gaps.append("没有转会记录，转会分析不可用")
    if statistic_count == 0:
        gaps.append("没有赛季统计，产出与主力地位无法判断")
    values = [value for value in coverage.values() if value is not None]
    return {
        "save": {"id": save_id, "name": save.name if save else None},
        "club": (
            {"id": club.id, "name": club.name, "league": club.league, "nation": club.nation}
            if club is not None
            else None
        ),
        "data_updated_at": iso(last_observed) if last_observed is not None else None,
        "data_completeness": round(sum(values) / len(values), 4) if values else 0.0,
        "coverage": coverage,
        "counts": {
            "players": player_count,
            "snapshots": snapshot_count,
            "transfers": transfer_count,
            "statistics": statistic_count,
            "watchlist": watch_count,
        },
        "data_gaps": gaps,
        "generated_at": iso(utcnow()),
    }


def answer(session: Session, save_id: int, question: str, instance_id: int | None = None) -> dict[str, Any]:
    """回答一个足球总监问题；返回结构化结论、依据、推荐、风险与缺口。"""
    intent = classify(question)
    if intent == "general":
        payload, calls = agent_service.answer_question(session, save_id, question, instance_id=instance_id)
        payload["intent"] = "general"
        payload["intent_label"] = INTENT_LABELS["general"]
        payload["mode"] = payload.get("mode") or "deterministic"
        payload["director"] = True
        return payload
    if intent == "watchlist":
        return _watchlist_answer(session, save_id, question)
    if intent == "age":
        return _age_answer(session, save_id)
    if intent == "development":
        return _development_answer(session, save_id)
    if intent == "sell":
        return _sell_answer(session, save_id)
    if intent == "plan":
        return _plan_answer(session, save_id)
    payload = _gaps_answer(session, save_id, include_overview=intent == "squad")
    if intent == "squad":
        payload["intent"] = "squad"
        payload["intent_label"] = INTENT_LABELS["squad"]
    return payload


# -- 阵容补强 -----------------------------------------------------------------------------------------------------


def _gaps_answer(session: Session, save_id: int, include_overview: bool = False) -> dict[str, Any]:
    overview = squad_overview(session, save_id)
    club = overview.get("club") or {}
    if not club or not overview.get("squad_size"):
        return _empty(
            "阵容补强",
            "当前存档没有可分析的阵容：缺少「我的俱乐部」或阵容名单为空。",
            ["请先在数据中心导入包含俱乐部与阵容的扫描，或在阵容分析页确认本队"],
            ["没有阵容数据"],
        )
    players = roster(session, save_id)
    weakness = list(overview.get("weakness") or [])[:3]
    gaps = list(overview.get("data_gaps") or [])
    sections: list[dict[str, Any]] = []
    if include_overview or not weakness:
        sections.append(
            _section(
                "overview",
                "阵容概览",
                bullets=[
                    f"球队：{club.get('name')}（{club.get('league') or '联赛未知'}）",
                    f"阵容人数：{overview.get('squad_size')}；综合评分：{overview.get('score') if overview.get('score') is not None else '不可计算'}",
                    f"数据完整度：{_pct(_avg_coverage(session, save_id))}",
                ],
                reliability="fact",
            )
        )
    if weakness:
        sections.append(
            _section(
                "gaps",
                "补强优先级",
                table=_table(
                    ["位置", "缺口评分", "人数/要求", "证据", "建议"],
                    [
                        [
                            str(item["slot_name"]),
                            str(item["severity"]),
                            f"{item['count']}/{item['required']}",
                            "；".join(str(value) for value in item.get("evidence") or []),
                            str(item["suggestion"]),
                        ]
                        for item in weakness
                    ],
                ),
                reliability="computed",
            )
        )
    recommendations: list[dict[str, Any]] = []
    for item in weakness[:2]:
        report = recommend(session, save_id, slot=str(item["slot"]), page_size=3)
        for candidate in (report.get("items") or [])[:2]:
            recommendations.append(
                _recommendation(
                    candidate,
                    reason=f"{item['slot_name']} 缺口评分 {item['severity']}（{item['count']}/{item['required']} 人）：{candidate.get('reason') or '综合评分靠前'}",
                    action_label="查看引援详情",
                    action_target=f"/recruitment?slot={item['slot']}",
                )
            )
    if recommendations:
        sections.append(
            _section(
                "candidates",
                "可选引援目标",
                table=_table(
                    ["球员", "年龄", "俱乐部", "综合评分"],
                    [
                        [
                            str(item["name"]),
                            str(item.get("age") or "—"),
                            str(item.get("club") or "自由身"),
                            str(item.get("score") if item.get("score") is not None else "数据不足"),
                        ]
                        for item in recommendations
                    ],
                ),
                reliability="computed",
            )
        )
    contracts = overview.get("contracts") or {}
    risks = [f"{contracts.get('at_risk_count')} 名球员合同将在 12 个月内到期"] if contracts.get("at_risk_count") else []
    risks.extend(str(item) for item in (contracts.get("missing") or []))
    sections.append(
        _section(
            "risks",
            "风险与数据缺失",
            bullets=risks + gaps or ["现有阵容数据没有触发额外风险提示"],
            reliability="unavailable" if gaps else "fact",
        )
    )
    conclusion = (
        f"{club.get('name')} 当前最需要补强 {weakness[0]['slot_name']}（缺口评分 {weakness[0]['severity']}），"
        f"其次是 {weakness[1]['slot_name'] if len(weakness) > 1 else '—'}。"
        if weakness
        else f"{club.get('name')} 当前没有明显的位置缺口，但综合评分仍受数据完整度限制。"
    )
    return _answer(
        "gaps",
        conclusion,
        sections,
        recommendations,
        gaps,
        [{"tool": "squad_overview", "summary": f"{overview.get('squad_size')} 人，{len(weakness)} 个补强优先级"}],
        mode="deterministic-rules",
    )


# -- 球员培养 -----------------------------------------------------------------------------------------------------


def _development_answer(session: Session, save_id: int) -> dict[str, Any]:
    players = roster(session, save_id)
    if not players:
        return _empty("球员培养", "当前没有阵容数据，无法给出培养建议。", ["先导入包含本队阵容的扫描"], ["没有阵容数据"])
    candidates = [
        player
        for player in players
        if (player.age is not None and player.age <= 23)
        and player.ca is not None
        and player.pa is not None
        and player.pa > player.ca
    ]
    candidates.sort(key=lambda item: (-(int(item.pa or 0) - int(item.ca or 0)), item.age or 99))
    gaps: list[str] = []
    if not candidates:
        gaps.append("没有同时具备年龄、CA 与 PA 的 U23 球员，无法给出培养排序")
    if all(player.minutes_played is None for player in players):
        gaps.append("缺少出场时间，无法判断年轻球员是否已经获得稳定机会")
    rows = [
        [
            player.name,
            str(player.age or "—"),
            str(player.ca or "—"),
            str(player.pa or "—"),
            str((player.pa or 0) - (player.ca or 0)),
            str(player.position or "—"),
        ]
        for player in candidates[:8]
    ]
    sections = [
        _section(
            "candidates",
            "重点培养候选",
            table=_table(["球员", "年龄", "CA", "PA", "成长空间", "位置"], rows)
            if rows
            else None,
            bullets=None if rows else ["没有可用于培养排序的 U23 球员"],
            reliability="fact",
        ),
        _section(
            "method",
            "判断口径",
            bullets=[
                "排序依据：年龄 ≤ 23、PA > CA（存在可靠潜力数据时），按可成长空间降序",
                "出场时间与训练条件不在当前数据源内，培养建议不等于保证成长",
            ],
            reliability="fact",
        ),
    ]
    recommendations = [
        _recommendation(
            {
                "instance_id": player.instance_id,
                "name": player.name,
                "age": player.age,
                "position": player.position,
                "club": None,
                "ca": player.ca,
                "pa": player.pa,
                "market_value": player.market_value,
                "score": None,
            },
            reason=f"{player.age} 岁，CA {player.ca} / PA {player.pa}，还有 {int(player.pa or 0) - int(player.ca or 0)} 点成长空间",
            action_label="打开球员详情",
            action_target=f"/players/{player.instance_id}",
        )
        for player in candidates[:5]
    ]
    if gaps:
        sections.append(_section("gaps", "数据缺失", bullets=gaps, reliability="unavailable"))
    conclusion = (
        f"最值得重点培养的是 {candidates[0].name}（{candidates[0].age} 岁，成长空间 {int(candidates[0].pa or 0) - int(candidates[0].ca or 0)}）。"
        if candidates
        else "当前阵容没有足够的潜力数据来排序培养对象。"
    )
    return _answer(
        "development",
        conclusion,
        sections,
        recommendations,
        gaps,
        [{"tool": "roster", "summary": f"{len(players)} 名球员，{len(candidates)} 名 U23 候选"}],
        mode="deterministic-rules",
    )


# -- 出售 / 外租 ---------------------------------------------------------------------------------------------------


def _sell_answer(session: Session, save_id: int) -> dict[str, Any]:
    players = roster(session, save_id)
    if not players:
        return _empty("出售与外租", "当前没有阵容数据，无法评估出售或外租对象。", ["先导入包含本队阵容的扫描"], ["没有阵容数据"])
    by_slot: dict[str, list[int]] = {}
    for player in players:
        if player.slot and player.ca is not None:
            by_slot.setdefault(player.slot, []).append(int(player.ca))
    medians = {slot: sorted(values)[len(values) // 2] for slot, values in by_slot.items() if values}
    today = _reference_date(session, save_id)
    rows: list[list[str]] = []
    recommendations: list[dict[str, Any]] = []
    gaps: list[str] = []
    for player in players:
        age = player.age
        if age is None:
            continue
        reasons: list[str] = []
        contract_months = None
        if player.contract_end is not None:
            contract_months = _months_between(today, player.contract_end)
        median = medians.get(player.slot or "")
        if age >= 30 and contract_months is not None and contract_months <= 12:
            reasons.append(f"{age} 岁且合同剩 {max(contract_months, 0)} 个月，续约与转售窗口重叠")
        if age >= 31 and median is not None and player.ca is not None and int(player.ca) <= median - 5:
            reasons.append(f"CA {player.ca} 低于同位置中位 {median}，竞技价值下降")
        if age <= 23 and median is not None and player.ca is not None and int(player.ca) <= median - 8:
            if player.pa is not None and int(player.pa) - int(player.ca) >= 6:
                reasons.append(f"CA {player.ca} / PA {player.pa}，需要出场时间，外租比留队更有利于成长")
        if not reasons:
            continue
        kind = "外租" if any("外租" in reason for reason in reasons) else "出售"
        rows.append(
            [
                player.name,
                str(age),
                str(player.ca or "—"),
                str(player.pa or "—"),
                player.contract_end.isoformat() if player.contract_end else "—",
                kind,
                "；".join(reasons),
            ]
        )
        recommendations.append(
            _recommendation(
                {
                    "instance_id": player.instance_id,
                    "name": player.name,
                    "age": player.age,
                    "position": player.position,
                    "club": None,
                    "ca": player.ca,
                    "pa": player.pa,
                    "market_value": player.market_value,
                    "score": None,
                },
                reason="；".join(reasons),
                action_label="打开球员详情",
                action_target=f"/players/{player.instance_id}",
            )
        )
    if all(player.minutes_played is None for player in players):
        gaps.append("缺少出场时间与比赛统计，无法判断球员是否仍是主力")
    if all(player.market_value is None for player in players):
        gaps.append("缺少身价数据，无法给出经济影响")
    sections = [
        _section(
            "candidates",
            "出售 / 外租候选",
            table=_table(["球员", "年龄", "CA", "PA", "合同到期", "建议", "原因"], rows)
            if rows
            else None,
            bullets=None if rows else ["当前数据下没有满足出售或外租条件的球员"],
            reliability="computed",
        ),
        _section(
            "method",
            "判断口径",
            bullets=[
                "出售：30 岁以上且合同 12 个月内到期，或 31 岁以上且能力低于同位置中位",
                "外租：23 岁以下、能力明显低于同位置中位但潜力更高，需要稳定出场时间",
                "不会自动修改任何球员状态或转会信息",
            ],
            reliability="fact",
        ),
    ]
    if gaps:
        sections.append(_section("gaps", "数据缺失", bullets=gaps, reliability="unavailable"))
    conclusion = (
        f"有 {len(rows)} 名球员可以考虑出售或外租，优先处理 {rows[0][0]}。"
        if rows
        else "当前数据下没有满足出售或外租条件的球员。"
    )
    return _answer(
        "sell",
        conclusion,
        sections,
        recommendations[:6],
        gaps,
        [{"tool": "sell_or_loan_rules", "summary": f"{len(players)} 人，{len(rows)} 个候选"}],
        mode="deterministic-rules",
    )


# -- 引援计划 -----------------------------------------------------------------------------------------------------


def _plan_answer(session: Session, save_id: int) -> dict[str, Any]:
    overview = squad_overview(session, save_id)
    if not overview.get("club") or not overview.get("squad_size"):
        return _empty("引援计划", "当前没有阵容数据，无法制定引援计划。", ["先导入包含本队阵容的扫描"], ["没有阵容数据"])
    weakness = list(overview.get("weakness") or [])[:2]
    gaps = list(overview.get("data_gaps") or [])
    sections: list[dict[str, Any]] = []
    recommendations: list[dict[str, Any]] = []
    plan_rows: list[list[str]] = []
    for priority, item in enumerate(weakness, start=1):
        report = recommend(session, save_id, slot=str(item["slot"]), page_size=3)
        candidates = report.get("items") or []
        plan_rows.append(
            [
                f"第 {priority} 优先",
                str(item["slot_name"]),
                f"{item['count']}/{item['required']}",
                str(item["severity"]),
                "、".join(str(candidate["name"]) for candidate in candidates[:3]) or "暂无满足数据门槛的候选",
            ]
        )
        for candidate in candidates[:2]:
            recommendations.append(
                _recommendation(
                    candidate,
                    reason=f"{item['slot_name']} 缺口 {item['severity']}；{candidate.get('reason') or '综合评分靠前'}",
                    action_label="查看引援详情",
                    action_target=f"/recruitment?slot={item['slot']}",
                )
            )
        gaps.extend(str(value) for value in report.get("gaps") or [])
    if plan_rows:
        sections.append(
            _section(
                "plan",
                "分阶段引援计划",
                table=_table(["阶段", "位置", "人数/要求", "缺口评分", "建议候选"], plan_rows),
                reliability="computed",
            )
        )
    sections.append(
        _section(
            "rules",
            "执行原则",
            bullets=[
                "先补人数不足且重要度高的位置，再看替补质量",
                "身价/工资缺失时不生成经济评分；没有候选时保持空缺而不是虚构球员",
                "最终报价与合同由你在游戏内确认，本计划不写回任何游戏数据",
            ],
            reliability="fact",
        )
    )
    if gaps:
        sections.append(_section("gaps", "数据缺失与限制", bullets=list(dict.fromkeys(gaps))[:8], reliability="unavailable"))
    conclusion = (
        f"下一阶段优先补强 {weakness[0]['slot_name']}，其次 {weakness[1]['slot_name'] if len(weakness) > 1 else '—'}；"
        f"计划共 {len(recommendations)} 个可选目标。"
        if weakness
        else "当前阵容没有明显缺口，建议先补充数据后再制定引援计划。"
    )
    return _answer(
        "plan",
        conclusion,
        sections,
        recommendations,
        gaps,
        [{"tool": "recruitment_recommend", "summary": f"{len(weakness)} 个优先位置，{len(recommendations)} 个候选"}],
        mode="deterministic-rules",
    )


# -- 关注名单 -----------------------------------------------------------------------------------------------------


def _watchlist_answer(session: Session, save_id: int, question: str) -> dict[str, Any]:
    items = watch_service.list_items(session, save_id)
    if not items:
        return _empty(
            "关注名单",
            "当前存档的关注名单为空。",
            ["可以在球员详情或全局搜索中把目标球员加入关注", "也可以直接说“帮我寻找年轻引援目标”"],
            ["关注名单为空"],
        )
    status_counts: dict[str, int] = {}
    for item in items:
        status = str(item.get("status") or "watching")
        status_counts[status] = status_counts.get(status, 0) + 1
    with_note = [item for item in items if item.get("note")]
    rows = [
        [
            str((item.get("player") or {}).get("name") or "—"),
            str(item.get("list_name") or "—"),
            _status_label(str(item.get("status") or "watching")),
            str(item.get("note") or "—"),
        ]
        for item in items[:12]
    ]
    sections = [
        _section(
            "summary",
            "关注概览",
            bullets=[
                f"共 {len(items)} 名关注球员，分布在 {len({item.get('list_name') for item in items})} 个名单",
                "；".join(f"{_status_label(key)} {value} 人" for key, value in sorted(status_counts.items())),
                f"{len(with_note)} 名球员有备注",
            ],
            reliability="fact",
        ),
        _section(
            "items",
            "关注球员",
            table=_table(["球员", "名单", "状态", "备注"], rows),
            reliability="fact",
        ),
    ]
    recommendations = [
        _recommendation(
            {
                "instance_id": (item.get("player") or {}).get("instance_id"),
                "name": (item.get("player") or {}).get("name"),
                "age": (item.get("player") or {}).get("age"),
                "position": (item.get("player") or {}).get("position"),
                "club": (item.get("player") or {}).get("club"),
                "ca": (item.get("player") or {}).get("ca"),
                "pa": (item.get("player") or {}).get("pa"),
                "market_value": (item.get("player") or {}).get("market_value"),
                "score": None,
            },
            reason=str(item.get("note") or f"关注状态：{_status_label(str(item.get('status') or 'watching'))}"),
            action_label="打开球员详情",
            action_target=f"/players/{(item.get('player') or {}).get('instance_id')}",
        )
        for item in items[:5]
    ]
    return _answer(
        "watchlist",
        f"关注名单共 {len(items)} 名球员，其中 {status_counts.get('preparing', 0)} 人处于「准备引进」。",
        sections,
        recommendations,
        ["关注状态与备注来自你的本地操作，不会同步到游戏"],
        [{"tool": "watchlist", "summary": f"{len(items)} 个关注项"}],
        mode="deterministic-rules",
    )


# -- 年龄结构 -----------------------------------------------------------------------------------------------------


def _age_answer(session: Session, save_id: int) -> dict[str, Any]:
    overview = squad_overview(session, save_id)
    structure = overview.get("age_structure") or {}
    if not overview.get("squad_size"):
        return _empty("年龄结构", "当前没有阵容数据，无法分析年龄结构。", ["先导入包含本队阵容的扫描"], ["没有阵容数据"])
    buckets = structure.get("buckets") or []
    rows = [
        [str(bucket.get("bucket") or "—"), str(bucket.get("count") or 0), _pct(float(bucket.get("share") or 0))]
        for bucket in buckets
    ]
    shares = {str(bucket.get("bucket")): float(bucket.get("share") or 0) for bucket in buckets}
    risks: list[str] = []
    young = shares.get("17-20", 0.0) + shares.get("21-24", 0.0)
    ageing = shares.get("29-31", 0.0) + shares.get("32+", 0.0)
    if ageing >= 0.4:
        risks.append("29 岁以上球员占比偏高，需要考虑更新换代")
    if young <= 0.1:
        risks.append("24 岁以下球员占比偏低，长期阵容深度存在风险")
    if not risks:
        risks.append("年龄分布没有触发明显的结构性风险")
    gaps = list(overview.get("data_gaps") or [])
    if all(player.age is None for player in roster(session, save_id)):
        gaps.append("部分球员缺少年龄，年龄结构只覆盖有年龄的球员")
    sections = [
        _section(
            "distribution",
            "年龄分布",
            bullets=[
                f"平均年龄：{structure.get('average_age') if structure.get('average_age') is not None else '—'}",
                f"中位年龄：{structure.get('median_age') if structure.get('median_age') is not None else '—'}",
            ],
            table=_table(["年龄段", "人数", "占比"], rows),
            reliability="fact",
        ),
        _section("risks", "结构风险", bullets=risks, reliability="inference"),
    ]
    if gaps:
        sections.append(_section("gaps", "数据缺失", bullets=gaps, reliability="unavailable"))
    return _answer(
        "age",
        f"阵容平均年龄 {structure.get('average_age') if structure.get('average_age') is not None else '未知'}；{risks[0]}。",
        sections,
        [],
        gaps,
        [{"tool": "age_structure", "summary": f"{overview.get('squad_size')} 人"}],
        mode="deterministic-rules",
    )


# -- helpers ------------------------------------------------------------------------------------------------------


def _months_between(today, target) -> int:
    return (target.year - today.year) * 12 + (target.month - today.month)


def _avg_coverage(session: Session, save_id: int) -> float:
    values = [value for value in coverage_for_save(session, save_id).values() if value is not None]
    return sum(values) / len(values) if values else 0.0


def _pct(value: float) -> str:
    return f"{value * 100:.0f}%"


def _status_label(status: str) -> str:
    return {
        "watching": "关注中",
        "preparing": "准备引进",
        "paused": "暂缓观察",
        "done": "已完成",
    }.get(status, status)


def _recommendation(candidate: dict[str, Any], reason: str, action_label: str, action_target: str) -> dict[str, Any]:
    return {
        "instance_id": candidate.get("instance_id"),
        "name": candidate.get("name"),
        "age": candidate.get("age"),
        "position": candidate.get("position"),
        "club": candidate.get("club"),
        "ca": candidate.get("ca"),
        "pa": candidate.get("pa"),
        "market_value": candidate.get("market_value"),
        "score": candidate.get("score"),
        "reason": reason,
        "actions": [
            {"label": "查看球员", "target": f"/players/{candidate.get('instance_id')}"},
            {"label": action_label, "target": action_target},
        ],
    }


def _empty(intent: str, conclusion: str, next_steps: list[str], gaps: list[str]) -> dict[str, Any]:
    return _answer(
        intent,
        conclusion,
        [
            _section("next", "下一步", bullets=next_steps, reliability="fact"),
            _section("gaps", "数据缺失", bullets=gaps, reliability="unavailable"),
        ],
        [],
        gaps,
        [],
        mode="deterministic-rules",
    )


def _answer(
    intent: str,
    conclusion: str,
    sections: list[dict[str, Any]],
    recommendations: list[dict[str, Any]],
    gaps: list[str],
    citations: list[dict[str, Any]],
    mode: str,
) -> dict[str, Any]:
    cards = [
        {
            "instance_id": item["instance_id"],
            "name": item["name"],
            "age": item.get("age"),
            "position": item.get("position"),
            "club": item.get("club"),
            "ca": item.get("ca"),
            "pa": item.get("pa"),
            "market_value": item.get("market_value"),
            "source_tool": "director",
        }
        for item in recommendations
        if isinstance(item.get("instance_id"), int) and isinstance(item.get("name"), str)
    ]
    return {
        "intent": intent,
        "intent_label": INTENT_LABELS.get(intent, intent),
        "conclusion": conclusion,
        "sections": sections,
        "recommendations": recommendations,
        "player_cards": cards[:8],
        "data_gaps": list(dict.fromkeys(str(gap) for gap in gaps if gap)),
        "citations": citations,
        "disclaimers": list(DISCLAIMERS),
        "mode": mode,
        "director": True,
        "generated_at": iso(utcnow()),
    }


def _section(
    key: str,
    title: str,
    bullets: list[str] | None = None,
    table: dict[str, Any] | None = None,
    reliability: str = "computed",
) -> dict[str, Any]:
    payload: dict[str, Any] = {"key": key, "title": title, "reliability": reliability}
    if bullets:
        payload["bullets"] = bullets
    if table:
        payload["table"] = table
    return payload


def _table(columns: list[str], rows: list[list[str]]) -> dict[str, Any]:
    return {"columns": columns, "rows": rows}
