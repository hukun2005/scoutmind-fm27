"""V3.3.3-01 Runtime 核心：State、计划校验、Graph 执行、错误分支与 HITL 确认。"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.agent_runtime import AgentRuntime
from app.agent_runtime.approval import ApprovalService
from app.agent_runtime.exceptions import ApprovalConsumed, ApprovalExpired, PlanInvalid
from app.agent_runtime.model_provider import MockProvider, RuleProvider
from app.agent_runtime.state import Limits
from app.agent_runtime.tool_adapter import ToolAdapter
from app.models import (
    AgentApproval,
    AgentTask,
    FmSave,
    NegotiationEvent,
    SaveWriteGate,
    TransferNegotiation,
    User,
)
from tests.conftest import SessionFactory
from tests.helpers import import_document, player_row, scan_document


def _limits(**overrides) -> Limits:
    base = dict(
        max_steps=6,
        max_tool_calls=4,
        task_timeout_seconds=60,
        model_timeout_seconds=5,
        tool_timeout_seconds=5,
        max_concurrent_tasks=1,
        event_buffer=50,
        approval_ttl_seconds=60,
    )
    base.update(overrides)
    return Limits(**base)


def _runtime(provider=None, **limit_overrides) -> AgentRuntime:
    from langgraph.checkpoint.memory import InMemorySaver

    return AgentRuntime(
        session_factory=SessionFactory,
        provider=provider or RuleProvider(),
        checkpointer=InMemorySaver(),
        limits=_limits(**limit_overrides),
    )


def _seed_players(db, save: FmSave) -> None:
    document = scan_document(
        scan_id=f"v333-{save.id}",
        players=[player_row("P1", "Zhang Wei", ca=150, pa=170, position="ST", age=21)],
    )
    import_document(db, document)
    db.commit()


def _create(runtime: AgentRuntime, db, save: FmSave, goal: str, task_type: str = "general") -> AgentTask:
    user = db.scalar(select(User))
    return runtime.create_task(db, user=user, save=save, goal=goal, task_type=task_type)


def _fresh(db, task_id: str) -> AgentTask:
    db.expire_all()
    task = db.get(AgentTask, task_id)
    assert task is not None
    return task


# ---------------------------- State / 计划校验 ----------------------------


def test_tool_adapter_validation_and_limits() -> None:
    adapter = ToolAdapter(max_tool_calls=2)
    with pytest.raises(PlanInvalid):
        adapter.validate("save_everything", {})
    with pytest.raises(PlanInvalid):
        adapter.validate("search_players", {"save_id": 1})
    with pytest.raises(PlanInvalid):
        adapter.validate("search_players", {"limit": 10_000})
    with pytest.raises(PlanInvalid):
        adapter.assert_plan_size([{"tool": "squad_overview"}] * 3)
    assert adapter.requires_approval("record_negotiation") is True
    assert adapter.requires_approval("squad_overview") is False
    meta = adapter.describe("record_negotiation")
    assert meta["side_effect"] is True and meta["requires_approval"] is True
    assert meta["idempotency"] == "task-payload-hash"
    assert adapter.describe("squad_overview")["read_only"] is True


def test_rule_provider_never_emits_scope_arguments() -> None:
    reply = RuleProvider().plan(question="帮我找一个年轻前锋，预算 3000 万", tools=[], timeout=5)
    assert reply.mode == "deterministic"
    assert reply.tool_calls
    for spec in reply.tool_calls:
        assert "save_id" not in spec.arguments
        assert "user_id" not in spec.arguments


# ---------------------------- Graph 正常路径 ----------------------------


def test_squad_task_completes_with_deterministic_report(client, db, save: FmSave) -> None:
    _seed_players(db, save)
    runtime = _runtime()
    task = _create(runtime, db, save, "我的阵容结构怎么样？")
    result = runtime.run(task.id)
    assert result["execution_status"] == "completed", result.get("error")

    row = _fresh(db, task.id)
    assert row.status == "completed"
    assert row.progress == 100
    assert row.mode == "deterministic"
    assert row.final_result_json
    assert "tool_call_count" in row.final_result_json

    events = runtime.snapshot(db, row)
    assert events["pending_approvals"] == 0


def test_events_are_ordered_and_replayable(client, db, save: FmSave) -> None:
    _seed_players(db, save)
    runtime = _runtime()
    task = _create(runtime, db, save, "我的阵容怎么样？")
    runtime.run(task.id)

    from app.agent_runtime.events import TaskEventBus

    bus = TaskEventBus()
    events = bus.list_after(db, task.id, 0)
    assert [item["seq"] for item in events] == list(range(1, len(events) + 1))
    assert events[0]["type"] == "task_created"
    assert events[-1]["type"] == "task_completed"


# ---------------------------- Graph 失败/降级路径 ----------------------------


def test_provider_failure_falls_back_to_rules(client, db, save: FmSave) -> None:
    _seed_players(db, save)
    runtime = _runtime(provider=MockProvider([]))
    task = _create(runtime, db, save, "我的阵容怎么样？")
    result = runtime.run(task.id)
    assert result["execution_status"] == "completed", result
    report = result["final_report"]
    assert report["mode"] == "deterministic"
    assert report.get("llm_fallback")
    assert "MockProvider" in report["llm_fallback"]


def test_all_tools_failing_marks_task_failed(client, db, save: FmSave) -> None:
    _seed_players(db, save)
    runtime = _runtime(
        provider=MockProvider([[{"tool": "player_profile", "arguments": {"instance_id": 999_999}}]])
    )
    task = _create(runtime, db, save, "看看这个球员")
    result = runtime.run(task.id)
    assert result["execution_status"] == "failed"
    row = _fresh(db, task.id)
    assert row.status == "failed"
    assert row.error_code == "AGENT_TOOL_FAILED", (row.error_code, row.error_summary)


def test_plan_over_tool_cap_is_rejected(client, db, save: FmSave) -> None:
    _seed_players(db, save)
    runtime = _runtime(
        provider=MockProvider(
            [[{"tool": "squad_overview"}, {"tool": "position_depth"}, {"tool": "squad_overview"}]]
        ),
        max_tool_calls=2,
    )
    task = _create(runtime, db, save, "全面分析阵容")
    result = runtime.run(task.id)
    assert result["execution_status"] == "failed"
    assert _fresh(db, task.id).error_code == "AGENT_PLAN_INVALID"


def test_save_generation_mismatch_blocks_task(client, db, save: FmSave) -> None:
    _seed_players(db, save)
    db.add(SaveWriteGate(fm_save_id=save.id, generation=5))
    db.commit()
    runtime = _runtime()
    task = _create(runtime, db, save, "我的阵容怎么样？")
    row = _fresh(db, task.id)
    row.save_generation = 4
    db.commit()

    result = runtime.run(task.id)
    assert result["execution_status"] == "failed"
    assert _fresh(db, task.id).error_code == "AGENT_SCOPE_VIOLATION"


# ---------------------------- HITL 确认 ----------------------------


def _seed_negotiation(db, save: FmSave) -> TransferNegotiation:
    from app.models import PlayerInstance

    instance = db.scalar(select(PlayerInstance).where(PlayerInstance.fm_save_id == save.id))
    negotiation = TransferNegotiation(
        fm_save_id=save.id,
        player_instance_id=instance.id,
        direction="buy",
        status="DRAFT",
    )
    db.add(negotiation)
    db.commit()
    return negotiation


def _approval_plan(negotiation_id: int) -> list[dict]:
    return [
        {
            "tool": "record_negotiation",
            "arguments": {"negotiation_id": negotiation_id, "event_type": "note", "note": "第一次电话沟通"},
        }
    ]


def test_write_tool_pauses_then_executes_after_approval(client, db, save: FmSave) -> None:
    _seed_players(db, save)
    negotiation = _seed_negotiation(db, save)
    runtime = _runtime(provider=MockProvider([_approval_plan(negotiation.id)]))
    task = _create(runtime, db, save, "记录一次谈判")

    runtime.run(task.id)
    row = _fresh(db, task.id)
    assert row.status == "waiting_approval"

    pending = ApprovalService().list_pending(db, task.id)
    assert len(pending) == 1

    ApprovalService().approve(db, row, pending[0].id, user_id=row.user_id, save_id=row.fm_save_id)
    result = runtime.resume(task.id, decision="approve")
    assert result["execution_status"] == "completed", result.get("error")
    assert db.query(NegotiationEvent).filter(NegotiationEvent.negotiation_id == negotiation.id).count() == 1

    row = _fresh(db, task.id)
    assert db.get(AgentApproval, pending[0].id).status == "consumed"
    with pytest.raises(ApprovalConsumed):
        ApprovalService().approve(db, row, pending[0].id, user_id=row.user_id, save_id=row.fm_save_id)


def test_reject_ends_task_without_side_effects(client, db, save: FmSave) -> None:
    _seed_players(db, save)
    negotiation = _seed_negotiation(db, save)
    runtime = _runtime(provider=MockProvider([_approval_plan(negotiation.id)]))
    task = _create(runtime, db, save, "记录一次谈判")
    runtime.run(task.id)

    row = _fresh(db, task.id)
    pending = ApprovalService().list_pending(db, task.id)
    ApprovalService().reject(db, row, pending[0].id, user_id=row.user_id, save_id=row.fm_save_id)
    result = runtime.resume(task.id, decision="reject")
    assert result["execution_status"] == "cancelled"
    assert db.query(NegotiationEvent).filter(NegotiationEvent.negotiation_id == negotiation.id).count() == 0


def test_expired_approval_cannot_execute(client, db, save: FmSave) -> None:
    _seed_players(db, save)
    negotiation = _seed_negotiation(db, save)
    runtime = _runtime(provider=MockProvider([_approval_plan(negotiation.id)]))
    task = _create(runtime, db, save, "记录一次谈判")
    runtime.run(task.id)
    row = _fresh(db, task.id)

    record = ApprovalService().list_pending(db, task.id)[0]
    record.expires_at = __import__("datetime").datetime(2000, 1, 1)
    db.commit()
    with pytest.raises(ApprovalExpired):
        ApprovalService().approve(db, row, record.id, user_id=row.user_id, save_id=row.fm_save_id)
