"""Manual canonical review and append-only audit (V3.2.1 SM-061E)."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    Club,
    ImportJob,
    Player,
    PlayerInstance,
    PlayerObservationCanonical,
    PlayerObservationCanonicalAction,
    PlayerAttribute,
    PlayerAttributeValue,
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


def canonical_detail(session: Session, save_id: int, canonical_id: int) -> dict[str, Any]:
    """Snapshot diff payload plus the player's canonical timeline."""
    canonical = _canonical_or_error(session, save_id, canonical_id)
    instance = session.get(PlayerInstance, canonical.player_instance_id)
    player = session.get(Player, instance.player_id) if instance else None
    rows = session.execute(
        select(PlayerSnapshot, ImportJob.source, ImportJob.reader_version, ImportJob.game_build)
        .outerjoin(ImportJob, ImportJob.id == PlayerSnapshot.import_job_id)
        .where(
            PlayerSnapshot.player_instance_id == canonical.player_instance_id,
            PlayerSnapshot.game_date == canonical.game_date,
        )
        .order_by(PlayerSnapshot.observed_at, PlayerSnapshot.id)
    ).all()
    snapshot_ids = [row[0].id for row in rows]
    attributes: dict[int, list[dict[str, Any]]] = {snapshot_id: [] for snapshot_id in snapshot_ids}
    if snapshot_ids:
        attr_rows = session.execute(
            select(
                PlayerAttributeValue.player_snapshot_id,
                PlayerAttribute.key,
                PlayerAttribute.name,
                PlayerAttribute.name_zh,
                PlayerAttribute.category,
                PlayerAttributeValue.value,
            )
            .join(PlayerAttribute, PlayerAttribute.id == PlayerAttributeValue.attribute_id)
            .where(PlayerAttributeValue.player_snapshot_id.in_(snapshot_ids))
            .order_by(PlayerAttribute.sort_order, PlayerAttribute.key)
        )
        for snapshot_id, key, name, name_zh, category, value in attr_rows:
            attributes.setdefault(snapshot_id, []).append({
                "key": key, "name": name, "name_zh": name_zh,
                "category": category, "value": float(value),
            })
    club_names = {
        club.id: club.name for club in session.scalars(
            select(Club).where(Club.fm_save_id == save_id, Club.id.in_({snapshot.club_id for snapshot, *_ in rows if snapshot.club_id}))
        )
    } if any(snapshot.club_id for snapshot, *_ in rows) else {}
    snapshots = []
    for snapshot, source, reader_version, game_build in rows:
        snapshots.append({
            "id": snapshot.id,
            "observed_at": snapshot.observed_at.isoformat() if snapshot.observed_at else None,
            "game_date": (snapshot.game_date or snapshot.observed_at.date()).isoformat(),
            "ca": snapshot.ca, "pa": snapshot.pa, "wage": snapshot.wage,
            "market_value": snapshot.market_value,
            "contract_end": snapshot.contract_end.isoformat() if snapshot.contract_end else None,
            "club_id": snapshot.club_id,
            "club_name": club_names.get(snapshot.club_id),
            "position": snapshot.position,
            "height_cm": snapshot.height_cm,
            "foot": snapshot.foot,
            "source": source, "reader_version": reader_version, "game_build": game_build,
            "attributes": attributes.get(snapshot.id, []),
        })
    timeline_rows = list(session.scalars(
        select(PlayerObservationCanonical)
        .where(
            PlayerObservationCanonical.fm_save_id == save_id,
            PlayerObservationCanonical.player_instance_id == canonical.player_instance_id,
        )
        .order_by(PlayerObservationCanonical.game_date)
    ))
    timeline = [{
        "id": row.id,
        "game_date": row.game_date.isoformat(),
        "status": row.status,
        "canonical_snapshot_id": row.canonical_snapshot_id,
        "conflict": row.conflict,
        "snapshot_count": row.snapshot_count,
        "reason": row.reason,
    } for row in timeline_rows]
    try:
        conflict_types = json.loads(canonical.conflict_types_json or "[]")
    except json.JSONDecodeError:
        conflict_types = []
    max_attrs = max((len(item["attributes"]) for item in snapshots), default=0)
    completeness = round(
        sum(len(item["attributes"]) for item in snapshots) / (max_attrs * len(snapshots)), 4
    ) if snapshots and max_attrs else 0.0
    recommended = max(
        snapshots,
        key=lambda item: (len(item["attributes"]), item["observed_at"] or ""),
        default=None,
    )
    risk = min(100, 20 + len(conflict_types) * 10 + max(0, canonical.snapshot_count - 1) * 5)
    suggestion = {
        "risk_score": risk,
        "priority": "high" if risk >= 60 else "medium" if risk >= 40 else "low",
        "evidence_completeness": completeness,
        "recommended_snapshot_id": recommended["id"] if recommended else None,
        "reason": (
            "按属性完整度优先、同完整度取最新观测；仅为建议，未写入 canonical"
            if recommended else "没有可推荐快照"
        ),
        "auto_applied": False,
    }
    return {
        "canonical": {
            "id": canonical.id,
            "fm_save_id": canonical.fm_save_id,
            "player_instance_id": canonical.player_instance_id,
            "player_name": player.full_name if player else None,
            "player_uid": instance.save_local_uid if instance else None,
            "game_date": canonical.game_date.isoformat(),
            "status": canonical.status,
            "conflict": canonical.conflict,
            "conflict_types": conflict_types,
            "snapshot_count": canonical.snapshot_count,
            "distinct_content_count": canonical.distinct_content_count,
            "canonical_snapshot_id": canonical.canonical_snapshot_id,
            "reason": canonical.reason,
        },
        "snapshots": snapshots,
        "timeline": timeline,
        "suggestion": suggestion,
    }


def governance_overview(session: Session, save_id: int) -> dict[str, Any]:
    """KPI block for the Data Governance Center; read-only."""
    from ..models import PlayerSnapshot
    from .rules import run_quality_rules

    snapshot_count = session.scalar(
        select(func.count()).select_from(PlayerSnapshot).join(PlayerInstance, PlayerInstance.id == PlayerSnapshot.player_instance_id)
        .where(PlayerInstance.fm_save_id == save_id)
    ) or 0
    game_dates = session.scalar(
        select(func.count(func.distinct(PlayerSnapshot.game_date))).join(
            PlayerInstance, PlayerInstance.id == PlayerSnapshot.player_instance_id
        ).where(PlayerInstance.fm_save_id == save_id)
    ) or 0
    players = session.scalar(
        select(func.count(func.distinct(PlayerInstance.id))).where(PlayerInstance.fm_save_id == save_id)
    ) or 0
    counts = {status: 0 for status in ("resolved", "resolved_manual", "needs_review", "excluded", "review_required", "resolved_auto")}
    for status, count in session.execute(
        select(PlayerObservationCanonical.status, func.count())
        .where(PlayerObservationCanonical.fm_save_id == save_id)
        .group_by(PlayerObservationCanonical.status)
    ):
        counts[status] = int(count)
    conflict_types: dict[str, int] = {}
    for raw in session.scalars(
        select(PlayerObservationCanonical.conflict_types_json).where(
            PlayerObservationCanonical.fm_save_id == save_id,
            PlayerObservationCanonical.status == "needs_review",
        )
    ):
        try:
            for item in json.loads(raw or "[]"):
                conflict_types[item] = conflict_types.get(item, 0) + 1
        except json.JSONDecodeError:
            continue
    report = run_quality_rules(session, save_id)
    anomaly_count = sum(finding["count"] for finding in report["findings"] if finding["severity"] in {"error", "warning"})
    return {
        "save_id": save_id,
        "total_snapshots": int(snapshot_count),
        "unique_game_dates": int(game_dates),
        "players": int(players),
        "canonical_groups": sum(counts.values()),
        "resolved_auto": counts["resolved"] + counts["resolved_auto"],
        "resolved_manual": counts["resolved_manual"],
        "needs_review": counts["needs_review"],
        "excluded": counts["excluded"],
        "review_required": counts["review_required"],
        "quality_anomalies": int(anomaly_count),
        "quality_error_groups": report["severity_counts"].get("error", 0),
        "quality_warning_groups": report["severity_counts"].get("warning", 0),
        "conflict_types": [{"type": key, "count": value} for key, value in sorted(conflict_types.items(), key=lambda item: -item[1])],
    }
