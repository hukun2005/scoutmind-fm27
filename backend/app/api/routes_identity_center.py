"""V3.2.9 Player Identity Center（身份审核中心 API）。

边界：

* 所有查询都按存档作用域过滤；
* 所有写操作都经过审核服务，不能把任何状态直接写成 Verified；
* 审核历史与原始记录只追加，不删除；
* 批处理有界、可暂停/恢复/取消，恢复前校验作用域。
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import (
    CrossSaveIdentityCandidate,
    FmSave,
    IdentityScanRun,
    Player,
    PlayerIdentityLink,
    PlayerIdentityReviewItem,
    PlayerInstance,
    PlayerUidObservation,
    Transfer,
)
from ..schemas import (
    CrossSaveReviewIn,
    IdentityReviewResolveIn,
    IdentityScanResumeIn,
    IdentityScanStartIn,
)
from ..services import identity_engine
from ..services import identity_errors as errors
from ..services import transfer_identity
from ..services.identity_errors import IdentityGovernanceError
from ..services.identity_review import item_payload, resolve_review
from ..services.uid_scope import current_identity_fingerprint, summary as uid_summary
from ..utils import iso, utcnow
from .deps import get_active_save, get_current_user, owned_save_or_404

router = APIRouter()


def _raise(exc: IdentityGovernanceError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.as_detail()) from exc


def _save_for(db: Session, save_id: int | None, user, active: FmSave) -> FmSave:
    return owned_save_or_404(db, save_id, user) if save_id else active


def _scan_payload(run: IdentityScanRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "scan_id": run.scan_id,
        "save_id": run.fm_save_id,
        "status": run.status,
        "cursor": run.cursor,
        "batch_size": run.batch_size,
        "total_instances": run.total_instances,
        "processed_count": run.processed_count,
        "matched_count": run.matched_count,
        "conflict_count": run.conflict_count,
        "failed_count": run.failed_count,
        "payload_checksum": run.payload_checksum,
        "save_identity_fingerprint": run.save_identity_fingerprint,
        "game_build": run.game_build,
        "layout_version": run.layout_version,
        "started_at": iso(run.started_at),
        "finished_at": iso(run.finished_at),
        "error_code": run.error_code,
        "error_message": run.error_message,
        "created_at": iso(run.created_at),
        "updated_at": iso(run.updated_at),
    }


def _run_by_scan(db: Session, save_id: int, scan_id: str) -> IdentityScanRun:
    run = db.scalar(
        select(IdentityScanRun).where(
            IdentityScanRun.fm_save_id == save_id, IdentityScanRun.scan_id == scan_id
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail={"code": errors.SCAN_NOT_FOUND, "message": "扫描不存在"})
    return run


@router.get("/identity/center/summary", summary="全库身份统计与治理状态")
def center_summary(
    save_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    target = _save_for(db, save_id, user, save)
    return {
        "save_id": target.id,
        "generated_at": iso(utcnow()),
        **identity_engine.center_summary(db, target.id),
        "transfer_links": transfer_identity.transfer_link_summary(db, target.id),
        "current_save_identity_fingerprint": current_identity_fingerprint(db, target.id),
    }


@router.get("/identity/center/queue", summary="人工审核队列")
def review_queue(
    status: str = Query(default="PendingHumanReview", pattern="^(PendingHumanReview|Confirmed|Rejected|KeptIndependent|Deferred|Stale|all)$"),
    item_type: str | None = Query(default=None, max_length=32),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    save_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    target = _save_for(db, save_id, user, save)
    query = select(PlayerIdentityReviewItem).where(PlayerIdentityReviewItem.fm_save_id == target.id)
    if status != "all":
        query = query.where(PlayerIdentityReviewItem.status == status)
    if item_type:
        query = query.where(PlayerIdentityReviewItem.item_type == item_type)
    total = int(db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    rows = list(
        db.scalars(
            query.order_by(PlayerIdentityReviewItem.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    counts = dict(
        db.execute(
            select(PlayerIdentityReviewItem.status, func.count())
            .where(PlayerIdentityReviewItem.fm_save_id == target.id)
            .group_by(PlayerIdentityReviewItem.status)
        ).all()
    )
    return {
        "items": [item_payload(db, row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "counts": {str(key): int(value) for key, value in counts.items()},
        "decisions": ["same", "different", "independent", "defer"],
        "note": "审核只产生 Confirmed/Rejected/KeptIndependent/Deferred；不会产生 Verified",
    }


@router.get("/identity/center/queue/{item_id}", summary="审核条目详情与历史")
def review_detail(
    item_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    item = db.get(PlayerIdentityReviewItem, item_id)
    if item is None or item.fm_save_id != save.id:
        raise HTTPException(status_code=404, detail={"code": errors.REVIEW_NOT_FOUND, "message": "审核条目不存在"})
    return item_payload(db, item)


@router.post("/identity/center/queue/{item_id}/resolve", summary="提交人工审核决定")
def review_resolve(
    item_id: int,
    body: IdentityReviewResolveIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    item = db.get(PlayerIdentityReviewItem, item_id)
    if item is None or item.fm_save_id != save.id:
        raise HTTPException(status_code=404, detail={"code": errors.REVIEW_NOT_FOUND, "message": "审核条目不存在"})
    try:
        resolve_review(db, item, user=user, decision=body.decision, note=body.note, payload=body.payload)
        db.commit()
    except IdentityGovernanceError as exc:
        db.rollback()
        _raise(exc)
    return {"id": item.id, "status": item.status, "resolved_at": iso(item.resolved_at)}


@router.get("/identity/center/players/{player_id}", summary="球员身份详情：实例/关联/观测/审核")
def player_identity_detail(
    player_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    player = db.get(Player, player_id)
    if player is None:
        raise HTTPException(status_code=404, detail={"code": errors.PERSON_NOT_FOUND, "message": "球员不存在"})
    instances = list(
        db.scalars(
            select(PlayerInstance).where(
                PlayerInstance.fm_save_id == save.id, PlayerInstance.player_id == player_id
            )
        )
    )
    if not instances:
        raise HTTPException(status_code=404, detail={"code": errors.PERSON_NOT_FOUND, "message": "该球员不属于当前存档"})
    instance_ids = [row.id for row in instances]
    links = list(
        db.scalars(
            select(PlayerIdentityLink).where(
                PlayerIdentityLink.fm_save_id == save.id,
                PlayerIdentityLink.player_instance_id.in_(instance_ids),
            ).order_by(PlayerIdentityLink.id.desc())
        )
    )
    observations = list(
        db.scalars(
            select(PlayerUidObservation)
            .where(
                PlayerUidObservation.fm_save_id == save.id,
                PlayerUidObservation.player_instance_id.in_(instance_ids),
            )
            .order_by(PlayerUidObservation.id.desc())
            .limit(50)
        )
    )
    reviews = list(
        db.scalars(
            select(PlayerIdentityReviewItem).where(
                PlayerIdentityReviewItem.fm_save_id == save.id,
                PlayerIdentityReviewItem.primary_player_id == player_id,
            ).order_by(PlayerIdentityReviewItem.id.desc())
        )
    )
    transfers = list(
        db.scalars(
            select(Transfer).where(
                Transfer.fm_save_id == save.id, Transfer.player_instance_id.in_(instance_ids)
            )
        )
    )
    return {
        "player_id": player.id,
        "full_name": player.full_name,
        "normalized_name": player.normalized_name,
        "birth_date": player.birth_date.isoformat() if player.birth_date else None,
        "nationality": player.nationality,
        "instances": [
            {
                "instance_id": row.id,
                "save_local_uid": row.save_local_uid,
                "uid_occurrence": row.uid_occurrence,
                "club_id": row.club_id,
                "position": row.position,
                "last_seen_at": iso(row.last_seen_at),
            }
            for row in instances
        ],
        "links": [
            {
                "id": row.id,
                "canonical_player_id": row.canonical_player_id,
                "verification_status": row.verification_status,
                "confidence": row.confidence,
                "valid_from": iso(row.valid_from),
                "valid_to": iso(row.valid_to),
                "evidence": json.loads(row.evidence_json or "{}"),
            }
            for row in links
        ],
        "uid_observations": [
            {
                "id": row.id,
                "uid": row.uid,
                "uid_status": row.uid_status,
                "status": row.status,
                "source_type": row.source_type,
                "observed_at": iso(row.observed_at),
                "attribute_record_digest": row.attribute_record_digest,
                "evidence_hash": row.evidence_hash,
            }
            for row in observations
        ],
        "reviews": [
            {
                "id": row.id,
                "item_type": row.item_type,
                "status": row.status,
                "conflict_reason": row.conflict_reason,
                "detected_at": iso(row.detected_at),
            }
            for row in reviews
        ],
        "transfer_ids": [row.id for row in transfers],
        "verified_note": "Verified 由 V3.2.8.1 存档作用域门控决定，本接口只展示不写入",
    }


@router.get("/identity/center/uid-map", summary="UID 作用域映射（存档内）")
def uid_map(
    uid: str | None = Query(default=None, max_length=64),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    save_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    target = _save_for(db, save_id, user, save)
    query = select(PlayerUidObservation).where(PlayerUidObservation.fm_save_id == target.id)
    if uid:
        query = query.where(PlayerUidObservation.uid == uid)
    total = int(db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    rows = list(
        db.scalars(
            query.order_by(PlayerUidObservation.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return {
        "summary": uid_summary(db, target.id),
        "items": [
            {
                "id": row.id,
                "uid": row.uid,
                "uid_status": row.uid_status,
                "uid_reason": row.uid_reason,
                "status": row.status,
                "player_id": row.player_id,
                "player_instance_id": row.player_instance_id,
                "source_type": row.source_type,
                "save_identity_fingerprint": row.save_identity_fingerprint,
                "game_build": row.game_build,
                "layout_version": row.layout_version,
                "observed_at": iso(row.observed_at),
            }
            for row in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "note": "UID 只在存档作用域内有效；跨存档相同 UID 不视为同一球员",
    }


@router.get("/identity/center/cross-save", summary="跨存档身份候选")
def cross_save_candidates(
    other_save_id: int | None = Query(default=None),
    generate: bool = Query(default=False),
    status: str = Query(default="all", max_length=24),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    if generate:
        if other_save_id is None:
            raise HTTPException(
                status_code=400, detail={"code": "cross_save_invalid", "message": "生成候选需要 other_save_id"}
            )
        owned_save_or_404(db, other_save_id, user)
        try:
            identity_engine.find_cross_save_candidates(db, save.id, other_save_id)
            db.commit()
        except IdentityGovernanceError as exc:
            db.rollback()
            _raise(exc)
    query = select(CrossSaveIdentityCandidate).where(CrossSaveIdentityCandidate.fm_save_id == save.id)
    if other_save_id is not None:
        query = query.where(CrossSaveIdentityCandidate.other_save_id == other_save_id)
    if status != "all":
        query = query.where(CrossSaveIdentityCandidate.status == status)
    rows = list(db.scalars(query.order_by(CrossSaveIdentityCandidate.match_score.desc()).limit(500)))
    return {
        "items": [
            {
                "id": row.id,
                "other_save_id": row.other_save_id,
                "subject_player_id": row.subject_player_id,
                "other_player_id": row.other_player_id,
                "normalized_name": row.normalized_name,
                "birth_date": row.birth_date.isoformat() if row.birth_date else None,
                "match_score": row.match_score,
                "status": row.status,
                "uid_equal": row.uid_equal,
                "evidence": json.loads(row.evidence_json or "{}"),
                "resolved_at": iso(row.resolved_at),
            }
            for row in rows
        ],
        "note": "跨存档候选不会自动合并；相同 UID 只是证据",
    }


@router.post("/identity/center/cross-save/{candidate_id}/review", summary="人工处理跨存档候选")
def cross_save_review(
    candidate_id: int,
    body: CrossSaveReviewIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    candidate = db.get(CrossSaveIdentityCandidate, candidate_id)
    if candidate is None or candidate.fm_save_id != save.id:
        raise HTTPException(status_code=404, detail={"code": "cross_save_not_found", "message": "候选不存在"})
    if candidate.status in ("CrossSaveMatched", "CrossSaveRejected"):
        raise HTTPException(
            status_code=409,
            detail={"code": errors.REVIEW_ALREADY_RESOLVED, "message": "该候选已处理，不覆盖历史"},
        )
    if body.decision == "same":
        # 两个存档各自关联到同一个 Canonical 球员；不移动实例、不删除记录。
        identity_engine.confirm_candidate_links(
            db,
            save_id=save.id,
            canonical_player_id=candidate.subject_player_id,
            player_ids=[candidate.subject_player_id],
            reason="cross_save_confirmed",
            evidence={"candidate_id": candidate.id, "note": body.note},
        )
        identity_engine.confirm_candidate_links(
            db,
            save_id=candidate.other_save_id,
            canonical_player_id=candidate.subject_player_id,
            player_ids=[candidate.other_player_id],
            reason="cross_save_confirmed",
            evidence={"candidate_id": candidate.id, "note": body.note},
        )
        candidate.status = "CrossSaveMatched"
    elif body.decision == "different":
        candidate.status = "CrossSaveRejected"
    else:
        candidate.status = "CrossSavePendingReview"
    candidate.resolved_at = utcnow() if body.decision != "defer" else None
    candidate.resolved_by_user_id = user.id
    db.commit()
    return {"id": candidate.id, "status": candidate.status, "resolved_at": iso(candidate.resolved_at)}


@router.get("/identity/center/history", summary="全库身份审核历史（追加写）")
def review_history(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    from ..models import PlayerIdentityReviewAction

    rows = list(
        db.scalars(
            select(PlayerIdentityReviewAction)
            .where(PlayerIdentityReviewAction.fm_save_id == save.id)
            .order_by(PlayerIdentityReviewAction.id.desc())
            .limit(limit)
        )
    )
    return {
        "items": [
            {
                "id": row.id,
                "review_id": row.review_id,
                "action": row.action,
                "decision": row.decision,
                "previous_status": row.previous_status,
                "new_status": row.new_status,
                "note": row.note,
                "user_id": row.user_id,
                "created_at": iso(row.created_at),
            }
            for row in rows
        ],
        "note": "审核历史只追加；错误决定通过新记录修正",
    }


# ---------------------------------------------------------------------------
# 扫描批次
# ---------------------------------------------------------------------------


@router.post("/identity/scans", summary="创建/执行全库身份扫描（幂等 scan_id）")
def create_scan(
    body: IdentityScanStartIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    fingerprint = body.save_identity_fingerprint or current_identity_fingerprint(db, save.id)
    try:
        run = identity_engine.start_scan(
            db,
            save.id,
            scan_id=body.scan_id,
            batch_size=body.batch_size,
            fingerprint=fingerprint,
            game_build=body.game_build,
            layout_version=body.layout_version,
        )
        db.commit()
        run = identity_engine.run_scan(db, run, max_batches=body.max_batches)
    except IdentityGovernanceError as exc:
        db.rollback()
        _raise(exc)
    return _scan_payload(run)


@router.get("/identity/scans", summary="扫描批次列表")
def list_scans(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    rows = list(
        db.scalars(
            select(IdentityScanRun)
            .where(IdentityScanRun.fm_save_id == save.id)
            .order_by(IdentityScanRun.id.desc())
            .limit(limit)
        )
    )
    return {"items": [_scan_payload(row) for row in rows]}


@router.get("/identity/scans/{scan_id}", summary="扫描批次详情")
def scan_detail(
    scan_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    return _scan_payload(_run_by_scan(db, save.id, scan_id))


@router.post("/identity/scans/{scan_id}/pause", summary="暂停扫描")
def pause_scan(
    scan_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    run = identity_engine.pause_scan(db, _run_by_scan(db, save.id, scan_id))
    db.commit()
    return _scan_payload(run)


@router.post("/identity/scans/{scan_id}/resume", summary="恢复扫描（校验作用域）")
def resume_scan(
    scan_id: str,
    body: IdentityScanResumeIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    run = _run_by_scan(db, save.id, scan_id)
    fingerprint = body.save_identity_fingerprint or current_identity_fingerprint(db, save.id)
    try:
        run = identity_engine.resume_scan(
            db,
            run,
            fingerprint=fingerprint,
            game_build=body.game_build,
            layout_version=body.layout_version,
            max_batches=body.max_batches,
        )
        db.commit()
    except IdentityGovernanceError as exc:
        db.rollback()
        _raise(exc)
    return _scan_payload(run)


@router.post("/identity/scans/{scan_id}/cancel", summary="取消扫描")
def cancel_scan(
    scan_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    run = identity_engine.cancel_scan(db, _run_by_scan(db, save.id, scan_id))
    db.commit()
    return _scan_payload(run)


@router.post("/identity/transfers/link", summary="补齐历史转会与球员身份的关联")
def link_transfers(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    result = transfer_identity.link_transfers(db, save.id)
    db.commit()
    return {**result, "summary": transfer_identity.transfer_link_summary(db, save.id)}
