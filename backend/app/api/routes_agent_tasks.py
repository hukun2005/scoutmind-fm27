"""V3.3.3-01 Agent 任务 API：创建、查询、事件重放、SSE、取消与人工确认。

与既有 ``/agent/conversations*``、``/agent/director/*`` 并存：旧端点与规则路径完全保留。
所有端点都依赖当前用户与当前存档；任务不属于当前作用域时统一 404。
"""

from __future__ import annotations

import json
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..agent_runtime import AgentRuntimeError, get_runtime
from ..agent_runtime import persistence
from ..agent_runtime.approval import ApprovalService
from ..agent_runtime.events import TaskEventBus
from ..agent_runtime.exceptions import TaskConflict, TaskNotFound
from ..db import get_db
from ..models import AgentApproval, AgentConversation, AgentTask, FmSave
from ..schemas import AgentApprovalDecisionIn, AgentTaskCreateIn
from .deps import get_active_save, get_current_user

router = APIRouter()

TERMINAL = {"completed", "failed", "cancelled"}


def _http(exc: AgentRuntimeError) -> HTTPException:
    return HTTPException(status_code=exc.http_status, detail={"code": exc.code, "message": str(exc)})


def _task_for(db: Session, task_id: str, user, save: FmSave) -> AgentTask:
    try:
        return persistence.task_in_scope(db, task_id, user_id=user.id, save_id=save.id)
    except TaskNotFound as exc:
        raise _http(exc) from exc


def _conversation_owned(db: Session, conversation_id: int, user, save: FmSave) -> None:
    conversation = db.get(AgentConversation, conversation_id)
    if conversation is None or conversation.user_id != user.id or conversation.fm_save_id != save.id:
        raise HTTPException(status_code=404, detail={"code": "conversation_not_found", "message": "会话不存在"})


@router.post("/agent/tasks", status_code=201, summary="创建 Agent 任务")
def create_task(
    body: AgentTaskCreateIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    if body.conversation_id is not None:
        _conversation_owned(db, body.conversation_id, user, save)
    runtime = get_runtime()
    try:
        task = runtime.create_task(
            db,
            user=user,
            save=save,
            goal=body.goal,
            task_type=body.task_type,
            conversation_id=body.conversation_id,
        )
    except AgentRuntimeError as exc:
        raise _http(exc) from exc
    runtime.start(task.id)
    return runtime.snapshot(db, task)


@router.get("/agent/tasks", summary="当前存档的 Agent 任务列表")
def list_tasks(
    status_filter: str | None = Query(default=None, alias="status", max_length=24),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    conditions = [AgentTask.fm_save_id == save.id, AgentTask.user_id == user.id]
    if status_filter:
        conditions.append(AgentTask.status == status_filter)
    total = int(db.scalar(select(func.count()).select_from(AgentTask).where(*conditions)) or 0)
    rows = list(
        db.scalars(
            select(AgentTask)
            .where(*conditions)
            .order_by(AgentTask.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    runtime = get_runtime()
    return {"items": [runtime.snapshot(db, row) for row in rows], "total": total}


@router.get("/agent/tasks/{task_id}", summary="Agent 任务详情")
def task_detail(
    task_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    task = _task_for(db, task_id, user, save)
    return get_runtime().snapshot(db, task)


@router.get("/agent/tasks/{task_id}/events", summary="按游标重放任务事件")
def task_events(
    task_id: str,
    after: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    _task_for(db, task_id, user, save)
    items = TaskEventBus().list_after(db, task_id, after, limit)
    return {"items": items, "next": items[-1]["seq"] if items else after, "total": len(items)}


@router.get("/agent/tasks/{task_id}/events/stream", summary="SSE 事件流（Last-Event-ID 续传）")
def task_events_stream(
    task_id: str,
    request: Request,
    after: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
):
    _task_for(db, task_id, user, save)
    header_cursor = request.headers.get("last-event-id")
    cursor = max(int(header_cursor) if header_cursor and header_cursor.isdigit() else 0, int(after))

    def generate():
        nonlocal cursor
        from ..db import SessionLocal

        bus = TaskEventBus()
        started = time.monotonic()
        while time.monotonic() - started < 600:
            session = SessionLocal()
            try:
                events = bus.list_after(session, task_id, cursor, 200)
                row = session.get(AgentTask, task_id)
                status = row.status if row is not None else "failed"
            finally:
                session.close()
            if not events and status in TERMINAL:
                yield "event: done\ndata: {}\n\n"
                return
            for event in events:
                cursor = int(event["seq"])
                yield (
                    f"id: {cursor}\n"
                    f"event: {event['type']}\n"
                    f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                )
            if status in TERMINAL and not events:
                yield "event: done\ndata: {}\n\n"
                return
            yield ": heartbeat\n\n"
            time.sleep(0.5)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@router.post("/agent/tasks/{task_id}/cancel", summary="取消任务（幂等）")
def cancel_task(
    task_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    task = _task_for(db, task_id, user, save)
    runtime = get_runtime()
    try:
        runtime.cancel(db, task)
    except TaskConflict as exc:
        # 已结束的任务再次取消视为成功（幂等），只有非法状态才报错。
        if task.status not in TERMINAL:
            raise _http(exc) from exc
    return runtime.snapshot(db, task)


@router.get("/agent/tasks/{task_id}/approvals", summary="待确认操作")
def list_approvals(
    task_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    _task_for(db, task_id, user, save)
    records = ApprovalService().list_pending(db, task_id)
    return {"items": [persistence.serialize_approval(record) for record in records], "total": len(records)}


@router.post("/agent/tasks/{task_id}/approvals/{approval_id}/approve", summary="确认并继续执行")
def approve(
    task_id: str,
    approval_id: str,
    body: AgentApprovalDecisionIn | None = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    task = _task_for(db, task_id, user, save)
    if task.status != "waiting_approval":
        raise HTTPException(
            status_code=409,
            detail={"code": "AGENT_TASK_CONFLICT", "message": f"任务状态为 {task.status}，没有待确认操作"},
        )
    runtime = get_runtime()
    try:
        ApprovalService().approve(db, task, approval_id, user_id=user.id, save_id=save.id)
        runtime.resume(task_id, decision="approve")
    except AgentRuntimeError as exc:
        raise _http(exc) from exc
    db.expire_all()
    refreshed = db.get(AgentTask, task_id)
    return runtime.snapshot(db, refreshed)  # type: ignore[arg-type]


@router.post("/agent/tasks/{task_id}/approvals/{approval_id}/reject", summary="拒绝并安全结束")
def reject(
    task_id: str,
    approval_id: str,
    body: AgentApprovalDecisionIn | None = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    task = _task_for(db, task_id, user, save)
    if task.status != "waiting_approval":
        raise HTTPException(
            status_code=409,
            detail={"code": "AGENT_TASK_CONFLICT", "message": f"任务状态为 {task.status}，没有待确认操作"},
        )
    runtime = get_runtime()
    try:
        ApprovalService().reject(db, task, approval_id, user_id=user.id, save_id=save.id)
        runtime.resume(task_id, decision="reject")
    except AgentRuntimeError as exc:
        raise _http(exc) from exc
    db.expire_all()
    refreshed = db.get(AgentTask, task_id)
    return runtime.snapshot(db, refreshed)  # type: ignore[arg-type]


@router.post("/agent/tasks/{task_id}/resume", summary="恢复已确认但未执行的暂停任务")
def resume_task(
    task_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    task = _task_for(db, task_id, user, save)
    approved = db.scalar(
        select(AgentApproval)
        .where(AgentApproval.task_id == task.id, AgentApproval.status == "approved")
        .order_by(AgentApproval.created_at.desc())
        .limit(1)
    )
    if approved is None:
        raise HTTPException(
            status_code=409,
            detail={"code": "AGENT_APPROVAL_REQUIRED", "message": "没有已确认的待执行操作"},
        )
    runtime = get_runtime()
    try:
        runtime.resume(task_id, decision="approve")
    except AgentRuntimeError as exc:
        raise _http(exc) from exc
    db.expire_all()
    refreshed = db.get(AgentTask, task_id)
    return runtime.snapshot(db, refreshed)  # type: ignore[arg-type]
