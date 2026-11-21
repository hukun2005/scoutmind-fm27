"""SM-051：LLM 工具参数的 JSON Schema 子集校验。"""

from __future__ import annotations

import math

import pytest

from app.agents import llm_planner


def _validate(tool: str, arguments: dict):
    return llm_planner._validate_arguments(llm_planner.TOOL_SPECS[tool], arguments)


def test_contract_years_bounds() -> None:
    assert _validate("simulate_transfer", {"instance_id": 1, "contract_years": 8})["contract_years"] == 8
    with pytest.raises(llm_planner.PlannerError, match="超过上限"):
        _validate("simulate_transfer", {"instance_id": 1, "contract_years": 8.5})
    with pytest.raises(llm_planner.PlannerError, match="小于下限"):
        _validate("simulate_transfer", {"instance_id": 1, "contract_years": 0.1})


def test_season_and_page_size_lengths() -> None:
    assert _validate("club_transfer_intelligence", {"club_id": 1, "season": "2026/27"})["season"] == "2026/27"
    with pytest.raises(llm_planner.PlannerError, match="长度"):
        _validate("club_transfer_intelligence", {"club_id": 1, "season": "2026"})
    assert _validate("recruitment_recommend", {"page_size": 20})["page_size"] == 20
    with pytest.raises(llm_planner.PlannerError, match="超过上限"):
        _validate("recruitment_recommend", {"page_size": 21})


def test_bool_is_not_an_integer_or_number() -> None:
    with pytest.raises(llm_planner.PlannerError, match="整数"):
        _validate("player_profile", {"instance_id": True})
    with pytest.raises(llm_planner.PlannerError, match="数字"):
        _validate("simulate_transfer", {"instance_id": 1, "fee": True})


def test_nan_and_infinity_are_rejected() -> None:
    for value in (math.nan, math.inf, -math.inf):
        with pytest.raises(llm_planner.PlannerError, match="有限数字"):
            _validate("simulate_transfer", {"instance_id": 1, "fee": value})


def test_unknown_and_forbidden_arguments() -> None:
    with pytest.raises(llm_planner.PlannerError, match="未知参数"):
        _validate("player_profile", {"instance_id": 1, "extra": "x"})
    for key in ("save_id", "fm_save_id", "user_id", "session_id"):
        with pytest.raises(llm_planner.PlannerError, match="受限参数"):
            _validate("player_profile", {"instance_id": 1, key: 1})


def test_required_and_enum_and_string_length() -> None:
    with pytest.raises(llm_planner.PlannerError, match="缺少必需"):
        _validate("player_profile", {})
    with pytest.raises(llm_planner.PlannerError, match="允许取值"):
        _validate("recruitment_recommend", {"prefer": "impossible"})
    with pytest.raises(llm_planner.PlannerError, match="长度"):
        _validate("recruitment_recommend", {"slot": "x" * 9})


def test_valid_arguments_are_returned_unchanged() -> None:
    args = {"instance_id": 5, "contract_years": 3.5, "fee": 0}
    assert _validate("simulate_transfer", args) == args
