"""V3.2.9 Phase 6：历史转会记录的身份关联准备。

原则：

* 只补齐 ``transfer_history.player_instance_id`` 为空的记录，绝不覆盖已有关联；
* 唯一姓名匹配才写入关联，多匹配进入人工审核，零匹配保持未关联；
* 俱乐部变化、自由球员、退役都不改变身份；
* 租借/附加条款的语义由既有 ``transfer_type`` / ``status`` / 费用组件表达，本模块不改写金额。
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Player, PlayerInstance, Transfer
from ..utils import normalize_name
from .identity_review import ensure_review_item


def link_transfers(db: Session, save_id: int) -> dict[str, int]:
    """为名字唯一匹配的转会补齐实例关联；结果幂等。"""
    transfers = list(
        db.scalars(
            select(Transfer).where(
                Transfer.fm_save_id == save_id,
                Transfer.player_instance_id.is_(None),
            )
        )
    )
    linked = ambiguous = unmatched = 0
    for transfer in transfers:
        normalized = normalize_name(transfer.player_name)
        matches = list(
            db.scalars(
                select(PlayerInstance)
                .join(Player, Player.id == PlayerInstance.player_id)
                .where(
                    PlayerInstance.fm_save_id == save_id,
                    Player.normalized_name == normalized,
                )
            )
        )
        player_ids = sorted({row.player_id for row in matches})
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
        transfer.player_instance_id = matches[0].id
        linked += 1
    db.flush()
    return {"transfers_scanned": len(transfers), "linked": linked, "ambiguous": ambiguous, "unmatched": unmatched}


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
        "note": "只补齐空关联；同一球员转会前后身份不变，自由球员/租借不降低身份",
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
