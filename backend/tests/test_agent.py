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


def _money(value: object) -> str:
    amount = float(value)
    if abs(amount) >= 100_000_000:
        return f"{amount / 100_000_000:.2f} 亿"
    if abs(amount) >= 10_000:
        return f"{amount / 10_000:.0f} 万"
    return f"{amount:.0f}"
