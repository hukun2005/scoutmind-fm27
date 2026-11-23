"""SM-115（幂等）：同一扫描重复导入不重复创建观察，不同扫描不会自动合并候选。"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ingestion.importer import ScanImporter
from app.ingestion.protocol import ScanPayload
from app.models import FmSave, ImportJob, PlayerInstance, UnresolvedPlayerCandidate, UnresolvedPlayerObservation
from app.utils import utcnow
from tests.helpers import RAW_DIR, import_document, player_row, scan_document
from tests.test_unresolved_persistence import unresolved_row

LATER = datetime(2026, 11, 2, 12)


def test_same_scan_id_is_idempotent(db: Session, save) -> None:
    document = scan_document(scan_id="scan-dup", players=[unresolved_row("Free Agent A")])
    first = import_document(db, document)
    observations = db.scalar(select(func.count()).select_from(UnresolvedPlayerObservation))
    assert first.unresolved_observations_created == 1

    second = import_document(db, document)
    assert second.duplicate is True
    assert db.scalar(select(func.count()).select_from(UnresolvedPlayerObservation)) == observations
    assert db.scalar(select(func.count()).select_from(UnresolvedPlayerCandidate)) == 1


def test_new_scan_does_not_merge_sentinel_candidates(db: Session, save) -> None:
    import_document(db, scan_document(scan_id="scan-a", players=[unresolved_row("Same Name")]))
    outcome = import_document(
        db,
        scan_document(scan_id="scan-b", when=LATER, players=[unresolved_row("Same Name")]),
    )

    assert outcome.unresolved_created == 1
    candidates = list(db.scalars(select(UnresolvedPlayerCandidate)))
    assert len(candidates) == 2, "同名 + 同哨兵 + 无稳定 ID：不得自动合并"
    assert {item.source_identity_kind for item in candidates} == {"observation"}
    assert db.scalar(select(func.count()).select_from(UnresolvedPlayerObservation)) == 2


def test_verified_stable_identity_correlates_observations(db: Session, save) -> None:
    evidence = {
        "source": "fmsuperscout_dump",
        "stable_identity_id": "person-777",
        "stable_identity_verified": True,
    }
    import_document(db, scan_document(scan_id="scan-stable-1", players=[unresolved_row("Stable Person", evidence=evidence)]))
    outcome = import_document(
        db,
        scan_document(
            scan_id="scan-stable-2",
            when=LATER,
            players=[unresolved_row("Stable Person", evidence=evidence)],
        ),
    )

    assert outcome.unresolved_created == 0
    assert outcome.unresolved_candidates_matched == 1
    candidates = list(db.scalars(select(UnresolvedPlayerCandidate)))
    assert len(candidates) == 1
    assert candidates[0].source_identity_kind == "stable_id"
    assert candidates[0].source_identity_value == "person-777"
    assert db.scalar(select(func.count()).select_from(UnresolvedPlayerObservation)) == 2


def test_unverified_stable_identity_does_not_correlate(db: Session, save) -> None:
    evidence = {"source": "fmsuperscout_dump", "stable_identity_id": "person-888"}
    import_document(db, scan_document(scan_id="scan-unverified-1", players=[unresolved_row("Person", evidence=evidence)]))
    import_document(
        db,
        scan_document(
            scan_id="scan-unverified-2",
            when=LATER,
            players=[unresolved_row("Person", evidence=evidence)],
        ),
    )
    assert db.scalar(select(func.count()).select_from(UnresolvedPlayerCandidate)) == 2


def test_observation_unique_constraint_is_enforced_by_the_database(db: Session, save) -> None:
    import_document(db, scan_document(scan_id="scan-unique", players=[unresolved_row("Unique Candidate")]))
    candidate = db.scalar(select(UnresolvedPlayerCandidate))
    assert candidate is not None
    duplicate = UnresolvedPlayerObservation(
        candidate_id=candidate.id,
        fm_save_id=save.id,
        scan_id="scan-unique",
        row_index=1,
        observed_at=utcnow(),
        uid_status="sentinel",
        raw_uid="4294967295",
        name="Duplicate",
        payload_hash="x" * 64,
        raw_evidence_json="{}",
    )
    db.add(duplicate)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_failed_job_can_be_retried_without_duplicating_observations(db: Session, save) -> None:
    document = scan_document(scan_id="scan-retry", players=[unresolved_row("Retry Candidate")])
    db.add(
        ImportJob(
            fm_save_id=save.id,
            scan_id="scan-retry",
            source="fm27_live_reader",
            schema_version="1.1",
            status="failed",
            received_at=utcnow(),
        )
    )
    db.commit()

    outcome = ScanImporter(db, raw_dir=RAW_DIR).import_payload(save.id, ScanPayload.model_validate(document))
    db.commit()
    assert outcome.duplicate is False
    assert outcome.unresolved_observations_created == 1
    assert db.scalar(select(func.count()).select_from(UnresolvedPlayerObservation)) == 1


def test_valid_and_unresolved_rows_coexist_in_one_scan(db: Session, save) -> None:
    document = scan_document(
        scan_id="scan-mixed",
        players=[
            player_row("3001", "Known Player"),
            unresolved_row("Unknown Player"),
        ],
    )
    outcome = import_document(db, document)
    assert outcome.status == "succeeded"
    assert outcome.players_imported == 1
    assert outcome.unresolved_observations_created == 1
    assert db.scalar(select(func.count()).select_from(PlayerInstance)) == 1
    assert db.scalar(select(func.count()).select_from(UnresolvedPlayerCandidate)) == 1
    assert db.get(FmSave, save.id) is not None
