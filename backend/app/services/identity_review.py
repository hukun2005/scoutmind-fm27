"""V3.2.9 Phase 3/4：人工审核队列。

规则：

* 扫描只能**创建**待审核条目；它永远不写 Verified，也不会自动合并。
* 人工决定有四种：确认同一人 / 确认不同人 / 保留为独立身份 / 暂缓。
* 所有决定追加到 ``player_identity_review_actions``，冲突历史与原始记录永不删除。
* 接口层不得让调用者把任何状态直接写成 ``Verified`` —— 这一层显式拒绝。
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    PlayerIdentityReviewAction,
    PlayerIdentityReviewItem,
    PlayerInstance,
    User,
)
from ..utils import utcnow
from . import identity_errors as errors
from .identity_errors import IdentityGovernanceError
from .uid_scope import digest_json

DECISION_TO_STATUS = {
    "same": "Confirmed",
    "different": "Rejected",
    "independent": "KeptIndependent",
    "defer": "Deferred",
}
DECISION_LABELS = {
    "same": "same_person",
    "different": "different_people",
    "independent": "kept_independent",
    "defer": "deferred",
}
RESOLVED_STATUSES = ("Confirmed", "Rejected", "KeptIndependent")


def item_key(item_type: str, *, subject_uid: str | None, player_ids: list[int], reason: str | None = None) -> str:
    return digest_json(
        {
            "item_type": item_type,
            "subject_uid": subject_uid or "",
            "player_ids": sorted(int(item) for item in player_ids),
            "reason": reason or "",
        }
    )


def ensure_review_item(
    db: Session,
    save_id: int,
    *,
    item_type: str,
    subject_uid: str | None,
    player_ids: list[int],
    reason: str | None,
    payload: dict[str, Any],
    primary_player_id: int | None = None,
    severity: str = "warning",
) -> PlayerIdentityReviewItem:
    """幂等创建待审核条目；已存在的条目（包括人工已处理的）原样返回，不被扫描覆盖。"""
    key = item_key(item_type, subject_uid=subject_uid, player_ids=player_ids, reason=reason)
    existing = db.scalar(
        select(PlayerIdentityReviewItem).where(
            PlayerIdentityReviewItem.fm_save_id == save_id,
            PlayerIdentityReviewItem.item_key == key,
        )
    )
    if existing is not None:
        return existing
    item = PlayerIdentityReviewItem(
        fm_save_id=save_id,
        item_key=key,
        item_type=item_type,
        severity=severity,
        status="PendingHumanReview",
        subject_uid=subject_uid,
        primary_player_id=primary_player_id if primary_player_id is not None else (player_ids[0] if player_ids else None),
        candidate_player_ids_json=json.dumps(sorted(int(item) for item in player_ids), ensure_ascii=False),
        conflict_reason=reason,
        payload_json=json.dumps(payload, ensure_ascii=False, default=str),
        detected_at=utcnow(),
    )
    db.add(item)
    db.flush()
    return item


def _assert_no_verified(payload: dict[str, Any] | None) -> None:
    """客户端不能通过审核接口把任何东西直接标成 Verified。"""
    if not payload:
        return
    for key in ("verification_status", "identity_status", "status"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip().lower() == "verified":
            raise IdentityGovernanceError(
                errors.VERIFIED_NOT_SETTABLE,
                "审核接口不接受 Verified：Verified 只能由 V3.2.8.1 的存档作用域门控产生",
                status_code=400,
            )


def resolve_review(
    db: Session,
    item: PlayerIdentityReviewItem,
    *,
    user: User,
    decision: str,
    note: str | None = None,
    payload: dict[str, Any] | None = None,
) -> PlayerIdentityReviewItem:
    if decision not in DECISION_TO_STATUS:
        raise IdentityGovernanceError("review_decision_invalid", f"未知决定：{decision}", status_code=400)
    _assert_no_verified(payload)
    if item.status in RESOLVED_STATUSES:
        raise IdentityGovernanceError(
            errors.REVIEW_ALREADY_RESOLVED,
            f"该条目已处理（{item.status}），请新增条目而不是覆盖历史",
        )
    previous = item.status
    item.status = DECISION_TO_STATUS[decision]
    item.resolved_at = utcnow() if item.status in RESOLVED_STATUSES else None

    if decision == "same":
        from .identity_engine import confirm_candidate_links  # 局部导入避免循环依赖

        player_ids = [int(value) for value in json.loads(item.candidate_player_ids_json or "[]")]
        if item.primary_player_id is not None and item.primary_player_id not in player_ids:
            player_ids.append(item.primary_player_id)
        confirm_candidate_links(
            db,
            save_id=item.fm_save_id,
            canonical_player_id=item.primary_player_id or (player_ids[0] if player_ids else None),
            player_ids=player_ids,
            reason=f"review:{item.item_type}",
            evidence={"review_id": item.id, "decision": decision},
        )

    db.add(
        PlayerIdentityReviewAction(
            review_id=item.id,
            fm_save_id=item.fm_save_id,
            user_id=user.id,
            action=decision,
            decision=DECISION_LABELS[decision],
            previous_status=previous,
            new_status=item.status,
            note=note,
            payload_json=json.dumps(payload or {}, ensure_ascii=False, default=str),
        )
    )
    db.flush()
    return item


def item_payload(db: Session, item: PlayerIdentityReviewItem) -> dict[str, Any]:
    player_ids = [int(value) for value in json.loads(item.candidate_player_ids_json or "[]")]
    instances = list(
        db.scalars(
            select(PlayerInstance).where(
                PlayerInstance.fm_save_id == item.fm_save_id,
                PlayerInstance.player_id.in_(player_ids or [-1]),
            )
        )
    )
    actions = list(
        db.scalars(
            select(PlayerIdentityReviewAction)
            .where(PlayerIdentityReviewAction.review_id == item.id)
            .order_by(PlayerIdentityReviewAction.id)
        )
    )
    return {
        "id": item.id,
        "item_type": item.item_type,
        "severity": item.severity,
        "status": item.status,
        "subject_uid": item.subject_uid,
        "primary_player_id": item.primary_player_id,
        "candidate_player_ids": player_ids,
        "conflict_reason": item.conflict_reason,
        "payload": json.loads(item.payload_json or "{}"),
        "detected_at": item.detected_at,
        "resolved_at": item.resolved_at,
        "instances": [
            {
                "instance_id": row.id,
                "player_id": row.player_id,
                "save_local_uid": row.save_local_uid,
                "uid_occurrence": row.uid_occurrence,
                "club_id": row.club_id,
                "position": row.position,
            }
            for row in instances
        ],
        "history": [
            {
                "id": action.id,
                "action": action.action,
                "decision": action.decision,
                "previous_status": action.previous_status,
                "new_status": action.new_status,
                "note": action.note,
                "user_id": action.user_id,
                "created_at": action.created_at,
                "payload": json.loads(action.payload_json or "{}"),
            }
            for action in actions
        ],
        "retention": "原始记录与审核历史永久保留；确认只会新增 Canonical 关联，不删除数据",
    }
