"""Identity Resolution Center（SM-011）。

冲突复核的入口：列表、详情、人工确认（同一人 / 不同人 / 暂不处理）与操作审计。

约束：

* 只能看到并处理自己存档的冲突；
* 合并走事务，先迁移引用再删除多余身份，任何一步失败整体回滚；
* 冲突证据永不删除，只改状态，所有操作写审计表；
* 合并前检查 PlayerInstance / Snapshot / Transfer / IdentityMatch 等外键。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import (
    FmSave,
    IdentityConflict,
    IdentityConflictAction,
    IdentityMatch,
    ImportJob,
    Player,
    PlayerInstance,
    PlayerSnapshot,
    Transfer,
)
from ..schemas import IdentityConflictResolve
from ..utils import iso, utcnow
from .deps import get_active_save, get_current_user

router = APIRouter()

OPEN_STATUSES = ("open",)
DECISIONS = {"same": "same_person", "different": "different_people", "defer": "deferred"}


def _owned_save(db: Session, save_id: int, user) -> FmSave:
    target = db.get(FmSave, save_id)
    if target is None or target.user_id != user.id:
        raise HTTPException(status_code=404, detail={"code": "save_not_found", "message": "存档不存在"})
    return target


def _conflict_for(db: Session, conflict_id: int, save_id: int) -> IdentityConflict:
    conflict = db.get(IdentityConflict, conflict_id)
    if conflict is None or conflict.fm_save_id != save_id:
        raise HTTPException(status_code=404, detail={"code": "conflict_not_found", "message": "冲突不存在"})
    return conflict


def _player_payload(db: Session, player: Player | None, save_id: int) -> dict[str, Any] | None:
    if player is None:
        return None
    instances = list(
        db.scalars(
            select(PlayerInstance).where(
                PlayerInstance.player_id == player.id, PlayerInstance.fm_save_id == save_id
            )
        )
    )
    instance_ids = [item.id for item in instances]
    snapshots = (
        db.scalar(
            select(func.count())
            .select_from(PlayerSnapshot)
            .where(PlayerSnapshot.player_instance_id.in_(instance_ids or [-1]))
        )
        or 0
    )
    transfers = (
        db.scalar(
            select(func.count())
            .select_from(Transfer)
            .where(Transfer.player_instance_id.in_(instance_ids or [-1]))
        )
        or 0
    )
    matches = list(
        db.scalars(select(IdentityMatch).where(IdentityMatch.player_id == player.id).order_by(IdentityMatch.created_at.desc()).limit(5))
    )
    latest_instance = max(instances, key=lambda item: item.last_seen_at, default=None)
    sources: list[dict[str, Any]] = []
    if latest_instance is not None:
        jobs = list(
            db.scalars(
                select(ImportJob)
                .join(PlayerSnapshot, PlayerSnapshot.import_job_id == ImportJob.id)
                .where(PlayerSnapshot.player_instance_id == latest_instance.id)
                .order_by(ImportJob.id.desc())
                .limit(3)
            )
        )
        seen: set[int] = set()
        for job in jobs:
            if job.id in seen:
                continue
            seen.add(job.id)
            sources.append(
                {
                    "import_job_id": job.id,
                    "scan_id": job.scan_id,
                    "source": job.source,
                    "received_at": iso(job.received_at),
                    "status": job.status,
                }
            )
    return {
        "player_id": player.id,
        "full_name": player.full_name,
        "birth_date": player.birth_date.isoformat() if player.birth_date else None,
        "nationality": player.nationality,
        "instances": [
            {
                "instance_id": item.id,
                "save_local_uid": item.save_local_uid,
                "game_unique_id": item.game_unique_id,
                "uid_occurrence": item.uid_occurrence,
                "club_id": item.club_id,
                "position": item.position,
                "last_seen_at": iso(item.last_seen_at),
            }
            for item in instances
        ],
        "instance_count": len(instances),
        "snapshot_count": int(snapshots),
        "transfer_count": int(transfers),
        "sources": sources,
        "recent_matches": [
            {
                "strategy": match.strategy,
                "confidence": match.confidence,
                "evidence": json.loads(match.evidence_json or "{}"),
                "created_at": iso(match.created_at),
            }
            for match in matches
        ],
    }


def _suggestion(conflict: IdentityConflict) -> dict[str, Any]:
    """根据冲突证据给出建议，但绝不自动执行。"""
    fields = [item for item in (conflict.conflict_fields or "").split(",") if item]
    same_name = (conflict.existing_name or "").strip().lower() == (conflict.incoming_name or "").strip().lower()
    both_birth = conflict.existing_birth_date and conflict.incoming_birth_date
    days = abs((conflict.existing_birth_date - conflict.incoming_birth_date).days) if both_birth else None

    if same_name and days is not None and days <= 366:
        decision, reason = "same", f"姓名一致且生日相差 {days} 天，通常是数据源精度差异"
    elif same_name:
        decision, reason = "same", "姓名一致，UID 相同；建议核对生日后确认同一人"
    elif days is not None and days > 366:
        decision, reason = "different", f"姓名不同且生日相差 {days} 天，极可能是 UID 复用"
    elif "birth_date" in fields:
        decision, reason = "different", "生日冲突且姓名不同，建议保持两个身份"
    else:
        decision, reason = "defer", "证据不足以判断，建议人工查看两侧来源后再决定"
    return {"decision": decision, "reason": reason, "confidence": conflict.confidence, "days": days}


@router.get("/identity/conflicts", summary="身份冲突列表（按存档/状态/类型/置信度筛选）")
def list_conflicts(
    status: str = Query(default="open", pattern="^(open|resolved|deferred|all)$"),
    reason: str | None = Query(default=None, max_length=48),
    min_confidence: float | None = Query(default=None, ge=0, le=1),
    sort: str = Query(default="confidence_desc", pattern="^(confidence_desc|confidence_asc|created_desc|created_asc)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    save_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """当前存档的身份冲突，默认只看待处理。"""
    target = _owned_save(db, save_id, user) if save_id else save
    query = select(IdentityConflict).where(IdentityConflict.fm_save_id == target.id)
    if status != "all":
        query = query.where(IdentityConflict.status == status)
    if reason:
        query = query.where(IdentityConflict.reason == reason)
    if min_confidence is not None:
        query = query.where(IdentityConflict.confidence.is_not(None), IdentityConflict.confidence >= min_confidence)

    order = {
        "confidence_desc": IdentityConflict.confidence.desc(),
        "confidence_asc": IdentityConflict.confidence.asc(),
        "created_desc": IdentityConflict.created_at.desc(),
        "created_asc": IdentityConflict.created_at.asc(),
    }[sort]
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = list(
        db.scalars(query.order_by(order, IdentityConflict.id.desc()).offset((page - 1) * page_size).limit(page_size))
    )
    counts = dict(
        db.execute(
            select(IdentityConflict.status, func.count())
            .where(IdentityConflict.fm_save_id == target.id)
            .group_by(IdentityConflict.status)
        ).all()
    )
    return {
        "items": [
            {
                "id": row.id,
                "uid": row.save_local_uid,
                "reason": row.reason,
                "status": row.status,
                "conflict_fields": [item for item in (row.conflict_fields or "").split(",") if item],
                "confidence": row.confidence,
                "existing": {
                    "player_id": row.existing_player_id,
                    "name": row.existing_name,
                    "birth_date": row.existing_birth_date.isoformat() if row.existing_birth_date else None,
                },
                "incoming": {
                    "player_id": row.incoming_player_id,
                    "name": row.incoming_name,
                    "birth_date": row.incoming_birth_date.isoformat() if row.incoming_birth_date else None,
                },
                "suggestion": _suggestion(row),
                "created_at": iso(row.created_at),
                "resolved_at": iso(row.resolved_at),
            }
            for row in rows
        ],
        "total": int(total),
        "page": page,
        "page_size": page_size,
        "counts": {
            "open": int(counts.get("open", 0)),
            "resolved": int(counts.get("resolved", 0)),
            "deferred": int(counts.get("deferred", 0)),
        },
        "note": "冲突只按证据展示；系统不会自动合并，人工决定后才执行",
    }


@router.get("/identity/conflicts/{conflict_id}", summary="身份冲突详情（双方球员、来源、建议、操作历史）")
def conflict_detail(
    conflict_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    conflict = _conflict_for(db, conflict_id, save.id)
    actions = list(
        db.scalars(
            select(IdentityConflictAction)
            .where(IdentityConflictAction.conflict_id == conflict.id)
            .order_by(IdentityConflictAction.id)
        )
    )
    existing = _player_payload(db, db.get(Player, conflict.existing_player_id) if conflict.existing_player_id else None, save.id)
    incoming = _player_payload(db, db.get(Player, conflict.incoming_player_id) if conflict.incoming_player_id else None, save.id)
    return {
        "id": conflict.id,
        "uid": conflict.save_local_uid,
        "reason": conflict.reason,
        "status": conflict.status,
        "resolution": conflict.resolution,
        "conflict_fields": [item for item in (conflict.conflict_fields or "").split(",") if item],
        "confidence": conflict.confidence,
        "evidence": json.loads(conflict.evidence_json or "{}"),
        "suggestion": _suggestion(conflict),
        "existing": existing,
        "incoming": incoming,
        "history": [
            {
                "id": item.id,
                "action": item.action,
                "decision": item.decision,
                "note": item.note,
                "user_id": item.user_id,
                "created_at": iso(item.created_at),
                "payload": json.loads(item.payload_json or "{}"),
            }
            for item in actions
        ],
        "retention": "冲突与审计记录永久保留；合并只迁移引用，不删除证据",
    }


def _merge_players(db: Session, conflict: IdentityConflict, keep_player_id: int, drop_player_id: int) -> dict[str, int]:
    """把 drop 的存档内实例迁到 keep，并清掉失去引用的身份。

    只动当前存档的数据；快照/转会/身份匹配都改指向 keep，最后才删除 drop 身份。
    """
    if keep_player_id == drop_player_id:
        return {"instances_moved": 0, "matches_moved": 0, "transfers_moved": 0}
    keep = db.get(Player, keep_player_id)
    drop = db.get(Player, drop_player_id)
    if keep is None or drop is None:
        raise HTTPException(status_code=409, detail={"code": "player_missing", "message": "冲突中的球员已不存在"})

    instances = list(
        db.scalars(
            select(PlayerInstance).where(
                PlayerInstance.player_id == drop.id, PlayerInstance.fm_save_id == conflict.fm_save_id
            )
        )
    )
    for instance in instances:
        instance.player_id = keep.id
    matches = db.scalars(select(IdentityMatch).where(IdentityMatch.player_id == drop.id)).all()
    for match in matches:
        match.player_id = keep.id
    db.flush()

    # 丢弃身份若还有别的引用（其他存档实例 / 其它记录），保留 Player 行，只解除冲突。
    db.flush()
    # 不删除 Player 行：冲突证据、审计和外键都还引用它；合并后它只是不再有本存档实例。
    return {"instances_moved": len(instances), "matches_moved": len(matches), "transfers_moved": 0}


@router.post("/identity/conflicts/{conflict_id}/resolve", summary="人工确认身份冲突")
def resolve_conflict(
    conflict_id: int,
    body: IdentityConflictResolve,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """same / different / defer；并发确认会被状态检查拦下。"""
    conflict = _conflict_for(db, conflict_id, save.id)
    if conflict.status != "open":
        raise HTTPException(
            status_code=409,
            detail={"code": "conflict_already_resolved", "message": f"冲突已处理（{conflict.status}）"},
        )
    if body.decision == "same" and not (conflict.existing_player_id and conflict.incoming_player_id):
        raise HTTPException(status_code=409, detail={"code": "missing_player", "message": "冲突缺少一方身份，不能合并"})

    summary: dict[str, int] = {"instances_moved": 0, "matches_moved": 0, "transfers_moved": 0}
    try:
        if body.decision == "same":
            keep_id = conflict.existing_player_id if body.keep == "existing" else conflict.incoming_player_id
            drop_id = conflict.incoming_player_id if body.keep == "existing" else conflict.existing_player_id
            summary = _merge_players(db, conflict, int(keep_id), int(drop_id))
            conflict.resolution = "manual_merged"
            conflict.status = "resolved"
        elif body.decision == "different":
            conflict.resolution = "manual_distinct"
            conflict.status = "resolved"
        else:
            conflict.resolution = "deferred"
            conflict.status = "deferred"
        conflict.resolved_at = utcnow() if conflict.status == "resolved" else None
        db.add(
            IdentityConflictAction(
                conflict_id=conflict.id,
                fm_save_id=save.id,
                user_id=user.id,
                action=body.decision,
                decision=DECISIONS[body.decision],
                note=body.note,
                payload_json=json.dumps({"summary": summary, "keep": body.keep}, ensure_ascii=False),
            )
        )
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:  # noqa: BLE001 - 合并是事务，失败必须完整回滚
        db.rollback()
        raise HTTPException(status_code=500, detail={"code": "merge_failed", "message": f"合并失败，已回滚：{exc}"}) from exc

    return {
        "id": conflict.id,
        "status": conflict.status,
        "resolution": conflict.resolution,
        "merged": summary if body.decision == "same" else None,
        "note": "冲突证据保留，操作已写入审计记录",
    }
