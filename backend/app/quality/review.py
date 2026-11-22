"""Manual canonical review and append-only audit (V3.2.1 SM-061E)."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    Player,
    PlayerInstance,
    PlayerObservationCanonical,
    PlayerObservationCanonicalAction,
    PlayerSnapshot,
)

ACTIONS = {"select_snapshot", "exclude_game_date", "keep_pending"}


class ReviewError(ValueError):
    """Validation error with a stable code for the API."""

    def __init__(self, code: str, message: str, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _canonical_or_error(session: Session, save_id: int, canonical_id: int) -> PlayerObservationCanonical:
    canonical = session.get(PlayerObservationCanonical, canonical_id)
    if canonical is None or canonical.fm_save_id != save_id:
        raise ReviewError("canonical_not_found", "canonical 记录不存在", 404)
    return canonical


def review_queue(
    session: Session,
    save_id: int,
    *,
    status: str | None = None,
    player_query: str | None = None,
    game_date: date | None = None,
    conflict_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    query = (
        select(PlayerObservationCanonical, Player.full_name, PlayerInstance.save_local_uid)
        .join(PlayerInstance, PlayerInstance.id == PlayerObservationCanonical.player_instance_id)
        .join(Player, Player.id == PlayerInstance.player_id)
        .where(PlayerObservationCanonical.fm_save_id == save_id)
    )
    if status:
        query = query.where(PlayerObservationCanonical.status == status)
    if player_query:
        like = f"%{player_query}%"
        query = query.where((Player.full_name.ilike(like)) | (PlayerInstance.save_local_uid.ilike(like)))
    if game_date is not None:
        query = query.where(PlayerObservationCanonical.game_date == game_date)
    if conflict_type:
        query = query.where(PlayerObservationCanonical.conflict_types_json.ilike(f"%{conflict_type}%"))
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = list(session.execute(query.order_by(
        PlayerObservationCanonical.conflict.desc(),
        PlayerObservationCanonical.snapshot_count.desc(),
        PlayerObservationCanonical.id,
    ).offset(offset).limit(limit)))
    items = []
    for canonical, name, uid in rows:
        try:
            types = json.loads(canonical.conflict_types_json or "[]")
        except json.JSONDecodeError:
            types = []
        items.append({
            "id": canonical.id,
            "player_instance_id": canonical.player_instance_id,
            "player_name": name,
            "player_uid": uid,
            "game_date": canonical.game_date.isoformat(),
            "status": canonical.status,
            "conflict": canonical.conflict,
            "snapshot_count": canonical.snapshot_count,
            "distinct_content_count": canonical.distinct_content_count,
            "conflict_types": types,
            "canonical_snapshot_id": canonical.canonical_snapshot_id,
            "reason": canonical.reason,
        })
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def history(session: Session, save_id: int, canonical_id: int) -> dict[str, Any]:
    canonical = _canonical_or_error(session, save_id, canonical_id)
    rows = list(session.scalars(
        select(PlayerObservationCanonicalAction)
        .where(
            PlayerObservationCanonicalAction.fm_save_id == save_id,
            PlayerObservationCanonicalAction.canonical_id == canonical_id,
        )
        .order_by(PlayerObservationCanonicalAction.id)
    ))
    return {
        "canonical_id": canonical.id,
        "status": canonical.status,
        "items": [_action_payload(row) for row in rows],
    }


def decide(
    session: Session,
    save_id: int,
    canonical_id: int,
    *,
    reviewer_user_id: int,
    action: str,
    selected_snapshot_id: int | None,
    reason: str,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    canonical = _canonical_or_error(session, save_id, canonical_id)
    if action not in ACTIONS:
        raise ReviewError("invalid_action", "未知审核动作")
    if not reason or not reason.strip():
        raise ReviewError("reason_required", "必须填写审核理由")
    if action == "select_snapshot":
        if selected_snapshot_id is None:
            raise ReviewError("snapshot_required", "select_snapshot 需要 selected_snapshot_id")
        snapshot = session.get(PlayerSnapshot, selected_snapshot_id)
        snapshot_date = (snapshot.game_date or snapshot.observed_at.date()) if snapshot else None
        if snapshot is None or snapshot.player_instance_id != canonical.player_instance_id or snapshot_date != canonical.game_date:
            raise ReviewError("snapshot_not_in_group", "所选快照不属于该球员的同一 game_date", 404)
        new_status = "resolved_manual"
        canonical.canonical_snapshot_id = snapshot.id
        canonical.conflict = False
    elif action == "exclude_game_date":
        new_status = "excluded"
        canonical.canonical_snapshot_id = None
        canonical.conflict = True
    else:
        new_status = "needs_review"
        canonical.canonical_snapshot_id = None
        canonical.conflict = True

    latest = session.scalar(
        select(PlayerObservationCanonicalAction)
        .where(PlayerObservationCanonicalAction.canonical_id == canonical.id)
        .order_by(PlayerObservationCanonicalAction.id.desc())
    )
    if latest is not None and (
        latest.action == action
        and latest.selected_snapshot_id == selected_snapshot_id
        and latest.reason == reason.strip()
    ):
        raise ReviewError("duplicate_decision", "重复提交相同的审核动作", 409)

    previous_status = canonical.status
    canonical.status = new_status
    canonical.reason = reason.strip()
    canonical.reviewed_by_user_id = reviewer_user_id
    canonical.reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    audit = PlayerObservationCanonicalAction(
        canonical_id=canonical.id,
        fm_save_id=save_id,
        player_instance_id=canonical.player_instance_id,
        game_date=canonical.game_date,
        reviewer_user_id=reviewer_user_id,
        action=action,
        selected_snapshot_id=selected_snapshot_id if action == "select_snapshot" else None,
        previous_status=previous_status,
        new_status=new_status,
        reason=reason.strip(),
        evidence_json=json.dumps(evidence or {}, ensure_ascii=False),
    )
    session.add(audit)
    session.commit()
    session.refresh(canonical)
    session.refresh(audit)
    return {"canonical": _canonical_payload(canonical), "action": _action_payload(audit)}


def _canonical_payload(canonical: PlayerObservationCanonical) -> dict[str, Any]:
    return {
        "id": canonical.id,
        "player_instance_id": canonical.player_instance_id,
        "game_date": canonical.game_date.isoformat(),
        "canonical_snapshot_id": canonical.canonical_snapshot_id,
        "status": canonical.status,
        "conflict": canonical.conflict,
    }


def _action_payload(action: PlayerObservationCanonicalAction) -> dict[str, Any]:
    try:
        evidence = json.loads(action.evidence_json or "{}")
    except json.JSONDecodeError:
        evidence = {}
    return {
        "id": action.id,
        "action": action.action,
        "selected_snapshot_id": action.selected_snapshot_id,
        "previous_status": action.previous_status,
        "new_status": action.new_status,
        "reason": action.reason,
        "evidence": evidence,
        "reviewer_user_id": action.reviewer_user_id,
        "created_at": action.created_at.isoformat() if action.created_at else None,
    }
