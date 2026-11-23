"""待确认自由球员（Unresolved）审阅 API（SM-118）。

设计约束：

* 候选只属于一个存档；所有入口都先解析并校验存档归属，越权统一 404（不泄露"存在但不属于你"）。
* 列表/详情默认只展示证据与建议，不把建议写成事实；``status`` 里没有任何"已确认身份"的默认值。
* ``resolve`` 必须显式 ``confirm=true``，且用条件 UPDATE 防止重复确认；每次决定追加一条不可修改的审计记录。
* ``dismiss`` 只改状态，删除观察记录是被禁止的。
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..db import get_db
from ..ingestion.unresolved import identity_suggestions, sibling_candidates
from ..models import (
    FmSave,
    IdentityMatch,
    Player,
    PlayerInstance,
    UnresolvedPlayerAction,
    UnresolvedPlayerCandidate,
    UnresolvedPlayerObservation,
)
from ..schemas import UnresolvedDismissIn, UnresolvedResolveIn
from ..utils import iso, utcnow
from .deps import get_active_save, get_current_user

router = APIRouter()

#: Statuses a human may still decide on; a decided candidate cannot be decided again.
OPEN_STATUSES = ("pending", "review_required")


def _candidate_for(db: Session, candidate_id: int, save: FmSave) -> UnresolvedPlayerCandidate:
    candidate = db.get(UnresolvedPlayerCandidate, candidate_id)
    if candidate is None or candidate.fm_save_id != save.id:
        raise HTTPException(
            status_code=404, detail={"code": "unresolved_not_found", "message": "待确认候选不存在"}
        )
    return candidate


def _latest_observations(db: Session, candidate_ids: list[int]) -> dict[int, UnresolvedPlayerObservation]:
    """Latest observation per candidate in one query, so a page does not issue N+1 reads."""
    if not candidate_ids:
        return {}
    rows = db.scalars(
        select(UnresolvedPlayerObservation)
        .where(UnresolvedPlayerObservation.candidate_id.in_(candidate_ids))
        .order_by(
            UnresolvedPlayerObservation.candidate_id,
            UnresolvedPlayerObservation.observed_at.desc(),
            UnresolvedPlayerObservation.id.desc(),
        )
    )
    latest: dict[int, UnresolvedPlayerObservation] = {}
    for row in rows:
        latest.setdefault(row.candidate_id, row)
    return latest


def _candidate_payload(
    candidate: UnresolvedPlayerCandidate,
    latest: UnresolvedPlayerObservation | None,
) -> dict[str, Any]:
    """Evidence-first projection: what was observed, never a claimed identity."""
    return {
        "id": candidate.id,
        "save_id": candidate.fm_save_id,
        "status": candidate.status,
        "display_name": candidate.display_name,
        "normalized_name": candidate.normalized_name,
        "birth_date": candidate.birth_date.isoformat() if candidate.birth_date else None,
        "nationality": candidate.nationality,
        "position": candidate.position,
        "observation_count": candidate.observation_count,
        "first_seen_at": iso(candidate.first_seen_at),
        "last_seen_at": iso(candidate.last_seen_at),
        "uid": {
            "status": candidate.uid_status,
            "reason": candidate.uid_reason,
            "raw_uid": candidate.raw_uid,
            "note": "原始 UID 只作为证据保存，不会写入 save_local_uid",
        },
        "latest_observation": None
        if latest is None
        else {
            "observation_id": latest.id,
            "scan_id": latest.scan_id,
            "row_index": latest.row_index,
            "observed_at": iso(latest.observed_at),
            "game_date": latest.game_date.isoformat() if latest.game_date else None,
            "ca": latest.ca,
            "pa": latest.pa,
            "club_name": latest.club_name,
            "contract_end": latest.contract_end.isoformat() if latest.contract_end else None,
        },
        "resolution": {
            "method": candidate.resolution_method,
            "player_id": candidate.resolved_player_id,
            "player_instance_id": candidate.resolved_player_instance_id,
            "resolved_at": iso(candidate.resolved_at),
        }
        if candidate.status == "resolved"
        else None,
        "dismissal": {
            "reason": candidate.dismiss_reason,
            "dismissed_at": iso(candidate.dismissed_at),
        }
        if candidate.status == "dismissed"
        else None,
        "suggestions_are_advisory": True,
    }


def _action_payload(action: UnresolvedPlayerAction) -> dict[str, Any]:
    return {
        "id": action.id,
        "action": action.action,
        "decision": action.decision,
        "previous_status": action.previous_status,
        "new_status": action.new_status,
        "target_player_id": action.target_player_id,
        "note": action.note,
        "created_at": iso(action.created_at),
        "evidence": json.loads(action.payload_json or "{}"),
    }


def _suggestions(candidate: UnresolvedPlayerCandidate, save: FmSave, db: Session) -> dict[str, Any]:
    matches = identity_suggestions(
        db, save.id, name=candidate.display_name, birth_date=candidate.birth_date
    )
    siblings = sibling_candidates(
        db,
        save.id,
        normalized_name=candidate.normalized_name,
        exclude_candidate_id=candidate.id,
    )
    return {
        "player_matches": matches,
        "sibling_candidates": siblings,
        "note": "以上只是匹配建议，不会自动合并；确认后才建立身份关联",
    }


@router.get("/unresolved-players", summary="待确认自由球员候选列表")
def list_unresolved_players(
    status: str = Query(default="all", pattern="^(all|pending|review_required|resolved|dismissed)$"),
    name: str | None = Query(default=None, max_length=128),
    position: str | None = Query(default=None, max_length=16),
    min_ca: int | None = Query(default=None, ge=0, le=400),
    min_pa: int | None = Query(default=None, ge=0, le=400),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Candidates of the current save, newest first, with per-status counts."""
    query = select(UnresolvedPlayerCandidate).where(UnresolvedPlayerCandidate.fm_save_id == save.id)
    if status != "all":
        query = query.where(UnresolvedPlayerCandidate.status == status)
    if name:
        query = query.where(UnresolvedPlayerCandidate.display_name.ilike(f"%{name}%"))
    if position:
        query = query.where(UnresolvedPlayerCandidate.position == position)
    if min_ca is not None:
        query = query.where(
            UnresolvedPlayerCandidate.latest_ca.is_not(None), UnresolvedPlayerCandidate.latest_ca >= min_ca
        )
    if min_pa is not None:
        query = query.where(
            UnresolvedPlayerCandidate.latest_pa.is_not(None), UnresolvedPlayerCandidate.latest_pa >= min_pa
        )

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = list(
        db.scalars(
            query.order_by(UnresolvedPlayerCandidate.last_seen_at.desc(), UnresolvedPlayerCandidate.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    latest = _latest_observations(db, [row.id for row in rows])
    counts = dict(
        db.execute(
            select(UnresolvedPlayerCandidate.status, func.count())
            .where(UnresolvedPlayerCandidate.fm_save_id == save.id)
            .group_by(UnresolvedPlayerCandidate.status)
        ).all()
    )
    return {
        "items": [_candidate_payload(row, latest.get(row.id)) for row in rows],
        "total": int(total),
        "page": page,
        "page_size": page_size,
        "counts": {
            "pending": int(counts.get("pending", 0)),
            "review_required": int(counts.get("review_required", 0)),
            "resolved": int(counts.get("resolved", 0)),
            "dismissed": int(counts.get("dismissed", 0)),
        },
        "note": "这些球员没有可用身份；确认之前不进入任何正式统计",
    }


@router.get("/unresolved-players/{candidate_id}", summary="候选详情（证据、建议、操作历史）")
def unresolved_player_detail(
    candidate_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    candidate = _candidate_for(db, candidate_id, save)
    latest = _latest_observations(db, [candidate.id]).get(candidate.id)
    actions = list(
        db.scalars(
            select(UnresolvedPlayerAction)
            .where(UnresolvedPlayerAction.candidate_id == candidate.id)
            .order_by(UnresolvedPlayerAction.id)
        )
    )
    return {
        **_candidate_payload(candidate, latest),
        "evidence_summary": json.loads(candidate.evidence_summary_json or "{}"),
        "suggestions": _suggestions(candidate, save, db),
        "history": [_action_payload(item) for item in actions],
        "retention": "观察与审计记录永久保留；忽略候选不会删除任何观察",
    }


@router.get("/unresolved-players/{candidate_id}/observations", summary="候选的历史观察")
def unresolved_player_observations(
    candidate_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    candidate = _candidate_for(db, candidate_id, save)
    query = select(UnresolvedPlayerObservation).where(
        UnresolvedPlayerObservation.candidate_id == candidate.id,
        UnresolvedPlayerObservation.fm_save_id == save.id,
    )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = list(
        db.scalars(
            query.order_by(UnresolvedPlayerObservation.observed_at.desc(), UnresolvedPlayerObservation.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    job_ids = [row.import_job_id for row in rows if row.import_job_id is not None]
    return {
        "candidate_id": candidate.id,
        "items": [
            {
                "id": row.id,
                "scan_id": row.scan_id,
                "row_index": row.row_index,
                "observed_at": iso(row.observed_at),
                "game_date": row.game_date.isoformat() if row.game_date else None,
                "raw_uid": row.raw_uid,
                "uid_status": row.uid_status,
                "name": row.name,
                "birth_date": row.birth_date.isoformat() if row.birth_date else None,
                "nationality": row.nationality,
                "position": row.position,
                "ca": row.ca,
                "pa": row.pa,
                "club_name": row.club_name,
                "contract_end": row.contract_end.isoformat() if row.contract_end else None,
                "import_job_id": row.import_job_id,
                "payload_hash": row.payload_hash,
            }
            for row in rows
        ],
        "total": int(total),
        "page": page,
        "page_size": page_size,
        "import_job_ids": sorted(set(job_ids)),
    }


@router.post("/unresolved-players/{candidate_id}/resolve", summary="人工确认候选的身份关联")
def resolve_unresolved_player(
    candidate_id: int,
    body: UnresolvedResolveIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Attach a candidate to an existing identity in the same save.

    The decision is explicit (``confirm=true``), transactional, audited append-only, and cannot be repeated:
    a concurrent or second decision is rejected with 409 instead of overwriting the first one.
    """
    candidate = _candidate_for(db, candidate_id, save)
    if candidate.status not in OPEN_STATUSES:
        raise HTTPException(
            status_code=409,
            detail={"code": "unresolved_already_decided", "message": f"候选已处理（{candidate.status}）"},
        )
    if not body.confirm:
        raise HTTPException(
            status_code=400,
            detail={"code": "confirmation_required", "message": "必须显式确认（confirm=true）才能建立身份关联"},
        )

    instance = _target_instance(db, save, body)
    suggestions = _suggestions(candidate, save, db)
    evidence = {
        "candidate_id": candidate.id,
        "uid_status": candidate.uid_status,
        "raw_uid": candidate.raw_uid,
        "observation_count": candidate.observation_count,
        "target_player_id": instance.player_id,
        "target_player_instance_id": instance.id,
        "target_save_local_uid": instance.save_local_uid,
        "suggestions_at_decision": suggestions,
        "note": body.note,
    }
    previous = candidate.status
    decided_at = utcnow()

    try:
        changed = db.execute(
            update(UnresolvedPlayerCandidate)
            .where(
                UnresolvedPlayerCandidate.id == candidate.id,
                UnresolvedPlayerCandidate.fm_save_id == save.id,
                UnresolvedPlayerCandidate.status.in_(OPEN_STATUSES),
            )
            .values(
                status="resolved",
                resolution_method="manual_attached",
                resolved_player_id=instance.player_id,
                resolved_player_instance_id=instance.id,
                resolved_at=decided_at,
                resolved_by_user_id=user.id,
                updated_at=decided_at,
            )
        ).rowcount
        if not changed:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail={"code": "unresolved_already_decided", "message": "候选已被另一个请求处理"},
            )
        db.add(
            IdentityMatch(
                player_id=instance.player_id,
                fm_save_id=save.id,
                strategy="unresolved_manual_link",
                confidence=1.0,
                evidence_json=json.dumps(evidence, ensure_ascii=False, default=str),
            )
        )
        action = UnresolvedPlayerAction(
            candidate_id=candidate.id,
            fm_save_id=save.id,
            user_id=user.id,
            action="resolve",
            decision="manual_attached",
            previous_status=previous,
            new_status="resolved",
            target_player_id=instance.player_id,
            note=body.note,
            payload_json=json.dumps(evidence, ensure_ascii=False, default=str),
            created_at=decided_at,
        )
        db.add(action)
        db.commit()
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - the link is one transaction; a failure must not half-apply
        db.rollback()
        raise HTTPException(
            status_code=500, detail={"code": "unresolved_resolve_failed", "message": f"确认失败，已回滚：{exc}"}
        ) from exc

    db.refresh(candidate)
    return {
        "id": candidate.id,
        "status": candidate.status,
        "resolution_method": candidate.resolution_method,
        "player_id": candidate.resolved_player_id,
        "player_instance_id": candidate.resolved_player_instance_id,
        "resolved_at": iso(candidate.resolved_at),
        "evidence": evidence,
        "audit_action_id": action.id,
        "note": "身份关联已写入，原始观察历史保留",
    }


@router.post("/unresolved-players/{candidate_id}/dismiss", summary="忽略候选（不删除观察）")
def dismiss_unresolved_player(
    candidate_id: int,
    body: UnresolvedDismissIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Mark a candidate dismissed; the observations stay queryable for audit."""
    candidate = _candidate_for(db, candidate_id, save)
    if candidate.status == "dismissed":
        raise HTTPException(
            status_code=409,
            detail={"code": "unresolved_already_dismissed", "message": "候选已被忽略"},
        )
    previous = candidate.status
    decided_at = utcnow()
    changed = db.execute(
        update(UnresolvedPlayerCandidate)
        .where(
            UnresolvedPlayerCandidate.id == candidate.id,
            UnresolvedPlayerCandidate.fm_save_id == save.id,
            UnresolvedPlayerCandidate.status != "dismissed",
        )
        .values(
            status="dismissed",
            dismissed_at=decided_at,
            dismissed_by_user_id=user.id,
            dismiss_reason=body.reason,
            updated_at=decided_at,
        )
    ).rowcount
    if not changed:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"code": "unresolved_already_dismissed", "message": "候选已被另一个请求忽略"},
        )
    action = UnresolvedPlayerAction(
        candidate_id=candidate.id,
        fm_save_id=save.id,
        user_id=user.id,
        action="dismiss",
        decision="dismissed_by_reviewer",
        previous_status=previous,
        new_status="dismissed",
        note=body.note,
        payload_json=json.dumps(
            {"reason": body.reason, "observations_kept": candidate.observation_count}, ensure_ascii=False
        ),
        created_at=decided_at,
    )
    db.add(action)
    db.commit()
    db.refresh(candidate)
    return {
        "id": candidate.id,
        "status": candidate.status,
        "dismiss_reason": candidate.dismiss_reason,
        "dismissed_at": iso(candidate.dismissed_at),
        "observations_kept": candidate.observation_count,
        "audit_action_id": action.id,
    }


def _target_instance(db: Session, save: FmSave, body: UnresolvedResolveIn) -> PlayerInstance:
    """Resolve the target identity, rejecting anything outside this save."""
    if body.player_instance_id is not None:
        instance = db.get(PlayerInstance, body.player_instance_id)
        if instance is None or instance.fm_save_id != save.id:
            raise HTTPException(
                status_code=404,
                detail={"code": "target_not_in_save", "message": "目标球员实例不存在于当前存档"},
            )
        return instance
    if body.player_id is not None:
        player = db.get(Player, body.player_id)
        if player is None:
            raise HTTPException(
                status_code=404, detail={"code": "target_not_in_save", "message": "目标球员不存在"}
            )
        instance = db.scalar(
            select(PlayerInstance)
            .where(PlayerInstance.player_id == player.id, PlayerInstance.fm_save_id == save.id)
            .order_by(PlayerInstance.id.desc())
            .limit(1)
        )
        if instance is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "target_not_in_save", "message": "目标球员没有当前存档内的实例"},
            )
        return instance
    raise HTTPException(
        status_code=400,
        detail={"code": "missing_target", "message": "必须提供 player_instance_id 或 player_id"},
    )
