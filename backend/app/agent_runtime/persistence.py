"""任务持久化：业务库中的 ``agent_tasks`` 行及其 API 序列化。"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import AgentApproval, AgentTask
from ..utils import iso, utcnow
from .exceptions import TaskNotFound
from .state import STATUS_QUEUED, AgentTaskState, progress_of


def new_task_id() -> str:
    return str(uuid.uuid4())


def create_task(
    session: Session,
    *,
    user_id: int,
    save_id: int,
    save_generation: int | None,
    user_goal: str,
    task_type: str = "general",
    conversation_id: int | None = None,
    provider_id: str | None = None,
    model_id: str | None = None,
) -> AgentTask:
    task = AgentTask(
        id=new_task_id(),
        thread_id=new_task_id(),
        conversation_id=conversation_id,
        user_id=user_id,
        fm_save_id=save_id,
        save_generation=save_generation,
        task_type=task_type,
        user_goal=user_goal,
        status=STATUS_QUEUED,
        provider_id=provider_id,
        model_id=model_id,
    )
    session.add(task)
    session.commit()
    return task


def get_task(session: Session, task_id: str) -> AgentTask | None:
    return session.get(AgentTask, task_id)


def task_in_scope(session: Session, task_id: str, *, user_id: int, save_id: int) -> AgentTask:
    """任务必须属于当前用户与当前存档；否则统一 404，不泄露存在性。"""
    task = session.get(AgentTask, task_id)
    if task is None or task.user_id != user_id or task.fm_save_id != save_id:
        raise TaskNotFound("任务不存在")
    return task


def apply_state(session: Session, task: AgentTask, state: AgentTaskState) -> AgentTask:
    """把最终 State 的关键字段写回任务行（状态、进度、计数、报告、错误）。"""
    status = str(state.get("execution_status") or task.status)
    task.status = status
    task.progress = progress_of(state)
    task.step_count = int(state.get("step_count") or 0)
    task.tool_call_count = int(state.get("tool_call_count") or 0)
    task.current_step = str(state.get("current_step") or "")[:64] or None
    error = state.get("error") or None
    task.error_code = str(error.get("code"))[:64] if error else None
    task.error_summary = str(error.get("message"))[:1000] if error else None
    report = state.get("final_report")
    task.final_result_json = json.dumps(report, ensure_ascii=False, default=str) if report else None
    if report and isinstance(report, dict):
        task.mode = str(report.get("mode") or task.mode or "deterministic")[:24]
    if status == "running" and task.started_at is None:
        task.started_at = utcnow()
    if status in {"completed", "failed", "cancelled"}:
        task.finished_at = utcnow()
    session.commit()
    return task


def pending_approval_count(session: Session, task_id: str) -> int:
    return int(
        session.scalar(
            select(func.count()).select_from(AgentApproval).where(
                AgentApproval.task_id == task_id, AgentApproval.status == "pending"
            )
        )
        or 0
    )


def serialize_approval(record: AgentApproval) -> dict[str, Any]:
    try:
        payload = json.loads(record.payload_json or "{}")
    except json.JSONDecodeError:
        payload = {}
    expired = record.status == "pending" and record.expires_at <= utcnow()
    return {
        "id": record.id,
        "task_id": record.task_id,
        "approval_type": record.approval_type,
        "operation_type": record.operation_type,
        "payload": payload,
        "reason": record.reason,
        "status": "expired" if expired else record.status,
        "expires_at": iso(record.expires_at),
        "created_at": iso(record.created_at),
        "decided_at": iso(record.decided_at) if record.decided_at else None,
        "consumed_at": iso(record.consumed_at) if record.consumed_at else None,
    }


def serialize_task(task: AgentTask, *, pending_approvals: int = 0) -> dict[str, Any]:
    """列表/详情共用的安全结构：不含用户、存档、线程等内部标识。"""
    report = None
    if task.final_result_json:
        try:
            report = json.loads(task.final_result_json)
        except json.JSONDecodeError:
            report = None
    return {
        "id": task.id,
        "task_type": task.task_type,
        "user_goal": task.user_goal,
        "status": task.status,
        "progress": task.progress,
        "current_step": task.current_step,
        "mode": task.mode,
        "provider_id": task.provider_id,
        "model_id": task.model_id,
        "step_count": task.step_count,
        "tool_call_count": task.tool_call_count,
        "pending_approvals": pending_approvals,
        "report": report,
        "error": {"code": task.error_code, "message": task.error_summary} if task.error_code else None,
        "created_at": iso(task.created_at),
        "updated_at": iso(task.updated_at),
        "started_at": iso(task.started_at) if task.started_at else None,
        "finished_at": iso(task.finished_at) if task.finished_at else None,
    }
