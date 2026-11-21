"""SM-032：全 API 存档权限回归（ID 读写类接口）。"""

from __future__ import annotations

from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import (
    Alert,
    Club,
    FmSave,
    Player,
    PlayerInstance,
    PlayerSnapshot,
    User,
    Watchlist,
    WatchlistItem,
)


def _other_save(db) -> FmSave:
    user = User(username="intruder-sm032", display_name="别人")
    db.add(user)
    db.commit()
    save = FmSave(user_id=user.id, name="别人的存档", game_version="27.1", game_build="x", is_active=True)
    db.add(save)
    db.commit()
    return save


def _player(db, save, uid: str):
    player = Player(full_name=f"Isolation {uid}", normalized_name=f"isolation-{uid.lower()}")
    db.add(player)
    db.commit()
    instance = PlayerInstance(player_id=player.id, fm_save_id=save.id, save_local_uid=uid, position="ST")
    db.add(instance)
    db.commit()
    db.add(
        PlayerSnapshot(
            player_instance_id=instance.id,
            observed_at=datetime(2026, 7, 1, 12),
            game_date=date(2026, 7, 1),
            age=23,
            ca=140,
            pa=160,
            market_value=5_000_000,
            wage=10_000,
            source="manual",
        )
    )
    db.commit()
    return instance


def _club(db, save, name: str) -> Club:
    club = Club(fm_save_id=save.id, uid="club-" + name.lower().replace(" ", "-"), name=name)
    db.add(club)
    db.commit()
    return club


def _watch_item(db, save, instance) -> WatchlistItem:
    user = db.get(User, save.user_id)
    watchlist = Watchlist(user_id=user.id, fm_save_id=save.id, name="默认关注")
    db.add(watchlist)
    db.commit()
    item = WatchlistItem(watchlist_id=watchlist.id, player_instance_id=instance.id, tag="test")
    db.add(item)
    db.commit()
    return item


def _alert(db, save, instance) -> Alert:
    alert = Alert(
        fm_save_id=save.id,
        player_instance_id=instance.id,
        alert_type="contract",
        severity="info",
        title="测试提醒",
        message="测试",
    )
    db.add(alert)
    db.commit()
    return alert


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/players/{instance_id}",
        "/api/v1/players/{instance_id}/history",
        "/api/v1/players/{instance_id}/status",
        "/api/v1/players/{instance_id}/development",
        "/api/v1/development/player/{instance_id}",
        "/api/v1/performance/player/{instance_id}",
    ],
)
def test_foreign_player_reads_are_404(client: TestClient, db, save, path: str) -> None:
    foreign = _other_save(db)
    instance = _player(db, foreign, "F1")
    assert client.get(path.format(instance_id=instance.id)).status_code == 404


def test_foreign_scouting_evaluate_is_404(client: TestClient, db, save) -> None:
    foreign = _other_save(db)
    instance = _player(db, foreign, "F2")
    response = client.post(
        "/api/v1/scouting/evaluate",
        json={"instance_id": instance.id, "role_key": "st_advanced_forward"},
    )
    assert response.status_code == 404


def test_foreign_user_club_read_write_delete_are_404(client: TestClient, db, save) -> None:
    foreign = _other_save(db)
    club = _club(db, foreign, "Foreign Club")
    assert client.get(f"/api/v1/saves/{foreign.id}/user-club").status_code == 404
    assert client.put(f"/api/v1/saves/{foreign.id}/user-club", json={"club_id": club.id}).status_code == 404
    assert client.delete(f"/api/v1/saves/{foreign.id}/user-club").status_code == 404


def test_foreign_watch_item_patch_and_delete_are_404(client: TestClient, db, save) -> None:
    foreign = _other_save(db)
    instance = _player(db, foreign, "F3")
    item = _watch_item(db, foreign, instance)
    assert client.patch(f"/api/v1/watchlist/items/{item.id}", json={"tag": "hacked"}).status_code == 404
    assert client.delete(f"/api/v1/watchlist/items/{item.id}").status_code == 404
    db.expire_all()
    assert db.get(WatchlistItem, item.id).tag == "test"


def test_foreign_alert_read_is_404(client: TestClient, db, save) -> None:
    foreign = _other_save(db)
    instance = _player(db, foreign, "F4")
    alert = _alert(db, foreign, instance)
    assert client.post(f"/api/v1/alerts/{alert.id}/read").status_code == 404
    db.expire_all()
    assert db.get(Alert, alert.id).read_at is None


def test_foreign_club_profile_is_404(client: TestClient, db, save) -> None:
    foreign = _other_save(db)
    club = _club(db, foreign, "Foreign Profile")
    assert client.get(f"/api/v1/clubs/{club.id}/transfer-profile").status_code == 404


def test_own_reads_still_work(client: TestClient, db, save) -> None:
    instance = _player(db, save, "OWN")
    club = _club(db, save, "Own Club")
    item = _watch_item(db, save, instance)
    alert = _alert(db, save, instance)
    assert client.get(f"/api/v1/players/{instance.id}").status_code == 200
    assert client.get(f"/api/v1/players/{instance.id}/history").status_code == 200
    assert client.post(
        "/api/v1/scouting/evaluate", json={"instance_id": instance.id, "role_key": "st_advanced_forward"}
    ).status_code == 200
    assert client.get(f"/api/v1/saves/{save.id}/user-club").status_code == 200
    assert client.put(f"/api/v1/saves/{save.id}/user-club", json={"club_id": club.id}).status_code == 200
    assert client.patch(f"/api/v1/watchlist/items/{item.id}", json={"tag": "own"}).status_code == 200
    assert client.post(f"/api/v1/alerts/{alert.id}/read").status_code == 204
    assert client.get(f"/api/v1/clubs/{club.id}/transfer-profile").status_code == 200

def test_foreign_transfer_instance_endpoints_are_404(client: TestClient, db, save) -> None:
    foreign = _other_save(db)
    instance = _player(db, foreign, "F5")
    assert client.get(f"/api/v1/transfers/similar?instance_id={instance.id}").status_code == 404
    assert client.get(f"/api/v1/transfers/valuation?instance_id={instance.id}").status_code == 404
    assert client.get(f"/api/v1/scouting/rank?instance_id={instance.id}").status_code == 404


def test_own_transfer_instance_endpoints_still_work(client: TestClient, db, save) -> None:
    instance = _player(db, save, "OWN2")
    assert client.get(f"/api/v1/transfers/valuation?instance_id={instance.id}").status_code == 200
    assert client.get(f"/api/v1/scouting/rank?instance_id={instance.id}").status_code == 200
