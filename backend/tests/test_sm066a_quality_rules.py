"""SM-066A：数据质量规则引擎。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.ingestion.importer import ScanImporter
from app.ingestion.protocol import ScanPayload
from app.models import FmSave, ImportJob, PlayerInstance, PlayerSnapshot, User
from app.quality.rules import run_quality_rules

from tests.helpers import player_row, scan_document


def _import(db, save, scan_id: str, when: datetime, players: list[dict]):
    payload = scan_document(scan_id=scan_id, when=when, players=players)
    ScanImporter(db).import_payload(save.id, ScanPayload.model_validate(payload))
    db.commit()


def _instance(db, save, uid: str) -> PlayerInstance:
    return db.scalar(select(PlayerInstance).where(PlayerInstance.fm_save_id == save.id, PlayerInstance.save_local_uid == uid))


def _clean(db, save) -> None:
    _import(
        db,
        save,
        "q-clean",
        datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
        [player_row("Q1", "Quality One", ca=140, pa=160)],
    )


def test_clean_save_has_no_findings(db, save) -> None:
    _clean(db, save)
    report = run_quality_rules(db, save.id)
    assert report["checked_snapshot_count"] == 1
    assert report["findings"] == []
    assert report["read_only"] is True


def test_missing_fields_and_negative_values(db, save) -> None:
    _clean(db, save)
    snapshot = db.scalar(select(PlayerSnapshot))
    snapshot.contract_end = None
    snapshot.market_value = None
    snapshot.wage = None
    db.commit()
    report = run_quality_rules(db, save.id)
    ids = {finding["rule_id"] for finding in report["findings"]}
    assert {"missing_contract", "missing_market_value", "missing_wage"} <= ids
    assert report["severity_counts"]["warning"] >= 1

    snapshot.ca = -3
    db.commit()
    report = run_quality_rules(db, save.id)
    assert any(finding["rule_id"] == "negative_value" for finding in report["findings"])


def test_same_day_duplicate_and_conflict(db, save) -> None:
    players = [player_row("Q2", "Quality Two", ca=100), player_row("Q3", "Quality Three", ca=110)]
    _import(db, save, "q-a", datetime(2026, 7, 1, 9, tzinfo=timezone.utc), players)
    _import(
        db, save, "q-b", datetime(2026, 7, 1, 20, tzinfo=timezone.utc),
        [player_row("Q2", "Quality Two", ca=105), player_row("Q3", "Quality Three", ca=110)],
    )
    report = run_quality_rules(db, save.id)
    by_rule = {finding["rule_id"]: finding for finding in report["findings"]}
    assert by_rule["duplicate_same_day"]["count"] == 2
    assert by_rule["same_day_conflict"]["count"] == 1, "只有 CA 变化的球员是冲突"
    assert by_rule["same_day_conflict"]["affected_player_count"] == 1


def test_stale_observation(db, save) -> None:
    _import(
        db, save, "q-stale", datetime(2026, 9, 1, 12, tzinfo=timezone.utc),
        [player_row("Q4", "Quality Four")],
    )
    snapshot = db.scalar(select(PlayerSnapshot))
    snapshot.game_date = datetime(2026, 1, 1).date()
    db.commit()
    report = run_quality_rules(db, save.id)
    assert any(finding["rule_id"] == "stale_observation" for finding in report["findings"])


def test_import_count_mismatch_and_unknown_source(db, save) -> None:
    _clean(db, save)
    job = db.scalar(select(ImportJob))
    snapshot = db.scalar(select(PlayerSnapshot))
    snapshot.import_job_id = None
    db.commit()
    full = run_quality_rules(db, save.id)
    assert "unknown_source" in {finding["rule_id"] for finding in full["findings"]}

    snapshot.import_job_id = job.id
    job.player_count = 99
    db.commit()
    report = run_quality_rules(db, save.id, import_job_id=job.id)
    assert "import_count_mismatch" in {finding["rule_id"] for finding in report["findings"]}


def test_cross_save_isolation(db, save) -> None:
    _clean(db, save)
    other_user = User(username="q-other", display_name="other")
    db.add(other_user)
    db.commit()
    other = FmSave(user_id=other_user.id, name="other", game_version="27.1", game_build="x", is_active=False)
    db.add(other)
    db.commit()
    _import(db, other, "q-other", datetime(2026, 7, 2, 12, tzinfo=timezone.utc), [player_row("Q9", "Other")])
    report = run_quality_rules(db, save.id)
    assert report["checked_snapshot_count"] == 1


def test_rules_do_not_modify_data(db, save) -> None:
    _clean(db, save)
    before = (
        db.query(PlayerSnapshot).count(),
        db.query(ImportJob).count(),
        db.query(PlayerInstance).count(),
    )
    run_quality_rules(db, save.id)
    db.expire_all()
    after = (
        db.query(PlayerSnapshot).count(),
        db.query(ImportJob).count(),
        db.query(PlayerInstance).count(),
    )
    assert before == after


def test_rule_catalog_and_api(client, db, save) -> None:
    _clean(db, save)
    rules = client.get("/api/v1/data-quality/rules")
    assert rules.status_code == 200
    assert rules.json()["total"] >= 10
    report = client.get("/api/v1/data-quality/report")
    assert report.status_code == 200
    assert report.json()["read_only"] is True
    job = db.scalar(select(ImportJob))
    assert client.get(f"/api/v1/data-quality/report?import_job_id={job.id}").status_code == 200


def test_foreign_import_job_is_404(client, db, save) -> None:
    other_user = User(username="q-foreign", display_name="foreign")
    db.add(other_user)
    db.commit()
    other = FmSave(user_id=other_user.id, name="foreign", game_version="27.1", game_build="x", is_active=False)
    db.add(other)
    db.commit()
    _import(db, other, "q-foreign", datetime(2026, 7, 3, 12, tzinfo=timezone.utc), [player_row("QF", "Foreign")])
    foreign_job = db.scalar(select(ImportJob).where(ImportJob.fm_save_id == other.id))
    assert client.get(f"/api/v1/data-quality/report?import_job_id={foreign_job.id}").status_code == 404
