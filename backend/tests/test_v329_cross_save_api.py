"""V3.2.9 Phase 4/9：跨存档候选、存档隔离与身份中心 API 测试。"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.models import (
    CrossSaveIdentityCandidate,
    FmSave,
    PlayerIdentityLink,
    PlayerIdentityReviewItem,
)
from app.services import identity_engine
from app.services.uid_scope import summary as uid_summary

from tests.v329_helpers import make_instance


def _second_save(db, save, name="Save B") -> FmSave:
    other = FmSave(user_id=save.user_id, name=name, game_build="26620374", is_active=False)
    db.add(other)
    db.flush()
    return other


def test_cross_save_candidates_use_name_and_birth(db, save) -> None:
    make_instance(db, save, uid="X1", name="Real Person", birth=date(1998, 4, 4))
    other = _second_save(db, save)
    make_instance(db, other, uid="Y9", name="Real Person", birth=date(1998, 4, 4))
    make_instance(db, other, uid="Y8", name="Real Person", birth=date(1980, 1, 1))

    candidates = identity_engine.find_cross_save_candidates(db, save.id, other.id)
    assert len(candidates) == 2
    by_status = {row.status for row in candidates}
    assert "CrossSaveCandidate" in by_status
    assert "CrossSaveConflicted" in by_status
    matched = next(row for row in candidates if row.status == "CrossSaveCandidate")
    assert matched.match_score == 0.9
    assert matched.uid_equal is False


def test_same_uid_across_saves_is_evidence_not_identity(db, save) -> None:
    make_instance(db, save, uid="SHARED", name="Different One", birth=date(1990, 1, 1))
    other = _second_save(db, save)
    make_instance(db, other, uid="SHARED", name="Different Two", birth=date(1991, 2, 2))

    assert identity_engine.find_cross_save_candidates(db, save.id, other.id) == []
    assert uid_summary(db, save.id)["duplicate_uid_count"] == 0
    assert db.scalar(select(CrossSaveIdentityCandidate)) is None


def test_save_isolation_and_stale_links(db, save) -> None:
    left = make_instance(db, save, uid="ISO1", name="Isolated Person", birth=date(1995, 5, 5))
    other = _second_save(db, save)
    right = make_instance(db, other, uid="ISO2", name="Other Person", birth=date(1995, 5, 5))

    identity_engine._write_link(
        db,
        save_id=save.id,
        canonical_player_id=left.player_id,
        instance=left,
        status="Candidate",
        confidence=0.6,
        evidence={},
    )
    identity_engine._write_link(
        db,
        save_id=other.id,
        canonical_player_id=right.player_id,
        instance=right,
        status="Candidate",
        confidence=0.6,
        evidence={},
    )
    db.commit()

    marked = identity_engine.mark_save_links_stale(db, save.id, reason="save_switch")
    assert marked == 1
    stale = db.scalar(select(PlayerIdentityLink).where(PlayerIdentityLink.fm_save_id == save.id))
    untouched = db.scalar(select(PlayerIdentityLink).where(PlayerIdentityLink.fm_save_id == other.id))
    assert stale.verification_status == "Stale"
    assert stale.valid_to is not None
    assert untouched.verification_status == "Candidate"
    assert untouched.valid_to is None


def test_cross_save_api_generate_and_review(client, db, save) -> None:
    make_instance(db, save, uid="API1", name="Api Person", birth=date(1997, 7, 7))
    other = _second_save(db, save, name="API B")
    make_instance(db, other, uid="API2", name="Api Person", birth=date(1997, 7, 7))
    db.commit()

    generated = client.get(f"/api/v1/identity/center/cross-save?other_save_id={other.id}&generate=true")
    assert generated.status_code == 200, generated.text
    items = generated.json()["items"]
    assert len(items) == 1
    candidate_id = items[0]["id"]

    reviewed = client.post(
        f"/api/v1/identity/center/cross-save/{candidate_id}/review",
        json={"decision": "same", "note": "人工核对为同一人"},
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["status"] == "CrossSaveMatched"

    links = list(db.scalars(select(PlayerIdentityLink)))
    assert {row.fm_save_id for row in links} == {save.id, other.id}
    assert {row.verification_status for row in links} == {"ConfirmedByHuman"}

    again = client.post(
        f"/api/v1/identity/center/cross-save/{candidate_id}/review", json={"decision": "different"}
    )
    assert again.status_code == 409


def test_scan_api_lifecycle(client, db, save) -> None:
    for index in range(3):
        make_instance(db, save, uid=f"SC{index}", name=f"Scan Player {index}")
    db.commit()

    created = client.post(
        "/api/v1/identity/scans",
        json={"scan_id": "api-scan-1", "batch_size": 1, "max_batches": 1},
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["status"] == "Paused"
    assert body["processed_count"] == 1

    listed = client.get("/api/v1/identity/scans")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["scan_id"] == "api-scan-1"

    resumed = client.post("/api/v1/identity/scans/api-scan-1/resume", json={})
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["status"] == "Completed"

    detail = client.get("/api/v1/identity/scans/api-scan-1")
    assert detail.json()["processed_count"] == 3

    cancelled = client.post("/api/v1/identity/scans/api-scan-1/cancel")
    assert cancelled.json()["status"] == "Completed"  # 已完成批次不会被“取消”改写


def test_summary_uid_map_and_player_detail_api(client, db, save) -> None:
    instance = make_instance(db, save, uid="UID-77", name="Detail Person", birth=date(1994, 3, 3))
    db.commit()
    client.post("/api/v1/identity/scans", json={"scan_id": "detail-scan"})

    summary = client.get("/api/v1/identity/center/summary")
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["player_instances"] == 1
    assert body["uid"]["distinct_save_local_uids"] == 1

    uid_map = client.get("/api/v1/identity/center/uid-map?uid=UID-77")
    assert uid_map.status_code == 200
    assert uid_map.json()["total"] == 1
    assert uid_map.json()["items"][0]["status"] == "Valid"

    detail = client.get(f"/api/v1/identity/center/players/{instance.player_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["instances"][0]["save_local_uid"] == "UID-77"
    assert detail.json()["links"]

    other = _second_save(db, save)
    db.commit()
    hidden = client.get(f"/api/v1/identity/center/players/{instance.player_id}?save_id={other.id}")
    assert hidden.status_code == 404


def test_scan_creating_review_is_visible_in_queue_api(client, db, save) -> None:
    make_instance(db, save, uid="Q1", name="Queue Person", birth=date(1995, 1, 1))
    make_instance(db, save, uid="Q2", name="Queue Person", birth=date(1985, 1, 1))
    db.commit()
    client.post("/api/v1/identity/scans", json={"scan_id": "queue-scan"})

    queue = client.get("/api/v1/identity/center/queue")
    assert queue.status_code == 200
    assert queue.json()["counts"].get("PendingHumanReview", 0) == 1
    types = {item["item_type"] for item in queue.json()["items"]}
    assert "same_name" in types
    assert db.scalar(select(PlayerIdentityReviewItem)) is not None
