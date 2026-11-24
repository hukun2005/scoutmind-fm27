"""存档身份注册、验证与会话生命周期 API（V3.2.7.2 Phase 2/6）。

身份由 Reader 产生证据、Agent 转发；本路由只做协议入口与事务边界，
所有判定规则在 ``app.services.save_identity``，写接口仍由 ``save_context`` 把关。
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import FmSave, SaveIdentity, SaveIdentityAuditEvent, SaveSession
from ..schemas import (
    SaveIdentityRegisterIn,
    SaveIdentityVerifyIn,
    SaveSessionHeartbeatIn,
    SaveSessionInvalidateIn,
    SaveSessionStartIn,
)
from ..services import save_identity as service
from ..utils import iso
from .deps import get_active_save

router = APIRouter()


def _identity_or_404(db: Session, save: FmSave, identity_id: int) -> SaveIdentity:
    identity = db.get(SaveIdentity, identity_id)
    if identity is None or identity.fm_save_id != save.id:
        raise HTTPException(
            status_code=404,
            detail={"code": "save_identity_not_found", "message": "存档身份不存在"},
        )
    return identity


def _audit_payload(row: SaveIdentityAuditEvent) -> dict[str, Any]:
    return {
        "event_id": row.id,
        "save_id": row.fm_save_id,
        "identity_id": row.identity_id,
        "session_id": row.session_id,
        "capture_id": row.capture_id,
        "event_type": row.event_type,
        "old_status": row.old_status,
        "new_status": row.new_status,
        "old_fingerprint": row.old_fingerprint,
        "new_fingerprint": row.new_fingerprint,
        "evidence_summary": json.loads(row.evidence_summary or "{}"),
        "actor": row.actor,
        "reason": row.reason,
        "occurred_at": iso(row.occurred_at),
        "correlation_id": row.correlation_id,
    }


@router.post("/save-identities/register", summary="注册或更新存档身份（幂等）")
def register_identity(
    body: SaveIdentityRegisterIn,
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    identity = service.register_identity(db, save, body)
    db.commit()
    db.refresh(identity)
    return service.identity_payload(db, identity, include_evidence=True)


@router.post("/save-identities/{identity_id}/verify", summary="人工确认存档身份")
def verify_identity(
    identity_id: int,
    body: SaveIdentityVerifyIn,
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    identity = service.verify_identity(db, save, identity_id, body)
    db.commit()
    db.refresh(identity)
    return service.identity_payload(db, identity, include_evidence=True)


@router.get("/save-identities", summary="当前存档的存档身份列表")
def list_identities(
    status: str | None = Query(default=None, max_length=24),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    query = select(SaveIdentity).where(SaveIdentity.fm_save_id == save.id)
    if status:
        query = query.where(SaveIdentity.identity_status == status)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(SaveIdentity.last_seen_at.desc(), SaveIdentity.id.desc()).offset(offset).limit(limit))
    counts = dict(
        db.execute(
            select(SaveIdentity.identity_status, func.count())
            .where(SaveIdentity.fm_save_id == save.id)
            .group_by(SaveIdentity.identity_status)
        ).all()
    )
    return {
        "items": [service.identity_payload(db, row) for row in rows],
        "total": int(total),
        "counts": {key: int(value) for key, value in counts.items()},
        "limit": limit,
        "offset": offset,
        "protocol_version": service.PROTOCOL_VERSION,
    }


@router.get("/save-identities/{identity_id}", summary="存档身份详情")
def get_identity(
    identity_id: int,
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    identity = _identity_or_404(db, save, identity_id)
    payload = service.identity_payload(db, identity, include_evidence=True)
    sessions = db.scalars(
        select(SaveSession)
        .where(SaveSession.fm_save_id == save.id, SaveSession.save_identity_id == identity.id)
        .order_by(SaveSession.id.desc())
        .limit(20)
    )
    allowed, blockers = service.capture_gate(db, save, identity)
    payload["sessions"] = [service.session_payload(row) for row in sessions]
    payload["capture_allowed"] = allowed
    payload["blockers"] = blockers
    return payload


@router.post("/save-sessions/start", summary="登记游戏进程会话（幂等）")
def start_session(
    body: SaveSessionStartIn,
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    session = service.start_session(db, save, body)
    db.commit()
    db.refresh(session)
    return service.session_payload(session)


@router.post("/save-sessions/{session_id}/heartbeat", summary="会话心跳")
def heartbeat(
    session_id: int,
    body: SaveSessionHeartbeatIn,
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    session = service.heartbeat(db, save, session_id, body)
    db.commit()
    db.refresh(session)
    return service.session_payload(session)


@router.post("/save-sessions/{session_id}/end", summary="正常结束会话")
def end_session(
    session_id: int,
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    session = service.end_session(db, save, session_id)
    db.commit()
    db.refresh(session)
    return service.session_payload(session)


@router.post("/save-sessions/{session_id}/invalidate", summary="失效会话（切换/关闭/重启）")
def invalidate_session(
    session_id: int,
    body: SaveSessionInvalidateIn,
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    session = service.invalidate_session(db, save, session_id, reason=body.reason)
    db.commit()
    db.refresh(session)
    return service.session_payload(session)


@router.get("/save-identity-audit", summary="存档身份审计事件")
def list_audit(
    identity_id: int | None = Query(default=None, ge=1),
    session_id: int | None = Query(default=None, ge=1),
    capture_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    query = select(SaveIdentityAuditEvent).where(SaveIdentityAuditEvent.fm_save_id == save.id)
    if identity_id is not None:
        query = query.where(SaveIdentityAuditEvent.identity_id == identity_id)
    if session_id is not None:
        query = query.where(SaveIdentityAuditEvent.session_id == session_id)
    if capture_id is not None:
        query = query.where(SaveIdentityAuditEvent.capture_id == capture_id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(SaveIdentityAuditEvent.occurred_at.desc(), SaveIdentityAuditEvent.id.desc()).offset(offset).limit(limit))
    return {"items": [_audit_payload(row) for row in rows], "total": int(total), "limit": limit, "offset": offset}
