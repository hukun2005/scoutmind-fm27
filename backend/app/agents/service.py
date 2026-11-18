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
from . import planner, tools
from .tools import ToolCall

DISCLAIMERS = ["结论是决策辅助，不是游戏内真实报价或官方市场价格。"]
DEMO_WARNING = "当前存档包含演示数据（synthetic_fixture），不能用于真实决策。"


def answer_question(
    session: Session,
    save_id: int,
    question: str,
    instance_id: int | None = None,
    club_id: int | None = None,
) -> tuple[dict[str, object], list[ToolCall]]:
    """Answer one question and return the structured answer plus the tool calls behind it."""
    intent = planner.parse(question, instance_id=instance_id, club_id=club_id)
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
    else:
        answer = _scout(session, save_id, intent, calls)
    if _has_demo_data(session, save_id):
        answer["disclaimers"] = list(answer["disclaimers"]) + [DEMO_WARNING]
    answer["filters"] = _filters_of(intent)
    answer["evidence"] = [
        {"type": "tool", "label": call.name, "value": call.payload()["result_summary"]} for call in calls
    ]
    answer["mode"] = "deterministic"
    answer["generated_at"] = iso(utcnow())
    return answer, calls


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
) -> dict[str, object]:
    payload: dict[str, object] = {"key": key, "title": title}
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
