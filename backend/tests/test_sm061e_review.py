"""SM-061E：人工 canonical 决策与追加式审计。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.ingestion.importer import ScanImporter
from app.ingestion.protocol import ScanPayload
from app.models import (
    FmSave,
    PlayerInstance,
    PlayerObservationCanonical,
    PlayerObservationCanonicalAction,
    PlayerSnapshot,
    User,
)
from app.quality.dedup import build_canonicals
from app.quality.review import ReviewError, decide, history, review_queue

from tests.helpers import player_row, scan_document


def _import(db, save, scan_id: str, when: datetime, ca: int):
    payload = scan_document(scan_id=scan_id, when=when, players=[player_row("R1", "Review One", ca=ca)])
    ScanImporter(db).import_payload(save.id, ScanPayload.model_validate(payload))
    db.commit()


def _setup(db, save):
    _import(db, save, "r-a", datetime(2026, 7, 1, 9, tzinfo=timezone.utc), 100)
    _import(db, save, "r-b", datetime(2026, 7, 1, 20, tzinfo=timezone.utc), 105)
    build_canonicals(db, save.id, dry_run=False)
    return db.scalar(select(PlayerObservationCanonical).where(PlayerObservationCanonical.status == "needs_review"))


def test_queue_and_select_snapshot_with_audit(db, save) -> None:
    canonical = _setup(db, save)
    queue = review_queue(db, save.id, status="needs_review")
    assert queue["total"] == 1
    assert queue["items"][0]["player_name"] == "Review One"
    snapshots = list(db.scalars(select(PlayerSnapshot).order_by(PlayerSnapshot.id)))
    result = decide(
        db, save.id, canonical.id,
        reviewer_user_id=1, action="select_snapshot",
        selected_snapshot_id=snapshots[0].id, reason="界面确认第一条",
        evidence={"ui": "screenshot"},
    )
    assert result["canonical"]["status"] == "resolved_manual"
    assert result["canonical"]["canonical_snapshot_id"] == snapshots[0].id
    records = history(db, save.id, canonical.id)
    assert len(records["items"]) == 1
    assert records["items"][0]["previous_status"] == "needs_review"
    assert records["items"][0]["new_status"] == "resolved_manual"


def test_rescan_does_not_overwrite_manual_decision(db, save) -> None:
    canonical = _setup(db, save)
    snapshot = db.scalar(select(PlayerSnapshot).order_by(PlayerSnapshot.id))
    decide(db, save.id, canonical.id, reviewer_user_id=1, action="select_snapshot",
           selected_snapshot_id=snapshot.id, reason="人工确认")
    build_canonicals(db, save.id, dry_run=False)
    db.refresh(canonical)
    assert canonical.status == "resolved_manual"
    assert canonical.canonical_snapshot_id == snapshot.id
    assert db.query(PlayerObservationCanonicalAction).count() == 1


def test_duplicate_decision_is_rejected(db, save) -> None:
    canonical = _setup(db, save)
    snapshot = db.scalar(select(PlayerSnapshot).order_by(PlayerSnapshot.id))
    decide(db, save.id, canonical.id, reviewer_user_id=1, action="select_snapshot",
           selected_snapshot_id=snapshot.id, reason="确认")
    with pytest.raises(ReviewError) as exc:
        decide(db, save.id, canonical.id, reviewer_user_id=1, action="select_snapshot",
               selected_snapshot_id=snapshot.id, reason="确认")
    assert exc.value.code == "duplicate_decision"


def test_snapshot_must_belong_to_group(db, save) -> None:
    canonical = _setup(db, save)
    _import(db, save, "r-other", datetime(2026, 7, 2, 9, tzinfo=timezone.utc), 110)
    other_snapshot = db.scalar(select(PlayerSnapshot).where(PlayerSnapshot.game_date == datetime(2026, 7, 2).date()))
    with pytest.raises(ReviewError) as exc:
        decide(db, save.id, canonical.id, reviewer_user_id=1, action="select_snapshot",
               selected_snapshot_id=other_snapshot.id, reason="错的日期")
    assert exc.value.code == "snapshot_not_in_group"


def test_exclude_and_keep_pending(db, save) -> None:
    canonical = _setup(db, save)
    decide(db, save.id, canonical.id, reviewer_user_id=1, action="exclude_game_date", selected_snapshot_id=None, reason="数据异常")
    assert canonical.status == "excluded"
    decide(db, save.id, canonical.id, reviewer_user_id=1, action="keep_pending", selected_snapshot_id=None, reason="继续等待")
    assert canonical.status == "needs_review"
    assert db.query(PlayerObservationCanonicalAction).count() == 2


def test_cross_save_history_and_decision_are_404(db, save) -> None:
    canonical = _setup(db, save)
    other_user = User(username="review-other", display_name="other")
    db.add(other_user)
    db.commit()
    other = FmSave(user_id=other_user.id, name="other", game_version="27.1", game_build="x", is_active=False)
    db.add(other)
    db.commit()
    with pytest.raises(ReviewError) as exc:
        history(db, other.id, canonical.id)
    assert exc.value.status_code == 404


def test_api_review_flow(client, db, save) -> None:
    canonical = _setup(db, save)
    queue = client.get("/api/v1/data-quality/canonical/review-queue?status=needs_review")
    assert queue.status_code == 200
    assert queue.json()["total"] == 1
    snapshot_id = queue.json()["items"][0]["canonical_snapshot_id"]
    # canonical_snapshot_id is null for conflicts, select the first raw snapshot
    snapshot = db.scalar(select(PlayerSnapshot).order_by(PlayerSnapshot.id))
    response = client.post(
        f"/api/v1/data-quality/canonical/{canonical.id}/decision",
        json={"action": "select_snapshot", "selected_snapshot_id": snapshot.id, "reason": "API 确认"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["canonical"]["status"] == "resolved_manual"
    history = client.get(f"/api/v1/data-quality/canonical/{canonical.id}/history").json()
    assert history["items"][0]["action"] == "select_snapshot"


def test_canonical_detail_and_overview(client, db, save) -> None:
    _import(db, save, "r-detail-a", datetime(2026, 7, 1, 9, tzinfo=timezone.utc), 100)
    _import(db, save, "r-detail-b", datetime(2026, 7, 1, 20, tzinfo=timezone.utc), 105)
    build_canonicals(db, save.id, dry_run=False)
    canonical = db.scalar(select(PlayerObservationCanonical).where(PlayerObservationCanonical.status == "needs_review"))
    detail = client.get(f"/api/v1/data-quality/canonical/{canonical.id}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["canonical"]["player_name"] == "Review One"
    assert len(body["snapshots"]) == 2
    assert body["snapshots"][0]["attributes"] == []
    assert len(body["timeline"]) == 1
    overview = client.get("/api/v1/data-quality/governance/overview")
    assert overview.status_code == 200
    stats = overview.json()
    assert stats["canonical_groups"] == 1
    assert stats["needs_review"] == 1
    assert stats["total_snapshots"] == 2
