"""Decision assistant orchestration and answer composition.

The composer never computes a number itself: it only formats values returned by :mod:`app.agents.tools`. If a tool
refuses (insufficient sample), the answer says so instead of inventing an estimate.
"""

from __future__ import annotations

import json
import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..analytics.transfers import serialize_transfer
from ..models import DataSource, Player, PlayerInstance, Transfer
from ..utils import iso, utcnow
from . import llm_planner, planner, tools
from .tools import ToolCall

DISCLAIMERS = ["结论是决策辅助，不是游戏内真实报价或官方市场价格。"]
DEMO_WARNING = "当前存档包含演示数据（synthetic_fixture），不能用于真实决策。"


def answer_question(
    session: Session,
    save_id: int,
    question: str,
    instance_id: int | None = None,
    club_id: int | None = None,
    user_id: int | None = None,
) -> tuple[dict[str, object], list[ToolCall]]:
    """Answer one question and return the structured answer plus the tool calls behind it.

    如果配置了 LLM，先让它规划工具调用（数字仍只来自确定性工具）；任何失败都退回规则规划器，
    并在回答里说明降级原因，绝不把规则结果伪装成 LLM 结果。
    """
    if user_id is not None:
        # AI 工具同样受存档归属约束：调用方传入用户时，先在数据层拦一次。
        from ..models import FmSave

        owner = session.get(FmSave, save_id)
        if owner is None or owner.user_id != user_id:
            raise ValueError("save not found for this user")

    intent = planner.parse(question, instance_id=instance_id, club_id=club_id)
    if llm_planner.llm_enabled():
        try:
            planned = llm_planner.plan_with_llm(session, save_id, question)
        except (llm_planner.LlmUnavailable, llm_planner.PlannerError) as exc:
            fallback_reason = str(exc)
        else:
            answer = _compose_llm_answer(session, save_id, question, planned)
            if _has_demo_data(session, save_id):
                answer["disclaimers"] = list(answer["disclaimers"]) + [DEMO_WARNING]
            answer["generated_at"] = iso(utcnow())
            return answer, planned.calls
    else:
        fallback_reason = "未配置 LLM（agent_llm_enabled=false 或缺少 api_key）"
    if intent.instance_id is None and intent.kind in {"valuation", "similar", "deal"}:
        resolved = _resolve_instance(session, save_id, question)
        intent.instance_id = resolved.id if resolved is not None else None
    calls: list[ToolCall] = []
    if intent.kind == "price_stats":
        answer = _price_stats(session, save_id, intent, calls)
    elif intent.kind == "valuation":
        answer = _valuation(session, save_id, intent, calls)
    elif intent.kind == "similar":
        answer = _similar(session, intent, calls)
    elif intent.kind == "club_profile":
        answer = _club_profile(session, save_id, intent, calls)
    elif intent.kind == "deal":
        answer = _deal(session, save_id, intent, calls)
    elif intent.kind == "squad":
        answer = _squad(session, save_id, intent, calls)
    elif intent.kind == "depth":
        answer = _depth(session, save_id, intent, calls)
    elif intent.kind == "recruitment":
        answer = _recruitment(session, save_id, intent, calls)
    elif intent.kind == "growth":
        answer = _growth(session, save_id, intent, calls)
    elif intent.kind == "compare":
        answer = _compare(session, save_id, intent, calls)
    elif intent.kind == "transfer_history":
        answer = _transfer_history(session, save_id, intent, calls)
    else:
        answer = _scout(session, save_id, intent, calls)
    if _has_demo_data(session, save_id):
        answer["disclaimers"] = list(answer["disclaimers"]) + [DEMO_WARNING]
    answer["filters"] = _filters_of(intent)
    answer["evidence"] = [
        {"type": "tool", "label": call.name, "value": call.payload()["result_summary"]} for call in calls
    ]
    answer["reliability"] = _reliability_block(answer)
    answer["citations"] = _citations(calls)
    answer["mode"] = "deterministic"
    if "fallback_reason" in dir():
        answer["llm_fallback"] = fallback_reason
    answer["generated_at"] = iso(utcnow())
    return answer, calls


def _compose_llm_answer(
    session: Session, save_id: int, question: str, planned: llm_planner.PlanResult
) -> dict[str, object]:
    """把 LLM 规划 + 确定性工具结果组装成与规则路径同构的回答。

    数字全部来自 ``call.payload()``；这里只做字符串拼接，不做任何估算。
    """
    payloads = [call.payload() for call in planned.calls]
    summaries = [str(item.get("result_summary") or "") for item in payloads]
    conclusion = "；".join(summary for summary in summaries if summary) or "当前问题没有足够的确定性数据支持结论。"
    return {
        "conclusion": conclusion,
        "sections": [
            {"tool": payload["name"], "summary": payload.get("result_summary"), "result": payload.get("result")}
            for payload in payloads
        ],
        "filters": {},
        "evidence": [
            {"type": "tool", "label": payload["name"], "value": payload.get("result_summary")} for payload in payloads
        ],
        "reliability": {
            "level": "tool-backed",
            "note": "所有数字来自确定性工具；LLM 只负责选择工具与组织说明",
            "calls": len(payloads),
        },
        "citations": _citations(planned.calls),
        "disclaimers": list(DISCLAIMERS),
        "mode": "llm-planned",
        "plan_trace": planned.trace,
        "tool_call_limit": llm_planner.MAX_TOOL_CALLS,
    }


# -- V2 handlers: squad, depth, recruitment, growth, comparison, history -----------------------------------------


def _squad(session: Session, save_id: int, intent: planner.Intent, calls: list[ToolCall]) -> dict[str, object]:
    call = tools.get_squad_overview(session, save_id)
    calls.append(call)
    result = call.result
    club = result.get("club") or {}
    components = result.get("components") or []
    sections: list[dict[str, object]] = [
        _section(
            "score",
            "阵容评分",
            bullets=[
                f"球队：{club.get('name') or '—'}（{club.get('league') or '未知联赛'}）",
                f"综合评分：{result.get('score') if result.get('score') is not None else '不可计算'}",
                f"权重模板：{(result.get('profile') or {}).get('name', '—')}",
                f"阵容人数：{result.get('squad_size')}",
            ],
            reliability="fact",
        ),
        _section(
            "components",
            "六个维度",
            table=_table(
                ["维度", "得分", "权重"],
                [
                    [
                        str(component["label"]),
                        str(component["value"]) if component["value"] is not None else "不可计算",
                        f"{float(component['weight']):.0%}",
                    ]
                    for component in components  # type: ignore[union-attr]
                ],
            ),
        ),
    ]
    weakness = result.get("weakness") or []
    if weakness:
        sections.append(
            _section(
                "weakness",
                "阵容短板",
                table=_table(
                    ["位置", "缺口评分", "人数/要求", "建议"],
                    [
                        [
                            str(item["slot_name"]),
                            str(item["severity"]),
                            f"{item['count']}/{item['required']}",
                            str(item["suggestion"]),
                        ]
                        for item in weakness  # type: ignore[union-attr]
                    ],
                ),
            )
        )
    contracts = result.get("contracts") or {}
    if isinstance(contracts, dict) and contracts.get("at_risk_names"):
        sections.append(
            _section(
                "contracts",
                "合同风险",
                bullets=[f"12 个月内到期：{', '.join(str(name) for name in contracts['at_risk_names'][:8])}"],
                reliability="fact",
            )
        )
    gaps = [str(item) for item in result.get("data_gaps", [])]  # type: ignore[union-attr]
    sections.append(_section("risks", "数据缺口", bullets=gaps or ["六个维度全部有数据支撑"], reliability="unavailable"))
    conclusion = (
        f"{club.get('name') or '本队'} 阵容评分 {result.get('score')}，最薄弱位置是 "
        f"{weakness[0]['slot_name'] if weakness else '—'}。"
    )
    return _answer(conclusion, sections, int(result.get("squad_size") or 0), "medium", gaps)


def _depth(session: Session, save_id: int, intent: planner.Intent, calls: list[ToolCall]) -> dict[str, object]:
    call = tools.analyze_position_depth(session, save_id)
    calls.append(call)
    result = call.result
    depth = result.get("depth") or []
    weakness = result.get("weakness") or []
    rows = [
        [
            str(item["slot_name"]),
            str(item["count"]),
            str(item["required"]),
            str(item["status"]),
            str(item["suggestion"]),
        ]
        for item in depth  # type: ignore[union-attr]
        if item["slot"] != "UNKNOWN"
    ]
    sections = [
        _section("depth", "位置深度", table=_table(["位置", "人数", "最低要求", "状态", "建议"], rows), reliability="fact"),
        _section(
            "weakness",
            "优先补强",
            bullets=[
                f"{item['slot_name']}：缺口评分 {item['severity']}，{item['suggestion']}" for item in weakness  # type: ignore[union-attr]
            ]
            or ["没有可评估的位置"],
        ),
    ]
    conclusion = f"最需要补强的位置是 {weakness[0]['slot_name']}。" if weakness else "没有位置深度数据。"
    return _answer(conclusion, sections, len(rows), "medium", [])


def _recruitment(session: Session, save_id: int, intent: planner.Intent, calls: list[ToolCall]) -> dict[str, object]:
    slot = intent.slot
    report = tools.generate_recruitment_report(
        session, save_id, slot=slot, budget=int(intent.budget) if intent.budget else None, limit=5
    )
    calls.append(report)
    items = report.result.get("items") or []
    rows = [
        [
            str(item["player"]["name"]),
            str(item["player"].get("age") or "—"),
            str(item["player"].get("club") or "自由身"),
            str(item["score"]),
            _money(item["cost_estimate"].get("market_value")),
            "、".join(str(value) for value in item["strengths"][:2]) or "—",
        ]
        for item in items  # type: ignore[union-attr]
    ]
    sections = [
        _section(
            "criteria",
            "筛选条件",
            bullets=[
                f"位置：{slot or '不限'}",
                f"预算：{_money(intent.budget) if intent.budget else '未指定'}",
                f"年龄：{intent.min_age or '不限'} - {intent.max_age or '不限'}",
            ],
            reliability="fact",
        )
    ]
    if rows:
        sections.append(
            _section(
                "candidates",
                "候选名单",
                table=_table(["球员", "年龄", "俱乐部", "综合评分", "身价", "强项"], rows),
            )
        )
    gaps = [str(item) for item in report.result.get("data_gaps", [])][:6]  # type: ignore[union-attr]
    sections.append(
        _section(
            "risks",
            "推荐理由与风险",
            bullets=[
                *(f"{item['player']['name']}：{item['reason']}" for item in items[:3]),  # type: ignore[union-attr]
                *(f"风险 — {risk}" for item in items[:1] for risk in item["risks"]),  # type: ignore[union-attr]
            ]
            or ["没有符合条件且数据足够的候选"],
            reliability="inference",
        )
    )
    if gaps:
        sections.append(_section("gaps", "数据缺口", bullets=gaps, reliability="unavailable"))
    conclusion = (
        f"按 {slot or '不限位置'}、预算 {_money(intent.budget) if intent.budget else '不限'} 找到 "
        f"{report.result.get('items') and len(items) or 0} 名候选，首选 "
        f"{items[0]['player']['name']}（综合评分 {items[0]['score']}）。"  # type: ignore[index]
        if items
        else "没有找到符合条件且数据足够的候选球员。"
    )
    return _answer(conclusion, sections, len(items), "medium", gaps)


def _growth(session: Session, save_id: int, intent: planner.Intent, calls: list[ToolCall]) -> dict[str, object]:
    if intent.instance_id is None:
        return _growth_board(session, save_id, calls)
    call = tools.get_player_growth_history(session, intent.instance_id)
    calls.append(call)
    result = call.result
    player = result["player"]
    assert isinstance(player, dict)
    outlook = result["outlook"]
    assert isinstance(outlook, dict)
    points = result["points"] or []
    rows = [
        [
            str(point["date"]),
            str(point["age"] or "—"),
            str(point["ca"] or "—"),
            str(point["pa"] or "—"),
            str(point["change_label"]),
        ]
        for point in points  # type: ignore[union-attr]
    ]
    sections = [
        _section("timeline", "成长记录", table=_table(["日期", "年龄", "CA", "PA", "主要变化"], rows), reliability="fact"),
        _section(
            "rate",
            "成长速率",
            bullets=[
                f"公式：{result['rates']['formula']}",  # type: ignore[index]
                f"月均成长：{result['rates']['overall_per_month']}",  # type: ignore[index]
                f"最近区间：{result['rates']['recent_per_month']}",  # type: ignore[index]
                f"分类：{result['rates']['classification']}",  # type: ignore[index]
            ],
        ),
        _section(
            "outlook",
            "潜力判断",
            bullets=[
                f"判断：{outlook['label']}（概率 {outlook.get('probability')}）",
                f"外推区间：{outlook.get('projected_low')} – {outlook.get('projected_high')} CA",
                str(outlook.get("rationale") or ""),
                "这是等级与区间，不是精确 CA 预测",
            ],
            reliability="inference",
        ),
        _section(
            "advice",
            "发展建议",
            bullets=[f"{item['action']}：{item['reason']}（{item['confidence']}）" for item in result["advice"]],  # type: ignore[index]
            reliability="inference",
        ),
    ]
    gaps = [str(item) for item in result.get("data_gaps", [])]  # type: ignore[union-attr]
    if gaps:
        sections.append(_section("gaps", "数据缺口", bullets=gaps, reliability="unavailable"))
    conclusion = (
        f"{player['name']}：{len(points)} 个快照，月均成长 {result['rates']['overall_per_month']}，"  # type: ignore[index]
        f"潜力判断「{outlook['label']}」。"
    )
    return _answer(conclusion, sections, len(points), "medium", gaps)


def _compare(session: Session, save_id: int, intent: planner.Intent, calls: list[ToolCall]) -> dict[str, object]:
    instance_ids = _mention_instances(session, save_id, intent.question)
    if len(instance_ids) < 2:
        sections = [
            _section(
                "filters",
                "需要至少两名球员",
                bullets=["比较需要至少两名球员；请在问题中写出两名球员的姓名"],
                reliability="unavailable",
            )
        ]
        return _answer("缺少可比较的球员。", sections, 0, "insufficient", ["未识别到两名球员"])
    call = tools.compare_players(session, save_id, instance_ids)
    calls.append(call)
    items = call.result.get("items") or []
    rows = [
        [
            str(item["player"]["name"]),
            str(item["player"].get("age") or "—"),
            str(item["score"]),
            "、".join(str(value) for value in item["strengths"][:2]) or "—",
        ]
        for item in items  # type: ignore[union-attr]
    ]
    sections = [
        _section("compare", "对比结果", table=_table(["球员", "年龄", "综合评分", "强项"], rows)),
        _section(
            "dimensions",
            "可比维度",
            bullets=[f"共同可评分维度：{'、'.join(call.result.get('shared_dimensions') or []) or '无'}"],
            reliability="fact",
        ),
    ]
    conclusion = (
        f"{items[0]['player']['name']} 综合评分最高（{items[0]['score']}）。" if items else "没有可比较的数据。"
    )
    return _answer(conclusion, sections, len(items), "medium", [])


def _transfer_history(session: Session, save_id: int, intent: planner.Intent, calls: list[ToolCall]) -> dict[str, object]:
    call = tools.analyze_transfer_history(session, save_id, intent.club_id)
    calls.append(call)
    review = call.result.get("review") or {}
    summary = review.get("summary") or {} if isinstance(review, dict) else {}
    categories = (call.result.get("categories") or {}).get("categories", [])  # type: ignore[union-attr]
    sections: list[dict[str, object]] = [
        _section(
            "categories",
            "交易类型",
            table=_table(
                ["类型", "笔数", "计入价格统计", "处理方式"],
                [
                    [
                        str(item["label"]),
                        str(item["count"]),
                        "是" if item["counts_in_stats"] else "否",
                        str(item["treatment"]),
                    ]
                    for item in categories  # type: ignore[union-attr]
                ],
            ),
            reliability="fact",
        )
    ]
    if isinstance(summary, dict) and summary.get("deals"):
        sections.append(
            _section(
                "summary",
                "复盘汇总",
                bullets=[
                    f"交易 {summary.get('deals')} 笔，其中 {summary.get('profitable')} 笔身价已上升",
                    f"身价变化中位数：{_money(summary.get('median_value_delta'))}",
                    *(
                        f"{item['band']} 岁段：{item['deals']} 笔，中位变化 {_money(item['median_delta'])}"
                        for item in summary.get("by_age_band") or []  # type: ignore[union-attr]
                    ),
                ],
            )
        )
        rows = [
            [
                str(item["player"]["name"]),
                str(item["transfer_date"]),
                _money(item["fee"]),
                str(item["verdict"]),
                _money(item["value_delta_since"]),
            ]
            for item in (review.get("items") or [])[:10]  # type: ignore[union-attr]
        ]
        if rows:
            sections.append(
                _section("deals", "逐笔复盘", table=_table(["球员", "日期", "成交价", "结论", "身价变化"], rows))
            )
    sections.append(
        _section(
            "risks",
            "风险提示",
            bullets=[str((review or {}).get("note") or "复盘只使用带身价对比的交易")],
            reliability="unavailable",
        )
    )
    conclusion = (
        f"本队 {summary.get('deals')} 笔交易中 {summary.get('profitable')} 笔身价上升。"
        if isinstance(summary, dict) and summary.get("deals")
        else "没有可复盘的本队交易。"
    )
    return _answer(conclusion, sections, int(summary.get("deals") or 0) if isinstance(summary, dict) else 0, "low", [])


def _reliability_block(answer: dict[str, object]) -> dict[str, object]:
    """Split the answer into facts, computed values, inferences and unavailable data (product rule 9.5)."""
    sections = answer.get("sections") or []
    buckets: dict[str, list[str]] = {"fact": [], "computed": [], "inference": [], "unavailable": []}
    for section in sections:  # type: ignore[union-attr]
        tag = str(section.get("reliability") or "computed")
        buckets.setdefault(tag, []).append(str(section.get("title")))
    buckets["unavailable"].extend(str(item) for item in answer.get("data_gaps") or [])
    return {
        "facts": buckets.get("fact", []),
        "computed": buckets.get("computed", []),
        "inferences": buckets.get("inference", []),
        "unavailable": [item for item in dict.fromkeys(buckets.get("unavailable", [])) if item],
        "rule": "数据库事实 / 模型计算结果 / AI 推断 / 无法获得的数据 四类必须分开呈现",
    }


def _citations(calls: list[ToolCall]) -> list[dict[str, object]]:
    """Every number in the answer maps to one of these tool results."""
    return [
        {
            "tool": call.name,
            "arguments": call.arguments,
            "summary": call.summary,
            "warnings": call.warnings,
        }
        for call in calls
    ]


def _growth_board(session: Session, save_id: int, calls: list[ToolCall]) -> dict[str, object]:
    """Growth answer when the question does not name one player: the youngest tracked players by rate."""
    from ..analytics.development import development_board

    board = development_board(session, save_id, limit=10, min_age=23)
    rows = [
        [
            str(item["player"]["name"]),
            str(item["player"].get("age") or "—"),
            str(item["overall_per_month"]),
            str((item["outlook"] or {}).get("label") or "—"),
            str((item["advice_top"] or {}).get("action") or "—"),
        ]
        for item in board["items"]  # type: ignore[union-attr]
    ]
    sections = [
        _section(
            "board",
            "U23 成长排行",
            table=_table(["球员", "年龄", "月均成长", "潜力判断", "建议"], rows)
            if rows
            else None,
            bullets=None if rows else ["没有至少两个快照的 U23 球员，无法给出成长结论"],
        ),
        _section(
            "method",
            "口径",
            bullets=[
                "成长速率 = (CA_t − CA_t−1) / Δ月；只统计至少两个快照的球员",
                "潜力判断是区间与等级，不是精确 CA 预测",
                str(board.get("note") or ""),
            ],
            reliability="fact",
        ),
    ]
    conclusion = (
        f"U23 中成长最快的是 {board['items'][0]['player']['name']}（月均 {board['items'][0]['overall_per_month']}）。"  # type: ignore[index]
        if board["items"]
        else "没有足够的快照数据来评估成长。"
    )
    return _answer(conclusion, sections, int(board["total"]), "medium", [])


def _mention_instances(session: Session, save_id: int, question: str) -> list[int]:
    """Player instances whose full name appears in the question."""
    found: list[int] = []
    rows = session.execute(
        select(Player.full_name, PlayerInstance.id)
        .join(PlayerInstance, PlayerInstance.player_id == Player.id)
        .where(PlayerInstance.fm_save_id == save_id)
    ).all()
    for name, instance_id in rows:
        if str(name) and str(name) in question and int(instance_id) not in found:
            found.append(int(instance_id))
    return found[:5]


def _price_stats(session: Session, save_id: int, intent: planner.Intent, calls: list[ToolCall]) -> dict[str, object]:
    criteria = {
        "position_group": intent.position_group,
        "min_age": intent.min_age,
        "max_age": intent.max_age,
        "min_ca": intent.min_ca,
    }
    call = tools.get_transfer_price_stats(session, save_id, criteria)
    calls.append(call)
    stats = call.result
    sample = int(stats.get("sample_size") or 0)
    warnings = list(stats.get("warnings") or [])
    bullets = [
        f"筛选：{_criteria_text(criteria)}",
        f"样本：{sample} 笔已完成且带金额的交易",
        f"覆盖率：金额 {float(stats['coverage']['fee']):.0%}，成交时 CA {float(stats['coverage']['ca_at_transfer']):.0%}",
    ]
    sections = [_section("sample", "样本说明", bullets=bullets)]
    if sample:
        sections.append(
            _section(
                "stats",
                "价格统计",
                table=_table(
                    ["指标", "数值"],
                    [
                        ["中位数", _money(stats["median"])],
                        ["P25", _money(stats["p25"])],
                        ["P75", _money(stats["p75"])],
                        ["均值", _money(stats["mean"])],
                        ["最小值", _money(stats["min"])],
                        ["最大值", _money(stats["max"])],
                    ],
                ),
            )
        )
        sections.append(
            _section(
                "factors",
                "影响因素",
                bullets=[
                    "仅统计已完成交易；未完成、撤消与失败交易被排除",
                    f"算法版本：{stats['algorithm_version']}",
                    "分位数对极端成交不敏感，适合作为报价参考",
                ],
            )
        )
        conclusion = (
            f"{sample} 笔已完成交易，中位数 {_money(stats['median'])}，"
            f"25/75 分位 {_money(stats['p25'])} / {_money(stats['p75'])}。"
        )
        confidence = "medium" if sample >= 20 else "low"
    else:
        conclusion = "当前筛选条件下没有带金额的已完成交易，无法给出价格统计。"
        confidence = "insufficient"
    sections.append(_section("risks", "风险提示", bullets=warnings or ["样本量较小，分位数可能不稳定"]))
    return _answer(conclusion, sections, sample, confidence, warnings)


def _valuation(session: Session, save_id: int, intent: planner.Intent, calls: list[ToolCall]) -> dict[str, object]:
    if intent.instance_id is None:
        call = tools.search_players(session, save_id, {"position_group": intent.position_group, "min_age": intent.min_age,
                                                       "max_age": intent.max_age, "min_ca": intent.min_ca}, limit=10)
        calls.append(call)
        section = _section(
            "sample",
            "需要指定球员",
            bullets=[
                "没有识别到具体球员，请从下方候选里选择一名球员后再问估值或报价",
                f"候选数量：{call.result['total']}",
            ],
        )
        rows = [
            [item["name"], f"{item['position'] or '—'}", f"{item['age'] or '—'}", f"{item['ca'] or '—'}", _money(item["market_value"])]
            for item in call.result["items"][:5]
        ]
        sections = [section]
        if rows:
            sections.append(_section("candidates", "候选球员", table=_table(["球员", "位置", "年龄", "CA", "身价"], rows)))
        sections.append(_section("risks", "风险提示", bullets=["未指定球员时不会给出任何估值数字"]))
        return _answer("需要先指定球员，才能基于可比成交给出估值。", sections, 0, "insufficient", ["缺少球员上下文"])
    profile_call = tools.get_player_profile(session, intent.instance_id)
    calls.append(profile_call)
    similar_call = tools.find_similar_transfers(session, intent.instance_id, limit=20)
    calls.append(similar_call)
    valuation_call = tools.estimate_transfer_value(session, intent.instance_id)
    calls.append(valuation_call)
    valuation = valuation_call.result
    profile = profile_call.result["summary"]
    if valuation["insufficient_sample"]:
        conclusion = (
            f"{profile['name']} 的可比成交只有 {valuation['sample_size']} 笔，"
            f"低于最小样本要求，因此不给出估值区间。"
        )
    else:
        conclusion = (
            f"{profile['name']} 的可比成交中位数 {_money(valuation['basis']['median'])}，"
            f"建议目标区间 {_money(valuation['low'])} – {_money(valuation['high'])}，参考中值 {_money(valuation['mid'])}。"
        )
    sections = [
        _section(
            "sample",
            "样本说明",
            bullets=[
                f"相似成交 {similar_call.result['sample_size']} 笔；估值样本 {valuation['sample_size']} 笔",
                f"相似度权重：{_weights_text(similar_call.result['effective_weights'])}",
                f"缺失字段：{', '.join(similar_call.result['missing_fields']) or '无'}",
            ],
        )
    ]
    if not valuation["insufficient_sample"]:
        sections.append(
            _section(
                "stats",
                "价格统计",
                table=_table(
                    ["指标", "数值"],
                    [
                        ["可比成交中位数", _money(valuation["basis"]["median"])],
                        ["P25", _money(valuation["basis"]["p25"])],
                        ["P75", _money(valuation["basis"]["p75"])],
                        ["估值区间", f"{_money(valuation['low'])} – {_money(valuation['high'])}"],
                        ["合同调整系数", f"{valuation['basis']['adjustment']['contract_factor']:.2f}"],
                    ],
                ),
            )
        )
    rows = []
    for item in similar_call.result["items"][:5]:
        transfer = item["transfer"]
        rows.append(
            [
                str(transfer["player_name"]),
                str(transfer["transfer_date"]),
                str(transfer["from_club"] or "—"),
                str(transfer["to_club"] or "—"),
                _money(transfer["effective_fee"]),
                f"{float(item['similarity']):.0%}",
            ]
        )
    if rows:
        sections.append(
            _section("comparables", "可比交易", table=_table(["球员", "日期", "卖方", "买方", "成交价", "相似度"], rows))
        )
    if intent.budget is not None:
        offer_call = tools.simulate_transfer_offer(session, intent.instance_id, intent.budget, intent.installments)
        calls.append(offer_call)
        offer = offer_call.result
        if not offer.get("insufficient_sample"):
            sections.append(
                _section(
                    "offer",
                    "报价建议",
                    table=_table(
                        ["项目", "金额"],
                        [
                            ["首报", _money(offer["opening_bid"])],
                            ["目标成交价", _money(offer["target_price"])],
                            ["最高可接受", _money(offer["walk_away_price"])],
                        ],
                    ),
                )
            )
    warnings = list(valuation.get("warnings") or []) + list(similar_call.result.get("data_gaps") or [])
    sections.append(_section("risks", "风险提示", bullets=warnings or ["样本有限，实际成交受谈判与合同影响"]))
    return _answer(conclusion, sections, int(valuation["sample_size"]), str(valuation["confidence"]), warnings)


def _similar(session: Session, intent: planner.Intent, calls: list[ToolCall]) -> dict[str, object]:
    if intent.instance_id is None:
        sections = [
            _section(
                "sample",
                "需要指定球员",
                bullets=["请先选择一名球员，再检索相似成交；不同位置的成交不可横向比较"],
            ),
            _section("risks", "风险提示", bullets=["未指定球员时不会返回任何成交样本"]),
        ]
        return _answer("需要先指定球员，才能检索相似成交。", sections, 0, "insufficient", ["缺少球员上下文"])
    call = tools.find_similar_transfers(session, intent.instance_id, limit=20)
    calls.append(call)
    items = call.result["items"]
    fees = [float(item["transfer"]["effective_fee"]) for item in items if item["transfer"].get("effective_fee") is not None]
    sections = [
        _section(
            "sample",
            "样本说明",
            bullets=[
                f"相似成交 {len(items)} 笔",
                f"权重：{_weights_text(call.result['effective_weights'])}",
                f"缺失字段：{', '.join(call.result['missing_fields']) or '无'}",
            ],
        )
    ]
    rows = [
        [
            str(item["transfer"]["player_name"]),
            str(item["transfer"]["transfer_date"]),
            _money(item["transfer"]["effective_fee"]),
            f"{float(item['similarity']):.0%}",
        ]
        for item in items[:8]
    ]
    if rows:
        sections.append(_section("comparables", "可比交易", table=_table(["球员", "日期", "成交价", "相似度"], rows)))
    if fees:
        import statistics

        sections.append(
            _section(
                "stats",
                "价格统计",
                bullets=[f"可比成交中位数：{_money(statistics.median(fees))}", f"样本：{len(fees)} 笔"],
            )
        )
    warnings = list(call.result.get("data_gaps") or [])
    sections.append(_section("risks", "风险提示", bullets=warnings or ["相似度是加权距离，不代表同一市场行情"]))
    conclusion = (
        f"找到 {len(items)} 笔相似成交，中位数 {_money(fees[len(fees) // 2] if fees else None)}。"
        if fees
        else "没有找到可比较的成交记录。"
    )
    return _answer(conclusion, sections, len(items), "medium" if len(items) >= 10 else "low", warnings)


def _club_profile(session: Session, save_id: int, intent: planner.Intent, calls: list[ToolCall]) -> dict[str, object]:
    club_id = intent.club_id
    if club_id is None:
        own = session.execute(
            select(PlayerInstance.club_id)
            .where(PlayerInstance.fm_save_id == save_id)
            .group_by(PlayerInstance.club_id)
            .order_by(func.count().desc())
            .limit(1)
        ).first()
        from ..models import Club

        user_club = session.scalar(select(Club).where(Club.fm_save_id == save_id, Club.is_user_club.is_(True)))
        club_id = user_club.id if (user_club and intent.mentions_own_club) else (own[0] if own else None)
    if club_id is None:
        sections = [
            _section("sample", "缺少俱乐部", bullets=["当前存档没有俱乐部数据，请先导入一次包含俱乐部的扫描"]),
            _section("risks", "风险提示", bullets=["没有俱乐部数据时不分析买卖行为"]),
        ]
        return _answer("需要俱乐部数据才能分析转会画像。", sections, 0, "insufficient", ["缺少俱乐部数据"])
    call = tools.get_club_transfer_profile(session, club_id)
    calls.append(call)
    profile = call.result
    sections = [
        _section(
            "sample",
            "样本说明",
            bullets=[
                f"{profile['name']} 相关已完成交易 {profile['sample_size']} 笔",
                f"金额覆盖率 {float(profile['coverage']['fee']):.0%}",
                f"算法版本 {profile['algorithm_version']}",
            ],
        ),
        _section(
            "stats",
            "价格统计",
            table=_table(
                ["项目", "数值"],
                [
                    ["买入笔数", str(profile["bought"]["count"])],
                    ["买入总额", _money(profile["bought"]["total"])],
                    ["卖出笔数", str(profile["sold"]["count"])],
                    ["卖出总额", _money(profile["sold"]["total"])],
                    ["净投入", _money(profile["net_spend"])],
                    ["平均每笔已实现利润", _money(profile["avg_profit_per_sale"])],
                    ["23 岁以下签约占比", f"{float(profile['young_signing_ratio']):.0%}" if profile["young_signing_ratio"] is not None else "—"],
                ],
            ),
        ),
    ]
    rows = [
        [item["player_name"], item["transfer_date"], _money(item["effective_fee"])] for item in profile["top_transfers"]
    ]
    if rows:
        sections.append(_section("comparables", "最大交易", table=_table(["球员", "日期", "费用"], rows)))
    warnings = list(profile.get("warnings") or [])
    sections.append(_section("risks", "风险提示", bullets=warnings or ["俱乐部画像只反映当前存档可读取的交易"]))
    conclusion = (
        f"{profile['name']} 买入 {profile['bought']['count']} 笔、卖出 {profile['sold']['count']} 笔，"
        f"净投入 {_money(profile['net_spend'])}。"
    )
    return _answer(conclusion, sections, int(profile["sample_size"]), "medium", warnings)


def _deal(session: Session, save_id: int, intent: planner.Intent, calls: list[ToolCall]) -> dict[str, object]:
    transfer_id = intent.transfer_id
    if transfer_id is None:
        transfer = session.scalar(
            select(Transfer)
            .where(Transfer.fm_save_id == save_id, Transfer.status == "completed")
            .order_by(Transfer.transfer_date.desc())
            .limit(1)
        )
        transfer_id = transfer.id if transfer is not None else None
    if transfer_id is None:
        sections = [
            _section("sample", "没有可复盘的交易", bullets=["当前存档没有已完成交易"]),
            _section("risks", "风险提示", bullets=["没有交易数据时不给出复盘结论"]),
        ]
        return _answer("没有可复盘的交易。", sections, 0, "insufficient", ["缺少交易数据"])
    call = tools.analyze_own_club_deal(session, transfer_id)
    calls.append(call)
    result = call.result
    sections = [
        _section(
            "sample",
            "样本说明",
            bullets=[f"同类样本 {result['comparables']} 笔", f"成交价分位：{result['fee_percentile']:.0%}" if result.get("fee_percentile") is not None else "成交价分位：—"],
        ),
        _section(
            "stats",
            "价格统计",
            table=_table(
                ["指标", "数值"],
                [
                    ["实际成交", _money(result["effective_fee"])],
                    ["同类中位数", _money(result["market_median"])],
                    ["P25 / P75", f"{_money(result['market_p25'])} / {_money(result['market_p75'])}"],
                ],
            ),
        ),
    ]
    warnings = list(result.get("stats", {}).get("warnings") or [])
    sections.append(_section("risks", "风险提示", bullets=warnings or ["复盘基于同类样本，未考虑条款细节"]))
    conclusion = f"{result['player_name']} 的成交价处于同类样本第 {result['fee_percentile']:.0%} 分位，判定为「{result['verdict']}」。" if result.get("fee_percentile") is not None else f"{result['player_name']} 缺少同类样本，无法判断价格高低。"
    return _answer(conclusion, sections, int(result["comparables"]), "low", warnings)


def _scout(session: Session, save_id: int, intent: planner.Intent, calls: list[ToolCall]) -> dict[str, object]:
    criteria = {
        "position_group": intent.position_group,
        "min_age": intent.min_age,
        "max_age": intent.max_age,
        "min_ca": intent.min_ca,
        "min_pa": intent.min_pa,
        "max_value": intent.max_value,
    }
    call = tools.search_players(session, save_id, criteria, limit=10)
    calls.append(call)
    items = call.result["items"]
    sections = [
        _section(
            "sample",
            "样本说明",
            bullets=[f"筛选：{_criteria_text(criteria)}", f"命中 {call.result['total']} 名球员"],
        )
    ]
    rows = [
        [
            item["name"],
            item["position"] or "—",
            str(item["age"] or "—"),
            str(item["ca"] or "—"),
            str(item["pa"] or "—"),
            _money(item["market_value"]),
            f"{float(item['data_completeness'] or 0):.0%}",
        ]
        for item in items
    ]
    if rows:
        sections.append(_section("candidates", "候选球员", table=_table(["球员", "位置", "年龄", "CA", "PA", "身价", "完整度"], rows)))
    warnings = ["属性完整度不足 70% 的球员不建议直接用于报价决策"] if any((item["data_completeness"] or 0) < 0.7 for item in items) else []
    sections.append(_section("risks", "风险提示", bullets=warnings or ["筛选结果只反映最近一次快照"]))
    conclusion = f"按条件命中 {call.result['total']} 名球员，已按能力排序给出前 {len(items)} 名候选。"
    return _answer(conclusion, sections, len(items), "medium", warnings)


def _resolve_instance(session: Session, save_id: int, question: str) -> PlayerInstance | None:
    tokens = [token for token in re.split(r"[^\w\u4e00-\u9fff]+", question) if len(token) >= 4]
    for token in tokens[:4]:
        player = session.scalar(select(Player).where(Player.full_name.ilike(f"%{token}%")))
        if player is None:
            continue
        instance = session.scalar(
            select(PlayerInstance)
            .where(PlayerInstance.player_id == player.id, PlayerInstance.fm_save_id == save_id)
            .limit(1)
        )
        if instance is not None:
            return instance
    return None


def _has_demo_data(session: Session, save_id: int) -> bool:
    return (
        session.scalar(
            select(DataSource.id).where(
                DataSource.fm_save_id == save_id, DataSource.source == "synthetic_fixture"
            )
        )
        is not None
    )


def _answer(
    conclusion: str, sections: list[dict[str, object]], sample_size: int, confidence: str, warnings: list[str]
) -> dict[str, object]:
    return {
        "conclusion": conclusion,
        "sections": sections,
        "sample_size": sample_size,
        "confidence": confidence,
        "data_gaps": warnings,
        "disclaimers": list(DISCLAIMERS),
    }


def _section(
    key: str,
    title: str,
    bullets: list[str] | None = None,
    table: dict[str, object] | None = None,
    body: str | None = None,
    reliability: str = "computed",
) -> dict[str, object]:
    payload: dict[str, object] = {"key": key, "title": title, "reliability": reliability}
    if body:
        payload["body"] = body
    if bullets:
        payload["bullets"] = bullets
    if table:
        payload["table"] = table
    return payload


def _table(columns: list[str], rows: list[list[str]]) -> dict[str, object]:
    return {"columns": columns, "rows": rows}


def _money(value: object) -> str:
    if value is None:
        return "—"
    amount = float(value)
    if abs(amount) >= 100_000_000:
        return f"{amount / 100_000_000:.2f} 亿"
    if abs(amount) >= 10_000:
        return f"{amount / 10_000:.0f} 万"
    return f"{amount:.0f}"


def _criteria_text(criteria: dict[str, object]) -> str:
    labels = {
        "position_group": "位置组",
        "min_age": "最小年龄",
        "max_age": "最大年龄",
        "min_ca": "最小 CA",
        "max_ca": "最大 CA",
        "min_pa": "最小 PA",
        "max_value": "最高身价",
    }
    parts = [f"{labels[key]} {value}" for key, value in criteria.items() if value is not None]
    return "、".join(parts) if parts else "全部球员"


def _weights_text(weights: dict[str, float]) -> str:
    return "、".join(f"{key} {value:.0%}" for key, value in weights.items() if value)


def _filters_of(intent: planner.Intent) -> dict[str, object]:
    return {
        key: value
        for key, value in {
            "position_group": intent.position_group,
            "min_age": intent.min_age,
            "max_age": intent.max_age,
            "min_ca": intent.min_ca,
            "min_pa": intent.min_pa,
            "budget": intent.budget,
        }.items()
        if value is not None
    }


def summarize_result(result: dict[str, object]) -> str:
    """Compact JSON summary stored alongside a message for debugging."""
    return json.dumps(result, ensure_ascii=False, default=str)[:4000]
