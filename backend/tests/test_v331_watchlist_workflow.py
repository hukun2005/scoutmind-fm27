"""V3.3.1 P0-03 关注名单：多名单、状态、搜索、移动与存档隔离。"""

from __future__ import annotations

from datetime import date, datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Club, FmSave, Player, PlayerInstance, PlayerSnapshot


def _player(db: Session, save: FmSave, name: str, uid: str, **snapshot_fields) -> PlayerInstance:
    player = Player(full_name=name, normalized_name=name.lower(), birth_date=date(2002, 1, 1))
    db.add(player)
    db.flush()
    club = Club(fm_save_id=save.id, uid=f"club-{uid}", name="测试俱乐部")
    db.add(club)
    db.flush()
    instance = PlayerInstance(
        player_id=player.id,
        fm_save_id=save.id,
        save_local_uid=uid,
        uid_occurrence=0,
        club_id=club.id,
        position="ST",
    )
    db.add(instance)
    db.flush()
    db.add(
        PlayerSnapshot(
            player_instance_id=instance.id,
            observed_at=datetime(2026, 11, 1, 12, 0, 0),
            age=23,
            ca=150,
            pa=170,
            market_value=30_000_000,
            position="ST",
            source="test",
            **snapshot_fields,
        )
    )
    db.commit()
    return instance


def test_named_lists_status_search_and_move(client: TestClient, db: Session, save: FmSave) -> None:
    striker = _player(db, save, "Mario Rossi", "P-1")
    _player(db, save, "Luca Bianchi", "P-2")

    created = client.post("/api/v1/watchlist/lists", json={"name": "潜力新星"})
    assert created.status_code == 201, created.text
    list_id = created.json()["id"]

    duplicate = client.post("/api/v1/watchlist/lists", json={"name": "潜力新星"})
    assert duplicate.status_code == 400
    assert "同名" in duplicate.json()["error"]["message"]

    added = client.post(
        "/api/v1/watchlist/items",
        json={"instance_id": striker.id, "list_id": list_id, "status": "preparing", "tag": "核心培养", "note": "左脚中锋"},
    )
    assert added.status_code == 201, added.text
    item_id = added.json()["id"]
    assert added.json()["status"] == "preparing"

    again = client.post("/api/v1/watchlist/items", json={"instance_id": striker.id})
    assert again.status_code == 400
    assert "已在关注名单" in again.json()["error"]["message"]

    listing = client.get("/api/v1/watchlist", params={"list_id": list_id})
    assert listing.status_code == 200, listing.text
    body = listing.json()
    assert body["total"] == 1
    row = body["items"][0]
    assert row["list_id"] == list_id
    assert row["list_name"] == "潜力新星"
    assert row["status"] == "preparing"
    assert row["note"] == "左脚中锋"
    assert row["player"]["club"] == "测试俱乐部"
    assert {group["name"] for group in body["lists"]} >= {"默认关注", "潜力新星"}

    search = client.get("/api/v1/watchlist", params={"q": "mario"})
    assert search.status_code == 200
    assert [item["player"]["name"] for item in search.json()["items"]] == ["Mario Rossi"]
    missing = client.get("/api/v1/watchlist", params={"q": "nobody"})
    assert missing.json()["total"] == 0

    filtered = client.get("/api/v1/watchlist", params={"status": "watching"})
    assert filtered.json()["total"] == 0

    # 规则刷新只追加关注项，不覆盖用户备注与状态。
    refreshed = client.post("/api/v1/watchlist/refresh")
    assert refreshed.status_code == 200
    after = client.get("/api/v1/watchlist", params={"q": "Mario"})
    assert after.json()["items"][0]["note"] == "左脚中锋"

    default_id = next(group["id"] for group in body["lists"] if group["is_default"])
    moved = client.patch(f"/api/v1/watchlist/items/{item_id}", json={"list_id": default_id, "status": "paused"})
    assert moved.status_code == 200, moved.text
    assert moved.json()["list_id"] == default_id
    assert moved.json()["status"] == "paused"
    assert moved.json()["note"] == "左脚中锋"

    bad_status = client.patch(f"/api/v1/watchlist/items/{item_id}", json={"status": "unknown"})
    assert bad_status.status_code == 422


def test_watchlist_is_isolated_between_saves(client: TestClient, db: Session, save: FmSave) -> None:
    striker = _player(db, save, "Mario Rossi", "P-1")
    other = FmSave(user_id=save.user_id, name="另一个存档", is_active=False)
    db.add(other)
    db.commit()

    assert client.post("/api/v1/watchlist/items", json={"instance_id": striker.id}).status_code == 201

    foreign = client.get("/api/v1/watchlist", params={"save_id": other.id})
    assert foreign.status_code == 200
    assert foreign.json()["total"] == 0

    # 另一个存档的名单不能接收本存档的球员实例。
    from app.models import Watchlist

    foreign_list = Watchlist(user_id=other.user_id, fm_save_id=other.id, name="外部名单")
    db.add(foreign_list)
    db.commit()
    cross = client.post("/api/v1/watchlist/items", json={"instance_id": striker.id, "list_id": foreign_list.id})
    assert cross.status_code == 400
    assert "关注名单不存在" in cross.json()["error"]["message"]
