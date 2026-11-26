"""V3.2.9 Phase 6：历史转会身份关联测试。"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.models import PlayerIdentityReviewItem, Transfer
from app.services.transfer_identity import link_transfers, transfer_link_summary

from tests.v329_helpers import make_instance


def _transfer(
    db,
    save,
    record_id: str,
    name: str,
    *,
    transfer_type="permanent",
    status="completed",
    age: int | None = None,
    to_club: str | None = None,
) -> Transfer:
    row = Transfer(
        fm_save_id=save.id,
        source_record_id=record_id,
        player_name=name,
        transfer_type=transfer_type,
        status=status,
        transfer_date=date(2026, 7, 1),
        currency="EUR",
        source="test",
        player_age_at_transfer=age,
        to_club_name=to_club,
    )
    db.add(row)
    db.flush()
    return row


def test_unique_name_match_links_transfer_with_age_evidence(db, save) -> None:
    instance = make_instance(db, save, uid="T1", name="Transfer Target", birth=date(1999, 1, 1))
    transfer = _transfer(db, save, "R1", "Transfer Target", age=27)
    result = link_transfers(db, save.id)
    assert result["linked"] == 1
    db.refresh(transfer)
    assert transfer.player_instance_id == instance.id


def test_name_only_is_insufficient_evidence(db, save) -> None:
    """姓名不是身份：只有姓名匹配时必须保持未关联并进入人工审核。"""
    make_instance(db, save, uid="T9", name="Name Only", birth=date(1999, 1, 1))
    transfer = _transfer(db, save, "R10", "Name Only")

    result = link_transfers(db, save.id)

    assert result["linked"] == 0
    assert result["insufficient_evidence"] == 1
    db.refresh(transfer)
    assert transfer.player_instance_id is None
    item = db.scalar(
        select(PlayerIdentityReviewItem).where(
            PlayerIdentityReviewItem.item_type == "transfer_identity",
            PlayerIdentityReviewItem.conflict_reason == "insufficient_evidence",
        )
    )
    assert item is not None


def test_age_mismatch_goes_to_review(db, save) -> None:
    make_instance(db, save, uid="T10", name="Age Mismatch", birth=date(1999, 1, 1))
    transfer = _transfer(db, save, "R11", "Age Mismatch", age=41)

    result = link_transfers(db, save.id)

    assert result["linked"] == 0
    assert result["evidence_conflict"] == 1
    db.refresh(transfer)
    assert transfer.player_instance_id is None


def test_club_agreement_is_independent_evidence(db, save) -> None:
    from app.models import Club

    club = Club(fm_save_id=save.id, uid="C1", name="Target United")
    db.add(club)
    db.flush()
    instance = make_instance(db, save, uid="T11", name="Club Player", birth=date(1999, 1, 1), club_id=club.id)
    _transfer(db, save, "R12", "Club Player", to_club="Target United")

    result = link_transfers(db, save.id)

    assert result["linked"] == 1
    row = db.scalar(select(Transfer).where(Transfer.source_record_id == "R12"))
    assert row is not None and row.player_instance_id == instance.id


def test_club_change_does_not_break_identity(db, save) -> None:
    instance = make_instance(db, save, uid="T2", name="Moved Player", birth=date(1999, 1, 1))
    first = _transfer(db, save, "R2", "Moved Player", age=27)
    second = _transfer(db, save, "R3", "Moved Player", age=27)
    link_transfers(db, save.id)
    db.refresh(first)
    db.refresh(second)
    assert first.player_instance_id == instance.id
    assert second.player_instance_id == instance.id


def test_multiple_matches_go_to_review_without_linking(db, save) -> None:
    make_instance(db, save, uid="T3", name="Common Name", birth=date(1999, 1, 1))
    make_instance(db, save, uid="T4", name="Common Name", birth=date(1990, 1, 1))
    transfer = _transfer(db, save, "R4", "Common Name")
    result = link_transfers(db, save.id)
    assert result["ambiguous"] == 1
    assert result["linked"] == 0
    db.refresh(transfer)
    assert transfer.player_instance_id is None
    item = db.scalar(select(PlayerIdentityReviewItem).where(PlayerIdentityReviewItem.item_type == "transfer_identity"))
    assert item is not None
    assert item.conflict_reason == "multiple_name_matches"


def test_unmatched_transfer_stays_unlinked(db, save) -> None:
    make_instance(db, save, uid="T5", name="Known Player", birth=date(1999, 1, 1))
    transfer = _transfer(db, save, "R5", "Unknown Player")
    result = link_transfers(db, save.id)
    assert result["unmatched"] == 1
    db.refresh(transfer)
    assert transfer.player_instance_id is None


def test_loan_free_and_pending_statuses_are_preserved(db, save) -> None:
    make_instance(db, save, uid="T6", name="Loan Player", birth=date(1999, 1, 1))
    _transfer(db, save, "R6", "Loan Player", transfer_type="loan", status="completed", age=27)
    _transfer(db, save, "R7", "Loan Player", transfer_type="free", status="completed", age=27)
    _transfer(db, save, "R8", "Loan Player", transfer_type="permanent", status="pending", age=27)
    link_transfers(db, save.id)
    summary = transfer_link_summary(db, save.id)
    assert summary["transfers"] == 3
    assert summary["linked_transfers"] == 3
    assert set(summary["linked_by_type"]) == {"loan", "free", "permanent"}
    assert summary["by_status"]["pending"] == 1


def test_link_transfers_is_idempotent(db, save) -> None:
    make_instance(db, save, uid="T7", name="Idem Transfer", birth=date(1999, 1, 1))
    _transfer(db, save, "R9", "Idem Transfer", age=27)
    assert link_transfers(db, save.id)["linked"] == 1
    assert link_transfers(db, save.id)["transfers_scanned"] == 0
