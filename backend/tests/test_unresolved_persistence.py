"""SM-115 / SM-117：无 UID 球员的持久化与统计。"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ingestion.importer import ImportOutcome
from app.models import (
    ImportJob,
    Player,
    PlayerInstance,
    PlayerObservationCanonical,
    PlayerSnapshot,
    UnresolvedPlayerCandidate,
    UnresolvedPlayerObservation,
)
from tests.helpers import import_document, player_row, scan_document


def unresolved_row(
    name: str,
    *,
    raw_uid: str | None = "4294967295",
    reason: str | None = "sentinel_uid",
    uid_status: str = "sentinel",
    ca: int = 120,
    pa: int = 140,
    position: str = "ST",
    birth_date: str | None = "2003-07-01",
    club_uid: str | None = None,
    evidence: dict | None = None,
) -> dict:
    """One unresolved player row as the reader emits it."""
    identity: dict = {
        "kind": "unresolved",
        "reason": reason,
        "uid_status": uid_status,
        "source_record_id": f"dump_row:{name}",
        "evidence": evidence or {"source": "fmsuperscout_dump", "row_index": 1},
    }
    if raw_uid is not None:
        identity["raw_uid"] = raw_uid
    return {
        "name": name,
        "identity": identity,
        "birth_date": birth_date,
        "nationality": "England",
        "position": position,
        "club_uid": club_uid,
        "ca": ca,
        "pa": pa,
        "contract_end": None,
        "attributes": {"finishing": 12},
    }


def test_sentinel_rows_are_stored_as_unresolved_not_as_players(db: Session, save) -> None:
    document = scan_document(
        scan_id="scan-unresolved-1",
        players=[
            player_row("1001", "Normal One"),
            player_row("1002", "Normal Two"),
            player_row("1003", "Normal Three"),
            unresolved_row("Free Agent A"),
            unresolved_row("Free Agent B"),
        ],
    )
    outcome = import_document(db, document)

    assert outcome.status == "succeeded"
    assert outcome.players_imported == 3
    assert outcome.snapshots_created == 3
    assert outcome.unresolved_created == 2
    assert outcome.unresolved_observations_created == 2
    assert outcome.rows_rejected == 0

    assert db.scalar(select(func.count()).select_from(PlayerInstance)) == 3
    assert db.scalar(select(func.count()).select_from(PlayerSnapshot)) == 3
    assert db.scalar(select(func.count()).select_from(Player)) == 3
    assert db.scalar(select(func.count()).select_from(UnresolvedPlayerCandidate)) == 2
    assert db.scalar(select(func.count()).select_from(UnresolvedPlayerObservation)) == 2
    assert db.scalar(select(func.count()).select_from(PlayerObservationCanonical)) == 0

    uids = {row for row in db.scalars(select(PlayerInstance.save_local_uid))}
    assert "4294967295" not in uids
    assert uids == {"1001", "1002", "1003"}

    candidates = list(db.scalars(select(UnresolvedPlayerCandidate).order_by(UnresolvedPlayerCandidate.id)))
    assert [item.display_name for item in candidates] == ["Free Agent A", "Free Agent B"]
    assert all(item.uid_status == "sentinel" and item.raw_uid == "4294967295" for item in candidates)
    assert all(item.status == "pending" for item in candidates)
    assert all(item.resolved_player_id is None for item in candidates)

    observations = list(db.scalars(select(UnresolvedPlayerObservation).order_by(UnresolvedPlayerObservation.id)))
    assert [item.name for item in observations] == ["Free Agent A", "Free Agent B"]
    assert all(item.scan_id == "scan-unresolved-1" for item in observations)
    assert all(item.uid_status == "sentinel" for item in observations)
    assert all(item.payload_hash for item in observations)
    job = db.get(ImportJob, outcome.job_id)
    assert job is not None
    assert all(item.import_job_id == job.id for item in observations)


def test_unresolved_observation_keeps_display_facts(db: Session, save) -> None:
    document = scan_document(
        scan_id="scan-unresolved-facts",
        clubs=[{"uid": "C9", "name": "Harbour Town", "nation": "England", "league": "Championship", "reputation": 5000, "is_user_club": False}],
        players=[
            unresolved_row("Free Agent Facts", ca=133, pa=155, position="AML", club_uid="C9", birth_date="2004-02-29"),
        ],
    )
    import_document(db, document)
    observation = db.scalar(select(UnresolvedPlayerObservation))
    assert observation is not None
    assert observation.ca == 133
    assert observation.pa == 155
    assert observation.position == "AML"
    assert observation.birth_date is not None and observation.birth_date.isoformat() == "2004-02-29"
    assert observation.club_name == "Harbour Town"
    assert observation.contract_end is None
    assert "identity" in observation.raw_evidence_json


def test_missing_uid_row_is_not_dropped(db: Session, save) -> None:
    document = scan_document(
        scan_id="scan-unresolved-missing",
        players=[
            unresolved_row("No Id Player", raw_uid=None, reason="missing_uid", uid_status="missing"),
        ],
    )
    outcome = import_document(db, document)
    assert outcome.unresolved_observations_created == 1
    observation = db.scalar(select(UnresolvedPlayerObservation))
    assert observation is not None
    assert observation.raw_uid is None
    assert observation.uid_status == "missing"
    assert observation.name == "No Id Player"


def test_invalid_uid_keeps_raw_value(db: Session, save) -> None:
    document = scan_document(
        scan_id="scan-unresolved-invalid",
        players=[unresolved_row("Zero Uid", raw_uid="0", reason="zero_uid", uid_status="invalid")],
    )
    import_document(db, document)
    candidate = db.scalar(select(UnresolvedPlayerCandidate))
    assert candidate is not None
    assert candidate.raw_uid == "0"
    assert candidate.uid_status == "invalid"


def test_rows_rejected_are_still_reported(db: Session, save) -> None:
    document = scan_document(
        scan_id="scan-reject",
        players=[
            player_row("2001", "Fine Player"),
            {"name": "No Identity At All"},
        ],
    )
    outcome = import_document(db, document)
    assert outcome.rows_rejected == 1
    assert outcome.status == "partial"
    assert outcome.players_imported == 1
    assert any("missing_uid" in error["code"] for error in outcome.errors)


def test_import_outcome_exposes_report_fields() -> None:
    """The formal report names exist on the outcome object, so a scan report cannot invent them."""
    fields = set(ImportOutcome.__dataclass_fields__)
    for name in (
        "players_imported",
        "unresolved_created",
        "unresolved_observations_created",
        "rows_rejected",
        "rows_skipped",
        "canonical_candidates_created",
    ):
        assert name in fields
