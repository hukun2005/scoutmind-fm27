"""Agent 任务的类型化 State 与硬限制。

State 只保存可 JSON 序列化的业务字段：身份字段由服务端写入，模型与前端都不能覆盖；
API Key、原始存档、Traceback 一律不进入 State。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypedDict

from ..config import settings
from ..utils import utcnow

#: 执行状态机。``waiting_approval`` 与 ``paused`` 是可由用户恢复的中断态。
STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_WAITING_APPROVAL = "waiting_approval"
STATUS_PAUSED = "paused"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

ACTIVE_STATUSES = frozenset({STATUS_QUEUED, STATUS_RUNNING, STATUS_WAITING_APPROVAL, STATUS_PAUSED})
TERMINAL_STATUSES = frozenset({STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED})

#: 任务类型：规则分类器的输出之一，前端只用于展示分组。
TASK_TYPES = frozenset(
    {
        "general",
        "scout",
        "squad",
        "depth",
        "recruitment",
        "valuation",
        "price_stats",
        "similar",
        "growth",
        "compare",
        "transfer_history",
        "club_profile",
        "deal",
    }
)


class AgentTaskState(TypedDict, total=False):
    """一次 Agent 任务的完整状态（LangGraph checkpoint 的持久化对象）。"""

    # 身份：服务端注入，模型不可写
    task_id: str
    thread_id: str
    user_id: int
    save_id: int
    save_generation: int | None
    # 任务
    task_type: str
    user_goal: str
    intent: dict[str, Any]
    execution_plan: list[dict[str, Any]]
    current_step: str
    completed_steps: list[str]
    pending_steps: list[str]
    tool_results: list[dict[str, Any]]
    analysis_results: dict[str, Any]
    approval_requests: list[dict[str, Any]]
    approved_actions: list[dict[str, Any]]
    execution_status: str
    error: dict[str, Any] | None
    final_report: dict[str, Any] | None
    # 控制
    step_count: int
    tool_call_count: int
    deadline_epoch: float | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Limits:
    """一次 Runtime 的硬限制；默认来自 settings，测试可注入更小的值。"""

    max_steps: int = 8
    max_tool_calls: int = 5
    task_timeout_seconds: int = 120
    model_timeout_seconds: float = 30.0
    tool_timeout_seconds: int = 10
    max_concurrent_tasks: int = 2
    event_buffer: int = 200
    approval_ttl_seconds: int = 600

    @classmethod
    def from_settings(cls) -> Limits:
        return cls(
            max_steps=settings.agent_max_steps,
            max_tool_calls=settings.agent_max_tool_calls,
            task_timeout_seconds=settings.agent_task_timeout_seconds,
            model_timeout_seconds=settings.agent_model_timeout_seconds,
            tool_timeout_seconds=settings.agent_tool_timeout_seconds,
            max_concurrent_tasks=settings.agent_max_concurrent_tasks,
            event_buffer=settings.agent_event_buffer,
            approval_ttl_seconds=settings.agent_approval_ttl_seconds,
        )


def now_iso() -> str:
    """统一的 UTC ISO 时间戳。"""
    return utcnow().isoformat()


def new_state(
    *,
    task_id: str,
    thread_id: str,
    user_id: int,
    save_id: int,
    save_generation: int | None,
    task_type: str,
    user_goal: str,
) -> AgentTaskState:
    """构造刚创建的任务状态；所有集合字段显式初始化，避免 checkpoint 合并时出现 None。"""
    stamp = now_iso()
    return AgentTaskState(
        task_id=task_id,
        thread_id=thread_id,
        user_id=user_id,
        save_id=save_id,
        save_generation=save_generation,
        task_type=task_type,
        user_goal=user_goal,
        intent={},
        execution_plan=[],
        current_step="",
        completed_steps=[],
        pending_steps=[],
        tool_results=[],
        analysis_results={},
        approval_requests=[],
        approved_actions=[],
        execution_status=STATUS_QUEUED,
        error=None,
        final_report=None,
        step_count=0,
        tool_call_count=0,
        deadline_epoch=None,
        created_at=stamp,
        updated_at=stamp,
    )


def state_from_task(task: Any) -> AgentTaskState:
    """从数据库任务行恢复初始状态（重启恢复/断线重连）。"""
    import json

    report = None
    if getattr(task, "final_result_json", None):
        try:
            report = json.loads(task.final_result_json)
        except json.JSONDecodeError:
            report = None
    state = new_state(
        task_id=task.id,
        thread_id=task.thread_id,
        user_id=task.user_id,
        save_id=task.fm_save_id,
        save_generation=task.save_generation,
        task_type=task.task_type,
        user_goal=task.user_goal,
    )
    state["execution_status"] = task.status
    state["step_count"] = int(task.step_count or 0)
    state["tool_call_count"] = int(task.tool_call_count or 0)
    state["final_report"] = report
    if task.error_code:
        state["error"] = {"code": task.error_code, "message": task.error_summary or ""}
    return state


def progress_of(state: AgentTaskState) -> int:
    """按已完成步骤占比计算 0-100 进度；没有计划时保持 0。"""
    plan = state.get("execution_plan") or []
    if not plan:
        return 0
    done = len(state.get("completed_steps") or [])
    return max(0, min(100, int(round(done * 100 / len(plan)))))
