"""AgentRuntime：LangGraph 任务的唯一入口。

职责：创建任务、串行执行、断点恢复、取消与重启恢复。
执行本身仍在 :mod:`app.agent_runtime.nodes`；这里只做会话、并发与状态回写。
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models import AgentTask, FmSave, User
from ..utils import utcnow
from . import persistence
from .approval import ApprovalService, current_generation
from .checkpointer import build_checkpointer
from .events import TaskEventBus
from .exceptions import AgentRuntimeError, RuntimeUnavailable, TaskConflict, TaskNotFound
from .model_provider import ModelProvider, RuleProvider, build_provider
from .state import (
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_PAUSED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    STATUS_WAITING_APPROVAL,
    TERMINAL_STATUSES,
    AgentTaskState,
    Limits,
    state_from_task,
)
from .tool_adapter import ToolAdapter

log = logging.getLogger("scoutmind.agent.runtime")

RUNTIME_VERSION = "v3.3.3-01"


class AgentRuntime:
    """进程内 Runtime；每个任务一个 thread_id，同一任务串行执行。"""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session] = SessionLocal,
        provider: ModelProvider | None = None,
        checkpointer: Any = None,
        limits: Limits | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.session_factory = session_factory
        self.limits = limits or Limits.from_settings()
        self.provider = provider or build_provider()
        self.checkpointer = checkpointer
        self.clock = clock
        self._graph: Any = None
        self._graph_error: AgentRuntimeError | None = None
        self._nodes: Any = None
        self._semaphore = threading.BoundedSemaphore(max(1, self.limits.max_concurrent_tasks))
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self._threads: dict[str, threading.Thread] = {}

    # -- 生命周期 -------------------------------------------------------------------------------
    @property
    def graph(self) -> Any:
        """惰性装配：LangGraph 缺失时只让新任务失败，旧 Agent 仍可用。"""
        if self._graph is not None:
            return self._graph
        if self._graph_error is not None:
            raise self._graph_error
        try:
            if self.checkpointer is None:
                self.checkpointer = build_checkpointer()
            from .graph import build_graph
            from .nodes import AgentNodes, NodeContext

            nodes = AgentNodes(
                NodeContext(
                    session_factory=self.session_factory,
                    adapter=ToolAdapter(max_tool_calls=self.limits.max_tool_calls),
                    provider=self.provider,
                    rule_provider=self.provider if getattr(self.provider, "provider_id", "") == "rule" else RuleProvider(),
                    events=TaskEventBus(buffer_size=self.limits.event_buffer),
                    approvals=ApprovalService(ttl_seconds=self.limits.approval_ttl_seconds),
                    limits=self.limits,
                    clock=self.clock,
                )
            )
            self._nodes = nodes
            self._graph = build_graph(nodes, self.checkpointer)
        except AgentRuntimeError as exc:
            self._graph_error = exc
            raise
        except Exception as exc:  # noqa: BLE001 - 装配失败同样要显式
            self._graph_error = RuntimeUnavailable(f"Runtime 装配失败：{exc}")
            raise self._graph_error from exc
        return self._graph

    # -- 任务创建/查询 --------------------------------------------------------------------------
    def create_task(
        self,
        session: Session,
        *,
        user: User,
        save: FmSave,
        goal: str,
        task_type: str = "general",
        conversation_id: int | None = None,
    ) -> AgentTask:
        text = (goal or "").strip()
        if not text:
            raise TaskConflict("任务目标不能为空")
        if len(text) > 2000:
            raise TaskConflict("任务目标过长（最多 2000 字）")
        task = persistence.create_task(
            session,
            user_id=user.id,
            save_id=save.id,
            save_generation=current_generation(session, save.id),
            user_goal=text,
            task_type=(task_type or "general").strip() or "general",
            conversation_id=conversation_id,
            provider_id=getattr(self.provider, "provider_id", None),
            model_id=getattr(self.provider, "model_id", None),
        )
        TaskEventBus(buffer_size=self.limits.event_buffer).append(
            session,
            task.id,
            "task_created",
            {"task_type": task.task_type, "goal": task.user_goal, "provider_id": task.provider_id},
        )
        return task

    def snapshot(self, session: Session, task: AgentTask) -> dict[str, Any]:
        return persistence.serialize_task(task, pending_approvals=persistence.pending_approval_count(session, task.id))

    # -- 执行 -----------------------------------------------------------------------------------
    def start(self, task_id: str) -> None:
        """后台线程执行；受 ``agent_max_concurrent_tasks`` 限制。"""
        thread = threading.Thread(target=self._run_guarded, args=(task_id,), name=f"agent-task-{task_id[:8]}", daemon=True)
        self._threads[task_id] = thread
        thread.start()

    def _run_guarded(self, task_id: str) -> None:
        with self._semaphore:
            try:
                self.run(task_id)
            except Exception:  # noqa: BLE001 - 后台失败必须落库，不能吞掉
                log.exception("agent task %s failed", task_id)
                self._mark_failed(task_id, "AGENT_RUNTIME_ERROR", "任务执行异常，请重试或查看诊断")

    def run(self, task_id: str) -> dict[str, Any]:
        """同步执行一个新建任务（测试与后台线程共用）。"""
        task = self._load(task_id)
        state = state_from_task(task)
        config = {
            "configurable": {"thread_id": task.thread_id},
            "recursion_limit": self.limits.max_steps * 4 + 20,
        }
        with self._lock_for(task.thread_id):
            result = self.graph.invoke(state, config)
            return self._persist(task_id, result)

    def resume(self, task_id: str, *, decision: str) -> dict[str, Any]:
        """恢复被 interrupt 挂起的任务；``decision`` 为 approve/reject。"""
        task = self._load(task_id)
        from langgraph.types import Command

        config = {
            "configurable": {"thread_id": task.thread_id},
            "recursion_limit": self.limits.max_steps * 4 + 20,
        }
        with self._lock_for(task.thread_id):
            result = self.graph.invoke(Command(resume={"decision": decision}), config)
            return self._persist(task_id, result)

    def resume_async(self, task_id: str, *, decision: str) -> None:
        thread = threading.Thread(target=self._resume_guarded, args=(task_id, decision), name=f"agent-resume-{task_id[:8]}", daemon=True)
        self._threads[task_id] = thread
        thread.start()

    def _resume_guarded(self, task_id: str, decision: str) -> None:
        with self._semaphore:
            try:
                self.resume(task_id, decision=decision)
            except Exception:  # noqa: BLE001
                log.exception("agent task %s resume failed", task_id)
                self._mark_failed(task_id, "AGENT_RUNTIME_ERROR", "任务恢复失败，请重试")

    def cancel(self, session: Session, task: AgentTask, *, reason: str = "用户取消") -> AgentTask:
        if task.status in {"completed", "failed", "cancelled"}:
            raise TaskConflict(f"任务状态为 {task.status}，不能取消")
        task.cancel_requested = True
        if task.status in {STATUS_QUEUED, STATUS_WAITING_APPROVAL, STATUS_PAUSED}:
            task.status = STATUS_CANCELLED
            task.finished_at = utcnow()
            session.commit()
            TaskEventBus(buffer_size=self.limits.event_buffer).append(session, task.id, "task_cancelled", {"reason": reason})
        else:
            session.commit()
        return task

    def recover(self, *, session_factory: Callable[[], Session] | None = None) -> int:
        """启动恢复：中断的 running/paused 任务安全标记为失败；等待确认的任务保留可恢复。"""
        factory = session_factory or self.session_factory
        session = factory()
        try:
            rows = list(session.scalars(select(AgentTask).where(AgentTask.status.in_([STATUS_RUNNING, STATUS_PAUSED]))))
            bus = TaskEventBus(buffer_size=self.limits.event_buffer)
            for task in rows:
                task.status = STATUS_FAILED
                task.error_code = "AGENT_TASK_INTERRUPTED"
                task.error_summary = "进程重启导致任务中断，请重新发起"
                task.finished_at = utcnow()
                session.commit()
                bus.append(
                    session,
                    task.id,
                    "task_failed",
                    {"code": "AGENT_TASK_INTERRUPTED", "message": "进程重启导致任务中断，请重新发起"},
                )
            return len(rows)
        finally:
            session.close()

    # -- 内部 -----------------------------------------------------------------------------------
    def _persist(self, task_id: str, result: dict[str, Any]) -> dict[str, Any]:
        state: AgentTaskState = {key: value for key, value in dict(result).items() if key != "__interrupt__"}  # type: ignore[assignment]
        session = self.session_factory()
        try:
            task = session.get(AgentTask, task_id)
            if task is None:
                raise TaskNotFound("任务不存在")
            persistence.apply_state(session, task, state)
        finally:
            session.close()
        if state.get("execution_status") in TERMINAL_STATUSES:
            self._release_task(task_id)
        return dict(result)

    def _load(self, task_id: str) -> AgentTask:
        session = self.session_factory()
        try:
            task = session.get(AgentTask, task_id)
            if task is None:
                raise TaskNotFound("任务不存在")
            session.expunge(task)
            return task
        finally:
            session.close()

    def _mark_failed(self, task_id: str, code: str, message: str) -> None:
        session = self.session_factory()
        try:
            task = session.get(AgentTask, task_id)
            if task is None:
                return
            task.status = STATUS_FAILED
            task.error_code = code
            task.error_summary = message
            task.finished_at = utcnow()
            session.commit()
            TaskEventBus(buffer_size=self.limits.event_buffer).append(
                session, task.id, "task_failed", {"code": code, "message": message}
            )
        finally:
            session.close()
        self._release_task(task_id)

    def _release_task(self, task_id: str) -> None:
        """任务终态后释放节点缓存（写缓存按任务累积，不释放会随进程运行时间增长）。"""
        nodes = getattr(self, "_nodes", None)
        if nodes is not None:
            nodes.release(task_id)

    def _lock_for(self, thread_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(thread_id, threading.Lock())


_runtime: AgentRuntime | None = None
_runtime_lock = threading.Lock()


def get_runtime() -> AgentRuntime:
    """进程级单例；测试可以直接构造独立的 :class:`AgentRuntime`。"""
    global _runtime
    with _runtime_lock:
        if _runtime is None:
            _runtime = AgentRuntime()
        return _runtime
