"""V3.3.1 全局搜索：三类实体、字面量 LIKE、存档隔离与参数边界。"""

from __future__ import annotations

from app.ingestion.importer import ScanImporter
from app.ingestion.protocol import ScanPayload
from app.models import FmSave

from tests.helpers import RAW_DIR, club_row, import_document, player_row, scan_document, transfer_row


def _seed(db) -> None:
    players = [
        player_row("P1", "Mario Bianchi", ca=150, pa=170, club_uid="C1"),
        player_row("P2", "Luca Verdi", ca=130, pa=150, club_uid="C2"),
    ]
    transfers = [transfer_row("T1", "P1", "Mario Bianchi", fee=30_000_000)]
    import_document(db, scan_document(players=players, transfers=transfers))


def test_empty_query_returns_empty_categories(client):
    body = client.get("/api/v1/search?q=%20%20").json()
    assert body["total"] == 0
    assert body["categories"] == {"players": [], "clubs": [], "transfers": [], "watchlist": []}


def test_player_and_transfer_search_return_navigation_targets(client, db, save):
    _seed(db)
    body = client.get(f"/api/v1/search?q=Mario&save_id={save.id}").json()
    assert body["categories"]["players"][0]["display_name"] == "Mario Bianchi"
    assert body["categories"]["players"][0]["navigation_target"].startswith("/players/")
    assert body["categories"]["transfers"][0]["meta"]["fee"] == 30_000_000
    assert body["categories"]["transfers"][0]["meta"]["status"] == "completed"


def test_club_search_includes_player_count(client, db, save):
    _seed(db)
    body = client.get(f"/api/v1/search?q=Northbridge&save_id={save.id}").json()
    club = body["categories"]["clubs"][0]
    assert club["display_name"] == "Northbridge United"
    assert club["meta"]["player_count"] == 1
    assert club["navigation_target"].startswith("/players?club_id=")


def test_type_filter_limits_categories(client, db, save):
    _seed(db)
    body = client.get(f"/api/v1/search?q=Mario&type=players&save_id={save.id}").json()
    assert len(body["categories"]["players"]) == 1
    assert body["categories"]["clubs"] == []
    assert body["categories"]["transfers"] == []


def test_like_wildcards_are_literal(client, db, save):
    """`%` 和 `_` 必须按字面量搜索，不能变成全表匹配。"""
    _seed(db)
    body = client.get(f"/api/v1/search?q=%25&save_id={save.id}").json()
    assert body["total"] == 0


def test_search_respects_save_isolation(client, db, save):
    _seed(db)
    other = FmSave(user_id=save.user_id, name="另一个存档", game_version="27.0", game_build="test", is_active=False)
    db.add(other)
    db.commit()
    document = scan_document(
        scan_id="scan-other",
        clubs=[club_row("C9", "隔离俱乐部")],
        players=[player_row("P9", "Mario Isolated", club_uid="C9")],
        transfers=[],
    )
    ScanImporter(db, raw_dir=RAW_DIR).import_payload(other.id, ScanPayload.model_validate(document))
    db.commit()
    body = client.get(f"/api/v1/search?q=Mario&save_id={save.id}").json()
    names = [item["display_name"] for item in body["categories"]["players"]]
    assert names == ["Mario Bianchi"]


def test_long_query_is_rejected(client):
    response = client.get("/api/v1/search?q=" + "a" * 65)
    assert response.status_code == 422


def test_limit_is_capped(client, db, save):
    _seed(db)
    response = client.get(f"/api/v1/search?q=Mario&limit=99&save_id={save.id}")
    assert response.status_code == 422
