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

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
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


def item_key(
    item_type: str,
    *,
    subject_uid: str | None,
    player_ids: list[int],
    reason: str | None = None,
    extra: str | None = None,
) -> str:
    return digest_json(
        {
            "item_type": item_type,
            "subject_uid": subject_uid or "",
            "player_ids": sorted(int(item) for item in player_ids),
            "reason": reason or "",
            "extra": extra or "",
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
    extra: str | None = None,
) -> PlayerIdentityReviewItem:
    """幂等创建待审核条目；已存在的条目（包括人工已处理的）原样返回，不被扫描覆盖。"""
    key = item_key(item_type, subject_uid=subject_uid, player_ids=player_ids, reason=reason, extra=extra)
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
    expected_version: int | None = None,
    request_key: str | None = None,
) -> PlayerIdentityReviewItem:
    """提交一次人工审核决定。

    V3.2.9.2 并发保护：

    * 每条审核记录带 ``version``；客户端必须携带读取到的 ``expected_version``；
    * 用条件 UPDATE（版本 + 未解决状态）抢占写入权，只有一个审核者能成功；
    * 后到者收到 ``REVIEW_VERSION_CONFLICT``，且不得静默覆盖；
    * ``request_key`` 幂等：重复提交同一请求不会重复追加历史。
    """
    if decision not in DECISION_TO_STATUS:
        raise IdentityGovernanceError("review_decision_invalid", f"未知决定：{decision}", status_code=400)
    _assert_no_verified(payload)

    if request_key:
        existing = db.scalar(
            select(PlayerIdentityReviewAction).where(
                PlayerIdentityReviewAction.review_id == item.id,
                PlayerIdentityReviewAction.request_key == request_key,
            )
        )
        if existing is not None:
            db.refresh(item)
            return item

    # 先读取数据库中的最新版本，避免用陈旧 ORM 状态做判断。
    db.refresh(item)
    previous = item.status
    previous_version = item.version

    if previous in RESOLVED_STATUSES:
        raise IdentityGovernanceError(
            errors.REVIEW_ALREADY_RESOLVED,
            f"该条目已处理（{previous}），请新增条目而不是覆盖历史",
        )
    if expected_version is not None and expected_version != previous_version:
        raise IdentityGovernanceError(
            errors.REVIEW_VERSION_CONFLICT,
            f"审核版本冲突：提交版本 {expected_version}，当前版本 {previous_version}，请重新读取后再提交",
        )

    target = DECISION_TO_STATUS[decision]
    new_version = previous_version + 1
    resolved_at = utcnow() if target in RESOLVED_STATUSES else None
    claimed = db.execute(
        update(PlayerIdentityReviewItem)
        .where(
            PlayerIdentityReviewItem.id == item.id,
            PlayerIdentityReviewItem.version == previous_version,
            PlayerIdentityReviewItem.status.notin_(RESOLVED_STATUSES),
        )
        .values(status=target, version=new_version, resolved_at=resolved_at, updated_at=utcnow())
        .execution_options(synchronize_session=False)
    )

    if claimed.rowcount != 1:
        db.refresh(item)
        if item.status in RESOLVED_STATUSES:
            raise IdentityGovernanceError(
                errors.REVIEW_ALREADY_RESOLVED,
                f"该条目已被其他审核者处理（{item.status}），本次决定未写入",
            )
        raise IdentityGovernanceError(
            errors.REVIEW_VERSION_CONFLICT,
            f"审核版本冲突：当前版本 {item.version}，请重新读取后再提交",
        )

    db.refresh(item)

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
            new_status=target,
            previous_version=previous_version,
            new_version=new_version,
            request_key=request_key,
            note=note,
            payload_json=json.dumps(payload or {}, ensure_ascii=False, default=str),
        )
    )
    try:
        db.flush()
    except IntegrityError as exc:
        # 同一 request_key 并发提交：唯一约束兜底，绝不再写一条历史。
        raise IdentityGovernanceError(
            errors.REVIEW_VERSION_CONFLICT,
            "重复的审核请求已被幂等约束拦截，请重新读取最新状态",
        ) from exc
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
        "version": item.version,
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
                "previous_version": action.previous_version,
                "new_version": action.new_version,
                "request_key": action.request_key,
                "note": action.note,
                "user_id": action.user_id,
                "created_at": action.created_at,
                "payload": json.loads(action.payload_json or "{}"),
            }
            for action in actions
        ],
        "retention": "原始记录与审核历史永久保留；确认只会新增 Canonical 关联，不删除数据",
    }
