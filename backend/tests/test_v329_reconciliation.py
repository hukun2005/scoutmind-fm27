"""V3.2.9 Phase 2：全库关联引擎、批处理与断点恢复测试。"""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select

from app.models import (
    IdentityScanRun,
    Player,
    PlayerIdentityLink,
    PlayerIdentityReviewItem,
    PlayerUidObservation,
)
from app.services import identity_engine
from app.services import identity_errors as errors

from tests.v329_helpers import make_instance


def _start(db, save, scan_id="scan-1", **kwargs) -> IdentityScanRun:
    return identity_engine.start_scan(
        db,
        save.id,
        scan_id=scan_id,
        fingerprint=kwargs.pop("fingerprint", "si:v1:file:abc123"),
        game_build=kwargs.pop("game_build", "26620374"),
        layout_version=kwargs.pop("layout_version", "FM27_1"),
        **kwargs,
    )


def test_scan_completes_and_only_produces_candidates(db, save) -> None:
    make_instance(db, save, uid="1", name="One")
    make_instance(db, save, uid="2", name="Two")
    make_instance(db, save, uid="3", name="Three")

    run = _start(db, save)
    run = identity_engine.run_scan(db, run)
    assert run.status == "Completed"
    assert run.processed_count == 3
    assert run.matched_count == 3

    links = list(db.scalars(select(PlayerIdentityLink)))
    assert len(links) == 3
    assert {row.verification_status for row in links} == {"Candidate"}
    assert "Verified" not in {row.verification_status for row in links}
    assert db.scalar(select(func.count()).select_from(PlayerUidObservation)) == 3


def test_scan_pauses_and_resumes_without_duplicating_rows(db, save) -> None:
    for index in range(4):
        make_instance(db, save, uid=str(100 + index), name=f"Player {index}")

    run = _start(db, save, batch_size=1)
    run = identity_engine.run_scan(db, run, max_batches=1)
    assert run.status == "Paused"
    assert run.processed_count == 1
    assert run.cursor > 0

    run = identity_engine.run_scan(db, run)
    assert run.status == "Completed"
    assert run.processed_count == 4
    assert db.scalar(select(func.count()).select_from(PlayerIdentityLink)) == 4
    assert db.scalar(select(func.count()).select_from(PlayerUidObservation)) == 4


def test_scope_change_blocks_resume_with_checksum_error(db, save) -> None:
    make_instance(db, save, uid="10", name="First")
    run = _start(db, save, batch_size=1)
    run = identity_engine.run_scan(db, run, max_batches=1)
    assert run.status == "Paused"

    make_instance(db, save, uid="11", name="Late Arrival")
    run = identity_engine.run_scan(db, run)
    assert run.status == "Failed"
    assert run.error_code == errors.BATCH_CHECKSUM_MISMATCH
    assert db.scalar(select(func.count()).select_from(PlayerIdentityLink)) == 1


def test_save_identity_mismatch_blocks_resume(db, save) -> None:
    make_instance(db, save, uid="20", name="Only One")
    run = _start(db, save, scan_id="scan-scope")
    run = identity_engine.pause_scan(db, run)
    run = identity_engine.resume_scan(
        db, run, fingerprint="si:v1:file:different", game_build="26620374", layout_version="FM27_1"
    )
    assert run.status == "Failed"
    assert run.error_code == errors.SAVE_IDENTITY_MISMATCH
    assert db.scalar(select(func.count()).select_from(PlayerIdentityLink)) == 0


def test_same_name_is_conflicted_and_never_merged(db, save) -> None:
    make_instance(db, save, uid="30", name="Alex Same", birth=date(1995, 1, 1))
    make_instance(db, save, uid="31", name="Alex Same", birth=date(1985, 5, 5))

    run = identity_engine.run_scan(db, _start(db, save, scan_id="scan-name"))
    assert run.conflict_count >= 1

    items = list(db.scalars(select(PlayerIdentityReviewItem)))
    assert len(items) == 1
    assert items[0].item_type == "same_name"
    assert items[0].conflict_reason == "same_name_different_birth_date"
    assert items[0].status == "PendingHumanReview"

    # 两个球员实体都还在，没有被自动合并
    assert db.scalar(select(func.count()).select_from(Player)) == 2
    statuses = {row.verification_status for row in db.scalars(select(PlayerIdentityLink))}
    assert "Verified" not in statuses


def test_duplicate_uid_creates_review_and_marks_observations(db, save) -> None:
    make_instance(db, save, uid="40", name="Twin A", birth=date(1995, 1, 1))
    make_instance(db, save, uid="40", name="Twin B", birth=date(1996, 2, 2), occurrence=1)

    identity_engine.run_scan(db, _start(db, save, scan_id="scan-dup"))
    items = list(db.scalars(select(PlayerIdentityReviewItem).where(PlayerIdentityReviewItem.item_type == "uid_duplicate")))
    assert len(items) == 1
    assert items[0].subject_uid == "40"
    duplicate_observations = list(
        db.scalars(select(PlayerUidObservation).where(PlayerUidObservation.status == "Duplicate"))
    )
    assert duplicate_observations


def test_scan_is_idempotent_for_same_scan_id(db, save) -> None:
    make_instance(db, save, uid="50", name="Idem")
    first = _start(db, save, scan_id="scan-idem")
    first = identity_engine.run_scan(db, first)
    second = _start(db, save, scan_id="scan-idem")
    assert second.id == first.id
    assert db.scalar(select(func.count()).select_from(IdentityScanRun)) == 1


def test_pause_and_cancel_state_machine(db, save) -> None:
    make_instance(db, save, uid="60", name="State")
    run = _start(db, save, scan_id="scan-state")
    assert identity_engine.pause_scan(db, run).status == "Paused"
    cancelled = identity_engine.cancel_scan(db, run)
    assert cancelled.status == "Cancelled"
    assert identity_engine.run_scan(db, cancelled).status == "Cancelled"
