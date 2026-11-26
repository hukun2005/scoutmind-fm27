"""V3.2.9 Phase 2/4/5：全库关联引擎、Canonical 关联与跨存档候选。

三个明确边界：

1. 全库处理是**有界批处理**：每批一个游标、每批提交、可暂停/恢复/取消。
2. 引擎只生产 ``Candidate`` / ``Unverified`` / 冲突条目，**永不生产 Verified**。
3. 跨存档只生产候选，相同 UID 只作为证据，不构成身份。

恢复前必须校验作用域（存档身份指纹、构建、布局、实例范围）；不匹配立即停止，不复用旧指针。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    CrossSaveIdentityCandidate,
    IdentityScanRun,
    Player,
    PlayerIdentityLink,
    PlayerInstance,
    PlayerUidObservation,
)
from ..utils import normalize_name, utcnow
from . import identity_errors as errors
from .identity_errors import IdentityGovernanceError
from .identity_review import ensure_review_item
from .uid_scope import (
    STATUS_CONFLICTED,
    STATUS_DUPLICATE,
    STATUS_VALID,
    UidScope,
    digest_json,
    duplicate_uid_groups,
    players_for_uid,
    record_observation,
    summary as uid_summary,
)

#: 超过这个数量就不再一次性把元数据索引装进内存（按 200 一批也仍安全）。
MAX_INDEXED_INSTANCES = 200_000


# ---------------------------------------------------------------------------
# Canonical 关联
# ---------------------------------------------------------------------------


def _link_key(save_id: int, instance_id: int | None, canonical_player_id: int, valid_from: datetime) -> str:
    return digest_json(
        {
            "save_id": save_id,
            "player_instance_id": instance_id,
            "canonical_player_id": canonical_player_id,
            "valid_from": valid_from.replace(microsecond=0).isoformat(),
        }
    )


def active_link(db: Session, save_id: int, instance_id: int) -> PlayerIdentityLink | None:
    return db.scalar(
        select(PlayerIdentityLink)
        .where(
            PlayerIdentityLink.fm_save_id == save_id,
            PlayerIdentityLink.player_instance_id == instance_id,
            PlayerIdentityLink.valid_to.is_(None),
        )
        .order_by(PlayerIdentityLink.id.desc())
        .limit(1)
    )


def _write_link(
    db: Session,
    *,
    save_id: int,
    canonical_player_id: int,
    instance: PlayerInstance,
    status: str,
    confidence: float | None,
    evidence: dict[str, Any],
) -> PlayerIdentityLink:
    current = active_link(db, save_id, instance.id)
    if current is not None:
        if current.canonical_player_id == canonical_player_id and current.verification_status == status:
            return current
        # 人工确认不能被扫描降级；其余状态变化通过「关闭旧关联 + 追加新关联」保留历史。
        if (
            current.canonical_player_id == canonical_player_id
            and current.verification_status == "ConfirmedByHuman"
            and status != "ConfirmedByHuman"
        ):
            return current
        current.valid_to = utcnow()
    moment = utcnow()
    link = PlayerIdentityLink(
        canonical_player_id=canonical_player_id,
        fm_save_id=save_id,
        player_instance_id=instance.id,
        save_local_uid=instance.save_local_uid,
        uid_occurrence=instance.uid_occurrence,
        source_record_id=instance.game_unique_id,
        verification_status=status,
        confidence=confidence,
        link_key=_link_key(save_id, instance.id, canonical_player_id, moment),
        linked_at=moment,
        valid_from=moment,
        evidence_json=json.dumps(evidence, ensure_ascii=False, default=str),
    )
    db.add(link)
    db.flush()
    if current is not None and current.valid_to is not None:
        current.superseded_by_id = link.id
    return link


def confirm_candidate_links(
    db: Session,
    *,
    save_id: int,
    canonical_player_id: int | None,
    player_ids: list[int],
    reason: str,
    evidence: dict[str, Any],
) -> int:
    """人工确认后把若干球员的存档内实例关联到同一个 Canonical 球员。

    只新增/升级关联行，不移动实例、不删除球员、不改写 Verified。返回处理的实例数。
    """
    if canonical_player_id is None or not player_ids:
        raise IdentityGovernanceError(errors.CANONICAL_LINK_CONFLICT, "缺少可确认的球员或 Canonical 身份")
    canonical = db.get(Player, canonical_player_id)
    if canonical is None:
        raise IdentityGovernanceError(errors.PERSON_NOT_FOUND, "Canonical 球员不存在", status_code=404)
    instances = list(
        db.scalars(
            select(PlayerInstance).where(
                PlayerInstance.fm_save_id == save_id,
                PlayerInstance.player_id.in_(player_ids),
            )
        )
    )
    for instance in instances:
        _write_link(
            db,
            save_id=save_id,
            canonical_player_id=canonical_player_id,
            instance=instance,
            status="ConfirmedByHuman",
            confidence=1.0,
            evidence={"reason": reason, **evidence},
        )
    return len(instances)


def mark_save_links_stale(db: Session, save_id: int, *, reason: str) -> int:
    """存档身份/会话变化时让当前有效关联失效，但保留历史行。"""
    rows = list(
        db.scalars(
            select(PlayerIdentityLink).where(
                PlayerIdentityLink.fm_save_id == save_id,
                PlayerIdentityLink.valid_to.is_(None),
            )
        )
    )
    moment = utcnow()
    for row in rows:
        row.valid_to = moment
        row.verification_status = "Stale"
        row.evidence_json = json.dumps(
            {**json.loads(row.evidence_json or "{}"), "stale_reason": reason}, ensure_ascii=False
        )
    db.flush()
    return len(rows)


# ---------------------------------------------------------------------------
# 扫描批次
# ---------------------------------------------------------------------------


def _scope_checksum(
    save_id: int,
    *,
    fingerprint: str | None,
    game_build: str | None,
    layout_version: str | None,
    total_instances: int,
    max_instance_id: int,
) -> str:
    return digest_json(
        {
            "save_id": save_id,
            "save_identity_fingerprint": fingerprint,
            "game_build": game_build,
            "layout_version": layout_version,
            "total_instances": total_instances,
            "max_instance_id": max_instance_id,
        }
    )


def start_scan(
    db: Session,
    save_id: int,
    *,
    scan_id: str,
    batch_size: int = 200,
    fingerprint: str | None = None,
    game_build: str | None = None,
    layout_version: str | None = None,
) -> IdentityScanRun:
    """创建（或返回已存在的）扫描批次。同一 scan_id 重放是幂等的。"""
    if not scan_id or len(scan_id) > 64:
        raise IdentityGovernanceError("scan_id_invalid", "scan_id 必填且不超过 64 字符", status_code=400)
    existing = db.scalar(
        select(IdentityScanRun).where(
            IdentityScanRun.fm_save_id == save_id, IdentityScanRun.scan_id == scan_id
        )
    )
    if existing is not None:
        return existing
    total = int(
        db.scalar(
            select(func.count()).select_from(PlayerInstance).where(PlayerInstance.fm_save_id == save_id)
        )
        or 0
    )
    max_id = int(
        db.scalar(
            select(func.max(PlayerInstance.id)).where(PlayerInstance.fm_save_id == save_id)
        )
        or 0
    )
    run = IdentityScanRun(
        fm_save_id=save_id,
        scan_id=scan_id,
        status="Queued",
        batch_size=max(1, min(int(batch_size), 1000)),
        total_instances=total,
        payload_checksum=_scope_checksum(
            save_id,
            fingerprint=fingerprint,
            game_build=game_build,
            layout_version=layout_version,
            total_instances=total,
            max_instance_id=max_id,
        ),
        save_identity_fingerprint=fingerprint,
        game_build=game_build,
        layout_version=layout_version,
        metadata_json=json.dumps({"max_instance_id": max_id}, ensure_ascii=False),
    )
    db.add(run)
    db.flush()
    return run


@dataclass
class _Index:
    """一次扫描内的只读元数据索引；只装 id / 名称 / 生日 / UID，不装原始内存。"""

    players: dict[int, tuple[str, str, Any]]
    instances_by_player: dict[int, list[int]]
    uid_players: dict[str, set[int]]
    name_players: dict[str, set[int]]


def _build_index(db: Session, save_id: int) -> _Index:
    rows = db.execute(
        select(
            PlayerInstance.id,
            PlayerInstance.player_id,
            PlayerInstance.save_local_uid,
            Player.full_name,
            Player.normalized_name,
            Player.birth_date,
        )
        .join(Player, Player.id == PlayerInstance.player_id)
        .where(PlayerInstance.fm_save_id == save_id)
    ).all()
    players: dict[int, tuple[str, str, Any]] = {}
    instances_by_player: dict[int, list[int]] = {}
    uid_players: dict[str, set[int]] = {}
    name_players: dict[str, set[int]] = {}
    for instance_id, player_id, uid, full_name, normalized, birth_date in rows:
        players[player_id] = (full_name, normalized, birth_date)
        instances_by_player.setdefault(player_id, []).append(int(instance_id))
        uid_players.setdefault(str(uid), set()).add(int(player_id))
        name_players.setdefault(normalized, set()).add(int(player_id))
    return _Index(players, instances_by_player, uid_players, name_players)


def _scope_from_run(run: IdentityScanRun) -> UidScope:
    return UidScope(
        save_id=run.fm_save_id,
        source_type="scan",
        save_identity_fingerprint=run.save_identity_fingerprint,
        session_key=None,
        game_build=run.game_build,
        layout_version=run.layout_version,
    )


def _same_name_review(
    db: Session,
    run: IdentityScanRun,
    instance: PlayerInstance,
    index: _Index,
) -> tuple[str, str | None]:
    """同名检测：返回 (observation 状态, 冲突原因)。不合并、不改写任何球员。"""
    player_id = instance.player_id
    full_name, normalized, birth_date = index.players[player_id]
    others = [pid for pid in index.name_players.get(normalized, set()) if pid != player_id]
    if not others:
        return STATUS_VALID, None

    same_birth: list[int] = []
    different_birth: list[int] = []
    unknown_birth: list[int] = []
    for other_id in others:
        other_birth = index.players.get(other_id, (None, None, None))[2]
        if birth_date is not None and other_birth is not None:
            if birth_date == other_birth:
                same_birth.append(other_id)
            else:
                different_birth.append(other_id)
        else:
            unknown_birth.append(other_id)

    if same_birth:
        reason = "same_name_same_birth_date"
        status = STATUS_CONFLICTED
        candidate_ids = [player_id, *same_birth]
    elif different_birth:
        reason = "same_name_different_birth_date"
        status = STATUS_CONFLICTED
        candidate_ids = [player_id, *different_birth]
    else:
        # 同名且至少一方生日未知：只能待人工核验，不能判定为同一人，也不能判为不同人。
        reason = "same_name_unknown_birth_date"
        status = STATUS_CONFLICTED
        candidate_ids = [player_id, *unknown_birth]

    ensure_review_item(
        db,
        run.fm_save_id,
        item_type="same_name",
        # 同名条目按「参与者集合」去重：双方各自扫描时产生的是同一条审核项。
        subject_uid=None,
        player_ids=candidate_ids,
        reason=reason,
        primary_player_id=player_id,
        payload={
            "name": full_name,
            "normalized_name": normalized,
            "birth_date": str(birth_date) if birth_date else None,
            "other_birth_dates": [
                str(index.players[pid][2]) if index.players.get(pid) else None for pid in candidate_ids[1:]
            ],
            "uid": instance.save_local_uid,
            "note": "同名不构成身份；必须人工确认",
        },
    )
    return status, reason


def _duplicate_uid_review(db: Session, run: IdentityScanRun, index: _Index) -> int:
    created = 0
    for group in duplicate_uid_groups(db, run.fm_save_id):
        reason = "duplicate_uid_same_save"
        ensure_review_item(
            db,
            run.fm_save_id,
            item_type="uid_duplicate",
            subject_uid=group["uid"],
            player_ids=players_for_uid(db, run.fm_save_id, group["uid"]),
            reason=reason,
            primary_player_id=group["first_player_id"],
            payload={
                **group,
                "note": "同一存档内一个 UID 对应多个球员实体；不自动合并，全部保留",
            },
        )
        for observation in db.scalars(
            select(PlayerUidObservation).where(
                PlayerUidObservation.fm_save_id == run.fm_save_id,
                PlayerUidObservation.uid == group["uid"],
                PlayerUidObservation.status == STATUS_VALID,
            )
        ):
            observation.status = STATUS_DUPLICATE
        created += 1
    return created


def run_scan(db: Session, run: IdentityScanRun, *, max_batches: int | None = None) -> IdentityScanRun:
    """执行/继续扫描。每次最多 ``max_batches`` 批；未完成时停在 Paused，可再次调用恢复。"""
    if run.status in ("Completed", "Cancelled"):
        return run
    if run.status == "Failed":
        raise IdentityGovernanceError(errors.BATCH_RESUME_FAILED, "该批次已失败，请新建 scan_id 而不是复用")

    total_now = int(
        db.scalar(
            select(func.count()).select_from(PlayerInstance).where(PlayerInstance.fm_save_id == run.fm_save_id)
        )
        or 0
    )
    max_id_now = int(
        db.scalar(
            select(func.max(PlayerInstance.id)).where(PlayerInstance.fm_save_id == run.fm_save_id)
        )
        or 0
    )
    expected_max_id = int(json.loads(run.metadata_json or "{}").get("max_instance_id", 0))
    if run.payload_checksum and (total_now != run.total_instances or max_id_now != expected_max_id):
        run.status = "Failed"
        run.error_code = errors.BATCH_CHECKSUM_MISMATCH
        run.error_message = "作用域与创建批次时不一致（数据规模已变化），拒绝复用旧进度"
        run.finished_at = utcnow()
        db.flush()
        return run

    index = _build_index(db, run.fm_save_id)
    if len(index.players) > MAX_INDEXED_INSTANCES:
        raise IdentityGovernanceError(
            errors.UID_SCOPE_CONFLICT, "球员规模超出有界索引上限，请拆分扫描范围", status_code=409
        )

    if run.status in ("Queued", "Paused"):
        run.status = "Running"
        run.started_at = run.started_at or utcnow()

    batches = 0
    scope = _scope_from_run(run)
    while True:
        if max_batches is not None and batches >= max_batches:
            run.status = "Paused"
            db.flush()
            return run
        batch = list(
            db.scalars(
                select(PlayerInstance)
                .where(PlayerInstance.fm_save_id == run.fm_save_id, PlayerInstance.id > run.cursor)
                .order_by(PlayerInstance.id)
                .limit(run.batch_size)
            )
        )
        if not batch:
            break
        for instance in batch:
            try:
                _reconcile_instance(db, run, instance, index, scope)
                run.processed_count += 1
            except Exception as exc:  # noqa: BLE001 - 单行失败不拖垮整批，但要计数
                run.failed_count += 1
                run.error_message = f"instance {instance.id}: {exc}"[:500]
        run.cursor = batch[-1].id
        _duplicate_uid_review(db, run, index)
        batches += 1
        db.commit()

    remaining = db.scalar(
        select(func.count())
        .select_from(PlayerInstance)
        .where(PlayerInstance.fm_save_id == run.fm_save_id, PlayerInstance.id > run.cursor)
    )
    if int(remaining or 0) == 0:
        run.status = "Completed"
        run.finished_at = utcnow()
    else:
        run.status = "Paused"
    db.flush()
    db.commit()
    return run


def _reconcile_instance(
    db: Session,
    run: IdentityScanRun,
    instance: PlayerInstance,
    index: _Index,
    scope: UidScope,
) -> None:
    player = db.get(Player, instance.player_id)
    if player is None:
        raise IdentityGovernanceError(errors.PERSON_NOT_FOUND, f"实例 {instance.id} 的球员不存在")
    status, reason = _same_name_review(db, run, instance, index)
    uid_players = index.uid_players.get(str(instance.save_local_uid), set())
    conflicting_player_id = next(iter(sorted(uid_players - {instance.player_id})), None)
    if conflicting_player_id is not None:
        status = STATUS_DUPLICATE
        reason = reason or "duplicate_uid_same_save"

    record_observation(
        db,
        scope,
        uid_raw=instance.save_local_uid,
        player_instance_id=instance.id,
        player_id=instance.player_id,
        name=player.full_name,
        birth_date=player.birth_date,
        observed_at=run.started_at or utcnow(),
        confidence=1.0 if status == STATUS_VALID else 0.5,
        status=status,
        uid_reason=reason,
        conflicting_player_id=conflicting_player_id,
    )

    if status in (STATUS_CONFLICTED, STATUS_DUPLICATE):
        run.conflict_count += 1
    link_status = "Candidate" if status == STATUS_VALID else "Conflicted"
    _write_link(
        db,
        save_id=run.fm_save_id,
        canonical_player_id=instance.player_id,
        instance=instance,
        status=link_status,
        confidence=0.6 if status == STATUS_VALID else 0.2,
        evidence={
            "scan_id": run.scan_id,
            "uid": instance.save_local_uid,
            "observation_status": status,
            "reason": reason,
            "note": "扫描只产生候选；Verified 由存档作用域门控决定",
        },
    )
    if status == STATUS_VALID:
        run.matched_count += 1


def pause_scan(db: Session, run: IdentityScanRun) -> IdentityScanRun:
    if run.status in ("Queued", "Running"):
        run.status = "Paused"
        db.flush()
    return run


def cancel_scan(db: Session, run: IdentityScanRun) -> IdentityScanRun:
    if run.status in ("Completed", "Cancelled"):
        return run
    run.status = "Cancelled"
    run.finished_at = utcnow()
    db.flush()
    return run


def resume_scan(
    db: Session,
    run: IdentityScanRun,
    *,
    fingerprint: str | None,
    game_build: str | None,
    layout_version: str | None,
    max_batches: int | None = None,
) -> IdentityScanRun:
    """恢复前校验作用域；不一致时停止并保留历史，不复用旧指针。"""
    mismatch = (
        (run.save_identity_fingerprint or None) != (fingerprint or None)
        or (run.game_build or None) != (game_build or None)
        or (run.layout_version or None) != (layout_version or None)
    )
    if mismatch:
        run.status = "Failed"
        run.error_code = errors.SAVE_IDENTITY_MISMATCH
        run.error_message = "存档身份/构建/布局与批次创建时不一致，禁止继续使用旧进度"
        run.finished_at = utcnow()
        db.flush()
        return run
    return run_scan(db, run, max_batches=max_batches)


# ---------------------------------------------------------------------------
# 跨存档候选
# ---------------------------------------------------------------------------


def _player_rows(db: Session, save_ids: list[int]) -> dict[int, list[tuple[int, str, str, Any, str]]]:
    rows = db.execute(
        select(
            PlayerInstance.fm_save_id,
            PlayerInstance.player_id,
            Player.full_name,
            Player.normalized_name,
            Player.birth_date,
            PlayerInstance.save_local_uid,
        )
        .join(Player, Player.id == PlayerInstance.player_id)
        .where(PlayerInstance.fm_save_id.in_(save_ids))
        .distinct()
    ).all()
    grouped: dict[int, list[tuple[int, str, str, Any, str]]] = {}
    for save_id, player_id, full_name, normalized, birth_date, uid in rows:
        grouped.setdefault(int(save_id), []).append(
            (int(player_id), full_name, normalized, birth_date, str(uid))
        )
    return grouped


def find_cross_save_candidates(db: Session, save_id: int, other_save_id: int) -> list[CrossSaveIdentityCandidate]:
    """按「规范化姓名 + 出生日期」生成跨存档候选；同名不同生日记为冲突候选。"""
    if save_id == other_save_id:
        raise IdentityGovernanceError("cross_save_invalid", "跨存档比较需要两个不同存档", status_code=400)
    grouped = _player_rows(db, [save_id, other_save_id])
    subject_rows = grouped.get(save_id, [])
    other_rows = grouped.get(other_save_id, [])
    other_by_name: dict[str, list[tuple[int, str, str, Any, str]]] = {}
    for row in other_rows:
        other_by_name.setdefault(row[2], []).append(row)

    created: list[CrossSaveIdentityCandidate] = []
    seen_pairs: set[tuple[int, int]] = set()
    for player_id, full_name, normalized, birth_date, uid in subject_rows:
        for other_id, other_name, _other_norm, other_birth, other_uid in other_by_name.get(normalized, []):
            if (player_id, other_id) in seen_pairs:
                continue
            seen_pairs.add((player_id, other_id))
            if birth_date is not None and other_birth is not None and birth_date == other_birth:
                status = "CrossSaveCandidate"
                score = 0.9
                reason = "name_and_birth_date"
            elif birth_date is None or other_birth is None:
                status = "CrossSavePendingReview"
                score = 0.5
                reason = "missing_birth_date"
            else:
                status = "CrossSaveConflicted"
                score = 0.3
                reason = "birth_date_mismatch"

            uid_equal = bool(uid) and uid == other_uid
            if uid_equal and status == "CrossSaveConflicted":
                reason = "same_uid_different_person"
            candidate = db.scalar(
                select(CrossSaveIdentityCandidate).where(
                    CrossSaveIdentityCandidate.fm_save_id == save_id,
                    CrossSaveIdentityCandidate.other_save_id == other_save_id,
                    CrossSaveIdentityCandidate.subject_player_id == player_id,
                    CrossSaveIdentityCandidate.other_player_id == other_id,
                )
            )
            evidence = {
                "subject_name": full_name,
                "other_name": other_name,
                "subject_birth_date": str(birth_date) if birth_date else None,
                "other_birth_date": str(other_birth) if other_birth else None,
                "uid_equal": uid_equal,
                "reason": reason,
                "note": "跨存档 UID 不是身份；候选必须人工确认",
            }
            if candidate is None:
                candidate = CrossSaveIdentityCandidate(
                    fm_save_id=save_id,
                    other_save_id=other_save_id,
                    subject_player_id=player_id,
                    other_player_id=other_id,
                    normalized_name=normalized,
                    birth_date=birth_date,
                    match_score=score,
                    status=status,
                    uid_equal=uid_equal,
                    evidence_json=json.dumps(evidence, ensure_ascii=False, default=str),
                )
                db.add(candidate)
                db.flush()
            elif candidate.status not in ("CrossSaveMatched", "CrossSaveRejected"):
                candidate.match_score = score
                candidate.status = status
                candidate.uid_equal = uid_equal
                candidate.evidence_json = json.dumps(evidence, ensure_ascii=False, default=str)
            created.append(candidate)
    return created


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------


def center_summary(db: Session, save_id: int) -> dict[str, Any]:
    links = db.execute(
        select(PlayerIdentityLink.verification_status, func.count())
        .where(PlayerIdentityLink.fm_save_id == save_id, PlayerIdentityLink.valid_to.is_(None))
        .group_by(PlayerIdentityLink.verification_status)
    ).all()
    from ..models import PlayerIdentityReviewItem

    reviews = db.execute(
        select(PlayerIdentityReviewItem.status, func.count())
        .where(PlayerIdentityReviewItem.fm_save_id == save_id)
        .group_by(PlayerIdentityReviewItem.status)
    ).all()
    scans = db.execute(
        select(IdentityScanRun.status, func.count())
        .where(IdentityScanRun.fm_save_id == save_id)
        .group_by(IdentityScanRun.status)
    ).all()
    return {
        "save_id": save_id,
        "players": int(db.scalar(select(func.count()).select_from(Player)) or 0),
        "player_instances": int(
            db.scalar(
                select(func.count()).select_from(PlayerInstance).where(PlayerInstance.fm_save_id == save_id)
            )
            or 0
        ),
        "uid": uid_summary(db, save_id),
        "identity_links": {row[0]: int(row[1]) for row in links},
        "reviews": {row[0]: int(row[1]) for row in reviews},
        "scans": {row[0]: int(row[1]) for row in scans},
        "verified_note": "本层不生产 Verified；Verified 只由 V3.2.8.1 存档作用域门控给出",
    }


def review_item_reasons() -> list[str]:
    """供前端筛选下拉使用；与扫描产生的 item_type 保持一致。"""
    return ["same_name", "uid_duplicate", "cross_save", "transfer_identity"]
