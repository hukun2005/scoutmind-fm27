"""任务事件流：写入业务库并以游标重放。

事件只保存用户可读/前端可渲染的轻量载荷：不包含 API Key、原始存档、完整 State 或 Traceback。
SSE 与轮询都按 ``seq`` 游标读取，因此断线后可以从 ``Last-Event-ID`` 精确续传。
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import event as sa_event
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import AgentTaskEvent

EVENT_TYPES = frozenset(
    {
        "task_created",
        "task_started",
        "plan_created",
        "step_started",
        "tool_started",
        "tool_completed",
        "analysis_updated",
        "approval_required",
        "task_paused",
        "task_resumed",
        "task_completed",
        "task_failed",
        "task_cancelled",
    }
)

_MAX_STRING = 4000
_SENSITIVE = ("api_key", "apikey", "token", "secret", "password", "traceback")
# 事务内 seq 缓存：同一事务连续追加事件时不再每条都做一次 MAX(seq) 扫描。
# 事务结束即失效，避免另一个会话/线程已写入更高 seq 时仍复用旧值。
_SEQ_CACHE = "agent_event_seq"


@sa_event.listens_for(Session, "after_commit")
@sa_event.listens_for(Session, "after_rollback")
def _drop_seq_cache(session: Session) -> None:
    session.info.pop(_SEQ_CACHE, None)


def sanitize(payload: Any, *, depth: int = 0) -> Any:
    """移除敏感键并限制体积；保证事件可 JSON 序列化。"""
    if depth > 6:
        return "…"
    if isinstance(payload, dict):
        cleaned: dict[str, Any] = {}
        for key, value in payload.items():
            lowered = str(key).lower()
            if any(marker in lowered for marker in _SENSITIVE):
                continue
            cleaned[str(key)] = sanitize(value, depth=depth + 1)
        return cleaned
    if isinstance(payload, (list, tuple)):
        return [sanitize(item, depth=depth + 1) for item in payload[:50]]
    if isinstance(payload, str):
        return payload if len(payload) <= _MAX_STRING else payload[:_MAX_STRING] + "…"
    if isinstance(payload, (int, float, bool)) or payload is None:
        return payload
    return str(payload)[:_MAX_STRING]


class TaskEventBus:
    """按任务顺序追加事件；``seq`` 在任务内严格递增。"""

    def __init__(self, *, buffer_size: int = 200) -> None:
        self.buffer_size = buffer_size

    def append(
        self,
        session: Session,
        task_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        commit: bool = True,
    ) -> dict[str, Any]:
        if event_type not in EVENT_TYPES:
            raise ValueError(f"未知事件类型：{event_type}")
        cache: dict[str, int] = session.info.setdefault(_SEQ_CACHE, {})
        seq = cache.get(task_id)
        if seq is None:
            seq = int(
                session.scalar(select(func.max(AgentTaskEvent.seq)).where(AgentTaskEvent.task_id == task_id))
                or 0
            )
        next_seq = int(seq) + 1
        record = AgentTaskEvent(
            task_id=task_id,
            seq=next_seq,
            event_type=event_type,
            payload_json=json.dumps(sanitize(payload or {}), ensure_ascii=False, default=str),
        )
        session.add(record)
        try:
            session.flush()
        except Exception:
            # 回滚后缓存可能领先于数据库，丢弃以便下次重新读取 MAX(seq)。
            cache.pop(task_id, None)
            raise
        cache[task_id] = next_seq
        data = serialize_event(record)
        if commit:
            session.commit()
        return data

    def list_after(self, session: Session, task_id: str, after: int = 0, limit: int = 500) -> list[dict[str, Any]]:
        rows = session.scalars(
            select(AgentTaskEvent)
            .where(AgentTaskEvent.task_id == task_id, AgentTaskEvent.seq > max(0, int(after)))
            .order_by(AgentTaskEvent.seq)
            .limit(max(1, min(int(limit), 1000)))
        )
        return [serialize_event(row) for row in rows]


def serialize_event(row: AgentTaskEvent) -> dict[str, Any]:
    try:
        payload = json.loads(row.payload_json or "{}")
    except json.JSONDecodeError:
        payload = {}
    return {
        "id": row.id,
        "seq": row.seq,
        "type": row.event_type,
        "payload": payload,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
