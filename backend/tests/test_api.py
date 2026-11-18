"""HTTP API acceptance tests, including the local token guard."""

from __future__ import annotations

import json

from app.config import settings

from tests.helpers import import_document, player_row, scan_document, transfer_row


def _seed(db) -> None:
    import_document(
        db,
        scan_document(
            players=[
                player_row("P1", "Adam Wharton", ca=148, pa=165, position="DM", value=42_000_000),
                player_row("P2", "Second Player", ca=130, pa=150, position="ST", value=15_000_000),
            ],
            transfers=[
                transfer_row("T1", "P1", "Adam Wharton", fee=22_000_000),
                transfer_row("T2", "P2", "Second Player", fee=12_000_000),
            ],
        ),
    )


def test_health_is_public(client):
    """Health must answer without a token."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_bootstrap_lists_saves(client, save):
    """Bootstrap returns the active save and capabilities."""
    response = client.get("/api/v1/meta/bootstrap")
    assert response.status_code == 200
    body = response.json()
    assert body["product"] == "ScoutMind"
    assert body["active_save_id"] == save.id
    assert body["capabilities"]["watchlist"] is True


def test_import_multipart_and_duplicate(client, db, save):
    """The multipart upload path imports once and reports duplicates afterwards."""
    document = scan_document(players=[player_row("P1", "Manual Upload", ca=140)])
    files = {"file": ("scan.json", json.dumps(document).encode("utf-8"), "application/json")}
    first = client.post(f"/api/v1/imports/scan?save_id={save.id}", files=files)
    assert first.status_code == 201
    assert first.json()["snapshots_created"] == 1
    second = client.post(
        f"/api/v1/imports/scan?save_id={save.id}",
        files={"file": ("scan.json", json.dumps(document).encode("utf-8"), "application/json")},
    )
    assert second.status_code == 201
    assert second.json()["duplicate"] is True


def test_players_list_and_filter(client, db, save):
    """Player listing supports search and position filters and returns coverage."""
    _seed(db)
    response = client.get(f"/api/v1/players?save_id={save.id}&position_group=MF")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "Adam Wharton"
    assert "ca" in body["coverage"]


def test_player_detail_and_history(client, db, save):
    """Profile and history endpoints return the imported facts."""
    _seed(db)
    listed = client.get(f"/api/v1/players?save_id={save.id}&query=Adam").json()
    instance_id = listed["items"][0]["instance_id"]
    detail = client.get(f"/api/v1/players/{instance_id}").json()
    assert detail["summary"]["name"] == "Adam Wharton"
    assert detail["snapshot_count"] == 1
    timeline = client.get(f"/api/v1/players/{instance_id}/history").json()
    assert len(timeline["points"]) == 1


def test_transfer_stats_endpoint(client, db, save):
    """Statistics endpoint mirrors the analytics module."""
    _seed(db)
    response = client.get(f"/api/v1/transfers/stats?save_id={save.id}")
    body = response.json()
    assert response.status_code == 200
    assert body["sample_size"] == 2
    assert body["median"] == 17_000_000


def test_invalid_sort_is_rejected(client, db, save):
    """An unsupported sort field is a 400, not a silent fallback."""
    _seed(db)
    response = client.get(f"/api/v1/players?save_id={save.id}&sort=drop_table")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_sort"


def test_token_guard(client, db, save, monkeypatch):
    """When a token is configured, requests without it are refused."""
    monkeypatch.setattr(settings, "api_token", "secret-token")
    refused = client.get("/api/v1/players")
    assert refused.status_code == 401
    allowed = client.get("/api/v1/players", headers={"X-ScoutMind-Token": "secret-token"})
    assert allowed.status_code == 200


def test_agent_conversation_roundtrip(client, db, save):
    """A question produces a stored structured answer."""
    _seed(db)
    conversation = client.post("/api/v1/agent/conversations", json={"save_id": save.id}).json()
    response = client.post(
        f"/api/v1/agent/conversations/{conversation['id']}/messages",
        json={"question": "过去三年同位置球员的成交价格中位数是多少？", "save_id": save.id},
    )
    assert response.status_code == 201
    answer = response.json()["answer"]
    keys = {section["key"] for section in answer["sections"]}
    assert {"sample", "risks"} <= keys
    assert response.json()["tool_calls"][0]["name"] == "get_transfer_price_stats"


def test_overview_endpoint(client, db, save):
    """Dashboard aggregates reflect the imported data."""
    _seed(db)
    body = client.get(f"/api/v1/analytics/overview?save_id={save.id}").json()
    assert body["players"] == 2
    assert body["transfers"] == 2
    assert body["snapshots"] == 2
