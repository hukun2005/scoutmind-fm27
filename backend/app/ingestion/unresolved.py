"""Persistence of players an upstream source could not identify.

A row whose identity is a sentinel (``0xFFFFFFFF``), missing or invalid never becomes a
``PlayerInstance``: it is stored as an :class:`~app.models.UnresolvedPlayerObservation` under an
:class:`~app.models.UnresolvedPlayerCandidate`. Nothing here writes to canonical observations,
valuations, squad analysis or scouting; only an explicit human decision can link a candidate to a
real identity.

Correlation rules:

* a verified stable upstream identity correlates observations across scans (``candidate_key`` =
  ``stable:<id>``);
* without one, every observation gets its own candidate (``candidate_key`` = ``row:<scan>:<index>``),
  so two free agents sharing the sentinel never merge, and the same person observed twice is offered
  as a *suggestion*, never merged automatically.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    ImportJob,
    Player,
    PlayerInstance,
    UnresolvedPlayerCandidate,
    UnresolvedPlayerObservation,
)
from ..utils import normalize_name
from .protocol import PlayerRecord

if TYPE_CHECKING:
    from .importer import ImportOutcome
    from .protocol import ScanPayload

#: Upper bound for one stored raw evidence document; a payload cannot bloat the table.
MAX_RAW_EVIDENCE_CHARS = 8000

#: Suggestion confidence for a same-name row with conflicting birth dates; never enough to merge.
CONFLICTING_BIRTHDATE_CONFIDENCE = 0.15


def stable_identity_of(record: PlayerRecord) -> str | None:
    """Return a verified stable upstream identity, or ``None`` when the source only has an observation.

    A stable id is only trusted when the payload also marks it verified: an unverified id would turn a
    guess into a permanent cross-scan key.
    """
    identity = record.identity
    if identity is None:
        return None
    evidence = identity.evidence or {}
    value = evidence.get("stable_identity_id")
    if isinstance(value, str) and value.strip() and evidence.get("stable_identity_verified") is True:
        return value.strip()[:128]
    return None


def candidate_key_for(record: PlayerRecord, scan_id: str, row_index: int) -> tuple[str, str, str | None]:
    """Return ``(kind, key, stable_value)`` for one unresolved row.

    Without a verified stable id the key is unique per observation, which is what keeps two sentinel
    rows from the same scan apart and stops a later scan from silently merging into an earlier one.
    """
    stable = stable_identity_of(record)
    if stable:
        return "stable_id", f"stable:{stable}"[:160], stable
    return "observation", f"row:{scan_id}:{row_index}"[:160], None


def suggestion_for(
    *,
    name: str,
    birth_date: date | None,
    other_name: str,
    other_birth_date: date | None,
) -> dict[str, Any] | None:
    """Score a possible same-person match, or ``None`` when the evidence rules it out.

    The score is advisory only. Same name with a conflicting birth date stays a low-confidence
    suggestion instead of being dropped, because a source may simply have no birth date.
    """
    if normalize_name(name) != normalize_name(other_name):
        return None
    reasons = ["姓名一致"]
    confidence = 0.4
    if birth_date is not None and other_birth_date is not None:
        days = abs((birth_date - other_birth_date).days)
        if days == 0:
            confidence += 0.5
            reasons.append("出生日期一致")
        elif days <= 31:
            confidence += 0.3
            reasons.append(f"出生日期相差 {days} 天")
        elif days <= 366:
            confidence += 0.15
            reasons.append(f"出生日期相差 {days} 天（可能为精度差异）")
        else:
            confidence = CONFLICTING_BIRTHDATE_CONFIDENCE
            reasons.append(f"姓名相同但出生日期相差 {days} 天，不能视为同一人")
    elif birth_date is None or other_birth_date is None:
        reasons.append("缺少出生日期，无法核对")
        confidence = 0.25
    return {"confidence": round(confidence, 4), "reasons": reasons}


def identity_suggestions(
    session: Session,
    save_id: int,
    *,
    name: str,
    birth_date: date | None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Existing save-local identities that *might* be the same person. Never an automatic match."""
    normalized = normalize_name(name)
    rows = session.execute(
        select(Player, PlayerInstance)
        .join(PlayerInstance, PlayerInstance.player_id == Player.id)
        .where(PlayerInstance.fm_save_id == save_id, Player.normalized_name == normalized)
        .order_by(PlayerInstance.id)
        .limit(limit)
    ).all()
    suggestions: list[dict[str, Any]] = []
    for player, instance in rows:
        score = suggestion_for(
            name=name,
            birth_date=birth_date,
            other_name=player.full_name,
            other_birth_date=player.birth_date,
        )
        if score is None:
            continue
        suggestions.append(
            {
                "kind": "player_instance",
                "player_id": player.id,
                "player_instance_id": instance.id,
                "name": player.full_name,
                "birth_date": player.birth_date.isoformat() if player.birth_date else None,
                "save_local_uid": instance.save_local_uid,
                **score,
            }
        )
    suggestions.sort(key=lambda item: (-float(item["confidence"]), int(item["player_instance_id"])))
    return suggestions


def sibling_candidates(
    session: Session,
    save_id: int,
    *,
    normalized_name: str,
    exclude_candidate_id: int | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Other unresolved candidates in the same save with the same folded name (possible duplicates)."""
    if not normalized_name:
        return []
    query = select(UnresolvedPlayerCandidate).where(
        UnresolvedPlayerCandidate.fm_save_id == save_id,
        UnresolvedPlayerCandidate.normalized_name == normalized_name,
        UnresolvedPlayerCandidate.status != "dismissed",
    )
    if exclude_candidate_id is not None:
        query = query.where(UnresolvedPlayerCandidate.id != exclude_candidate_id)
    rows = list(session.scalars(query.order_by(UnresolvedPlayerCandidate.id).limit(limit)))
    return [
        {
            "candidate_id": row.id,
            "display_name": row.display_name,
            "birth_date": row.birth_date.isoformat() if row.birth_date else None,
            "status": row.status,
            "uid_status": row.uid_status,
        }
        for row in rows
    ]


def persist_unresolved_observation(
    session: Session,
    *,
    job: ImportJob,
    payload: "ScanPayload",
    row_index: int,
    record: PlayerRecord,
    raw_row: dict[str, Any] | None = None,
    outcome: "ImportOutcome",
    club_name: str | None = None,
) -> UnresolvedPlayerObservation | None:
    """Store one unresolved observation idempotently and return it, or ``None`` when already stored.

    The caller keeps the import transaction: a failure here is reported as a rejected row and makes the
    job ``partial`` rather than ``succeeded``.
    """
    scan_id = payload.scan.scan_id
    existing = session.scalar(
        select(UnresolvedPlayerObservation).where(
            UnresolvedPlayerObservation.fm_save_id == job.fm_save_id,
            UnresolvedPlayerObservation.scan_id == scan_id,
            UnresolvedPlayerObservation.row_index == row_index,
        )
    )
    if existing is not None:
        outcome.unresolved_observations_skipped += 1
        return None

    kind, key, stable_value = candidate_key_for(record, scan_id, row_index)
    candidate = session.scalar(
        select(UnresolvedPlayerCandidate).where(
            UnresolvedPlayerCandidate.fm_save_id == job.fm_save_id,
            UnresolvedPlayerCandidate.candidate_key == key,
        )
    )
    uid_status = record.uid_status or "missing"
    uid_reason = record.uid_reason
    identity = record.identity
    raw_uid = identity.raw_uid if identity is not None else None
    evidence = dict(identity.evidence) if identity is not None else {}
    suggestions = identity_suggestions(
        session, job.fm_save_id, name=record.name, birth_date=record.birth_date
    )
    if candidate is None:
        candidate = UnresolvedPlayerCandidate(
            fm_save_id=job.fm_save_id,
            candidate_key=key,
            source_identity_kind=kind,
            source_identity_value=stable_value,
            status="review_required" if suggestions else "pending",
            display_name=record.name.strip()[:128],
            normalized_name=normalize_name(record.name),
            birth_date=record.birth_date,
            nationality=record.nationality,
            position=record.position,
            raw_uid=raw_uid,
            uid_status=uid_status,
            uid_reason=uid_reason,
            evidence_summary_json=json.dumps(
                {
                    "scan_id": scan_id,
                    "row_index": row_index,
                    "identity": evidence,
                    "suggestions": suggestions,
                },
                ensure_ascii=False,
                default=str,
            )[:MAX_RAW_EVIDENCE_CHARS],
        )
        session.add(candidate)
        session.flush()
        outcome.unresolved_created += 1
    else:
        # A stable identity was seen again: refresh mutable display facts, never merge by name.
        candidate.display_name = record.name.strip()[:128]
        candidate.normalized_name = normalize_name(record.name)
        candidate.birth_date = record.birth_date or candidate.birth_date
        candidate.nationality = record.nationality or candidate.nationality
        candidate.position = record.position or candidate.position
        candidate.raw_uid = raw_uid or candidate.raw_uid
        candidate.uid_status = uid_status
        candidate.uid_reason = uid_reason or candidate.uid_reason
        if candidate.status == "pending" and suggestions:
            candidate.status = "review_required"
        outcome.unresolved_candidates_matched += 1

    observed_at = payload.scan.observed_at
    if candidate.first_seen_at is None or observed_at < candidate.first_seen_at:
        candidate.first_seen_at = observed_at
    if candidate.last_seen_at is None or observed_at >= candidate.last_seen_at:
        candidate.last_seen_at = observed_at
        candidate.latest_ca = record.ca if record.ca is not None else candidate.latest_ca
        candidate.latest_pa = record.pa if record.pa is not None else candidate.latest_pa
    candidate.observation_count = (candidate.observation_count or 0) + 1

    observation = UnresolvedPlayerObservation(
        candidate_id=candidate.id,
        fm_save_id=job.fm_save_id,
        import_job_id=job.id,
        scan_id=scan_id,
        row_index=row_index,
        observed_at=observed_at,
        game_date=payload.scan.game_date,
        raw_uid=raw_uid,
        uid_status=uid_status,
        name=record.name.strip()[:128],
        birth_date=record.birth_date,
        nationality=record.nationality,
        position=record.position,
        ca=record.ca,
        pa=record.pa,
        club_name=club_name,
        contract_end=record.contract_end,
        raw_evidence_json=_raw_evidence(record, raw_row, payload, row_index),
        payload_hash=_payload_hash(record, raw_row),
    )
    session.add(observation)
    session.flush()
    outcome.unresolved_observations_created += 1
    return observation


def _raw_evidence(
    record: PlayerRecord,
    raw_row: dict[str, Any] | None,
    payload: "ScanPayload",
    row_index: int,
) -> str:
    """Bounded evidence document: identity block plus the row that produced it."""
    document: dict[str, Any] = {
        "identity": record.identity.model_dump() if record.identity is not None else None,
        "scan_id": payload.scan.scan_id,
        "row_index": row_index,
        "source": payload.source,
        "reader_version": payload.reader_version,
        "game_build": payload.game.build,
    }
    if raw_row is not None:
        document["row"] = raw_row
    return json.dumps(document, ensure_ascii=False, default=str)[:MAX_RAW_EVIDENCE_CHARS]


def _payload_hash(record: PlayerRecord, raw_row: dict[str, Any] | None) -> str:
    """Digest of the observation as received, so two imports of one value can be compared later."""
    source = raw_row if raw_row is not None else record.model_dump(mode="json")
    canonical = json.dumps(source, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
