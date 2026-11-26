"""V3.2.9 Phase 6：历史转会身份关联测试。"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.models import PlayerIdentityReviewItem, Transfer
from app.services.transfer_identity import link_transfers, transfer_link_summary

from tests.v329_helpers import make_instance


def _transfer(db, save, record_id: str, name: str, *, transfer_type="permanent", status="completed") -> Transfer:
    row = Transfer(
        fm_save_id=save.id,
        source_record_id=record_id,
        player_name=name,
        transfer_type=transfer_type,
        status=status,
        transfer_date=date(2026, 7, 1),
        currency="EUR",
        source="test",
    )
    db.add(row)
    db.flush()
    return row


def test_unique_name_match_links_transfer(db, save) -> None:
    instance = make_instance(db, save, uid="T1", name="Transfer Target", birth=date(1999, 1, 1))
    transfer = _transfer(db, save, "R1", "Transfer Target")
    result = link_transfers(db, save.id)
    assert result["linked"] == 1
    db.refresh(transfer)
    assert transfer.player_instance_id == instance.id


def test_club_change_does_not_break_identity(db, save) -> None:
    instance = make_instance(db, save, uid="T2", name="Moved Player", birth=date(1999, 1, 1))
    first = _transfer(db, save, "R2", "Moved Player")
    second = _transfer(db, save, "R3", "Moved Player")
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
    _transfer(db, save, "R6", "Loan Player", transfer_type="loan", status="completed")
    _transfer(db, save, "R7", "Loan Player", transfer_type="free", status="completed")
    _transfer(db, save, "R8", "Loan Player", transfer_type="permanent", status="pending")
    link_transfers(db, save.id)
    summary = transfer_link_summary(db, save.id)
    assert summary["transfers"] == 3
    assert summary["linked_transfers"] == 3
    assert set(summary["linked_by_type"]) == {"loan", "free", "permanent"}
    assert summary["by_status"]["pending"] == 1


def test_link_transfers_is_idempotent(db, save) -> None:
    make_instance(db, save, uid="T7", name="Idem Transfer", birth=date(1999, 1, 1))
    _transfer(db, save, "R9", "Idem Transfer")
    assert link_transfers(db, save.id)["linked"] == 1
    assert link_transfers(db, save.id)["transfers_scanned"] == 0
