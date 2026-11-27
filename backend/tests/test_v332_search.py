"""V3.3.2 全局搜索：关注分类、位置/俱乐部/转会条件与存档隔离。"""

from __future__ import annotations

from app.ingestion.importer import ScanImporter
from app.ingestion.protocol import ScanPayload
from app.models import FmSave
from tests.helpers import RAW_DIR, club_row, import_document, player_row, scan_document, transfer_row


def _seed(db) -> None:
    players = [
        player_row("P1", "Mario Bianchi", ca=150, pa=170, position="ST", club_uid="C1"),
        player_row("P2", "Luca Verdi", ca=130, pa=150, position="GK", club_uid="C2"),
    ]
    transfers = [transfer_row("T1", "P1", "Mario Bianchi", fee=30_000_000, when="2026-07-01")]
    import_document(db, scan_document(players=players, transfers=transfers))


def test_player_search_matches_position_and_club_name(client, db, save) -> None:
    _seed(db)
    by_position = client.get("/api/v1/search", params={"q": "GK", "type": "players", "save_id": save.id}).json()
    assert [item["display_name"] for item in by_position["categories"]["players"]] == ["Luca Verdi"]

    by_club = client.get(
        "/api/v1/search", params={"q": "Northbridge", "type": "players", "save_id": save.id}
    ).json()
    assert [item["display_name"] for item in by_club["categories"]["players"]] == ["Mario Bianchi"]
    assert by_club["categories"]["players"][0]["meta"]["save_id"] == save.id


def test_club_search_matches_league(client, db, save) -> None:
    _seed(db)
    body = client.get("/api/v1/search", params={"q": "Premier Division", "type": "clubs", "save_id": save.id}).json()
    assert {item["display_name"] for item in body["categories"]["clubs"]} == {
        "Northbridge United",
        "Kingsport City",
    }


def test_transfer_search_matches_type_and_date(client, db, save) -> None:
    _seed(db)
    by_type = client.get(
        "/api/v1/search", params={"q": "permanent", "type": "transfers", "save_id": save.id}
    ).json()
    assert [item["display_name"] for item in by_type["categories"]["transfers"]] == ["Mario Bianchi"]

    by_date = client.get(
        "/api/v1/search", params={"q": "2026-07", "type": "transfers", "save_id": save.id}
    ).json()
    assert len(by_date["categories"]["transfers"]) == 1


def test_watchlist_category_lists_list_and_status(client, db, save) -> None:
    _seed(db)
    players = client.get("/api/v1/players", params={"query": "Mario", "save_id": save.id}).json()
    instance_id = players["items"][0]["instance_id"]
    created = client.post("/api/v1/watchlist/lists", json={"name": "重点观察"})
    assert created.status_code == 201, created.text
    added = client.post(
        "/api/v1/watchlist/items",
        json={
            "instance_id": instance_id,
            "list_id": created.json()["id"],
            "status": "preparing",
            "note": "左脚终结者",
        },
    )
    assert added.status_code == 201, added.text

    by_name = client.get(
        "/api/v1/search", params={"q": "Mario", "type": "watchlist", "save_id": save.id}
    ).json()
    item = by_name["categories"]["watchlist"][0]
    assert item["entity_type"] == "watchlist"
    assert item["meta"]["list_name"] == "重点观察"
    assert item["meta"]["status"] == "preparing"
    assert item["navigation_target"] == f"/players/{instance_id}"

    by_note = client.get(
        "/api/v1/search", params={"q": "左脚", "type": "watchlist", "save_id": save.id}
    ).json()
    assert len(by_note["categories"]["watchlist"]) == 1


def test_search_categories_are_save_scoped(client, db, save) -> None:
    _seed(db)
    players = client.get("/api/v1/players", params={"query": "Mario", "save_id": save.id}).json()
    client.post("/api/v1/watchlist/items", json={"instance_id": players["items"][0]["instance_id"]})

    other = FmSave(user_id=save.user_id, name="另一个存档", game_version="27.0", game_build="test", is_active=False)
    db.add(other)
    db.commit()
    ScanImporter(db, raw_dir=RAW_DIR).import_payload(
        other.id,
        ScanPayload.model_validate(
            scan_document(
                scan_id="scan-other",
                clubs=[club_row("C9", "隔离俱乐部")],
                players=[player_row("P9", "Mario Isolated", club_uid="C9")],
                transfers=[],
            )
        ),
    )
    db.commit()
    body = client.get("/api/v1/search", params={"q": "Mario", "save_id": save.id}).json()
    assert [item["display_name"] for item in body["categories"]["players"]] == ["Mario Bianchi"]
    assert [item["display_name"] for item in body["categories"]["watchlist"]] == ["Mario Bianchi"]
