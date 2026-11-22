"""Canonical observations and duplicate governance (V3.2 SM-061B).

Raw snapshots are immutable and are never deleted. A separate table records, per save/player/game
date, whether duplicates are content-identical (resolve to latest observation) or conflicting
(needs review, no canonical id). This gives growth analysis a deterministic input without hiding
the original rows.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ImportJob, PlayerInstance, PlayerObservationCanonical, PlayerSnapshot


def _signature(snapshot: PlayerSnapshot) -> tuple:
    return (
        snapshot.ca,
        snapshot.pa,
        snapshot.wage,
        snapshot.market_value,
        snapshot.contract_end,
        snapshot.club_id,
        snapshot.position,
        snapshot.height_cm,
        snapshot.foot,
    )


def build_canonicals(session: Session, save_id: int, *, dry_run: bool = True) -> dict[str, Any]:
    """Evaluate duplicate groups and optionally persist canonical decisions (never deletes)."""
    rows = list(
        session.execute(
            select(PlayerSnapshot)
            .join(PlayerInstance, PlayerInstance.id == PlayerSnapshot.player_instance_id)
            .where(PlayerInstance.fm_save_id == save_id)
            .order_by(PlayerSnapshot.player_instance_id, PlayerSnapshot.game_date, PlayerSnapshot.observed_at, PlayerSnapshot.id)
        ).scalars()
    )
    groups: dict[tuple[int, date], list[PlayerSnapshot]] = {}
    for snapshot in rows:
        game_date = snapshot.game_date or snapshot.observed_at.date()
        groups.setdefault((snapshot.player_instance_id, game_date), []).append(snapshot)

    resolved = 0
    needs_review = 0
    duplicate_rows = 0
    wrote = 0
    existing = {
        (row.player_instance_id, row.game_date): row
        for row in session.scalars(
            select(PlayerObservationCanonical).where(PlayerObservationCanonical.fm_save_id == save_id)
        )
    }
    for (instance_id, game_date), snapshots in groups.items():
        duplicate_rows += len(snapshots) - 1
        signatures = {_signature(snapshot) for snapshot in snapshots}
        if len(signatures) == 1:
            canonical = snapshots[-1]
            status = "resolved"
            reason = "内容一致的重复扫描；取最后观测作为 canonical" if len(snapshots) > 1 else "单条观测"
            resolved += 1
        else:
            canonical = None
            status = "needs_review"
            reason = "同一 game_date 内容不一致；保留全部原始快照，等待人工确认"
            needs_review += 1
        if dry_run:
            continue
        row = existing.get((instance_id, game_date))
        if row is None:
            row = PlayerObservationCanonical(
                fm_save_id=save_id,
                player_instance_id=instance_id,
                game_date=game_date,
            )
            session.add(row)
        row.canonical_snapshot_id = canonical.id if canonical is not None else None
        row.status = status
        row.conflict = status == "needs_review"
        row.snapshot_count = len(snapshots)
        row.distinct_content_count = len(signatures)
        row.reason = reason
        wrote += 1
    if not dry_run:
        session.commit()
    return {
        "save_id": save_id,
        "dry_run": dry_run,
        "groups": len(groups),
        "resolved": resolved,
        "needs_review": needs_review,
        "duplicate_rows": duplicate_rows,
        "written": wrote,
    }


def canonical_summary(session: Session, save_id: int) -> dict[str, Any]:
    """Counts for canonical governance; read-only."""
    rows = list(
        session.scalars(
            select(PlayerObservationCanonical).where(PlayerObservationCanonical.fm_save_id == save_id)
        )
    )
    resolved = sum(1 for row in rows if row.status == "resolved")
    needs_review = sum(1 for row in rows if row.status == "needs_review")
    duplicate_rows = sum(max(0, row.snapshot_count - 1) for row in rows)
    return {
        "save_id": save_id,
        "groups": len(rows),
        "resolved": resolved,
        "needs_review": needs_review,
        "duplicate_rows": duplicate_rows,
        "conflict_groups": sum(1 for row in rows if row.conflict),
        "with_canonical": sum(1 for row in rows if row.canonical_snapshot_id is not None),
    }
