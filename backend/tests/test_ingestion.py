"""Acceptance tests for scan ingestion: idempotency, append-only snapshots, identity and fee rules."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.ingestion.protocol import ProtocolError, ScanPayload, parse_payload
from app.models import PlayerInstance, PlayerSnapshot, Transfer

from tests.helpers import club_row, import_document, player_row, scan_document, transfer_row


def test_import_creates_players_snapshots_and_transfers(db, save):
    """A first scan creates instances, snapshots and transfers."""
    document = scan_document(
        players=[player_row("P1", "Adam Wharton", ca=148, pa=165)],
        transfers=[transfer_row("T1", "P1", "Adam Wharton", fee=22_000_000)],
    )
    outcome = import_document(db, document)
    assert outcome.status == "succeeded"
    assert outcome.snapshots_created == 1
    assert outcome.transfers_created == 1
    assert outcome.players_created == 1
    assert db.query(PlayerSnapshot).count() == 1
    assert db.query(Transfer).count() == 1


def test_same_scan_is_idempotent(db, save):
    """Re-importing the same scan_id changes nothing and reports duplicate."""
    document = scan_document(players=[player_row("P1", "Adam Wharton")])
    first = import_document(db, document)
    second = import_document(db, document)
    assert first.duplicate is False
    assert second.duplicate is True
    assert db.query(PlayerSnapshot).count() == 1
    assert db.query(PlayerInstance).count() == 1


def test_snapshots_are_append_only(db, save):
    """A later scan with a new observed_at adds a snapshot and never rewrites the old one."""
    first = scan_document(
        scan_id="scan-1",
        when=datetime(2026, 8, 1, tzinfo=timezone.utc),
        players=[player_row("P1", "Adam Wharton", ca=140, value=10_000_000)],
    )
    import_document(db, first)
    second = scan_document(
        scan_id="scan-2",
        when=datetime(2026, 11, 1, tzinfo=timezone.utc),
        players=[player_row("P1", "Adam Wharton", ca=148, value=16_000_000)],
    )
    import_document(db, second)
    snapshots = db.query(PlayerSnapshot).order_by(PlayerSnapshot.observed_at).all()
    assert len(snapshots) == 2
    assert snapshots[0].ca == 140
    assert snapshots[1].ca == 148
    assert snapshots[1].market_value == 16_000_000


def test_duplicate_observation_does_not_overwrite(db, save):
    """The same instance observed at the same instant is skipped, not updated."""
    when = datetime(2026, 11, 1, tzinfo=timezone.utc)
    import_document(db, scan_document(scan_id="scan-1", when=when, players=[player_row("P1", "A", ca=140)]))
    outcome = import_document(
        db, scan_document(scan_id="scan-2", when=when, players=[player_row("P1", "A", ca=155)])
    )
    assert outcome.snapshots_skipped == 1
    assert db.query(PlayerSnapshot).one().ca == 140


def test_uid_reuse_creates_new_identity(db, save):
    """A different birth date on the same save-local UID is treated as ID reuse, not an overwrite."""
    import_document(db, scan_document(scan_id="scan-1", players=[player_row("P1", "Old Player", age=25)]))
    outcome = import_document(
        db, scan_document(scan_id="scan-2", players=[player_row("P1", "New Player", age=18)])
    )
    assert outcome.players_created == 1
    assert any("ID 复用" in warning for warning in outcome.warnings)
    assert db.query(PlayerInstance).count() == 2


def test_invalid_player_row_is_recorded_not_fatal(db, save):
    """A row without identity is rejected while the rest of the scan imports."""
    bad = player_row("P2", "Broken Row")
    bad["save_local_uid"] = ""
    document = scan_document(players=[player_row("P1", "Good Row"), bad])
    outcome = import_document(db, document)
    assert outcome.rows_rejected == 1
    assert outcome.status == "partial"
    assert outcome.snapshots_created == 1
    assert outcome.errors[0]["code"] == "missing_uid"


def test_untriggered_addon_is_not_paid_money(db, save):
    """Effective fee counts paid components only; an untriggered add-on is potential money."""
    components = [
        {"type": "base_fee", "amount": 20_000_000, "status": "paid"},
        {"type": "addon", "amount": 5_000_000, "status": "untriggered"},
    ]
    document = scan_document(
        players=[player_row("P1", "Addon Player")],
        transfers=[transfer_row("T1", "P1", "Addon Player", fee=20_000_000, components=components)],
    )
    import_document(db, document)
    transfer = db.query(Transfer).one()
    assert transfer.effective_fee == 20_000_000
    assert transfer.addons_potential is None


def test_compatibility_gate_rejects_wrong_major_version():
    """A future schema major version is refused before any row is touched."""
    document = scan_document()
    document["schema_version"] = "2.0"
    with pytest.raises(Exception):
        ScanPayload.model_validate(document)


def test_ndjson_payload_is_supported():
    """NDJSON payloads carry a header line plus one entity per line."""
    header = {
        "schema_version": "1.0",
        "source": "fm27_live_reader",
        "scan": {"scan_id": "nd-1", "observed_at": "2026-11-01T12:00:00Z", "game_date": "2026-11-01"},
    }
    lines = [
        __import__("json").dumps(header),
        __import__("json").dumps({"entity": "club", **club_row("C1", "Northbridge")}),
        __import__("json").dumps({"entity": "player", **player_row("P1", "NDJSON Player")}),
    ]
    payload, warnings = parse_payload("\n".join(lines).encode("utf-8"))
    assert payload.scan.scan_id == "nd-1"
    assert len(payload.players) == 1
    assert warnings == []


def test_empty_payload_raises_protocol_error():
    """An empty body is a protocol error, not an empty successful import."""
    with pytest.raises(ProtocolError):
        parse_payload(b"   ")
