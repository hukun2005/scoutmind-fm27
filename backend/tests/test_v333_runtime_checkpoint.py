"""V3.3.3-01 Checkpoint：SQLite 持久化、重启恢复与多任务隔离。"""

from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy import select

from app.agent_runtime import AgentRuntime
from app.agent_runtime.approval import ApprovalService
from app.agent_runtime.checkpointer import checkpoint_path
from app.agent_runtime.model_provider import MockProvider
from app.agent_runtime.state import Limits
from app.config import settings
from app.models import AgentTask, FmSave, NegotiationEvent, TransferNegotiation, User
from tests.conftest import SessionFactory
from tests.helpers import import_document, player_row, scan_document


def _limits() -> Limits:
    return Limits(
        max_steps=6,
        max_tool_calls=4,
        task_timeout_seconds=60,
        model_timeout_seconds=5,
        tool_timeout_seconds=5,
        max_concurrent_tasks=2,
        event_buffer=50,
        approval_ttl_seconds=300,
    )


def _seed(db, save: FmSave) -> TransferNegotiation:
    document = scan_document(
        scan_id=f"cp-{save.id}", players=[player_row("CP1", "Checkpoint Player", ca=150, pa=170)]
    )
    import_document(db, document)
    db.commit()
    from app.models import PlayerInstance

    instance = db.scalar(select(PlayerInstance).where(PlayerInstance.fm_save_id == save.id))
    negotiation = TransferNegotiation(
        fm_save_id=save.id, player_instance_id=instance.id, direction="buy", status="DRAFT"
    )
    db.add(negotiation)
    db.commit()
    return negotiation


def _plan(negotiation_id: int) -> list[dict]:
    return [
        {
            "tool": "record_negotiation",
            "arguments": {"negotiation_id": negotiation_id, "event_type": "note", "note": "检查点测试"},
        }
    ]


def _runtime(provider=None) -> AgentRuntime:
    return AgentRuntime(
        session_factory=SessionFactory,
        provider=provider or MockProvider([]),
        limits=_limits(),
    )


def test_checkpoint_file_is_sqlite_wal(client, db, save: FmSave, monkeypatch, tmp_path) -> None:
    target = tmp_path / "agent-checkpoints.db"
    monkeypatch.setattr(settings, "agent_checkpoint_path", str(target), raising=False)
    assert checkpoint_path() == target

    runtime = _runtime()
    _seed(db, save)
    user = db.scalar(select(User))
    task = runtime.create_task(db, user=user, save=save, goal="我的阵容怎么样？")
    runtime.run(task.id)

    assert target.exists()
    connection = sqlite3.connect(target)
    try:
        mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        tables = {row[0] for row in connection.execute("select name from sqlite_master where type='table'")}
    finally:
        connection.close()
    assert str(mode).lower() == "wal"
    assert any("checkpoint" in name for name in tables)


def test_resume_after_runtime_restart(client, db, save: FmSave, monkeypatch, tmp_path) -> None:
    """新 Runtime 实例（模拟进程重启）能从 SQLite checkpoint 恢复挂起的任务。"""
    monkeypatch.setattr(settings, "agent_checkpoint_path", str(tmp_path / "restart.db"), raising=False)
    negotiation = _seed(db, save)
    user = db.scalar(select(User))

    first = _runtime(provider=MockProvider([_plan(negotiation.id)]))
    task = first.create_task(db, user=user, save=save, goal="记录一次谈判")
    first.run(task.id)
    db.expire_all()
    assert db.get(AgentTask, task.id).status == "waiting_approval"

    second = _runtime(provider=MockProvider([]))
    row = db.get(AgentTask, task.id)
    pending = ApprovalService().list_pending(db, task.id)
    ApprovalService().approve(db, row, pending[0].id, user_id=row.user_id, save_id=row.fm_save_id)
    result = second.resume(task.id, decision="approve")

    assert result["execution_status"] == "completed", result.get("error")
    assert db.query(NegotiationEvent).filter(NegotiationEvent.negotiation_id == negotiation.id).count() == 1


def test_two_tasks_do_not_share_thread_state(client, db, save: FmSave, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "agent_checkpoint_path", str(tmp_path / "iso.db"), raising=False)
    negotiation = _seed(db, save)
    user = db.scalar(select(User))

    runtime = _runtime(provider=MockProvider([_plan(negotiation.id)]))
    waiting = runtime.create_task(db, user=user, save=save, goal="记录一次谈判")
    runtime.run(waiting.id)

    other = runtime.create_task(db, user=user, save=save, goal="我的阵容怎么样？")
    runtime.run(other.id)
    db.expire_all()
    assert db.get(AgentTask, other.id).status == "completed"
    assert db.get(AgentTask, waiting.id).status == "waiting_approval"

    row = db.get(AgentTask, waiting.id)
    pending = ApprovalService().list_pending(db, waiting.id)
    ApprovalService().approve(db, row, pending[0].id, user_id=row.user_id, save_id=row.fm_save_id)
    result = runtime.resume(waiting.id, decision="approve")
    assert result["execution_status"] == "completed", result.get("error")
