"""V3.3.3-01 Agent 任务 API：作用域隔离、事件重放、SSE、确认与取消。"""

from __future__ import annotations

import time
from typing import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.agent_runtime import AgentRuntime
from app.agent_runtime.model_provider import MockProvider
from app.agent_runtime.state import Limits
from app.api import routes_agent_tasks
from app.models import AgentTask, FmSave, NegotiationEvent, PlayerInstance, TransferNegotiation, User
from tests.conftest import SessionFactory
from tests.helpers import import_document, player_row, scan_document


def _wait(predicate: Callable[[], bool], timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def _seed(db, save: FmSave) -> TransferNegotiation:
    document = scan_document(
        scan_id=f"api-{save.id}", players=[player_row("A1", "API Player", ca=150, pa=170)]
    )
    import_document(db, document)
    db.commit()
    instance = db.scalar(select(PlayerInstance).where(PlayerInstance.fm_save_id == save.id))
    negotiation = TransferNegotiation(
        fm_save_id=save.id, player_instance_id=instance.id, direction="buy", status="DRAFT"
    )
    db.add(negotiation)
    db.commit()
    return negotiation


def _runtime_with(replies: list[list[dict]]) -> AgentRuntime:
    from langgraph.checkpoint.memory import InMemorySaver

    return AgentRuntime(
        session_factory=SessionFactory,
        provider=MockProvider(replies),
        checkpointer=InMemorySaver(),
        limits=Limits(
            max_steps=6,
            max_tool_calls=4,
            task_timeout_seconds=60,
            model_timeout_seconds=5,
            tool_timeout_seconds=5,
            max_concurrent_tasks=1,
            event_buffer=50,
            approval_ttl_seconds=300,
        ),
    )


def test_create_task_runs_and_completes(client: TestClient, db, save: FmSave, monkeypatch) -> None:
    _seed(db, save)
    runtime = _runtime_with([])
    monkeypatch.setattr(routes_agent_tasks, "get_runtime", lambda: runtime)

    response = client.post("/api/v1/agent/tasks", json={"goal": "我的阵容怎么样？"})
    assert response.status_code == 201, response.text
    task_id = response.json()["id"]

    assert _wait(lambda: _status(db, task_id) == "completed"), _status(db, task_id)

    detail = client.get(f"/api/v1/agent/tasks/{task_id}").json()
    assert detail["status"] == "completed"
    assert detail["report"]["mode"] == "deterministic"

    events = client.get(f"/api/v1/agent/tasks/{task_id}/events").json()
    types = [item["type"] for item in events["items"]]
    assert "task_created" in types
    assert "task_completed" in types


def _status(db, task_id: str) -> str | None:
    db.expire_all()
    row = db.get(AgentTask, task_id)
    return None if row is None else row.status


def test_task_is_scoped_to_current_save(client: TestClient, db, save: FmSave, monkeypatch) -> None:
    _seed(db, save)
    runtime = _runtime_with([])
    monkeypatch.setattr(routes_agent_tasks, "get_runtime", lambda: runtime)
    task_id = client.post("/api/v1/agent/tasks", json={"goal": "阵容怎么样"}).json()["id"]
    assert _wait(lambda: _status(db, task_id) == "completed")

    user = db.scalar(select(User))
    other = FmSave(user_id=user.id, name="另一个存档", game_version="27.1", game_build="x", is_active=False)
    db.add(other)
    db.commit()

    cross = client.get(f"/api/v1/agent/tasks/{task_id}?save_id={other.id}")
    assert cross.status_code == 404
    assert cross.json()["error"]["code"] == "AGENT_TASK_NOT_FOUND"


def test_approval_flow_via_api(client: TestClient, db, save: FmSave, monkeypatch) -> None:
    negotiation = _seed(db, save)
    runtime = _runtime_with(
        [[{"tool": "record_negotiation", "arguments": {"negotiation_id": negotiation.id, "event_type": "note", "note": "API"}}]]
    )
    monkeypatch.setattr(routes_agent_tasks, "get_runtime", lambda: runtime)

    task_id = client.post("/api/v1/agent/tasks", json={"goal": "记录一次谈判"}).json()["id"]
    assert _wait(lambda: _status(db, task_id) == "waiting_approval"), _status(db, task_id)

    approvals = client.get(f"/api/v1/agent/tasks/{task_id}/approvals").json()
    assert approvals["total"] == 1
    approval_id = approvals["items"][0]["id"]

    approved = client.post(f"/api/v1/agent/tasks/{task_id}/approvals/{approval_id}/approve", json={})
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "completed"
    assert db.query(NegotiationEvent).filter(NegotiationEvent.negotiation_id == negotiation.id).count() == 1

    again = client.post(f"/api/v1/agent/tasks/{task_id}/approvals/{approval_id}/approve", json={})
    assert again.status_code == 409
    assert again.json()["error"]["code"] in {"AGENT_APPROVAL_INVALID", "AGENT_APPROVAL_CONSUMED", "AGENT_TASK_CONFLICT"}


def test_cancel_waiting_task(client: TestClient, db, save: FmSave, monkeypatch) -> None:
    negotiation = _seed(db, save)
    runtime = _runtime_with(
        [[{"tool": "record_negotiation", "arguments": {"negotiation_id": negotiation.id, "event_type": "note", "note": "取消"}}]]
    )
    monkeypatch.setattr(routes_agent_tasks, "get_runtime", lambda: runtime)
    task_id = client.post("/api/v1/agent/tasks", json={"goal": "记录一次谈判"}).json()["id"]
    assert _wait(lambda: _status(db, task_id) == "waiting_approval")

    cancelled = client.post(f"/api/v1/agent/tasks/{task_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    # 幂等：再取消一次仍是 cancelled，不报错。
    assert client.post(f"/api/v1/agent/tasks/{task_id}/cancel").json()["status"] == "cancelled"


def test_sse_stream_replays_until_terminal(client: TestClient, db, save: FmSave, monkeypatch) -> None:
    _seed(db, save)
    runtime = _runtime_with([])
    monkeypatch.setattr(routes_agent_tasks, "get_runtime", lambda: runtime)
    task_id = client.post("/api/v1/agent/tasks", json={"goal": "我的阵容怎么样？"}).json()["id"]
    assert _wait(lambda: _status(db, task_id) == "completed")

    with client.stream("GET", f"/api/v1/agent/tasks/{task_id}/events/stream") as response:
        body = "".join(chunk for chunk in response.iter_text())
    assert response.status_code == 200
    assert "event: task_completed" in body
    assert "event: done" in body
