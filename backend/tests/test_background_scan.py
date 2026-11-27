"""V3.3.2-05.2 后台扫描任务：持久化、执行、进度、取消、重试、恢复与并发保护。"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.db import SessionLocal
from app.models import (
    BackgroundTask,
    Club,
    FmSave,
    Player,
    PlayerAvailability,
    PlayerInstance,
    PlayerSnapshot,
    TransferOpportunity,
)
from app.services import background_scan, transfer_radar
from app.utils import utcnow

_counter = {"n": 0}


def _club(db, save: FmSave, name: str = "Task FC") -> Club:
    _counter["n"] += 1
    club = Club(fm_save_id=save.id, uid=f"task-club-{_counter['n']}", name=name)
    db.add(club)
    db.commit()
    return club


def _seed(db, save: FmSave, club: Club, *, count: int = 3, prefix: str = "t") -> list[PlayerInstance]:
    instances = []
    for index in range(count):
        _counter["n"] += 1
        player = Player(full_name=f"{prefix}-{index}", normalized_name=f"{prefix}-{index}-{_counter['n']}")
        db.add(player)
        db.flush()
        instance = PlayerInstance(
            player_id=player.id, fm_save_id=save.id, save_local_uid=f"{prefix}-{index}", club_id=club.id
        )
        db.add(instance)
        db.flush()
        snapshot = PlayerSnapshot(
            player_instance_id=instance.id,
            observed_at=utcnow(),
            game_date=date(2026, 7, 1),
            age=25,
            ca=140,
            pa=160,
            market_value=10_000_000,
            wage=20_000,
            contract_end=date(2026, 12, 31),
            club_id=club.id,
            club_uid=club.uid,
            position="ST",
            source="test",
        )
        db.add(snapshot)
        db.flush()
        instance.latest_snapshot_id = snapshot.id
        db.add(
            PlayerAvailability(
                player_instance_id=instance.id,
                observed_at=utcnow(),
                listed=True,
                loan_listed=False,
                set_for_release=False,
                source="test",
            )
        )
        instances.append(instance)
    db.commit()
    return instances


def _fresh(db) -> None:
    db.expire_all()


def test_create_task_dedupes_active_task(db, save: FmSave) -> None:
    task, reused = background_scan.create_task(db, save.id, background_scan.FULL_SCAN, autostart=False)
    assert reused is False
    assert task["status"] == "PENDING"
    again, reused_again = background_scan.create_task(db, save.id, background_scan.RECOVERY_SCAN, autostart=False)
    assert reused_again is True
    assert again["task_id"] == task["task_id"]
    assert again["task_type"] == background_scan.FULL_SCAN


def test_run_full_scan_task_reports_progress_and_completion(db, save: FmSave) -> None:
    club = _club(db, save)
    _seed(db, save, club, count=4)
    task, _ = background_scan.create_task(db, save.id, background_scan.FULL_SCAN, autostart=False)
    background_scan._run_task(task["task_id"])
    _fresh(db)
    finished = background_scan.get_task(db, save.id, task["task_id"])
    assert finished["status"] == "COMPLETED"
    assert finished["progress"] == 100.0
    assert finished["processed"] == 4
    assert finished["total"] >= 4
    assert finished["matched"] > 0
    assert finished["result"]["mode"] == "full"
    assert finished["started_at"] and finished["finished_at"]
    assert db.scalars(
        select(TransferOpportunity).where(TransferOpportunity.fm_save_id == save.id)
    ).all()


def test_incremental_task_uses_last_scan_checkpoint(db, save: FmSave) -> None:
    club = _club(db, save)
    _seed(db, save, club, count=3)
    full, _ = background_scan.create_task(db, save.id, background_scan.FULL_SCAN, autostart=False)
    background_scan._run_task(full["task_id"])
    _fresh(db)
    _seed(db, save, club, count=1, prefix="new")
    incremental, reused = background_scan.create_task(
        db, save.id, background_scan.INCREMENTAL_SCAN, autostart=False
    )
    assert reused is False
    background_scan._run_task(incremental["task_id"])
    _fresh(db)
    finished = background_scan.get_task(db, save.id, incremental["task_id"])
    assert finished["status"] == "COMPLETED"
    assert finished["result"]["mode"] == "incremental"
    assert finished["result"]["incremental_available"] is True
    assert finished["processed"] == 1


def test_club_link_repair_task_completes(db, save: FmSave) -> None:
    club = _club(db, save)
    instance = _seed(db, save, club, count=1)[0]
    instance.club_id = None
    db.commit()
    task, _ = background_scan.create_task(db, save.id, background_scan.CLUB_LINK_REPAIR, autostart=False)
    background_scan._run_task(task["task_id"])
    _fresh(db)
    finished = background_scan.get_task(db, save.id, task["task_id"])
    assert finished["status"] == "COMPLETED"
    assert finished["matched"] == 1
    assert db.get(PlayerInstance, instance.id).club_id == club.id


def test_task_failure_is_recorded_with_user_safe_message(db, save: FmSave, monkeypatch) -> None:
    def boom(*_args, **_kwargs):
        raise RuntimeError("internal stack trace that users must not see")

    monkeypatch.setattr(transfer_radar, "scan_batched", boom)
    task, _ = background_scan.create_task(db, save.id, background_scan.FULL_SCAN, autostart=False)
    background_scan._run_task(task["task_id"])
    _fresh(db)
    failed = background_scan.get_task(db, save.id, task["task_id"])
    assert failed["status"] == "FAILED"
    assert failed["error_code"] == "internal_error"
    assert "stack trace" not in (failed["error_message"] or "")
    assert failed["finished_at"]


def test_operational_error_retries_once_then_fails(db, save: FmSave, monkeypatch) -> None:
    submitted: list[str] = []

    def locked(*_args, **_kwargs):
        raise OperationalError("select 1", {}, Exception("database is locked"))

    monkeypatch.setattr(transfer_radar, "scan_batched", locked)
    monkeypatch.setattr(background_scan, "_submit", lambda task_id: submitted.append(task_id))
    task, _ = background_scan.create_task(db, save.id, background_scan.FULL_SCAN, autostart=False)
    background_scan._run_task(task["task_id"])
    _fresh(db)
    retried = background_scan.get_task(db, save.id, task["task_id"])
    assert retried["status"] == "PENDING"
    assert retried["error_code"] == "database_busy"
    assert submitted == [task["task_id"]]
    background_scan._run_task(task["task_id"])
    _fresh(db)
    failed = background_scan.get_task(db, save.id, task["task_id"])
    assert failed["status"] == "FAILED"
    assert failed["attempt_count"] == 2
    assert "locked" not in (failed["error_message"] or "")


def test_cancel_is_idempotent_and_terminal_tasks_stay_terminal(db, save: FmSave) -> None:
    club = _club(db, save)
    _seed(db, save, club, count=2)
    task, _ = background_scan.create_task(db, save.id, background_scan.FULL_SCAN, autostart=False)
    cancelled = background_scan.cancel_task(db, save.id, task["task_id"])
    assert cancelled["status"] == "CANCELLING"
    again = background_scan.cancel_task(db, save.id, task["task_id"])
    assert again["status"] == "CANCELLING"

    background_scan._run_task(task["task_id"])  # 非 PENDING，不会启动
    db.expire_all()
    raw = db.scalar(select(BackgroundTask).where(BackgroundTask.task_id == task["task_id"]))
    raw.status = "COMPLETED"
    db.commit()
    terminal = background_scan.cancel_task(db, save.id, task["task_id"])
    assert terminal["status"] == "COMPLETED"
    assert background_scan.cancel_task(db, save.id, "missing-task") is None


def test_cancelled_scan_saves_checkpoint(db, save: FmSave, monkeypatch) -> None:
    task, _ = background_scan.create_task(db, save.id, background_scan.FULL_SCAN, autostart=False)
    task_id = task["task_id"]

    def fake_scan(session, save_id, **kwargs):
        kwargs["progress_cb"](10, 100, 5, 0, 7)
        side = SessionLocal()
        try:
            background_scan.cancel_task(side, save_id, task_id)
        finally:
            side.close()
        assert kwargs["cancel_cb"]() is True
        raise transfer_radar.ScanCancelled(
            {"last_instance_id": 7, "token": task_id, "mode": "full", "processed": 10, "total": 100}
        )

    monkeypatch.setattr(transfer_radar, "scan_batched", fake_scan)
    background_scan._run_task(task_id)
    _fresh(db)
    cancelled = background_scan.get_task(db, save.id, task_id)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["checkpoint"]["last_instance_id"] == 7
    assert cancelled["progress"] == 10.0


def test_recover_resumes_checkpoint_or_marks_partial(db, save: FmSave, monkeypatch) -> None:
    submitted: list[str] = []
    monkeypatch.setattr(background_scan, "_submit", lambda task_id: submitted.append(task_id))
    resumable, _ = background_scan.create_task(db, save.id, background_scan.FULL_SCAN, autostart=False)
    raw = db.scalar(select(BackgroundTask).where(BackgroundTask.task_id == resumable["task_id"]))
    raw.status = "RUNNING"
    raw.checkpoint_json = '{"last_instance_id": 42, "token": "abc"}'
    db.commit()

    other = FmSave(user_id=save.user_id, name="另一个存档", game_version="27.0", game_build="test")
    db.add(other)
    db.commit()
    broken, _ = background_scan.create_task(db, other.id, background_scan.FULL_SCAN, autostart=False)
    raw_broken = db.scalar(select(BackgroundTask).where(BackgroundTask.task_id == broken["task_id"]))
    raw_broken.status = "RUNNING"
    db.commit()

    recovered = background_scan.recover(SessionLocal)
    assert recovered >= 2
    db.expire_all()
    resumed = db.scalar(select(BackgroundTask).where(BackgroundTask.task_id == resumable["task_id"]))
    assert resumed.status == "PENDING"
    assert submitted == [resumable["task_id"]]
    stopped = db.scalar(select(BackgroundTask).where(BackgroundTask.task_id == broken["task_id"]))
    assert stopped.status == "PARTIAL"
    assert stopped.error_code == "app_restart"


def test_save_isolation_for_tasks(db, save: FmSave) -> None:
    other = FmSave(user_id=save.user_id, name="另一个存档", game_version="27.0", game_build="test")
    db.add(other)
    db.commit()
    first, reused_a = background_scan.create_task(db, save.id, background_scan.FULL_SCAN, autostart=False)
    second, reused_b = background_scan.create_task(db, other.id, background_scan.FULL_SCAN, autostart=False)
    assert reused_a is False and reused_b is False
    assert first["task_id"] != second["task_id"]
    listing_a = background_scan.list_tasks(db, save.id)
    listing_b = background_scan.list_tasks(db, other.id)
    assert [item["task_id"] for item in listing_a["items"]] == [first["task_id"]]
    assert [item["task_id"] for item in listing_b["items"]] == [second["task_id"]]


def test_scan_task_api(client, db, save: FmSave, monkeypatch) -> None:
    monkeypatch.setattr(background_scan, "_submit", lambda task_id: None)
    club = _club(db, save)
    _seed(db, save, club, count=2)

    created = client.post("/api/v1/transfer-director/scans", json={"task_type": "FULL_SCAN"})
    assert created.status_code == 202, created.text
    body = created.json()
    assert body["reused"] is False
    task_id = body["task"]["task_id"]

    reused = client.post("/api/v1/transfer-director/scans", json={"task_type": "FULL_SCAN"})
    assert reused.status_code == 202 and reused.json()["reused"] is True

    detail = client.get(f"/api/v1/transfer-director/scans/{task_id}")
    assert detail.status_code == 200 and detail.json()["status"] == "PENDING"
    listing = client.get("/api/v1/transfer-director/scans", params={"active_only": True})
    assert listing.status_code == 200 and listing.json()["total"] == 1

    cancelled = client.post(f"/api/v1/transfer-director/scans/{task_id}/cancel")
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "CANCELLING"
    assert client.get("/api/v1/transfer-director/scans/unknown").status_code == 404
    assert client.post("/api/v1/transfer-director/scans/unknown/cancel").status_code == 404
