"""存档身份与会话的生命周期服务（V3.2.7.2 Phase 2/6）。

职责边界：

* 客户端（Reader/Agent）只能**上报证据与声明**；身份是否成立、能否升级为 ``verified``
  由本模块按固定规则判定，绝不因为客户端自称 ``verified`` 就信任。
* 所有状态变化写入 ``save_identity_audit_events``（只追加）。
* 写入资格沿用 V3.2.7 的 ``save_context`` 语义：只有 ``verified`` 会话可写。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import (
    FmSave,
    SaveEvidence,
    SaveIdentity,
    SaveIdentityAuditEvent,
    SaveIdentityConflict,
    SaveSession,
    SaveWriteGate,
)
from ..schemas import (
    SaveIdentityRegisterIn,
    SaveIdentityVerifyIn,
    SaveSessionHeartbeatIn,
    SaveSessionStartIn,
)
from ..utils import iso, utcnow

PROTOCOL_VERSION = "save-identity/v1"

IDENTITY_STATUSES = ("unknown", "discovered", "candidate", "verified", "conflict", "invalidated")
_STATUS_RANK = {"unknown": 0, "discovered": 1, "candidate": 2, "verified": 3}
CONFIDENCES = ("none", "low", "medium", "high", "verified")
IDENTITY_KINDS = ("internal_save_id", "world_id", "save_file", "user_confirmed", "unresolved")

SESSION_STATUSES = ("created", "verified", "switching", "invalidated", "closed")
#: 心跳超过该时长未更新，会话视为过期；此时不得继续写入。
HEARTBEAT_TIMEOUT = timedelta(seconds=120)

PRIMARY_EVIDENCE = {"game_internal_save_id", "world_id"}
SECONDARY_EVIDENCE = {"save_file_metadata", "save_file_hash", "save_file_header"}
USER_CONFIRMED_EVIDENCE = "user_confirmed"

#: 这些身份状态下，注册接口不得把状态“自动恢复”。
_TERMINAL_IDENTITY_STATUSES = {"conflict", "invalidated"}


def protocol_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _naive_utc(value: datetime | None, default: datetime | None = None) -> datetime | None:
    if value is None:
        return default
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def record_audit(
    db: Session,
    *,
    save_id: int | None,
    event_type: str,
    identity_id: int | None = None,
    session_id: int | None = None,
    capture_id: int | None = None,
    old_status: str | None = None,
    new_status: str | None = None,
    old_fingerprint: str | None = None,
    new_fingerprint: str | None = None,
    evidence_summary: dict[str, Any] | None = None,
    actor: str = "backend",
    reason: str | None = None,
    correlation_id: str | None = None,
) -> SaveIdentityAuditEvent:
    """追加一条审计事件；调用方负责提交事务。"""
    event = SaveIdentityAuditEvent(
        fm_save_id=save_id,
        identity_id=identity_id,
        session_id=session_id,
        capture_id=capture_id,
        event_type=event_type,
        old_status=old_status,
        new_status=new_status,
        old_fingerprint=old_fingerprint,
        new_fingerprint=new_fingerprint,
        evidence_summary=json.dumps(evidence_summary or {}, ensure_ascii=False),
        actor=actor,
        reason=reason,
        occurred_at=utcnow(),
        correlation_id=correlation_id,
    )
    db.add(event)
    return event


def _evidence_types(payload: SaveIdentityRegisterIn) -> list[str]:
    return [item.type.strip().lower() for item in payload.evidence]


def cap_declared_status(payload: SaveIdentityRegisterIn) -> str:
    """按证据给客户端声明封顶。返回后端允许的最终状态。"""
    declared = payload.identity_status.strip().lower()
    if declared not in IDENTITY_STATUSES:
        raise protocol_error(422, "invalid_identity_status", f"未知身份状态：{payload.identity_status}")

    types = set(_evidence_types(payload))
    has_primary = bool(types & PRIMARY_EVIDENCE)
    has_secondary = bool(types & SECONDARY_EVIDENCE)
    has_user_confirm = USER_CONFIRMED_EVIDENCE in types

    allowed = "unknown"
    if types:
        allowed = "discovered"
    if has_primary or has_secondary:
        allowed = "candidate"
    if has_primary or (has_user_confirm and has_secondary):
        allowed = "verified"

    # 未解析指纹不是身份，最多算“已发现”。
    if payload.fingerprint.startswith("si:v1:unresolved:"):
        allowed = "discovered"
    # 多候选未消歧时不得给出已验证。
    if payload.ambiguous:
        allowed = "discovered" if _STATUS_RANK[allowed] > _STATUS_RANK["candidate"] else allowed

    if declared in {"conflict", "invalidated"}:
        return declared
    return declared if _STATUS_RANK[declared] <= _STATUS_RANK[allowed] else allowed


def _confidence_for(status: str, declared: str) -> str:
    confidence = declared.strip().lower()
    if confidence not in CONFIDENCES:
        confidence = "none"
    if status != "verified" and confidence == "verified":
        return "high"
    return confidence


def _store_evidence(db: Session, identity: SaveIdentity, payload: SaveIdentityRegisterIn) -> None:
    """证据去重后追加：同一身份同一 (type, hash) 不重复写入。"""
    seen = set(
        db.execute(
            select(SaveEvidence.evidence_type, SaveEvidence.evidence_hash).where(
                SaveEvidence.save_identity_id == identity.id
            )
        ).all()
    )
    for item in payload.evidence:
        evidence_type = item.type.strip()
        key = (evidence_type, item.hash)
        if key in seen:
            continue
        seen.add(key)
        db.add(
            SaveEvidence(
                save_identity_id=identity.id,
                fm_save_id=identity.fm_save_id,
                evidence_type=evidence_type,
                evidence_source=item.source.strip() or "file",
                evidence_hash=item.hash,
                evidence_version=item.version,
                confidence=item.confidence.strip().lower() if item.confidence else "none",
                observed_at=_naive_utc(item.observed_at, utcnow()),
                metadata_json=json.dumps({"detail": item.detail}, ensure_ascii=False) if item.detail else "{}",
            )
        )


def _open_conflict(db: Session, save_id: int, current_identity_id: int, conflicting_identity_id: int, payload) -> None:
    existing = db.scalar(
        select(SaveIdentityConflict).where(
            SaveIdentityConflict.fm_save_id == save_id,
            SaveIdentityConflict.current_identity_id == current_identity_id,
            SaveIdentityConflict.conflicting_identity_id == conflicting_identity_id,
            SaveIdentityConflict.status == "open",
        )
    )
    if existing is not None:
        return
    db.add(
        SaveIdentityConflict(
            fm_save_id=save_id,
            current_identity_id=current_identity_id,
            conflicting_identity_id=conflicting_identity_id,
            conflict_reason="fingerprint_mismatch",
            conflict_evidence_json=json.dumps(
                {
                    "fingerprint": payload.fingerprint,
                    "game_build": payload.game_build,
                    "agent_id": payload.agent_id,
                    "session_key": payload.session_key,
                },
                ensure_ascii=False,
            ),
            detected_at=utcnow(),
            status="open",
        )
    )


def register_identity(
    db: Session,
    save: FmSave,
    payload: SaveIdentityRegisterIn,
    *,
    actor: str = "agent",
) -> SaveIdentity:
    """幂等注册/更新身份；返回已持久化（未提交）的身份行。"""
    if payload.save_id is not None and payload.save_id != save.id:
        raise protocol_error(409, "save_context_mismatch", "存档身份不属于当前存档")
    if not payload.fingerprint.startswith("si:v1:"):
        raise protocol_error(422, "invalid_fingerprint", "指纹必须使用 si:v1: 前缀")
    if payload.kind.strip().lower() not in IDENTITY_KINDS:
        raise protocol_error(422, "invalid_identity_kind", f"未知身份来源：{payload.kind}")

    declared = payload.identity_status.strip().lower()
    final_status = cap_declared_status(payload)
    now = utcnow()

    existing = db.scalar(
        select(SaveIdentity).where(
            SaveIdentity.fm_save_id == save.id,
            SaveIdentity.identity_version == payload.fingerprint_version,
            SaveIdentity.identity_fingerprint == payload.fingerprint,
        )
    )

    if existing is None:
        # 同一存档已有一个 verified 身份，却上报不同指纹：不得自动替换，进入冲突流程。
        verified_other = db.scalar(
            select(SaveIdentity).where(
                SaveIdentity.fm_save_id == save.id,
                SaveIdentity.identity_status == "verified",
                SaveIdentity.identity_fingerprint != payload.fingerprint,
            )
        )
        conflict_with_verified = verified_other is not None and final_status == "verified"
        identity = SaveIdentity(
            fm_save_id=save.id,
            identity_version=payload.fingerprint_version,
            identity_status="conflict" if conflict_with_verified else final_status,
            identity_confidence=_confidence_for(final_status, payload.confidence),
            identity_fingerprint=payload.fingerprint,
            identity_kind=payload.kind.strip().lower(),
            game_build=payload.game_build,
            plugin_version=payload.plugin_version,
            first_seen_at=now,
            last_seen_at=now,
            verified_at=now if final_status == "verified" and not conflict_with_verified else None,
            verified_by=actor if final_status == "verified" and not conflict_with_verified else None,
        )
        db.add(identity)
        try:
            db.flush()
        except IntegrityError:
            # 并发注册同一指纹：唯一约束先到先得，回滚后复用已有行。
            db.rollback()
            existing = db.scalar(
                select(SaveIdentity).where(
                    SaveIdentity.fm_save_id == save.id,
                    SaveIdentity.identity_version == payload.fingerprint_version,
                    SaveIdentity.identity_fingerprint == payload.fingerprint,
                )
            )
            if existing is None:
                raise
            existing.last_seen_at = now
            _store_evidence(db, existing, payload)
            record_audit(
                db,
                save_id=save.id,
                identity_id=existing.id,
                event_type="registered",
                new_status=existing.identity_status,
                new_fingerprint=existing.identity_fingerprint,
                evidence_summary={"concurrent": True, "evidence": len(payload.evidence)},
                actor=actor,
            )
            return existing

        _store_evidence(db, identity, payload)
        if conflict_with_verified and verified_other is not None:
            _open_conflict(db, save.id, verified_other.id, identity.id, payload)
            record_audit(
                db,
                save_id=save.id,
                identity_id=identity.id,
                event_type="conflict_detected",
                old_status=None,
                new_status="conflict",
                new_fingerprint=payload.fingerprint,
                evidence_summary={"current_identity_id": verified_other.id},
                actor=actor,
                reason="同一存档出现不同指纹，已阻止自动替换",
            )
        record_audit(
            db,
            save_id=save.id,
            identity_id=identity.id,
            event_type="registered",
            new_status=identity.identity_status,
            new_fingerprint=identity.identity_fingerprint,
            evidence_summary={"declared_status": declared, "evidence": len(payload.evidence)},
            actor=actor,
            reason=payload.session_key,
        )
        return identity

    # 已存在同一指纹：幂等更新，状态只按安全方向推进。
    old_status = existing.identity_status
    existing.last_seen_at = now
    if payload.game_build:
        existing.game_build = payload.game_build
    if payload.plugin_version:
        existing.plugin_version = payload.plugin_version

    new_status = old_status
    reason = None
    if declared == "conflict":
        new_status = "conflict"
        reason = "客户端报告身份冲突"
    elif old_status in _TERMINAL_IDENTITY_STATUSES:
        # 冲突/失效只能通过显式 verify 恢复，普通上报不得洗白。
        new_status = old_status
    elif old_status == "verified":
        new_status = "verified"
    else:
        new_status = max((old_status, final_status), key=lambda item: _STATUS_RANK.get(item, 0))

    existing.identity_status = new_status
    if new_status == "verified" and old_status != "verified":
        existing.verified_at = now
        existing.verified_by = actor
    existing.identity_confidence = _confidence_for(new_status, payload.confidence)
    existing.identity_kind = payload.kind.strip().lower()

    _store_evidence(db, existing, payload)
    if new_status != old_status:
        event_type = "conflict_detected" if new_status == "conflict" else "registered"
        record_audit(
            db,
            save_id=save.id,
            identity_id=existing.id,
            event_type=event_type,
            old_status=old_status,
            new_status=new_status,
            old_fingerprint=existing.identity_fingerprint,
            new_fingerprint=payload.fingerprint,
            evidence_summary={"declared_status": declared},
            actor=actor,
            reason=reason,
        )
    return existing


def verify_identity(
    db: Session,
    save: FmSave,
    identity_id: int,
    payload: SaveIdentityVerifyIn,
) -> SaveIdentity:
    """人工确认升级；必须指纹一致且已有第二优先级证据。"""
    identity = db.get(SaveIdentity, identity_id)
    if identity is None or identity.fm_save_id != save.id:
        raise protocol_error(404, "save_identity_not_found", "存档身份不存在")
    if identity.identity_status == "invalidated":
        raise protocol_error(409, "save_identity_unverified", "已失效的身份必须重新识别，不能直接确认")
    if payload.confirmed_fingerprint != identity.identity_fingerprint:
        raise protocol_error(409, "save_context_mismatch", "确认的指纹与当前身份不一致")
    has_secondary = db.scalar(
        select(SaveEvidence.id).where(
            SaveEvidence.save_identity_id == identity.id,
            SaveEvidence.evidence_type.in_(tuple(SECONDARY_EVIDENCE)),
        )
    )
    if has_secondary is None:
        raise protocol_error(409, "save_identity_unverified", "缺少第二优先级证据，不能升级为已验证")

    now = utcnow()
    old_status = identity.identity_status
    identity.identity_status = "verified"
    identity.identity_confidence = "verified"
    identity.verified_at = now
    identity.verified_by = payload.actor
    identity.last_seen_at = now

    confirmed_evidence = db.scalar(
        select(SaveEvidence.id).where(
            SaveEvidence.save_identity_id == identity.id,
            SaveEvidence.evidence_type == "user_confirmed",
        )
    )
    if confirmed_evidence is None:
        db.add(
            SaveEvidence(
                save_identity_id=identity.id,
                fm_save_id=identity.fm_save_id,
                evidence_type="user_confirmed",
                evidence_source="user",
                evidence_hash=identity.identity_fingerprint,
                evidence_version=None,
                confidence="high",
                observed_at=now,
                metadata_json=json.dumps({"actor": payload.actor, "basis": payload.basis}, ensure_ascii=False),
            )
        )

    # 该身份参与的未解决冲突随人工确认一起关闭，保留全部证据。
    conflicts = db.scalars(
        select(SaveIdentityConflict).where(
            SaveIdentityConflict.fm_save_id == save.id,
            SaveIdentityConflict.status == "open",
            SaveIdentityConflict.conflicting_identity_id == identity.id,
        )
    )
    for conflict in conflicts:
        conflict.status = "resolved"
        conflict.resolution = "user_confirmed"
        conflict.resolved_by = payload.actor
        conflict.resolved_at = now
        conflict.notes = payload.basis

    record_audit(
        db,
        save_id=save.id,
        identity_id=identity.id,
        event_type="user_confirmed",
        old_status=old_status,
        new_status="verified",
        old_fingerprint=identity.identity_fingerprint,
        new_fingerprint=identity.identity_fingerprint,
        evidence_summary={"basis": payload.basis},
        actor=payload.actor,
    )
    return identity


def _bind_session_epoch(db: Session, save: FmSave, session: SaveSession) -> None:
    """把会话固定到当前写入代次（延迟导入避免与 write_safety 形成模块环）。"""
    from .write_safety import bind_session_to_gate

    bind_session_to_gate(db, save, session)


def start_session(
    db: Session,
    save: FmSave,
    payload: SaveSessionStartIn,
    *,
    actor: str = "agent",
) -> SaveSession:
    if payload.save_id is not None and payload.save_id != save.id:
        raise protocol_error(409, "save_context_mismatch", "会话不属于当前存档")
    identity = db.get(SaveIdentity, payload.identity_id)
    if identity is None or identity.fm_save_id != save.id:
        raise protocol_error(409, "save_context_mismatch", "会话声明的身份不属于当前存档")
    if identity.identity_status in {"conflict", "invalidated"}:
        raise protocol_error(409, "save_context_mismatch", "存档身份处于冲突或失效状态")
    if identity.game_build and payload.game_build and identity.game_build != payload.game_build:
        raise protocol_error(409, "save_context_mismatch", "会话 game build 与存档身份不一致")

    now = utcnow()
    existing = db.scalar(select(SaveSession).where(SaveSession.session_key == payload.session_key))
    if existing is not None:
        if existing.fm_save_id != save.id or existing.save_identity_id not in (None, identity.id):
            raise protocol_error(409, "save_context_mismatch", "该会话键已绑定到其他存档或身份")
        if existing.session_status in {"invalidated", "closed"}:
            raise protocol_error(409, "save_session_invalidated", "会话已结束或失效，不能复用")
        existing.last_heartbeat_at = now
        if existing.session_status == "verified":
            existing.last_verified_at = now
        _bind_session_epoch(db, save, existing)
        return existing

    status = "verified" if identity.identity_status == "verified" else "created"
    session = SaveSession(
        fm_save_id=save.id,
        save_identity_id=identity.id,
        process_id=payload.process_id,
        process_start_time=_naive_utc(payload.process_start_time),
        session_key=payload.session_key,
        session_started_at=now,
        game_build=payload.game_build or identity.game_build,
        plugin_version=payload.plugin_version or identity.plugin_version,
        agent_id=payload.agent_id,
        session_status=status,
        last_heartbeat_at=now,
        last_verified_at=now if status == "verified" else None,
    )
    db.add(session)
    db.flush()
    record_audit(
        db,
        save_id=save.id,
        identity_id=identity.id,
        session_id=session.id,
        event_type="session_started",
        new_status=status,
        evidence_summary={"session_key": payload.session_key, "agent_id": payload.agent_id},
        actor=actor,
    )
    _bind_session_epoch(db, save, session)
    return session


def _invalidate_session(
    db: Session,
    save: FmSave,
    session: SaveSession,
    *,
    reason: str,
    actor: str,
    event_type: str = "session_invalidated",
) -> None:
    # V3.2.7.3：失效当前可写会话必须同时推进代次，否则在途 Worker 仍可凭旧 fence 提交。
    from .write_safety import get_gate, rotate_generation

    gate = get_gate(db, save.id)
    if gate is not None and gate.current_session_id == session.id:
        rotate_generation(db, save, reason=reason, actor=actor)
        db.expire_all()
        session = db.get(SaveSession, session.id)
        if session is None:
            db.commit()
            return

    if session.session_status != "invalidated":
        old_status = session.session_status
        session.session_status = "invalidated"
        session.invalidated_reason = reason
        session.session_ended_at = utcnow()
        record_audit(
            db,
            save_id=save.id,
            identity_id=session.save_identity_id,
            session_id=session.id,
            event_type=event_type,
            old_status=old_status,
            new_status="invalidated",
            evidence_summary={"reason": reason},
            actor=actor,
            reason=reason,
        )
    db.commit()


def heartbeat(
    db: Session,
    save: FmSave,
    session_id: int,
    payload: SaveSessionHeartbeatIn,
    *,
    actor: str = "agent",
    now: datetime | None = None,
) -> SaveSession:
    session = db.get(SaveSession, session_id)
    if session is None or session.fm_save_id != save.id:
        raise protocol_error(404, "save_session_not_found", "会话不存在")
    if session.session_status in {"invalidated", "closed"}:
        raise protocol_error(409, "save_session_invalidated", "会话已结束或失效")
    if session.session_status == "switching":
        raise protocol_error(409, "save_switch_in_progress", "存档正在切换，已暂停写入")

    current = _naive_utc(now) or utcnow()
    if payload.identity_id != session.save_identity_id:
        _invalidate_session(db, save, session, reason="identity_mismatch", actor=actor)
        raise protocol_error(409, "save_context_mismatch", "心跳身份与会话身份不一致，会话已失效")

    identity = db.get(SaveIdentity, session.save_identity_id) if session.save_identity_id else None
    if identity is None or identity.fm_save_id != save.id:
        _invalidate_session(db, save, session, reason="identity_missing", actor=actor)
        raise protocol_error(409, "save_context_mismatch", "会话绑定的身份不存在，会话已失效")
    if payload.fingerprint and payload.fingerprint != identity.identity_fingerprint:
        _invalidate_session(db, save, session, reason="fingerprint_mismatch", actor=actor)
        raise protocol_error(409, "save_context_mismatch", "心跳指纹与身份不一致，会话已失效")
    if identity.game_build and payload.game_build and identity.game_build != payload.game_build:
        _invalidate_session(db, save, session, reason="build_mismatch", actor=actor)
        raise protocol_error(409, "save_context_mismatch", "心跳 game build 与身份不一致，会话已失效")

    last_seen = session.last_heartbeat_at or session.session_started_at
    if last_seen is not None and current - last_seen > HEARTBEAT_TIMEOUT:
        _invalidate_session(db, save, session, reason="expired", actor=actor)
        raise protocol_error(409, "save_session_invalidated", "会话心跳超时，已失效")

    if identity.identity_status != "verified":
        raise protocol_error(409, "save_identity_unverified", "存档身份尚未验证，不能维持可写会话")
    if session.session_status != "verified":
        _invalidate_session(db, save, session, reason="not_verified", actor=actor)
        raise protocol_error(409, "save_session_invalidated", "会话不具备写入资格")

    # 代次落后说明存档已经切换或被新的写入会话取代；心跳不能把它"续回来"。
    gate = db.scalar(select(SaveWriteGate).where(SaveWriteGate.fm_save_id == save.id))
    if gate is not None and (
        gate.generation != session.session_epoch
        or (gate.current_session_id is not None and gate.current_session_id != session.id)
    ):
        _invalidate_session(db, save, session, reason="epoch_stale", actor=actor)
        raise protocol_error(409, "write_session_epoch_stale", "会话代次已落后，已失效，请重新识别存档")

    session.last_heartbeat_at = current
    session.last_verified_at = current
    return session


def end_session(
    db: Session,
    save: FmSave,
    session_id: int,
    *,
    actor: str = "agent",
) -> SaveSession:
    session = db.get(SaveSession, session_id)
    if session is None or session.fm_save_id != save.id:
        raise protocol_error(404, "save_session_not_found", "会话不存在")
    if session.session_status == "closed":
        return session
    old_status = session.session_status
    session.session_status = "closed"
    session.session_ended_at = utcnow()
    record_audit(
        db,
        save_id=save.id,
        identity_id=session.save_identity_id,
        session_id=session.id,
        event_type="session_ended",
        old_status=old_status,
        new_status="closed",
        actor=actor,
    )
    return session


def invalidate_session(
    db: Session,
    save: FmSave,
    session_id: int,
    *,
    reason: str,
    actor: str = "agent",
) -> SaveSession:
    session = db.get(SaveSession, session_id)
    if session is None or session.fm_save_id != save.id:
        raise protocol_error(404, "save_session_not_found", "会话不存在")
    _invalidate_session(db, save, session, reason=reason, actor=actor)
    return session


def block_capture(
    db: Session,
    save: FmSave,
    *,
    identity_id: int | None,
    session_id: int | None,
    capture_id: int | None,
    reason: str,
    actor: str = "backend",
) -> None:
    """记录一次采集阻断（供 Phase 4 的切换路径调用）。"""
    record_audit(
        db,
        save_id=save.id,
        identity_id=identity_id,
        session_id=session_id,
        capture_id=capture_id,
        event_type="capture_blocked",
        new_status="blocked",
        reason=reason,
        actor=actor,
    )


# -- payloads --------------------------------------------------------------------------------------------------


def evidence_level(db: Session, identity: SaveIdentity) -> str:
    types = {
        row.lower()
        for row in db.scalars(
            select(SaveEvidence.evidence_type).where(SaveEvidence.save_identity_id == identity.id)
        )
    }
    if types & PRIMARY_EVIDENCE:
        return "primary"
    if types & SECONDARY_EVIDENCE:
        return "secondary"
    if types:
        return "auxiliary"
    return "none"


def identity_payload(db: Session, identity: SaveIdentity, *, include_evidence: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "identity_id": identity.id,
        "save_id": identity.fm_save_id,
        "fingerprint": identity.identity_fingerprint,
        "fingerprint_version": identity.identity_version,
        "identity_status": identity.identity_status,
        "confidence": identity.identity_confidence,
        "kind": identity.identity_kind,
        "evidence_level": evidence_level(db, identity),
        "game_build": identity.game_build,
        "plugin_version": identity.plugin_version,
        "first_seen_at": iso(identity.first_seen_at),
        "last_seen_at": iso(identity.last_seen_at),
        "verified_at": iso(identity.verified_at),
        "verified_by": identity.verified_by,
        "protocol_version": PROTOCOL_VERSION,
    }
    if include_evidence:
        rows = db.scalars(
            select(SaveEvidence)
            .where(SaveEvidence.save_identity_id == identity.id)
            .order_by(SaveEvidence.observed_at.desc(), SaveEvidence.id.desc())
            .limit(50)
        )
        payload["evidence"] = [
            {
                "type": row.evidence_type,
                "source": row.evidence_source,
                "hash": row.evidence_hash,
                "version": row.evidence_version,
                "confidence": row.confidence,
                "observed_at": iso(row.observed_at),
            }
            for row in rows
        ]
    return payload


def session_payload(session: SaveSession) -> dict[str, Any]:
    return {
        "session_id": session.id,
        "save_id": session.fm_save_id,
        "identity_id": session.save_identity_id,
        "session_key": session.session_key,
        "process_id": session.process_id,
        "process_start_time": iso(session.process_start_time),
        "game_build": session.game_build,
        "plugin_version": session.plugin_version,
        "agent_id": session.agent_id,
        "status": session.session_status,
        "started_at": iso(session.session_started_at),
        "last_heartbeat_at": iso(session.last_heartbeat_at),
        "last_verified_at": iso(session.last_verified_at),
        "ended_at": iso(session.session_ended_at),
        "invalidated_reason": session.invalidated_reason,
        "session_epoch": session.session_epoch,
    }


def capture_gate(db: Session, save: FmSave, identity: SaveIdentity) -> tuple[bool, list[str]]:
    """当前身份是否允许采集写入，以及阻断原因（供诊断接口/前端使用）。"""
    blockers: list[str] = []
    if identity.identity_status != "verified":
        blockers.append(f"身份状态为 {identity.identity_status}，未达到 verified。")
    if db.scalar(
        select(SaveIdentityConflict.id).where(
            SaveIdentityConflict.fm_save_id == save.id,
            SaveIdentityConflict.status == "open",
        )
    ):
        blockers.append("存在未处理的存档身份冲突。")
    latest_session = db.scalar(
        select(SaveSession)
        .where(
            SaveSession.fm_save_id == save.id,
            SaveSession.save_identity_id == identity.id,
        )
        .order_by(SaveSession.last_heartbeat_at.desc(), SaveSession.id.desc())
        .limit(1)
    )
    if latest_session is None:
        blockers.append("当前身份没有可用会话。")
    elif latest_session.session_status != "verified":
        blockers.append(f"最近会话状态为 {latest_session.session_status}。")
    elif latest_session.last_heartbeat_at is not None and utcnow() - latest_session.last_heartbeat_at > HEARTBEAT_TIMEOUT:
        blockers.append("最近会话心跳超时。")
    return (not blockers), blockers
