"""SM-046：真实 LLM 运行时的重试、用量与成本（无真实 Key 时标记 NOT_RUN）。"""

from __future__ import annotations

from datetime import date

import httpx
import pytest
from sqlalchemy import select

from app.agents import llm_planner
from app.config import settings
from app.ingestion.importer import ScanImporter
from app.ingestion.protocol import ScanPayload
from app.models import PlayerInstance

from tests.helpers import player_row, scan_document


class _Response:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.request = httpx.Request("POST", "https://example.test")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=self.request, response=self)

    def json(self):
        return self._payload


def _enable_llm(monkeypatch, *, retries: int = 2, prices: tuple[float, float] = (1.0, 2.0)) -> None:
    monkeypatch.setattr(settings, "agent_llm_enabled", True)
    monkeypatch.setattr(settings, "agent_llm_api_key", "test-key")
    monkeypatch.setattr(settings, "agent_llm_max_retries", retries)
    monkeypatch.setattr(settings, "agent_llm_input_price_per_mtok", prices[0])
    monkeypatch.setattr(settings, "agent_llm_output_price_per_mtok", prices[1])


def test_usage_and_cost_are_computed(monkeypatch) -> None:
    _enable_llm(monkeypatch)
    usage = {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500}
    assert llm_planner._usage_from({"usage": usage}) == usage
    assert llm_planner._cost_of(usage) == pytest.approx(0.002)


def test_plan_result_carries_usage_and_cost(monkeypatch, db, save) -> None:
    _enable_llm(monkeypatch)
    payload = scan_document(
        scan_id="sm046",
        players=[player_row("LLM1", "LLM Target", age=22, ca=140, pa=170, value=10_000_000)],
    )
    ScanImporter(db).import_payload(save.id, ScanPayload.model_validate(payload))
    db.commit()
    instance = db.scalar(select(PlayerInstance))

    def fake_client(messages):
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"tool_calls":[{"tool":"player_forecast","arguments":{"instance_id":%d}}]}'
                        % instance.id
                    }
                }
            ],
            "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
        }

    result = llm_planner.plan_with_llm(db, save.id, "预测这个球员", client=fake_client)
    assert result.usage == {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150}
    assert result.cost_estimate == pytest.approx(120 / 1_000_000 + 30 * 2 / 1_000_000)


def test_retryable_status_is_retried(monkeypatch) -> None:
    _enable_llm(monkeypatch, retries=2)
    calls = {"n": 0}

    def fake_post(url, json=None, timeout=None, headers=None):
        calls["n"] += 1
        if calls["n"] < 3:
            return _Response(503, {})
        return _Response(200, {"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})

    monkeypatch.setattr(httpx, "post", fake_post)
    result = llm_planner.chat_completion([{"role": "user", "content": "x"}])
    assert calls["n"] == 3
    assert result["usage"]["total_tokens"] == 2


def test_retries_exhausted_raise_llm_unavailable(monkeypatch) -> None:
    _enable_llm(monkeypatch, retries=1)
    calls = {"n": 0}

    def fake_post(url, json=None, timeout=None, headers=None):
        calls["n"] += 1
        return _Response(500, {})

    monkeypatch.setattr(httpx, "post", fake_post)
    with pytest.raises(llm_planner.LlmUnavailable):
        llm_planner.chat_completion([{"role": "user", "content": "x"}])
    assert calls["n"] == 2


def test_real_call_is_not_run_without_key(monkeypatch) -> None:
    """没有真实 Key 时必须明确不可用；不得用假响应声称联调成功。"""
    monkeypatch.setattr(settings, "agent_llm_enabled", False)
    monkeypatch.setattr(settings, "agent_llm_api_key", None)
    with pytest.raises(llm_planner.LlmUnavailable):
        llm_planner.chat_completion([{"role": "user", "content": "x"}])
