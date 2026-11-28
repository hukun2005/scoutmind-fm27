"""V3.3.3-01 模型 Provider：路径可配置、JSON 模式回退、关闭时降级。"""

from __future__ import annotations

import json

import httpx
import pytest

from app.agents import llm_planner
from app.config import settings


class _FakeResponse:
    def __init__(self, status: int, payload: dict, text: str | None = None) -> None:
        self.status_code = status
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload)
        self.request = httpx.Request("POST", "http://test.local/chat")

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=self.request, response=self)  # type: ignore[arg-type]


def _patch(monkeypatch, **overrides) -> None:
    values = {
        "agent_llm_enabled": True,
        "agent_llm_api_key": "test-key",
        "agent_llm_base_url": "https://example.test/api",
        "agent_llm_chat_path": "/chat/completions",
        "agent_llm_model": "test-model",
        "agent_llm_max_retries": 1,
        "agent_llm_timeout_seconds": 5.0,
    }
    values.update(overrides)
    for key, value in values.items():
        monkeypatch.setattr(settings, key, value, raising=False)


def test_chat_path_is_configurable(monkeypatch) -> None:
    _patch(monkeypatch)
    urls: list[str] = []

    def fake_post(url, **kwargs):
        urls.append(url)
        return _FakeResponse(200, {"choices": [{"message": {"content": '{"ok": true}'}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}})

    monkeypatch.setattr(httpx, "post", fake_post)
    data = llm_planner.chat_completion([{"role": "user", "content": "x"}])
    assert urls == ["https://example.test/api/chat/completions"]
    assert data["choices"][0]["message"]["content"] == '{"ok": true}'


def test_response_format_fallback(monkeypatch) -> None:
    _patch(monkeypatch, agent_llm_max_retries=2)
    payloads: list[dict] = []

    def fake_post(url, **kwargs):
        payloads.append(kwargs["json"])
        if len(payloads) == 1:
            return _FakeResponse(400, {"error": "bad"}, text='{"error":"response_format unsupported"}')
        return _FakeResponse(200, {"choices": [{"message": {"content": "{}"}}]})

    monkeypatch.setattr(httpx, "post", fake_post)
    llm_planner.chat_completion([{"role": "user", "content": "x"}])
    assert "response_format" in payloads[0]
    assert "response_format" not in payloads[1]


def test_disabled_provider_raises(monkeypatch) -> None:
    _patch(monkeypatch, agent_llm_enabled=False)
    with pytest.raises(llm_planner.LlmUnavailable):
        llm_planner.chat_completion([{"role": "user", "content": "x"}])
