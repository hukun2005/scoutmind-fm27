"""SM-007 / SM-009：AI 存档隔离与 LLM 工具规划器。"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.agents import llm_planner, service
from app.config import settings
from app.models import AgentConversation, AgentMessage, AiReport, FmSave, User

from tests.helpers import player_row, scan_document
from tests.helpers import import_document


def _two_saves(db):
    user = db.scalar(select(User))
    other = FmSave(user_id=user.id, name="隔离测试存档", game_version="27.1", game_build="x", is_active=False)
    db.add(other)
    db.commit()
    return user, other


def _seed(client: TestClient, save_id: int) -> None:
    document = scan_document(
        scan_id=f"agent-{save_id}",
        players=[player_row(f"A{save_id}", f"Agent Player {save_id}", ca=150, pa=170)],
    )
    response = client.post(
        f"/api/v1/imports/scan?save_id={save_id}",
        content=json.dumps(document).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 201, response.text


def _conversation(client: TestClient, save_id: int) -> int:
    response = client.post("/api/v1/agent/conversations", json={"save_id": save_id, "title": "隔离"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


# ---------------------------- SM-007 ----------------------------


def test_conversation_messages_are_scoped_to_active_save(client: TestClient, db, save) -> None:
    """别的存档的会话不能通过当前存档读取。"""
    _, other = _two_saves(db)
    _seed(client, other.id)
    conversation_id = _conversation(client, other.id)
    response = client.get(f"/api/v1/agent/conversations/{conversation_id}/messages")
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "conversation_not_found"


def test_ask_cannot_cross_saves(client: TestClient, db, save) -> None:
    """会话属于存档 B，却用存档 A 提问 → 拒绝。"""
    _, other = _two_saves(db)
    _seed(client, other.id)
    conversation_id = _conversation(client, other.id)
    response = client.post(
        f"/api/v1/agent/conversations/{conversation_id}/messages",
        json={"question": "阵容怎么样", "save_id": save.id},
    )
    assert response.status_code in {400, 404}, response.text


def test_ask_with_save_id_mismatch_is_rejected(client: TestClient, db, save) -> None:
    _, other = _two_saves(db)
    _seed(client, other.id)
    conversation_id = _conversation(client, other.id)
    response = client.post(
        f"/api/v1/agent/conversations/{conversation_id}/messages",
        json={"question": "阵容怎么样", "save_id": other.id},
    )
    # 当前存档仍是 save（active），会话属于 other → 404
    assert response.status_code == 404, response.text


def test_unknown_conversation_is_404(client: TestClient, save) -> None:
    response = client.get("/api/v1/agent/conversations/999999/messages")
    assert response.status_code == 404


def test_reports_are_scoped_to_save(client: TestClient, db, save) -> None:
    """报告列表只返回当前存档；显式请求别人的存档 → 404。"""
    _, other = _two_saves(db)
    _seed(client, save.id)
    conversation_id = _conversation(client, save.id)
    ask = client.post(
        f"/api/v1/agent/conversations/{conversation_id}/messages",
        json={"question": "转会价格统计", "save_id": save.id},
    )
    assert ask.status_code == 201, ask.text

    mine = client.get("/api/v1/agent/reports")
    assert mine.status_code == 200
    assert mine.json()["total"] >= 1

    # 另一个用户拥有的存档：不能读取其报告
    stranger = User(username="stranger", display_name="陌生人")
    db.add(stranger)
    db.commit()
    stranger_save = FmSave(user_id=stranger.id, name="别人的存档", game_version="27.1", game_build="x")
    db.add(stranger_save)
    db.commit()
    foreign = client.get(f"/api/v1/agent/reports?save_id={stranger_save.id}")
    assert foreign.status_code == 404, foreign.text


def test_create_conversation_with_foreign_save_is_rejected(client: TestClient, db, save) -> None:
    other_user = User(username="intruder", display_name="别人")
    db.add(other_user)
    db.commit()
    foreign_save = FmSave(user_id=other_user.id, name="别人的存档", game_version="27.1", game_build="x")
    db.add(foreign_save)
    db.commit()

    response = client.post("/api/v1/agent/conversations", json={"save_id": foreign_save.id, "title": "x"})
    assert response.status_code == 404, response.text


# ---------------------------- SM-009 ----------------------------


def test_parse_plan_rejects_unknown_tool() -> None:
    with pytest.raises(llm_planner.PlannerError):
        llm_planner.parse_plan({"tool_calls": [{"tool": "drop_database", "arguments": {}}]})


def test_parse_plan_rejects_save_id_argument() -> None:
    with pytest.raises(llm_planner.PlannerError):
        llm_planner.parse_plan({"tool_calls": [{"tool": "squad_overview", "arguments": {"save_id": 2}}]})


def test_parse_plan_rejects_too_many_calls() -> None:
    calls = [{"tool": "squad_overview", "arguments": {}} for _ in range(llm_planner.MAX_TOOL_CALLS + 1)]
    with pytest.raises(llm_planner.PlannerError):
        llm_planner.parse_plan({"tool_calls": calls})


def test_parse_plan_validates_argument_ranges() -> None:
    with pytest.raises(llm_planner.PlannerError):
        llm_planner.parse_plan(
            {"tool_calls": [{"tool": "search_players", "arguments": {"min_age": 200}}]}
        )


def test_execute_plan_returns_tool_calls(db, save) -> None:
    import_document(
        db,
        scan_document(scan_id="llm-1", players=[player_row("L1", "Planned Player", ca=150, pa=170)]),
    )
    plan = llm_planner.parse_plan({"tool_calls": [{"tool": "squad_overview", "arguments": {}}]})
    result = llm_planner.execute_plan(db, save.id, plan)
    assert result.calls
    assert result.calls[0].name == "get_squad_overview", "工具名以实际 ToolCall 为准"
    assert result.trace[0]["status"] == "ok"


def test_llm_falls_back_when_not_configured(db, save, monkeypatch: pytest.MonkeyPatch) -> None:
    """未配置 LLM：回答仍是确定性结果，并说明降级原因。"""
    import_document(db, scan_document(scan_id="llm-2", players=[player_row("L2", "Fallback", ca=140, pa=160)]))
    monkeypatch.setattr(settings, "agent_llm_enabled", False)
    answer, calls = service.answer_question(db, save.id, "球队阵容怎么样")
    assert answer["mode"] == "deterministic"
    assert "llm_fallback" in answer
    assert calls


def test_llm_plan_drives_answer_without_fabricating_numbers(db, save, monkeypatch: pytest.MonkeyPatch) -> None:
    """配置 LLM 后：回答的数字必须来自工具结果。"""
    import_document(
        db,
        scan_document(scan_id="llm-3", players=[player_row("L3", "Llm Player", ca=151, pa=171)]),
    )
    monkeypatch.setattr(settings, "agent_llm_enabled", True)
    monkeypatch.setattr(settings, "agent_llm_api_key", "test-key")

    from app.agents import llm_planner as module

    def fake_client(messages):
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({"tool_calls": [{"tool": "squad_overview", "arguments": {}}]})
                    }
                }
            ]
        }

    monkeypatch.setattr(module, "chat_completion", fake_client)
    answer, calls = service.answer_question(db, save.id, "球队阵容怎么样")
    assert answer["mode"] == "llm-planned"
    facts = json.dumps([call.payload() for call in calls], ensure_ascii=False, default=str)
    assert answer["conclusion"]
    for token in [str(call.payload().get("result_summary")) for call in calls]:
        assert token in facts
    assert answer["reliability"]["calls"] == len(calls)


def test_llm_invalid_plan_falls_back(db, save, monkeypatch: pytest.MonkeyPatch) -> None:
    import_document(db, scan_document(scan_id="llm-4", players=[player_row("L4", "Bad Plan", ca=140, pa=160)]))
    monkeypatch.setattr(settings, "agent_llm_enabled", True)
    monkeypatch.setattr(settings, "agent_llm_api_key", "test-key")

    from app.agents import llm_planner as module

    def bad_client(messages):
        return {"choices": [{"message": {"content": json.dumps({"tool_calls": [{"tool": "nope", "arguments": {}}]})}}]}

    monkeypatch.setattr(module, "chat_completion", bad_client)
    answer, calls = service.answer_question(db, save.id, "球队阵容怎么样")
    assert answer["mode"] == "deterministic"
    assert answer.get("llm_fallback")
    assert calls
