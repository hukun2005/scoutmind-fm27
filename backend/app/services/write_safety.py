"""统一写入安全协议（V3.2.7.3）。

目标：自动采集、手动同步、CLI、HTTP 与后台导入线程共用同一套写入资格判定。

写入资格 = 有效身份 + 有效会话 + 一致指纹 + 当前代次（Epoch） + 唯一操作（Operation）。

关键设计：代次校验不是"先查一次再写"。调用方在**写入数据的同一个事务**里执行
:meth:`WriteFence.assert_current`，它是一条带代次条件的 UPDATE：

* PostgreSQL（READ COMMITTED）：并发切换提交后，条件重判失败，``rowcount == 0``。
* SQLite：写事务持有整库写锁，切换事务无法在 fence 与 commit 之间插入；先提交的切换
  会让条件不再匹配。

因此不存在"检查通过后等待其他操作再 INSERT"的竞态窗口。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from ..api.save_context import resolve_save_context
from ..config import settings as default_settings
from ..models import FmSave, SaveSession, SaveWriteGate
from ..utils import utcnow
from . import save_identity as identity_service

PROTOCOL_VERSION = "write-safety/v1"

WRITE_CONTEXT_REQUIRED = "write_context_required"
WRITE_FENCE_STALE = "write_fence_stale"
WRITE_EPOCH_STALE = "write_session_epoch_stale"
WRITE_GATE_BUSY = "write_gate_busy"
WRITE_OPERATION_REUSED = "write_operation_reused"

#: 允许继续写入的会话状态（与 save_context 保持一致）。
_WRITABLE_SESSION_STATUSES = {"verified"}
_ENDED_SESSION_STATUSES = {"invalidated", "closed"}


def _fail(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


class WriteRejected(Exception):
    """写入被 fence 拒绝；调用方必须回滚并标记任务为 rejected。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        save_id: int | None = None,
        generation: int | None = None,
        session_id: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.save_id = save_id
        self.generation = generation
        self.session_id = session_id


@dataclass(frozen=True)
class WriteContext:
    """一次写入操作的完整身份上下文；创建后不得在任务中途更换。"""

    save_id: int
    identity_id: int
    session_id: int
    fingerprint: str
    session_epoch: int
    agent_id: str | None = None
    capture_id: int | None = None
    operation_id: str | None = None
    protocol_version: str = PROTOCOL_VERSION


@dataclass(frozen=True)
class WriteFence:
    """绑定到某一代次的写入门票；必须在写入事务内调用 :meth:`assert_current`。"""

    save_id: int
    generation: int
    session_id: int
    identity_id: int | None
    operation_id: str | None

    def assert_current(self, db: Session) -> None:
        """在调用方事务内做条件更新；代次或会话已变则抛 :class:`WriteRejected`。

        不读取任何缓存，也不新建事务：UPDATE 与业务写入属于同一事务，提交前不可能被
        "先检查后写入"的竞态绕过。
        """
        result = db.execute(
            update(SaveWriteGate)
            .where(
                SaveWriteGate.fm_save_id == self.save_id,
                SaveWriteGate.generation == self.generation,
                SaveWriteGate.current_session_id == self.session_id,
            )
            .values(generation=SaveWriteGate.generation)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            raise WriteRejected(
                WRITE_FENCE_STALE,
                "存档代次已变化或会话已失去写入资格，本次提交被拒绝",
                save_id=self.save_id,
                generation=self.generation,
                session_id=self.session_id,
            )


# -- gate 读写 --------------------------------------------------------------------------------------------------


def get_gate(db: Session, save_id: int) -> SaveWriteGate | None:
    return db.scalar(select(SaveWriteGate).where(SaveWriteGate.fm_save_id == save_id))


def ensure_gate(db: Session, save_id: int) -> SaveWriteGate:
    """返回存档写入门；不存在时以 generation=0 创建（并发创建由唯一约束兜底）。"""
    gate = get_gate(db, save_id)
    if gate is not None:
        return gate
    candidate = SaveWriteGate(fm_save_id=save_id, generation=0)
    try:
        with db.begin_nested():
            db.add(candidate)
            db.flush()
    except IntegrityError:
        gate = get_gate(db, save_id)
        if gate is None:
            raise
        return gate
    return candidate


def gate_exists(db: Session, save_id: int) -> bool:
    return db.scalar(select(SaveWriteGate.id).where(SaveWriteGate.fm_save_id == save_id)) is not None


# -- 上下文校验 --------------------------------------------------------------------------------------------------


def resolve_write_context(
    db: Session,
    save: FmSave,
    *,
    identity_id: int | None,
    session_id: int | None,
    fingerprint: str | None = None,
    operation_id: str | None = None,
    agent_id: str | None = None,
    capture_id: int | None = None,
) -> WriteContext | None:
    """解析并校验写入上下文。

    * 存档从未进入 V3.2.7.3 协议（没有 gate）且未声明上下文：返回 ``None``（历史兼容路径）。
    * 一旦存档存在 gate，导入必须携带身份 + 会话 + 指纹 + 当前代次，否则拒绝。
    """
    gate = get_gate(db, save.id)
    if identity_id is None and session_id is None:
        if gate is None:
            if not default_settings.write_safety_legacy_allowed:
                raise _fail(
                    409,
                    WRITE_CONTEXT_REQUIRED,
                    "本服务已禁用无上下文的旧写入方式，请升级客户端或携带身份/会话",
                )
            return None
        raise _fail(
            409,
            WRITE_CONTEXT_REQUIRED,
            "该存档已启用写入保护，导入必须携带 save_identity_id / save_session_id",
        )

    context = resolve_save_context(db, save, identity_id, session_id)
    identity = context.identity
    session = context.session
    if gate is None:
        gate = ensure_gate(db, save.id)

    if session is None:
        raise _fail(409, WRITE_CONTEXT_REQUIRED, "写入必须携带已被验证的游戏会话")
    if identity is None:
        raise _fail(409, WRITE_CONTEXT_REQUIRED, "写入必须携带已验证的存档身份")
    if session.session_status in _ENDED_SESSION_STATUSES or session.session_status not in _WRITABLE_SESSION_STATUSES:
        raise _fail(409, "save_session_invalidated", "会话已失效，不能提交新数据")

    if session.session_epoch != gate.generation:
        raise _fail(
            409,
            WRITE_EPOCH_STALE,
            f"会话代次 {session.session_epoch} 已落后于当前代次 {gate.generation}，请重新识别存档",
        )
    if gate.current_session_id is not None and gate.current_session_id != session.id:
        raise _fail(409, WRITE_EPOCH_STALE, "该会话已被新的写入会话取代")
    if gate.current_identity_id is not None and gate.current_identity_id != identity.id:
        raise _fail(409, "save_context_mismatch", "会话身份与当前活动身份不一致")
    if gate.current_session_id is None:
        # 旧会话（协议上线前创建）第一次写入时认领 gate；两个会话并发认领由提交顺序串行化，
        # 后提交者的 fence 会因 current_session_id 不匹配而失败。
        gate.current_session_id = session.id
        gate.current_identity_id = identity.id

    if fingerprint and fingerprint != identity.identity_fingerprint:
        raise _fail(409, "save_context_mismatch", "指纹与当前已验证身份不一致")

    last_seen = session.last_heartbeat_at or session.session_started_at
    if last_seen is not None and utcnow() - last_seen > identity_service.HEARTBEAT_TIMEOUT:
        raise _fail(409, "save_session_invalidated", "会话心跳超时，已失去写入资格")

    return WriteContext(
        save_id=save.id,
        identity_id=identity.id,
        session_id=session.id,
        fingerprint=identity.identity_fingerprint,
        session_epoch=session.session_epoch,
        agent_id=agent_id or session.agent_id,
        capture_id=capture_id,
        operation_id=operation_id,
    )


def acquire_write_fence(db: Session, context: WriteContext) -> WriteFence:
    """把已验证上下文固化为一次性门票；后续写入必须以该代次提交。"""
    gate = get_gate(db, context.save_id)
    if gate is None or gate.generation != context.session_epoch:
        raise WriteRejected(
            WRITE_FENCE_STALE,
            "获取写入门票时存档代次已变化",
            save_id=context.save_id,
            generation=gate.generation if gate is not None else None,
            session_id=context.session_id,
        )
    return WriteFence(
        save_id=context.save_id,
        generation=context.session_epoch,
        session_id=context.session_id,
        identity_id=context.identity_id,
        operation_id=context.operation_id,
    )


# -- 代次推进 ----------------------------------------------------------------------------------------------------


def rotate_generation(
    db: Session,
    save: FmSave,
    *,
    reason: str,
    actor: str = "agent",
    next_session_id: int | None = None,
    next_identity_id: int | None = None,
    capture_id: int | None = None,
) -> int:
    """在事务中原子推进代次并使所有旧会话失效。

    使用条件更新（CAS）而不是先读后写：两个并发切换最多只有一个能拿到新的有效代次。
    调用方负责提交事务。
    """
    now = utcnow()
    new_generation: int | None = None
    for _ in range(5):
        gate = ensure_gate(db, save.id)
        old_generation = gate.generation
        try:
            result = db.execute(
                update(SaveWriteGate)
                .where(
                    SaveWriteGate.fm_save_id == save.id,
                    SaveWriteGate.generation == old_generation,
                )
                .values(
                    generation=old_generation + 1,
                    current_session_id=next_session_id,
                    current_identity_id=next_identity_id,
                    last_switch_at=now,
                    last_switch_reason=reason,
                    updated_at=now,
                )
                .execution_options(synchronize_session=False)
            )
        except OperationalError as exc:  # SQLite 写锁竞争：明确返回忙碌，不静默降级
            db.rollback()
            raise _fail(409, WRITE_GATE_BUSY, f"写入代次正在被其他事务更新，请重试：{exc.orig}") from exc
        if result.rowcount == 1:
            new_generation = old_generation + 1
            # Core UPDATE 不会同步 ORM 身份映射；必须让后续读取看到新代次。
            db.expire_all()
            break
        db.expire_all()
    if new_generation is None:
        db.rollback()
        raise _fail(409, WRITE_GATE_BUSY, "并发切换过多，写入代次未能推进，请重试")

    stale_sessions = list(
        db.scalars(
            select(SaveSession).where(
                SaveSession.fm_save_id == save.id,
                SaveSession.session_status.in_(("created", "verified", "switching")),
                SaveSession.id != (next_session_id if next_session_id is not None else -1),
            )
        )
    )
    for session in stale_sessions:
        old_status = session.session_status
        session.session_status = "invalidated"
        session.session_ended_at = now
        session.invalidated_reason = reason
        identity_service.record_audit(
            db,
            save_id=save.id,
            identity_id=session.save_identity_id,
            session_id=session.id,
            capture_id=capture_id,
            event_type="session_invalidated",
            old_status=old_status,
            new_status="invalidated",
            evidence_summary={"generation": new_generation, "reason": reason},
            actor=actor,
            reason=reason,
        )

    identity_service.record_audit(
        db,
        save_id=save.id,
        identity_id=next_identity_id,
        session_id=next_session_id,
        capture_id=capture_id,
        event_type="save_switched",
        old_status=str(old_generation),
        new_status=str(new_generation),
        evidence_summary={
            "reason": reason,
            "previous_generation": old_generation,
            "generation": new_generation,
            "invalidated_sessions": len(stale_sessions),
        },
        actor=actor,
        reason=reason,
    )
    return new_generation


def bind_session_to_gate(db: Session, save: FmSave, session: SaveSession) -> int:
    """把会话固定到当前代次并设为唯一可写会话；身份变化时先推进代次。"""
    gate = ensure_gate(db, save.id)
    if (
        gate.current_identity_id is not None
        and session.save_identity_id is not None
        and gate.current_identity_id != session.save_identity_id
        and gate.current_session_id not in (None, session.id)
    ):
        # next_session_id 必须显式传入：否则 rotate_generation 会把刚创建的新会话也置为
        # invalidated，导致身份切换后新会话永远无法写入（PR #8 审查 F-01）。
        rotate_generation(
            db,
            save,
            reason="identity_switch",
            actor="agent",
            next_session_id=session.id,
            next_identity_id=session.save_identity_id,
        )
        gate = ensure_gate(db, save.id)
        session = db.get(SaveSession, session.id) or session
    session.session_epoch = gate.generation
    gate.current_session_id = session.id
    gate.current_identity_id = session.save_identity_id
    return gate.generation


def diagnose(db: Session, save: FmSave) -> dict:
    """给前端/Agent 的诊断视图：真实后端代次，不依赖 Agent 本地缓存。"""
    gate = get_gate(db, save.id)
    sessions = list(
        db.scalars(
            select(SaveSession)
            .where(SaveSession.fm_save_id == save.id)
            .order_by(SaveSession.id.desc())
            .limit(10)
        )
    )
    return {
        "save_id": save.id,
        "protocol_version": PROTOCOL_VERSION,
        "gate": None
        if gate is None
        else {
            "generation": gate.generation,
            "current_session_id": gate.current_session_id,
            "current_identity_id": gate.current_identity_id,
            "last_switch_at": gate.last_switch_at.isoformat() if gate.last_switch_at else None,
            "last_switch_reason": gate.last_switch_reason,
        },
        "sessions": [
            {
                "session_id": row.id,
                "identity_id": row.save_identity_id,
                "session_epoch": row.session_epoch,
                "status": row.session_status,
                "agent_id": row.agent_id,
                "last_heartbeat_at": row.last_heartbeat_at.isoformat() if row.last_heartbeat_at else None,
                "invalidated_reason": row.invalidated_reason,
            }
            for row in sessions
        ],
    }


def record_legacy_write(
    db: Session,
    *,
    save_id: int,
    operation_id: str | None,
    endpoint: str,
) -> None:
    """旧客户端兼容写入的审计。调用方负责提交事务。"""
    identity_service.record_audit(
        db,
        save_id=save_id,
        event_type="legacy_write_allowed",
        new_status="allowed",
        evidence_summary={"operation_id": operation_id, "endpoint": endpoint},
        actor="legacy-client",
        reason="write_safety_legacy_allowed",
        correlation_id=operation_id,
    )


def record_rejection(
    db: Session,
    *,
    save_id: int,
    session_id: int | None,
    identity_id: int | None,
    capture_id: int | None,
    code: str,
    message: str,
    generation: int | None = None,
    operation_id: str | None = None,
) -> None:
    """记录一次写入拒绝（独立事务由调用方提交），便于前端与审计追溯。"""
    identity_service.record_audit(
        db,
        save_id=save_id,
        identity_id=identity_id,
        session_id=session_id,
        capture_id=capture_id,
        event_type="write_rejected",
        new_status="rejected",
        evidence_summary={
            "code": code,
            "message": message[:500],
            "generation": generation,
            "operation_id": operation_id,
        },
        actor="backend",
        reason=code,
    )
