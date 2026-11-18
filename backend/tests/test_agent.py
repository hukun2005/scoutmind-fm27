"""Regression tests for the decision assistant: no number without a tool result."""

from __future__ import annotations

from app.agents import service as agent_service
from app.models import PlayerInstance

from tests.helpers import import_document, player_row, scan_document, transfer_row

FEES = (12_000_000, 18_000_000, 26_000_000, 33_000_000, 47_000_000, 58_000_000)


def _seed(db, save) -> None:
    players = [player_row(f"P{index}", f"Striker {index}", ca=145, pa=170, position="ST") for index in range(6)]
    transfers = [
        transfer_row(f"T{index}", f"P{index}", f"Striker {index}", fee=fee, age=21, ca=145)
        for index, fee in enumerate(FEES)
    ]
    import_document(db, scan_document(players=players, transfers=transfers))


def test_price_answer_quotes_tool_median(db, save):
    """The answer's median equals the tool's median, and sample/risks sections always exist."""
    _seed(db, save)
    answer, calls = agent_service.answer_question(db, save.id, "前锋的成交价格中位数是多少？")
    stats_call = next(call for call in calls if call.name == "get_transfer_price_stats")
    median = stats_call.result["median"]
    stats_section = next(section for section in answer["sections"] if section["key"] == "stats")
    rows = {row[0]: row[1] for row in stats_section["table"]["rows"]}
    assert rows["中位数"] == _money(median)
    keys = {section["key"] for section in answer["sections"]}
    assert {"sample", "risks"} <= keys
    assert answer["sample_size"] == stats_call.result["sample_size"]
    assert answer["confidence"] in {"low", "medium", "high"}


def test_valuation_refuses_without_enough_comparables(db, save):
    """With too few comparables the assistant must refuse a range rather than invent one."""
    players = [player_row("P1", "Solo Striker", ca=150, pa=175, position="ST")]
    transfers = [transfer_row("T1", "P1", "Solo Striker", fee=30_000_000, ca=150)]
    import_document(db, scan_document(players=players, transfers=transfers))
    instance = db.query(PlayerInstance).filter(PlayerInstance.save_local_uid == "P1").one()
    answer, calls = agent_service.answer_question(
        db, save.id, "这名球员值多少？我应该出多少报价？", instance_id=instance.id
    )
    valuation_call = next(call for call in calls if call.name == "estimate_transfer_value")
    assert valuation_call.result["insufficient_sample"] is True
    assert "不给出估值区间" in answer["conclusion"]
    stats_sections = [section for section in answer["sections"] if section["key"] == "stats"]
    assert stats_sections == []


def test_offer_uses_valuation_numbers(db, save):
    """An offer simulation quotes opening/target/walk-away values derived from the valuation tool."""
    _seed(db, save)
    instance = db.query(PlayerInstance).filter(PlayerInstance.save_local_uid == "P3").one()
    answer, calls = agent_service.answer_question(
        db, save.id, "预算是 3000 万，这名球员应该出多少？", instance_id=instance.id
    )
    offer_calls = [call for call in calls if call.name == "simulate_transfer_offer"]
    assert offer_calls, "报价问题必须调用 simulate_transfer_offer"
    offer = offer_calls[0].result
    assert offer["opening_bid"] <= offer["target_price"] <= offer["walk_away_price"]
    offer_section = next(section for section in answer["sections"] if section["key"] == "offer")
    values = {row[0]: row[1] for row in offer_section["table"]["rows"]}
    assert values["首报"] == _money(offer["opening_bid"])


def test_missing_player_is_reported_not_guessed(db, save):
    """Without a player context the assistant asks for one and returns no numbers."""
    _seed(db, save)
    answer, calls = agent_service.answer_question(db, save.id, "这个球员值多少钱？")
    assert "指定球员" in answer["conclusion"]
    assert answer["sample_size"] == 0
    assert [call.name for call in calls] == ["search_players"]


def _seed_squad(db, save) -> list[dict]:
    """A managed squad plus outside candidates, enough for every V2 question."""
    squad = [
        player_row("K1", "Keeper One", position="GK", ca=140, pa=150, age=27, attributes={"reflexes": 15}),
        player_row("D1", "Defender One", position="DC", ca=142, pa=150, age=29, attributes={"tackling": 15}),
        player_row("D2", "Defender Two", position="DR", ca=135, pa=148, age=24, attributes={"tackling": 14}),
        player_row("M1", "Midfielder One", position="MC", ca=145, pa=160, age=25, attributes={"passing": 16}),
        player_row("M2", "Midfielder Two", position="DM", ca=138, pa=150, age=23, attributes={"tackling": 15}),
        player_row("F1", "Forward One", position="ST", ca=150, pa=172, age=21, attributes={"finishing": 17}),
    ]
    market = [
        player_row("X1", f"Market Target {index}", position="ST", ca=140 + index, pa=165, age=20 + index,
                   value=15_000_000 + index * 1_000_000, club_uid="C2", attributes={"finishing": 16})
        for index in range(7)
    ]
    import_document(db, scan_document(players=squad + market))
    return squad + market


def test_squad_question_uses_squad_tool(db, save):
    """A squad question must answer from the squad tool and expose the six components."""
    _seed_squad(db, save)
    answer, calls = agent_service.answer_question(db, save.id, "我的球队目前最大的问题是什么？")

    assert [call.name for call in calls] == ["get_squad_overview"]
    components = next(section for section in answer["sections"] if section["key"] == "components")
    assert len(components["table"]["rows"]) == 6
    assert answer["reliability"]["facts"], "数据库事实必须单独归类"
    assert answer["citations"], "每条结论都要能追溯到工具结果"


def test_depth_question_names_the_weakest_slot(db, save):
    """A depth question returns the ranked weakness list from the depth tool."""
    _seed_squad(db, save)
    answer, calls = agent_service.answer_question(db, save.id, "哪个位置最需要补强？")

    assert calls[0].name == "analyze_position_depth"
    weakness = calls[0].result["weakness"]
    assert weakness
    assert "最需要补强" in answer["conclusion"]


def test_recruitment_question_respects_budget_and_slot(db, save):
    """The recruitment answer quotes only candidates inside the parsed slot and budget."""
    _seed_squad(db, save)
    answer, calls = agent_service.answer_question(db, save.id, "帮我找一个 23 岁以下的年轻中锋，预算不超过 3000 万")

    assert calls[0].name == "generate_recruitment_report"
    items = calls[0].result["items"]
    assert items, "应当至少返回一个候选"
    assert all(item["player"]["slot"] == "ST" for item in items)
    assert all(float(item["cost_estimate"]["market_value"] or 0) <= 30_000_000 for item in items)
    assert "候选" in answer["conclusion"]


def test_growth_question_without_player_uses_board(db, save):
    """Without a named player the growth answer falls back to the U23 rate board instead of refusing."""
    _seed_squad(db, save)
    answer, calls = agent_service.answer_question(db, save.id, "为什么年轻球员成长停滞？")

    assert calls == []
    assert "成长" in answer["conclusion"]
    assert answer["reliability"]["unavailable"] is not None


def test_transfer_history_question_reports_taxonomy(db, save):
    """The history answer lists transaction categories and how each is accounted for."""
    _seed(db, save)
    answer, calls = agent_service.answer_question(db, save.id, "分析过去三个赛季我的转会策略")

    assert calls[0].name == "analyze_transfer_history"
    categories = next(section for section in answer["sections"] if section["key"] == "categories")
    labels = {row[0] for row in categories["table"]["rows"]}
    assert "正式转会" in labels


def test_reliability_block_separates_inference_from_fact(db, save):
    """Every answer carries the four-way reliability split required by the product spec."""
    _seed(db, save)
    answer, _calls = agent_service.answer_question(db, save.id, "我的球队现在什么情况？")
    reliability = answer["reliability"]

    assert set(reliability) >= {"facts", "computed", "inferences", "unavailable", "rule"}


def _money(value: object) -> str:
    amount = float(value)
    if abs(amount) >= 100_000_000:
        return f"{amount / 100_000_000:.2f} 亿"
    if abs(amount) >= 10_000:
        return f"{amount / 10_000:.0f} 万"
    return f"{amount:.0f}"
