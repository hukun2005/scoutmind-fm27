"""Canonical snapshot selection shared by growth/forecast analyses."""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ImportJob, PlayerInstance, PlayerObservationCanonical, PlayerSnapshot

_ALLOWED = {"resolved", "resolved_auto", "resolved_manual"}


def select_canonical_snapshots(
    session: Session,
    save_id: int,
    instance_id: int,
    *,
    legacy_if_missing: bool = True,
) -> tuple[list[PlayerSnapshot], dict[str, Any]]:
    """Return canonical snapshots (full rows) and governance metadata.

    If no canonical rows exist for the instance and legacy_if_missing is true, the caller gets the
    old last-wins selection but ``legacy_mode=True``/``canonicalization_pending=True`` so callers
    must surface that the data is not governed.
    """
    instance = session.get(PlayerInstance, instance_id)
    if instance is None or instance.fm_save_id != save_id:
        raise ValueError("player not found in this save")
    rows = list(
        session.scalars(
            select(PlayerSnapshot)
            .where(PlayerSnapshot.player_instance_id == instance_id)
            .order_by(PlayerSnapshot.observed_at, PlayerSnapshot.id)
        )
    )
    canonicals = list(
        session.scalars(
            select(PlayerObservationCanonical).where(
                PlayerObservationCanonical.fm_save_id == save_id,
                PlayerObservationCanonical.player_instance_id == instance_id,
            )
        )
    )
    by_id = {row.id: row for row in rows}
    raw_dates = {row.game_date or row.observed_at.date() for row in rows}
    selected: list[PlayerSnapshot] = []
    excluded = 0
    pending = 0
    covered = set()
    for canonical in canonicals:
        covered.add(canonical.game_date)
        if canonical.status not in _ALLOWED or canonical.canonical_snapshot_id is None:
            excluded += 1
            continue
        snapshot = by_id.get(canonical.canonical_snapshot_id)
        if snapshot is None or (snapshot.game_date or snapshot.observed_at.date()) != canonical.game_date:
            excluded += 1
            continue
        selected.append(snapshot)
    pending = len(raw_dates - covered)
    legacy = False
    if not canonicals and legacy_if_missing:
        # Explicit legacy mode: hand the raw rows to the caller's existing de-duplication logic.
        selected = rows
        legacy = True
        pending = len(raw_dates)
    return selected, {
        "raw_snapshot_count": len(rows),
        "canonical_point_count": len(selected),
        "excluded_conflict_count": excluded,
        "pending_canonical_count": pending,
        "legacy_mode": legacy,
        "canonicalization_pending": bool(pending),
    }
