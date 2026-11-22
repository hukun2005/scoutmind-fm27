"""SM-061B：同日重复/冲突的 canonical 治理（不删除原始快照）。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.ingestion.importer import ScanImporter
from app.ingestion.protocol import ScanPayload
from app.models import FmSave, PlayerInstance, PlayerObservationCanonical, PlayerSnapshot, User
from app.quality.dedup import build_canonicals, canonical_summary

from tests.helpers import player_row, scan_document


def _import(db, save, scan_id: str, when: datetime, players: list[dict]):
    payload = scan_document(scan_id=scan_id, when=when, players=players)
    ScanImporter(db).import_payload(save.id, ScanPayload.model_validate(payload))
    db.commit()


def _setup(db, save):
    players = [
        player_row("D1", "Duplicate Identical", ca=100, wage=1000),
        player_row("D2", "Duplicate Conflict", ca=110, wage=1000),
    ]
    _import(db, save, "dedup-a", datetime(2026, 7, 1, 9, tzinfo=timezone.utc), players)
    _import(
        db, save, "dedup-b", datetime(2026, 7, 1, 20, tzinfo=timezone.utc),
        [
            player_row("D1", "Duplicate Identical", ca=100, wage=1000),
            player_row("D2", "Duplicate Conflict", ca=115, wage=1500),
        ],
    )
    return (
        db.scalar(select(PlayerInstance).where(PlayerInstance.save_local_uid == "D1")),
        db.scalar(select(PlayerInstance).where(PlayerInstance.save_local_uid == "D2")),
    )


def test_dry_run_writes_nothing(db, save) -> None:
    _setup(db, save)
    before = db.query(PlayerObservationCanonical).count()
    result = build_canonicals(db, save.id, dry_run=True)
    assert result["groups"] == 2
    assert result["resolved"] == 1
    assert result["needs_review"] == 1
    assert result["duplicate_rows"] == 2
    assert db.query(PlayerObservationCanonical).count() == before


def test_identical_duplicate_resolves_latest_conflict_needs_review(db, save) -> None:
    d1, d2 = _setup(db, save)
    result = build_canonicals(db, save.id, dry_run=False)
    assert result["written"] == 2
    rows = {
        row.player_instance_id: row
        for row in db.scalars(select(PlayerObservationCanonical))
    }
    assert rows[d1.id].status == "resolved"
    assert rows[d1.id].conflict is False
    assert rows[d1.id].canonical_snapshot_id is not None
    latest = db.scalar(
        select(PlayerSnapshot)
        .where(PlayerSnapshot.player_instance_id == d1.id)
        .order_by(PlayerSnapshot.observed_at.desc(), PlayerSnapshot.id.desc())
    )
    assert rows[d1.id].canonical_snapshot_id == latest.id
    assert rows[d2.id].status == "needs_review"
    assert rows[d2.id].conflict is True
    assert rows[d2.id].canonical_snapshot_id is None
    assert db.query(PlayerSnapshot).count() == 4, "原始快照一条都不能删除"


def test_rerun_is_idempotent(db, save) -> None:
    _setup(db, save)
    build_canonicals(db, save.id, dry_run=False)
    first = db.query(PlayerObservationCanonical).count()
    build_canonicals(db, save.id, dry_run=False)
    assert db.query(PlayerObservationCanonical).count() == first


def test_cross_save_isolated(db, save) -> None:
    _setup(db, save)
    other_user = User(username="dedup-other", display_name="other")
    db.add(other_user)
    db.commit()
    other = FmSave(user_id=other_user.id, name="other", game_version="27.1", game_build="x", is_active=False)
    db.add(other)
    db.commit()
    _import(db, other, "dedup-other", datetime(2026, 7, 2, 12, tzinfo=timezone.utc), [player_row("DO", "Other")])
    result = build_canonicals(db, other.id, dry_run=False)
    assert result["groups"] == 1
    assert all(row.fm_save_id == other.id for row in db.scalars(select(PlayerObservationCanonical)))


def test_api_dry_run_and_write(client, db, save) -> None:
    _setup(db, save)
    preview = client.post("/api/v1/data-quality/canonical/scan")
    assert preview.status_code == 200
    assert preview.json()["dry_run"] is True
    assert db.query(PlayerObservationCanonical).count() == 0
    written = client.post("/api/v1/data-quality/canonical/scan?dry_run=false")
    assert written.status_code == 200
    assert written.json()["written"] == 2
    summary = client.get("/api/v1/data-quality/canonical/summary").json()
    assert summary["resolved"] == 1
    assert summary["needs_review"] == 1
    listing = client.get("/api/v1/data-quality/canonical?status=needs_review").json()
    assert listing["total"] == 1
    assert listing["items"][0]["canonical_snapshot_id"] is None
