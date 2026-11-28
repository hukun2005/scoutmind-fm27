"""Human-in-the-loop 确认服务：一次性、载荷哈希、存档代次与 TTL。

规则：
* 同一 (task, 载荷哈希) 只会存在一个 ``pending`` 确认单，重复挂起返回同一张（幂等）。
* 确认只能消费一次；消费后再调用返回 ``AGENT_APPROVAL_CONSUMED``。
* 过期单在读取/决策时被标记为 ``expired``，不会被执行。
* 决策时必须重新校验用户、存档与 ``save_generation``：存档更新后旧确认单自动失效。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import AgentApproval, AgentTask, SaveWriteGate
from ..utils import utcnow
from .exceptions import ApprovalConsumed, ApprovalExpired, ApprovalInvalid, ScopeViolation

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_EXPIRED = "expired"
STATUS_CONSUMED = "consumed"


def canonical_hash(payload: dict[str, Any]) -> str:
    """载荷哈希：键排序 + 紧凑分隔符，确保同一操作得到同一哈希。"""
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def current_generation(session: Session, save_id: int) -> int | None:
    """存档当前写入代次；没有 gate 行时为 None（视为未启用代次校验）。"""
    gate = session.scalar(select(SaveWriteGate).where(SaveWriteGate.fm_save_id == save_id))
    return None if gate is None else int(gate.generation)


class ApprovalService:
    """确认单的生命周期管理。"""

    def __init__(self, *, ttl_seconds: int | None = None) -> None:
        self.ttl_seconds = int(ttl_seconds or settings.agent_approval_ttl_seconds)

    def ensure_pending(
        self,
        session: Session,
        task: AgentTask,
        *,
        operation_type: str,
        payload: dict[str, Any],
        reason: str,
        approval_type: str = "write_operation",
    ) -> AgentApproval:
        """返回一张可用的 pending 确认单；重复调用不会生成第二张。"""
        payload_hash = canonical_hash(payload)
        latest = session.scalar(
            select(AgentApproval)
            .where(AgentApproval.task_id == task.id, AgentApproval.payload_hash == payload_hash)
            .order_by(AgentApproval.created_at.desc())
            .limit(1)
        )
        now = utcnow()
        if latest is not None:
            # 恢复（resume）会从节点开头重放：必须复用用户刚才决策的那张单，
            # 否则 apply_approved 会拿到一张新的 pending 单而拒绝执行。
            if latest.status in {STATUS_PENDING, STATUS_APPROVED, STATUS_CONSUMED}:
                if latest.status != STATUS_PENDING or latest.expires_at > now:
                    return latest
            if latest.status == STATUS_PENDING and latest.expires_at <= now:
                latest.status = STATUS_EXPIRED
                session.commit()
        record = AgentApproval(
            id=str(uuid.uuid4()),
            task_id=task.id,
            approval_type=approval_type,
            operation_type=operation_type,
            payload_json=json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str),
            payload_hash=payload_hash,
            reason=reason,
            status=STATUS_PENDING,
            user_id=task.user_id,
            fm_save_id=task.fm_save_id,
            save_generation=task.save_generation,
            expires_at=now + timedelta(seconds=self.ttl_seconds),
        )
        session.add(record)
        session.commit()
        return record

    def list_pending(self, session: Session, task_id: str) -> list[AgentApproval]:
        """列出未过期、未决策的确认单，并顺手把过期单标记为 expired。"""
        rows = list(
            session.scalars(
                select(AgentApproval)
                .where(AgentApproval.task_id == task_id, AgentApproval.status == STATUS_PENDING)
                .order_by(AgentApproval.created_at)
            )
        )
        now = utcnow()
        expired = [row for row in rows if row.expires_at <= now]
        for row in expired:
            row.status = STATUS_EXPIRED
        if expired:
            session.commit()
        return [row for row in rows if row.status == STATUS_PENDING]

    def get(self, session: Session, task: AgentTask, approval_id: str) -> AgentApproval:
        record = session.get(AgentApproval, approval_id)
        if record is None or record.task_id != task.id:
            raise ApprovalInvalid("确认单不存在", details={"approval_id": approval_id})
        return record

    def _assert_scope(self, session: Session, task: AgentTask, record: AgentApproval, *, user_id: int, save_id: int) -> None:
        if record.user_id != user_id or task.user_id != user_id:
            raise ScopeViolation("确认单不属于当前用户")
        if record.fm_save_id != save_id or task.fm_save_id != save_id:
            raise ScopeViolation("确认单不属于当前存档")
        generation = current_generation(session, save_id)
        expected = record.save_generation
        if expected is not None and generation is not None and expected != generation:
            raise ApprovalInvalid("存档已切换，确认单失效", details={"expected_generation": expected, "current_generation": generation})

    def _refresh_expiry(self, session: Session, record: AgentApproval) -> None:
        if record.status == STATUS_PENDING and record.expires_at <= utcnow():
            record.status = STATUS_EXPIRED
            session.commit()
            raise ApprovalExpired("确认单已过期")

    def approve(
        self,
        session: Session,
        task: AgentTask,
        approval_id: str,
        *,
        user_id: int,
        save_id: int,
    ) -> AgentApproval:
        record = self.get(session, task, approval_id)
        self._assert_scope(session, task, record, user_id=user_id, save_id=save_id)
        if record.status == STATUS_CONSUMED:
            raise ApprovalConsumed("确认单已被使用")
        if record.status != STATUS_PENDING:
            raise ApprovalInvalid(f"确认单状态为 {record.status}，不能确认")
        self._refresh_expiry(session, record)
        record.status = STATUS_APPROVED
        record.decided_at = utcnow()
        session.commit()
        return record

    def reject(
        self,
        session: Session,
        task: AgentTask,
        approval_id: str,
        *,
        user_id: int,
        save_id: int,
    ) -> AgentApproval:
        record = self.get(session, task, approval_id)
        self._assert_scope(session, task, record, user_id=user_id, save_id=save_id)
        if record.status == STATUS_CONSUMED:
            raise ApprovalConsumed("确认单已被使用")
        if record.status != STATUS_PENDING:
            raise ApprovalInvalid(f"确认单状态为 {record.status}，不能拒绝")
        self._refresh_expiry(session, record)
        record.status = STATUS_REJECTED
        record.decided_at = utcnow()
        session.commit()
        return record

    def consume(self, session: Session, record: AgentApproval) -> AgentApproval:
        """一次性消费：只有 approved 且未消费的确认单可以进入副作用执行。"""
        if record.status == STATUS_CONSUMED:
            raise ApprovalConsumed("确认单已被使用")
        if record.status != STATUS_APPROVED:
            raise ApprovalInvalid(f"确认单状态为 {record.status}，不能执行")
        record.status = STATUS_CONSUMED
        record.consumed_at = utcnow()
        session.commit()
        return record
