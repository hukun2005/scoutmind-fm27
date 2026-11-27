"""V3.3.2-07 A 方向：首次启动引导、数据中心、诊断修复、任务序列化与错误文案。

测试夹具产生的数据仅用于算法与接口验证，不代表真实 FM27 验收结果。
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import (
    BackgroundTask,
    Club,
    FmSave,
    ImportJob,
    Player,
    PlayerInstance,
    PlayerSnapshot,
    Transfer,
)
from app.services import user_experience
from app.utils import utcnow

API = "/api/v1"


def _club(db: Session, save: FmSave, *, name: str = "Alpha FC", uid: str = "club-1") -> Club:
    club = Club(fm_save_id=save.id, uid=uid, name=name)
    db.add(club)
    db.commit()
    return club


def _player(
    db: Session,
    save: FmSave,
    *,
    name: str = "UX Player",
    uid: str = "ux-1",
    club: Club | None = None,
    position: str = "ST",
) -> PlayerInstance:
    player = Player(full_name=name, normalized_name=name.lower())
    db.add(player)
    db.commit()
    instance = PlayerInstance(
        player_id=player.id,
        fm_save_id=save.id,
        save_local_uid=uid,
        club_id=club.id if club is not None else None,
        position=position,
    )
    db.add(instance)
    db.commit()
    snapshot = PlayerSnapshot(
        player_instance_id=instance.id,
        observed_at=utcnow(),
        game_date=date(2026, 7, 1),
        age=24,
        market_value=8_000_000,
        club_id=club.id if club is not None else None,
        position=position,
        source="fm27_live_reader",
    )
    db.add(snapshot)
    db.commit()
    instance.latest_snapshot_id = snapshot.id
    db.commit()
    return instance


def test_onboarding_empty_save(client: TestClient, save: FmSave) -> None:
    response = client.get(f"{API}/system/onboarding")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "needs_attention"
    assert body["data"]["has_players"] is False
    assert body["summary"]["player_count"] == 0
    actions = {item["key"]: item for item in body["actions"]}
    assert {"import", "scan", "data"} <= set(actions)
    assert actions["import"]["enabled"] is True
    # 普通用户可见文案不得包含内部堆栈或 SQL。
    raw = response.text.lower()
    assert "traceback" not in raw
    assert "select " not in raw


def test_onboarding_with_data(client: TestClient, db: Session, save: FmSave) -> None:
    club = _club(db, save)
    _player(db, save, club=club)
    body = client.get(f"{API}/system/onboarding").json()
    assert body["data"]["has_players"] is True
    assert body["data"]["player_count"] == 1
    assert body["data"]["club_count"] == 1
    assert body["summary"]["player_count"] == 1
    assert body["summary"]["save_status"] == "已有可用数据"
    actions = {item["key"]: item for item in body["actions"]}
    # 已有数据时不再要求重新导入。
    assert actions["import"]["enabled"] is False
    assert actions["scan"]["enabled"] is True


def test_onboarding_reports_recoverable_task(client: TestClient, db: Session, save: FmSave) -> None:
    db.add(
        BackgroundTask(
            task_id="task-running",
            fm_save_id=save.id,
            task_type="FULL_SCAN",
            lock_key="scan",
            status="RUNNING",
            total=1000,
            processed=20,
            started_at=utcnow(),
            heartbeat_at=utcnow(),
        )
    )
    db.commit()
    body = client.get(f"{API}/system/onboarding").json()
    assert body["data"]["recoverable_tasks"]
    assert body["data"]["recoverable_tasks"][0]["task_id"] == "task-running"


def test_data_health_shape_and_status(client: TestClient, db: Session, save: FmSave) -> None:
    club = _club(db, save)
    _player(db, save, club=club)
    body = client.get(f"{API}/system/data-health").json()
    assert {"save", "players", "clubs", "transfers", "opportunities", "status", "background", "can_repair"} <= set(body)
    assert body["status"]["level"] in {"ok", "warn", "error"}
    assert body["players"]["count"] == 1
    assert body["clubs"]["count"] == 1
    assert body["players"]["linked"] == 1
    assert body["players"]["unlinked"] == 0
    assert body["transfers"]["count"] == 0
    assert isinstance(body["notes"], list)


def test_diagnostics_is_read_only(client: TestClient, db: Session, save: FmSave) -> None:
    _player(db, save)
    before_imports = db.query(ImportJob).count()
    before_transfers = db.query(Transfer).count()
    first = client.post(f"{API}/system/diagnostics").json()
    second = client.post(f"{API}/system/diagnostics").json()
    assert first == second
    assert {"checks", "summary", "repairable"} <= set(first)
    assert "club_links" in first["repairable"]
    assert db.query(ImportJob).count() == before_imports
    assert db.query(Transfer).count() == before_transfers


def test_repair_only_safe_targets(client: TestClient, db: Session, save: FmSave) -> None:
    _player(db, save)
    players_before = db.query(PlayerInstance).count()
    body = client.post(
        f"{API}/system/repair",
        json={"targets": ["club_links", "player_identity"], "dry_run": False},
    ).json()
    executed = {item["target"] for item in body["executed"]}
    skipped = {item["target"] for item in body["skipped"]}
    assert executed == {"club_links"}
    assert "player_identity" in skipped
    assert any("不确定" in item["reason"] for item in body["skipped"])
    assert db.query(PlayerInstance).count() == players_before


def test_scan_serialization_stage_and_eta(client: TestClient, db: Session, save: FmSave) -> None:
    task = BackgroundTask(
        task_id="task-eta",
        fm_save_id=save.id,
        task_type="FULL_SCAN",
        lock_key="scan",
        status="RUNNING",
        total=1000,
        processed=100,
        started_at=utcnow() - timedelta(seconds=10),
        heartbeat_at=utcnow(),
    )
    db.add(task)
    db.commit()

    body = client.get(f"{API}/transfer-director/scans/task-eta").json()
    assert body["current_stage"]
    assert body["status_key"] == "RUNNING"
    assert body["eta_seconds"] is not None and body["eta_seconds"] > 0
    assert body["resumable"] is False
    assert body["heartbeat_at"] is not None

    # 样本不足以估算剩余时间时不编造 ETA。
    task.processed = 10
    task.total = 100
    db.commit()
    body = client.get(f"{API}/transfer-director/scans/task-eta").json()
    assert body["eta_seconds"] is None


def test_user_friendly_error_mapping() -> None:
    assert user_experience.friendly_message("database_busy") == "系统正在处理其他任务"
    assert user_experience.friendly_message("data_source_unavailable") == "暂时无法连接游戏数据"
    fallback = user_experience.friendly_message("unknown_internal_code")
    assert "SQL" not in fallback
    assert "Traceback" not in fallback
    assert fallback
