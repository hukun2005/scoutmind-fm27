"""V3.3.0 engine: one payload → detect, repair, import, verify, audit."""

from __future__ import annotations

import json

from app.datahub.engine import AutomaticDataImportEngine
from app.models import DataRepairAudit, FmSave, ImportJob, PlayerInstance, PlayerSnapshot, Transfer, User

from tests.helpers import club_row, player_row, scan_document, transfer_row


def _raw(document: dict) -> bytes:
    return json.dumps(document, ensure_ascii=False).encode("utf-8")


def test_first_import_repairs_and_verifies(db, save):
    row = {
        **player_row("P1", "  John Smith  "),
        "ca": " 148 ",
        "contract_end": "2029/06/30",
        "foot": "Left",
        "wage": "",
    }
    document = scan_document(
        players=[row],
        transfers=[transfer_row("T1", "P1", "John Smith", fee=22_000_000)],
    )
    report = AutomaticDataImportEngine(db).run(save.id, _raw(document))

    assert report.status == "PASS"
    assert report.outcome is not None and report.outcome.duplicate is False
    assert report.counts["created"] == 2  # 1 player instance + 1 transfer
    assert report.counts["quarantined"] == 0
    assert report.counts["repaired"] >= 4
    assert report.verification["status"] == "PASS"

    snapshot = db.query(PlayerSnapshot).one()
    assert snapshot.ca == 148
    assert snapshot.foot == "left"
    assert snapshot.contract_end.isoformat() == "2029-06-30"
    assert snapshot.wage is None

    audits = db.query(DataRepairAudit).all()
    assert audits
    assert {audit.decision for audit in audits} == {"repaired"}
    assert all(audit.import_job_id == report.outcome.job_id for audit in audits)
    assert all(audit.fm_save_id == save.id for audit in audits)


def test_reimport_is_idempotent_and_does_not_duplicate_audits(db, save):
    document = scan_document(players=[player_row("P1", "A", ca="150")])
    raw = _raw(document)
    engine = AutomaticDataImportEngine(db)
    first = engine.run(save.id, raw)
    audit_count = db.query(DataRepairAudit).count()

    second = engine.run(save.id, raw)
    assert second.outcome is not None and second.outcome.duplicate is True
    assert second.status == "PASS"
    assert db.query(PlayerSnapshot).count() == 1
    assert db.query(PlayerInstance).count() == 1
    assert db.query(DataRepairAudit).count() == audit_count
    assert first.outcome is not None


def test_partial_import_quarantines_invalid_rows(db, save):
    good = player_row("P1", "Good Player")
    bad = {"ca": 100, "club_uid": "C1"}  # missing name
    report = AutomaticDataImportEngine(db).run(
        save.id, _raw(scan_document(players=[good, bad]))
    )

    assert report.status == "PARTIAL"
    assert report.counts["quarantined"] == 1
    assert db.query(PlayerSnapshot).count() == 1
    assert db.query(PlayerInstance).filter(PlayerInstance.save_local_uid == "P1").count() == 1

    quarantined = db.query(DataRepairAudit).filter(DataRepairAudit.decision == "quarantined").all()
    assert len(quarantined) == 1
    assert quarantined[0].requires_review is True
    assert quarantined[0].rule_id == "l3.missing_name"


def test_dry_run_writes_nothing(db, save):
    report = AutomaticDataImportEngine(db).run(
        save.id,
        _raw(scan_document(players=[player_row("P1", "A", ca="140")])),
        dry_run=True,
    )
    assert report.dry_run is True
    assert report.status == "PASS"
    assert db.query(ImportJob).count() == 0
    assert db.query(DataRepairAudit).count() == 0
    assert db.query(PlayerSnapshot).count() == 0


def test_unsupported_version_is_blocked_without_writing(db, save):
    document = scan_document(players=[player_row("P1", "A")])
    document["schema_version"] = "2.0"
    report = AutomaticDataImportEngine(db).run(save.id, _raw(document))
    assert report.status == "BLOCKED"
    assert report.outcome is None
    assert db.query(ImportJob).count() == 0
    assert db.query(PlayerSnapshot).count() == 0


def test_same_scan_id_is_isolated_between_saves(db, save):
    user = db.query(User).first()
    other = FmSave(user_id=user.id, name="第二个存档", is_active=False)
    db.add(other)
    db.commit()
    raw = _raw(scan_document(scan_id="shared-scan", players=[player_row("P1", "A")]))

    first = AutomaticDataImportEngine(db).run(save.id, raw)
    second = AutomaticDataImportEngine(db).run(other.id, raw)
    assert first.outcome is not None and first.outcome.duplicate is False
    assert second.outcome is not None and second.outcome.duplicate is False
    assert db.query(ImportJob).count() == 2
    assert db.query(PlayerInstance).filter(PlayerInstance.fm_save_id == save.id).count() == 1
    assert db.query(PlayerInstance).filter(PlayerInstance.fm_save_id == other.id).count() == 1


def test_ndjson_payload_is_imported_through_the_same_engine(db, save):
    header = scan_document(scan_id="nd-1", players=[], clubs=[club_row("C1", "北桥联", user_club=True)])
    header.pop("players")
    header.pop("transfers")
    lines = [json.dumps(header, ensure_ascii=False)]
    lines.append(json.dumps({"entity": "player", **player_row("P1", "ND Player")}, ensure_ascii=False))
    report = AutomaticDataImportEngine(db).run(save.id, ("\n".join(lines)).encode("utf-8"))
    assert report.status == "PASS"
    assert db.query(PlayerSnapshot).count() == 1
    assert db.query(Transfer).count() == 0


def test_iso_date_on_transfer_is_still_a_completed_transfer(db, save):
    transfer = transfer_row("T1", "P1", "A", fee=22_000_000)
    transfer["transfer_date"] = "2026/07/01T00:00:00"
    report = AutomaticDataImportEngine(db).run(
        save.id,
        _raw(scan_document(players=[player_row("P1", "A")], transfers=[transfer])),
    )
    assert report.status == "PASS"
    stored = db.query(Transfer).one()
    assert stored.transfer_date.isoformat() == "2026-07-01"
    assert stored.status == "completed"
