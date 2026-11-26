"""V3.2.9 Phase 6 / V3.2.9.2 Phase 4：历史转会记录的身份关联边界。

原则：

* 只补齐 ``transfer_history.player_instance_id`` 为空的记录，绝不覆盖已有关联；
* **姓名不是身份**：只有姓名匹配不足以写入关联，必须至少再有一项独立证据
  （转会时年龄与生日一致，或转出/转入俱乐部与实例俱乐部一致）；
* 多匹配、证据冲突、证据不足分别进入人工审核，不自动选择；
* 俱乐部变化、自由球员、退役都不改变身份；
* 租借/附加条款/未完成交易的语义由既有字段表达，本模块不改写金额与状态。
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Club, Player, PlayerInstance, Transfer
from ..utils import normalize_name
from .identity_review import ensure_review_item

#: 允许的年龄误差（生日精度/赛季跨年）。
AGE_TOLERANCE_YEARS = 1


def _age_at(birth: date, on: date) -> int:
    return on.year - birth.year - ((on.month, on.day) < (birth.month, birth.day))


def _instance_index(db: Session, save_id: int) -> dict[str, list[tuple[PlayerInstance, Player, str | None]]]:
    """一次查询建立 归一化姓名 → (实例, 球员, 俱乐部名) 索引，避免逐条转会重复查库。"""
    rows = db.execute(
        select(PlayerInstance, Player, Club.name)
        .join(Player, Player.id == PlayerInstance.player_id)
        .outerjoin(Club, Club.id == PlayerInstance.club_id)
        .where(PlayerInstance.fm_save_id == save_id)
    ).all()
    index: dict[str, list[tuple[PlayerInstance, Player, str | None]]] = {}
    for instance, player, club_name in rows:
        index.setdefault(player.normalized_name, []).append((instance, player, club_name))
    return index


def _club_agrees(transfer: Transfer, club_name: str | None) -> bool:
    if not club_name:
        return False
    normalized = normalize_name(club_name)
    for candidate in (transfer.from_club_name, transfer.to_club_name):
        if candidate and normalize_name(candidate) == normalized:
            return True
    return False


def _evidence(transfer: Transfer, instance: PlayerInstance, player: Player, club_name: str | None) -> dict[str, Any]:
    """计算可用于身份关联的独立证据。姓名始终只是必要条件，不计入“第二证据”。"""
    age_match = False
    age_conflict = False
    if transfer.player_age_at_transfer is not None and player.birth_date is not None:
        observed = _age_at(player.birth_date, transfer.transfer_date)
        age_match = abs(observed - transfer.player_age_at_transfer) <= AGE_TOLERANCE_YEARS
        age_conflict = not age_match

    club_match = _club_agrees(transfer, club_name)

    return {
        "instance_id": instance.id,
        "player_id": player.id,
        "save_local_uid": instance.save_local_uid,
        "age_match": age_match,
        "age_conflict": age_conflict,
        "club_match": club_match,
        "club_name": club_name,
        "transfer_id": transfer.id,
        "transfer_type": transfer.transfer_type,
        "status": transfer.status,
        "from_club": transfer.from_club_name,
        "to_club": transfer.to_club_name,
        "transfer_date": str(transfer.transfer_date),
        "player_age_at_transfer": transfer.player_age_at_transfer,
        "player_birth_date": str(player.birth_date) if player.birth_date else None,
    }


def link_transfers(db: Session, save_id: int) -> dict[str, int]:
    """为证据充分的转会增加实例关联；结果幂等，证据不足一律进入人工审核。"""
    transfers = list(
        db.scalars(
            select(Transfer).where(
                Transfer.fm_save_id == save_id,
                Transfer.player_instance_id.is_(None),
            )
        )
    )
    index = _instance_index(db, save_id)
    linked = ambiguous = unmatched = insufficient = conflicted = 0

    for transfer in transfers:
        normalized = normalize_name(transfer.player_name)
        matches = index.get(normalized, [])
        player_ids = sorted({int(player.id) for _, player, _ in matches})
        if not matches:
            unmatched += 1
            continue

        if len(player_ids) > 1:
            ambiguous += 1
            ensure_review_item(
                db,
                save_id,
                item_type="transfer_identity",
                subject_uid=None,
                player_ids=player_ids,
                reason="multiple_name_matches",
                extra=str(transfer.id),
                payload={
                    "transfer_id": transfer.id,
                    "source_record_id": transfer.source_record_id,
                    "player_name": transfer.player_name,
                    "transfer_type": transfer.transfer_type,
                    "status": transfer.status,
                    "note": "同名多匹配，转会保持未关联并等待人工确认",
                },
            )
            continue

        instance, player, club_name = matches[0]
        evidence = _evidence(transfer, instance, player, club_name)

        if len(matches) > 1:
            # 同一球员在同一存档内出现多个实例：不能猜，交给人工选择具体实例。
            ambiguous += 1
            ensure_review_item(
                db,
                save_id,
                item_type="transfer_identity",
                subject_uid=None,
                player_ids=player_ids,
                reason="multiple_instance_matches",
                extra=str(transfer.id),
                payload={**evidence, "instance_ids": [row[0].id for row in matches]},
            )
            continue

        if evidence["age_match"] or evidence["club_match"]:
            transfer.player_instance_id = instance.id
            linked += 1
            continue

        is_conflict = bool(evidence["age_conflict"])
        if is_conflict:
            conflicted += 1
            reason = "evidence_conflict"
            note = "转会时年龄与球员生日不一致，拒绝仅凭姓名关联"
        else:
            insufficient += 1
            reason = "insufficient_evidence"
            note = "只有姓名匹配，缺少生日/年龄或俱乐部等独立证据，保持未关联并等待人工确认"

        ensure_review_item(
            db,
            save_id,
            item_type="transfer_identity",
            subject_uid=None,
            player_ids=player_ids,
            reason=reason,
            extra=str(transfer.id),
            payload={**evidence, "note": note},
        )

    db.flush()
    return {
        "transfers_scanned": len(transfers),
        "linked": linked,
        "ambiguous": ambiguous,
        "unmatched": unmatched,
        "insufficient_evidence": insufficient,
        "evidence_conflict": conflicted,
    }


def transfer_link_summary(db: Session, save_id: int) -> dict[str, Any]:
    total = int(
        db.scalar(select(func.count()).select_from(Transfer).where(Transfer.fm_save_id == save_id)) or 0
    )
    linked = int(
        db.scalar(
            select(func.count())
            .select_from(Transfer)
            .where(Transfer.fm_save_id == save_id, Transfer.player_instance_id.is_not(None))
        )
        or 0
    )
    by_type = dict(
        db.execute(
            select(Transfer.transfer_type, func.count())
            .where(Transfer.fm_save_id == save_id, Transfer.player_instance_id.is_not(None))
            .group_by(Transfer.transfer_type)
        ).all()
    )
    by_status = dict(
        db.execute(
            select(Transfer.status, func.count())
            .where(Transfer.fm_save_id == save_id)
            .group_by(Transfer.status)
        ).all()
    )
    return {
        "save_id": save_id,
        "transfers": total,
        "linked_transfers": linked,
        "unlinked_transfers": total - linked,
        "linked_by_type": {str(key): int(value) for key, value in by_type.items()},
        "by_status": {str(key): int(value) for key, value in by_status.items()},
        "note": "只补齐证据充分的关联；姓名不是身份，同一球员转会前后身份不变",
    }


def transfer_identity_evidence(transfer: Transfer) -> str:
    """给审核界面用的脱敏证据摘要。"""
    return json.dumps(
        {
            "transfer_id": transfer.id,
            "player_name": transfer.player_name,
            "transfer_type": transfer.transfer_type,
            "status": transfer.status,
            "from_club": transfer.from_club_name,
            "to_club": transfer.to_club_name,
            "transfer_date": str(transfer.transfer_date),
        },
        ensure_ascii=False,
    )
