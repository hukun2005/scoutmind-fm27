"""V3.3.0 repair rules: deterministic normalization, safe de-duplication and evidence-based club links."""

from __future__ import annotations

from app.datahub.repair import dedupe_document, normalize_document, resolve_level2
from app.datahub.validation import validate_header, validate_rows
from app.models import Club

from tests.helpers import club_row, player_row, scan_document, transfer_row


def test_level1_normalizes_format_without_changing_meaning():
    document = scan_document(
        players=[
            {
                **player_row("P1", "  John Smith  "),
                "ca": " 140 ",
                "wage": "",
                "contract_end": "2029/06/30",
                "foot": "Left",
            }
        ]
    )
    normalized, repairs = normalize_document(document)
    row = normalized["players"][0]
    assert row["name"] == "John Smith"
    assert row["ca"] == 140
    assert row["wage"] is None
    assert row["contract_end"] == "2029-06-30"
    assert row["foot"] == "left"
    rules = {repair.rule_id for repair in repairs}
    assert {"l1.trim_whitespace", "l1.numeric_string", "l1.blank_to_null", "l1.date_format", "l1.enum_case"} <= rules


def test_level1_maps_known_legacy_field_names():
    row = player_row("P1", "A")
    row.pop("ca")
    row["current_ability"] = 155
    normalized, repairs = normalize_document(scan_document(players=[row]))
    assert normalized["players"][0]["ca"] == 155
    assert any(repair.rule_id == "l1.field_alias" for repair in repairs)


def test_exact_duplicate_rows_are_removed_and_counted():
    row = player_row("P1", "A")
    document = scan_document(players=[row, dict(row)])
    deduped, repairs, removed = dedupe_document(document)
    assert len(deduped["players"]) == 1
    assert removed == 1
    assert repairs[0].rule_id == "l1.duplicate_row"


def test_transfer_loan_is_never_converted_to_permanent():
    transfer = transfer_row("T1", "P1", "A", fee=1_000_000)
    transfer["transfer_type"] = "LOAN"
    normalized, _ = normalize_document(scan_document(transfers=[transfer]))
    assert normalized["transfers"][0]["transfer_type"] == "loan"


def test_rumour_status_is_not_guessed_into_completed():
    transfer = transfer_row("T1", "P1", "A", fee=None)
    transfer["status"] = "rumour"
    normalized, _ = normalize_document(scan_document(transfers=[transfer]))
    assert normalized["transfers"][0]["status"] == "rumour"
    filtered, rejections = validate_rows(normalized)
    assert filtered["transfers"] == []
    assert rejections[0].code == "invalid_transfer"


def test_level2_fills_club_uid_only_when_name_is_unique(db, save):
    db.add(Club(fm_save_id=save.id, uid="C9", name="Unique United", normalized_name="unique united"))
    db.commit()
    transfer = transfer_row("T1", "P1", "A", fee=1_000_000)
    transfer["from_club_uid"] = None
    transfer["from_club_name"] = "Unique United"
    document, repairs = resolve_level2(db, save.id, scan_document(transfers=[transfer]))
    assert document["transfers"][0]["from_club_uid"] == "C9"
    assert repairs[0].rule_id == "l2.club_by_unique_name"
    assert repairs[0].level == 2


def test_level2_leaves_ambiguous_club_name_untouched(db, save):
    db.add_all(
        [
            Club(fm_save_id=save.id, uid="C1", name="Twin Town", normalized_name="twin town"),
            Club(fm_save_id=save.id, uid="C2", name="Twin Town", normalized_name="twin town"),
        ]
    )
    db.commit()
    transfer = transfer_row("T1", "P1", "A", fee=1_000_000)
    transfer["to_club_uid"] = None
    transfer["to_club_name"] = "Twin Town"
    document, repairs = resolve_level2(db, save.id, scan_document(transfers=[transfer]))
    assert document["transfers"][0]["to_club_uid"] is None
    assert repairs == []


def test_level2_never_matches_clubs_from_another_save(db, save):
    from app.models import FmSave, User

    user = db.query(User).first()
    other = FmSave(user_id=user.id, name="另一个存档", is_active=False)
    db.add(other)
    db.commit()
    db.add(Club(fm_save_id=other.id, uid="C-OTHER", name="Foreign FC", normalized_name="foreign fc"))
    db.commit()

    transfer = transfer_row("T1", "P1", "A", fee=1_000_000)
    transfer["from_club_uid"] = None
    transfer["from_club_name"] = "Foreign FC"
    document, repairs = resolve_level2(db, save.id, scan_document(transfers=[transfer]))
    assert document["transfers"][0]["from_club_uid"] is None
    assert repairs == []


def test_validation_quarantines_rows_without_identity():
    document = scan_document(players=[{"ca": 140}])
    filtered, rejections = validate_rows(document)
    assert filtered["players"] == []
    assert rejections[0].entity == "player"
    assert rejections[0].code == "missing_name"
    spec = rejections[0].audit_spec()
    assert spec["decision"] == "quarantined"
    assert spec["level"] == 3
    assert spec["requires_review"] is True


def test_header_validation_reports_unsupported_version():
    document = scan_document(players=[])
    document["schema_version"] = "9.0"
    payload, code, message = validate_header(document)
    assert payload is None
    assert code == "unsupported_version"
    assert message


def test_club_rows_are_validated_too():
    document = scan_document(players=[], clubs=[club_row("C1", "北桥联")])
    filtered, rejections = validate_rows(document)
    assert len(filtered["clubs"]) == 1
    assert rejections == []
