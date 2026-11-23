"""SM-067：自动采集记录 API。"""

from __future__ import annotations

from app.models import CaptureRun, FmSave, User


def test_capture_register_update_and_summary(client, db, save) -> None:
    created = client.post(
        "/api/v1/captures",
        json={
            "game_date": "2026-07-14",
            "reader_version": "0.1.0",
            "game_build": "26620374",
            "scan_scope": "players",
            "status": "scanning",
            "scan_id": "scan-1",
        },
    )
    assert created.status_code == 201, created.text
    capture_id = created.json()["id"]
    assert created.json()["started_at"] is not None

    updated = client.patch(
        f"/api/v1/captures/{capture_id}",
        json={"status": "completed", "attempt_count": 1},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "completed"
    assert updated.json()["finished_at"] is not None

    again = client.post(
        "/api/v1/captures",
        json={
            "game_date": "2026-07-14",
            "reader_version": "0.1.0",
            "game_build": "26620374",
            "scan_scope": "players",
            "status": "completed",
        },
    )
    assert again.status_code == 201
    assert again.json()["id"] == capture_id, "同一幂等键更新原记录而不是新增"
    assert db.query(CaptureRun).count() == 1

    summary = client.get("/api/v1/captures/summary").json()
    assert summary["counts"]["completed"] == 1
    assert summary["latest"]["id"] == capture_id


def test_supplemental_revision_is_separate(client, db, save) -> None:
    base = {
        "game_date": "2026-07-14",
        "reader_version": "0.1.0",
        "scan_scope": "players",
        "status": "completed",
    }
    assert client.post("/api/v1/captures", json=base).status_code == 201
    supplemental = client.post("/api/v1/captures", json={**base, "revision": 1})
    assert supplemental.status_code == 201
    assert supplemental.json()["supplemental"] is True
    assert db.query(CaptureRun).count() == 2


def test_capture_is_save_scoped(client, db, save) -> None:
    other_user = User(username="capture-other", display_name="other")
    db.add(other_user)
    db.commit()
    other = FmSave(user_id=other_user.id, name="other", game_version="27.1", game_build="x", is_active=False)
    db.add(other)
    db.commit()
    db.add(CaptureRun(fm_save_id=other.id, game_date=None, scan_scope="players", status="failed", metadata_json="{}"))
    db.commit()
    listing = client.get("/api/v1/captures").json()
    assert listing["total"] == 0


def test_invalid_status_rejected(client, save) -> None:
    response = client.post("/api/v1/captures", json={"status": "whatever"})
    assert response.status_code == 422
