"""SM-114：扫描协议的身份模式（合法 UID / Unresolved）与哨兵防护。"""

from __future__ import annotations

import pytest

from app.ingestion.protocol import (
    PlayerRecord,
    RowValidationError,
    ScanPayload,
    parse_payload,
    validate_player_row,
)
from app.ingestion.uid_status import UID_INVALID, UID_MISSING, UID_SENTINEL, UID_VALID, classify_uid
from tests.helpers import player_row, scan_document


@pytest.mark.parametrize(
    ("value", "status", "reason"),
    [
        (None, UID_MISSING, "missing_uid"),
        ("", UID_MISSING, "missing_uid"),
        ("   ", UID_MISSING, "missing_uid"),
        ("4294967295", UID_SENTINEL, "sentinel_uid"),
        (4294967295, UID_SENTINEL, "sentinel_uid"),
        ("-1", UID_SENTINEL, "sentinel_uid"),
        ("0xFFFFFFFF", UID_SENTINEL, "sentinel_uid"),
        ("0", UID_INVALID, "zero_uid"),
        ("-5", UID_SENTINEL, "sentinel_uid"),
        ("12345678", UID_VALID, None),
        (1234, UID_VALID, None),
        ("U1", UID_VALID, None),
    ],
)
def test_uid_classification(value: object, status: str, reason: str | None) -> None:
    """Classification never rewrites a value: the raw text survives for evidence."""
    assessment = classify_uid(value)
    assert assessment.status == status
    assert assessment.reason == reason


def test_valid_uid_row_keeps_schema_1_0_fields() -> None:
    record = validate_player_row(player_row("12345678", "Valid Player"))
    assert record.has_valid_uid
    assert record.save_local_uid == "12345678"
    assert record.identity is not None
    assert record.identity.kind == "save_local_uid"
    assert record.identity.value == "12345678"
    assert record.uid_status == UID_VALID


def test_legacy_sentinel_row_becomes_unresolved_instead_of_being_stored_as_uid() -> None:
    """A 1.0 payload with id=4294967295 keeps the player and never stores the sentinel as identity."""
    record = validate_player_row({"name": "Free Agent", "save_local_uid": "4294967295", "ca": 120, "pa": 140})
    assert not record.has_valid_uid
    assert record.save_local_uid is None
    assert record.identity is not None
    assert record.identity.kind == "unresolved"
    assert record.identity.raw_uid == "4294967295"
    assert record.identity.reason == "sentinel_uid"
    assert record.uid_status == UID_SENTINEL


def test_unresolved_row_requires_evidence() -> None:
    record = validate_player_row(
        {
            "name": "Free Agent",
            "identity": {
                "kind": "unresolved",
                "raw_uid": "4294967295",
                "reason": "sentinel_uid",
                "source_record_id": "dump_row:14",
                "evidence": {"source": "fmsuperscout_dump", "row_index": 14},
            },
        }
    )
    assert record.identity is not None
    assert record.identity.source_record_id == "dump_row:14"
    assert record.identity.evidence["source"] == "fmsuperscout_dump"
    assert record.uid_reason == "sentinel_uid"


def test_unresolved_row_without_reason_or_evidence_is_rejected() -> None:
    with pytest.raises(RowValidationError) as missing_uid:
        validate_player_row({"name": "No Identity"})
    assert missing_uid.value.code == "missing_uid"

    with pytest.raises(RowValidationError) as no_reason:
        validate_player_row({"name": "No Identity", "identity": {"kind": "unresolved", "raw_uid": "0"}})
    assert no_reason.value.code in {"invalid_identity", "invalid_uid"}


def test_identity_modes_are_mutually_exclusive() -> None:
    with pytest.raises(RowValidationError) as conflict_too:
        validate_player_row(
            {
                "name": "Mixed",
                "save_local_uid": "123",
                "identity": {"kind": "unresolved", "raw_uid": "4294967295", "reason": "sentinel_uid", "evidence": {"x": 1}},
            }
        )
    assert conflict_too.value.code == "identity_conflict"

    with pytest.raises(RowValidationError) as mismatch:
        validate_player_row(
            {
                "name": "Mixed",
                "save_local_uid": "123",
                "identity": {"kind": "save_local_uid", "value": "456"},
            }
        )
    assert mismatch.value.code == "identity_conflict"


def test_sentinel_cannot_be_disguised_as_a_legal_identity() -> None:
    """The new identity block must not be a way around the sentinel check."""
    with pytest.raises(RowValidationError) as exc:
        validate_player_row(
            {"name": "Fake", "identity": {"kind": "save_local_uid", "value": "4294967295"}}
        )
    assert exc.value.code == "sentinel_uid"

    with pytest.raises(RowValidationError) as zero:
        validate_player_row({"name": "Fake", "identity": {"kind": "save_local_uid", "value": "0"}})
    assert zero.value.code == "invalid_uid"


def test_unresolved_raw_uid_cannot_be_a_valid_uid() -> None:
    with pytest.raises(RowValidationError) as exc:
        validate_player_row(
            {
                "name": "Odd",
                "identity": {"kind": "unresolved", "raw_uid": "123456", "reason": "sentinel_uid", "evidence": {"x": 1}},
            }
        )
    assert exc.value.code == "identity_conflict"


def test_payload_cannot_declare_its_own_uid_status() -> None:
    """Derived fields are overwritten on validation, so a sender cannot claim a sentinel is valid."""
    record = validate_player_row(
        {
            "name": "Claim",
            "identity": {
                "kind": "unresolved",
                "raw_uid": "4294967295",
                "reason": "sentinel_uid",
                "uid_status": "valid",
                "evidence": {"x": 1},
            },
        }
    )
    assert record.uid_status == UID_SENTINEL
    assert record.identity is not None
    assert record.identity.uid_status == UID_SENTINEL


def test_oversized_identity_evidence_is_rejected() -> None:
    with pytest.raises(RowValidationError) as exc:
        validate_player_row(
            {
                "name": "Big",
                "identity": {
                    "kind": "unresolved",
                    "raw_uid": "4294967295",
                    "reason": "sentinel_uid",
                    "evidence": {"blob": "x" * 5000},
                },
            }
        )
    assert exc.value.code == "invalid_identity"


def test_scan_payload_accepts_1_x_wire_with_identity_blocks_and_rejects_2_x() -> None:
    document = scan_document(
        scan_id="scan-identity",
        players=[
            player_row("111", "Valid"),
            {
                "name": "Unresolved",
                "identity": {"kind": "unresolved", "raw_uid": "4294967295", "reason": "sentinel_uid", "evidence": {"x": 1}},
                "ca": 100,
                "pa": 120,
            },
        ],
    )
    payload = ScanPayload.model_validate({**document, "schema_version": "1.1"})
    assert payload.schema_version == "1.1"
    with pytest.raises(Exception):
        ScanPayload.model_validate({**document, "schema_version": "2.0"})

    raw = b'{"schema_version":"1.1","source":"fm27_live_reader","scan":{"scan_id":"s1","observed_at":"2026-11-01T12:00:00"},"players":[]}'
    parsed, warnings = parse_payload(raw)
    assert parsed.schema_version == "1.1"
    assert warnings == []


def test_player_record_direct_construction_is_also_guarded() -> None:
    """Defense in depth: constructing the model directly cannot smuggle a sentinel either."""
    with pytest.raises(Exception):
        PlayerRecord.model_validate({"name": "Direct", "identity": {"kind": "save_local_uid", "value": "4294967295"}})
