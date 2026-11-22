"""Canonical observations and duplicate governance (V3.2 SM-061B/D).

Raw snapshots are immutable and are never deleted. A separate table records, per save/player/game
date, whether duplicates are content-identical (resolve to latest observation) or conflicting
(needs review, no canonical id). The content signature includes CA/PA, all PlayerAttributeValue
rows, contract/economy fields, status fields and source/version metadata.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    ImportJob,
    PlayerAttribute,
    PlayerAttributeValue,
    PlayerInstance,
    PlayerObservationCanonical,
    PlayerSnapshot,
)


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


def _attribute_fingerprints(session: Session, snapshot_ids: list[int]) -> dict[int, tuple]:
    """Stable per-snapshot attribute fingerprint; missing keys stay absent, 0 stays present."""
    result: dict[int, list[tuple[str, float]]] = {snapshot_id: [] for snapshot_id in snapshot_ids}
    for start in range(0, len(snapshot_ids), 400):
        chunk = snapshot_ids[start:start + 400]
        rows = session.execute(
            select(
                PlayerAttributeValue.player_snapshot_id,
                PlayerAttribute.key,
                PlayerAttributeValue.value,
            )
            .join(PlayerAttribute, PlayerAttribute.id == PlayerAttributeValue.attribute_id)
            .where(PlayerAttributeValue.player_snapshot_id.in_(chunk))
            .order_by(PlayerAttributeValue.player_snapshot_id, PlayerAttribute.key)
        )
        for snapshot_id, key, value in rows:
            result.setdefault(snapshot_id, []).append((key, float(value)))
    return {snapshot_id: tuple(sorted(values)) for snapshot_id, values in result.items()}


def _classify(
    values: list[PlayerSnapshot],
    attrs: dict[int, tuple],
    sources: dict[int, tuple],
) -> tuple[list[str], list[str]]:
    """Return conflict categories and changed field names for one duplicate group."""
    categories: set[str] = set()
    changed: set[str] = set()

    def differs(getter) -> bool:
        return len({getter(value) for value in values}) > 1

    if differs(lambda item: (item.ca, item.pa, attrs.get(item.id, ()))):
        categories.add("ability_changed")
        if differs(lambda item: item.ca):
            changed.add("ca")
        if differs(lambda item: item.pa):
            changed.add("pa")
        if differs(lambda item: attrs.get(item.id, ())):
            changed.add("attributes")
        attribute_keys = {frozenset(key for key, _ in attrs.get(item.id, ())) for item in values}
        if len(attribute_keys) > 1:
            categories.add("missing_vs_present")
            changed.add("attributes:missing")
    if differs(lambda item: (item.wage, item.contract_end)):
        categories.add("contract_changed")
        if differs(lambda item: item.wage):
            changed.add("wage")
        if differs(lambda item: item.contract_end):
            changed.add("contract_end")
    if differs(lambda item: item.market_value):
        categories.add("valuation_changed")
        changed.add("market_value")
    if differs(lambda item: item.club_id):
        categories.add("club_changed")
        changed.add("club_id")
    if differs(lambda item: item.position):
        categories.add("position_changed")
        changed.add("position")
    if differs(lambda item: (item.height_cm, item.foot)):
        categories.add("physical_data_changed")
        if differs(lambda item: item.height_cm):
            changed.add("height_cm")
        if differs(lambda item: item.foot):
            changed.add("foot")
    if differs(lambda item: sources.get(item.id, ())):
        categories.add("source_changed")
        changed.add("source")
    for name in ("ca", "pa", "wage", "market_value", "contract_end", "club_id", "position", "height_cm", "foot"):
        presence = {getattr(value, name) is not None for value in values}
        if len(presence) > 1:
            categories.add("missing_vs_present")
            changed.add(f"{name}:missing")
    if len(categories) > 1:
        categories.add("mixed_changes")
    return sorted(categories), sorted(changed)


def build_canonicals(session: Session, save_id: int, *, dry_run: bool = True) -> dict[str, Any]:
    """Evaluate duplicate groups and optionally persist canonical decisions (never deletes)."""
    rows = list(
        session.execute(
            select(
                PlayerSnapshot,
                ImportJob.source,
                ImportJob.reader_version,
                ImportJob.game_build,
            )
            .join(PlayerInstance, PlayerInstance.id == PlayerSnapshot.player_instance_id)
            .outerjoin(ImportJob, ImportJob.id == PlayerSnapshot.import_job_id)
            .where(PlayerInstance.fm_save_id == save_id)
            .order_by(PlayerSnapshot.player_instance_id, PlayerSnapshot.game_date, PlayerSnapshot.observed_at, PlayerSnapshot.id)
        )
    )
    groups: dict[tuple[int, date], list[PlayerSnapshot]] = {}
    sources: dict[int, tuple] = {}
    for snapshot, source, reader_version, game_build in rows:
        game_date = snapshot.game_date or snapshot.observed_at.date()
        groups.setdefault((snapshot.player_instance_id, game_date), []).append(snapshot)
        sources[snapshot.id] = (source, reader_version, game_build)
    duplicate_ids = [snapshot.id for values in groups.values() if len(values) > 1 for snapshot in values]
    attrs = _attribute_fingerprints(session, duplicate_ids) if duplicate_ids else {}

    resolved = 0
    needs_review = 0
    duplicate_rows = 0
    wrote = 0
    conflict_type_counts: dict[str, int] = {}
    changed_field_counts: dict[str, int] = {}
    sample_conflicts: list[dict[str, Any]] = []
    existing = {
        (row.player_instance_id, row.game_date): row
        for row in session.scalars(
            select(PlayerObservationCanonical).where(PlayerObservationCanonical.fm_save_id == save_id)
        )
    }
    for (instance_id, game_date), snapshots in groups.items():
        duplicate_rows += len(snapshots) - 1
        signatures = {
            (_signature(snapshot), attrs.get(snapshot.id, ()), sources.get(snapshot.id, ()))
            for snapshot in snapshots
        }
        conflict_types: list[str] = []
        changed_fields: list[str] = []
        if len(signatures) == 1:
            canonical = snapshots[-1]
            status = "resolved"
            reason = "内容一致的重复扫描；取最后观测作为 canonical" if len(snapshots) > 1 else "单条观测"
            resolved += 1
        else:
            canonical = None
            status = "needs_review"
            conflict_types, changed_fields = _classify(snapshots, attrs, sources)
            reason = "同一 game_date 内容不一致：" + "、".join(conflict_types)
            needs_review += 1
            for item in conflict_types:
                conflict_type_counts[item] = conflict_type_counts.get(item, 0) + 1
            for item in changed_fields:
                changed_field_counts[item] = changed_field_counts.get(item, 0) + 1
            if len(sample_conflicts) < 20:
                sample_conflicts.append({
                    "player_instance_id": instance_id,
                    "game_date": game_date.isoformat(),
                    "snapshot_ids": [snapshot.id for snapshot in snapshots],
                    "conflict_types": conflict_types,
                    "changed_fields": changed_fields,
                })
        if dry_run:
            continue
        row = existing.get((instance_id, game_date))
        if row is not None and row.status in {"resolved_manual", "excluded"}:
            # Human decisions are never overwritten by a rescan.
            if row.snapshot_count != len(snapshots) or row.distinct_content_count != len(signatures):
                row.status = "review_required"
                row.reason = "重扫描后快照组发生变化，原人工决策需复核"
            continue
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
        "conflict_type_counts": conflict_type_counts,
        "changed_field_counts": changed_field_counts,
        "sample_conflicts": sample_conflicts,
    }


def canonical_summary(session: Session, save_id: int) -> dict[str, Any]:
    """Counts for canonical governance; read-only."""
    rows = list(
        session.scalars(
            select(PlayerObservationCanonical).where(PlayerObservationCanonical.fm_save_id == save_id)
        )
    )
    resolved = sum(1 for row in rows if row.status in {"resolved", "resolved_auto", "resolved_manual"})
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
