"""Transfer-event candidate detection (V3.2.2 SM-070).

A club change is evidence of a move, not proof of a permanent paid transfer. This module only
creates Unverified candidates; fees and final event types require explicit source evidence.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import PlayerInstance, TransferEventCandidate
from .canonical import select_canonical_snapshots


def detect_transfer_events(session: Session, save_id: int, *, dry_run: bool = True) -> dict[str, Any]:
    instances = list(session.scalars(select(PlayerInstance.id).where(PlayerInstance.fm_save_id == save_id)))
    created = 0
    candidates: list[dict[str, Any]] = []
    for instance_id in instances:
        snapshots, _ = select_canonical_snapshots(session, save_id, instance_id, legacy_if_missing=False)
        for previous, current in zip(snapshots, snapshots[1:]):
            if previous.club_id == current.club_id:
                continue
            game_date = current.game_date or current.observed_at.date()
            evidence = {
                "previous_snapshot_id": previous.id,
                "current_snapshot_id": current.id,
                "previous_club_id": previous.club_id,
                "current_club_id": current.club_id,
                "rule": "club_changed_between_canonical_observations",
                "fee": None,
            }
            candidates.append({
                "player_instance_id": instance_id,
                "from_club_id": previous.club_id,
                "to_club_id": current.club_id,
                "game_date": game_date,
                "evidence": evidence,
            })
            existing = session.scalar(
                select(TransferEventCandidate).where(
                    TransferEventCandidate.fm_save_id == save_id,
                    TransferEventCandidate.player_instance_id == instance_id,
                    TransferEventCandidate.from_club_id == previous.club_id,
                    TransferEventCandidate.to_club_id == current.club_id,
                    TransferEventCandidate.game_date == game_date,
                )
            )
            if existing is None:
                created += 1
                if not dry_run:
                    session.add(TransferEventCandidate(
                        fm_save_id=save_id,
                        player_instance_id=instance_id,
                        event_type="unknown_pending_verification",
                        from_club_id=previous.club_id,
                        to_club_id=current.club_id,
                        game_date=game_date,
                        evidence_level="Unverified",
                        status="pending",
                        evidence_json=json.dumps(evidence, ensure_ascii=False),
                    ))
    if not dry_run:
        session.commit()
    return {
        "save_id": save_id,
        "dry_run": dry_run,
        "candidates": candidates,
        "created": created,
        "note": "俱乐部变化只生成 Unverified 候选；不推断费用或永久转会",
    }
