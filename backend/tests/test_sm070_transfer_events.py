"""SM-070：转会事件候选不得把俱乐部变化当成有偿转会。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.analytics.transfer_events import detect_transfer_events
from app.ingestion.importer import ScanImporter
from app.ingestion.protocol import ScanPayload
from app.models import CaptureRun, PlayerInstance, TransferEventCandidate
from app.quality.dedup import build_canonicals
from tests.helpers import player_row, scan_document


def _scan(db, save, scan_id: str, day: int, club: str):
    payload = scan_document(
        scan_id=scan_id,
        when=datetime(2026, 7, day, 12, tzinfo=timezone.utc),
        players=[player_row("T1", "Transfer One", club_uid=club)],
    )
    ScanImporter(db).import_payload(save.id, ScanPayload.model_validate(payload))
    db.commit()


def test_club_change_is_unverified_candidate(db, save) -> None:
    _scan(db, save, "t-a", 1, "C1")
    _scan(db, save, "t-b", 2, "C2")
    build_canonicals(db, save.id, dry_run=False)
    result = detect_transfer_events(db, save.id, dry_run=False)
    assert result["created"] == 1
    row = db.scalar(select(TransferEventCandidate))
    assert row.event_type == "unknown_pending_verification"
    assert row.evidence_level == "Unverified"
    assert row.status == "pending"
    assert "fee" not in row.evidence_json or "null" in row.evidence_json
    assert db.query(TransferEventCandidate).count() == 1

    again = detect_transfer_events(db, save.id, dry_run=False)
    assert again["created"] == 0
    assert db.query(TransferEventCandidate).count() == 1


def test_no_club_change_no_event(db, save) -> None:
    _scan(db, save, "t-c", 1, "C1")
    _scan(db, save, "t-d", 2, "C1")
    build_canonicals(db, save.id, dry_run=False)
    assert detect_transfer_events(db, save.id, dry_run=False)["created"] == 0
