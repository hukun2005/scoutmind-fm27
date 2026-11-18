"""Tests for the FMSuperScout adapter.

The fixture mirrors the upstream dump layout (``meta`` + ``players`` + ``staff``, PascalCase attribute names, sentinel
values) as observed in FMSuperScout's own source. It is synthetic data: no real save is shipped with this repository.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.ingestion.adapters import fmscout
from app.models import Club, DataSource, ImportJob, PlayerInstance, PlayerSnapshot

from .helpers import ensure_save

DUMP_GENERATED = "2027-03-01T18:30:00+00:00"


def dump_document(players: list[dict] | None = None, *, my_club: str = "Northbridge United") -> dict:
    """An FMSuperScout-shaped dump with two clubs and a ghost newgen."""
    rows = players if players is not None else [
        {
            "id": 9001,
            "name": "Adam Wharton",
            "birthYear": 2004,
            "birthDoy": 37,
            "age": 23,
            "ca": 148,
            "pa": 165,
            "value": 42_000_000,
            "wage": 60_000,
            "expires": "2029-06-30",
            "club": my_club,
            "clubRep": 7456,
            "div": "Premier Division",
            "nat": "England",
            "pos": "DM (C), MC",
            "posArr": ["DM", "MC"],
            "posNat": ["DM"],
            "worldRep": 5200,
            "attrs": {
                "Passing": 15,
                "Tackling": 13,
                "Stamina": 16,
                "WorkRate": 14,
                "OffTheBall": 12,
                "JumpingReach": 11,
                "Corners": 6,
            },
            "professionalism": 14,
            "InjuryProneness": 8,
            "height": 182,
            "foot": "Right",
        },
        {
            "id": 9002,
            "name": "Diego Silva",
            "birthYear": 2009,
            "birthDoy": 200,
            "age": 18,
            "ca": 96,
            "pa": 172,
            "value": 3_500_000,
            "wage": 4_500,
            "expires": "2031-06-30",
            "club": "Kingsport City",
            "clubRep": 7102,
            "div": "Premier Division",
            "nat": "Brazil",
            "pos": "ST (C)",
            "posArr": ["ST"],
            "worldRep": 1200,
            "attrs": {"Finishing": 13, "OffTheBall": 14, "Pace": 15},
            "staffAttrs": {},
        },
        {
            "id": 9003,
            "name": "Ghost Newgen",
            "birthYear": 2011,
            "birthDoy": 12,
            "age": 16,
            "ca": 40,
            "pa": 180,
            "club": None,
            "worldRep": 0xFFFF,
            "attrs": {"Finishing": 9},
        },
    ]
    return {
        "meta": {
            "generated": DUMP_GENERATED,
            "game": "FM27",
            "gameDate": "2027-03-01",
            "myClub": my_club,
            "myClubRep": 7456,
            "manager": "Local Manager",
            "host": "workstation",
        },
        "players": rows,
        "staff": [{"id": 1, "name": "Coach", "job": "Coach"}],
    }


def dump_bytes(document: dict) -> bytes:
    """Serialise a dump the way the upstream app writes it."""
    return json.dumps(document, ensure_ascii=False).encode("utf-8")


def test_detect_accepts_dumps_and_rejects_scan_payloads() -> None:
    """Detection is structural: a scan payload always carries schema_version."""
    assert fmscout.detect(dump_document()) is True
    assert fmscout.detect({"schema_version": "1.0", "players": [{"id": 1}]}) is False
    assert fmscout.detect({"players": []}) is False
    assert fmscout.detect([1, 2, 3]) is False


def test_conversion_maps_documented_fields() -> None:
    """Player identity, ability, money, contract and attributes land on the protocol fields."""
    payload, report = fmscout.convert_dump(dump_bytes(dump_document()))

    assert payload["source"] == "fmsuperscout"
    assert payload["scan"]["game_date"] == "2027-03-01"
    assert payload["scan"]["observed_at"] == "2027-03-01T18:30:00"
    assert payload["scan"]["user_club_uid"] == "fs-northbridge-united"

    wharton = next(row for row in payload["players"] if row["name"] == "Adam Wharton")
    assert wharton["save_local_uid"] == "9001"
    assert wharton["ca"] == 148 and wharton["pa"] == 165
    assert wharton["market_value"] == 42_000_000
    assert wharton["contract_end"] == "2029-06-30"
    assert wharton["birth_date"] == "2004-02-06"  # 2004 day-of-year 37
    assert wharton["position"] == "DM"  # natural position preferred over posArr
    assert wharton["attributes"]["passing"] == 15.0
    assert wharton["attributes"]["work_rate"] == 14.0
    assert wharton["attributes"]["jumping"] == 11.0
    assert "corners" not in wharton["attributes"]

    assert report.players_total == 3
    assert report.players_skipped == 1  # the ghost newgen
    assert report.players_converted == 2
    assert report.clubs_converted == 2
    assert report.attributes_ignored == ["Corners"]
    assert report.user_club == "Northbridge United"


def test_ghost_and_sentinels_become_null_not_zero() -> None:
    """Upstream sentinels and missing clubs are filtered, never stored as 0 or an empty club."""
    document = dump_document()
    document["players"][1]["value"] = 0xFFFFFFFF  # unset money sentinel
    document["players"][1]["clubRep"] = 0xFFFF
    payload, report = fmscout.convert_dump(dump_bytes(document))

    assert all(row["name"] != "Ghost Newgen" for row in payload["players"])
    silva = next(row for row in payload["players"] if row["name"] == "Diego Silva")
    assert silva["market_value"] is None
    kingsport = next(club for club in payload["clubs"] if club["name"] == "Kingsport City")
    assert kingsport["reputation"] is None
    assert report.players_skipped == 1


def test_report_lists_absent_and_ignored_fields() -> None:
    """The report tells the operator exactly which ScoutMind features cannot be fed from this dump."""
    _payload, report = fmscout.convert_dump(dump_bytes(dump_document()))
    payload = report.payload()

    assert "minutes_played" in payload["absent_fields"]
    assert "transfers" in payload["absent_fields"]
    ignored = {row["field"] for row in payload["ignored_fields"]}  # type: ignore[union-attr]
    assert {"staff", "professionalism", "height", "foot"} <= ignored
    assert payload["coverage"]["ca"] == 1.0
    assert any("不含转会" in warning for warning in payload["warnings"])
    assert payload["scan_id"]


def test_conversion_is_deterministic_for_the_same_dump() -> None:
    """The scan id derives from the dump bytes, so re-importing the same file is recognised as a duplicate."""
    raw = dump_bytes(dump_document())
    first, _ = fmscout.convert_dump(raw)
    second, _ = fmscout.convert_dump(raw)
    changed = dict(dump_document(), meta={**dump_document()["meta"], "gameDate": "2027-04-01"})

    assert first["scan"]["scan_id"] == second["scan"]["scan_id"]
    assert first["scan"]["scan_id"] != fmscout.convert_dump(dump_bytes(changed))[0]["scan"]["scan_id"]


def test_rejects_unknown_files() -> None:
    """A file that is not a dump fails loudly instead of importing garbage."""
    for raw in (b"not json", json.dumps({"schema_version": "1.0"}).encode(), b"[]"):
        try:
            fmscout.convert_dump(raw)
        except ValueError:
            continue
        raise AssertionError("非 FMSuperScout 文件必须被拒绝")


def test_endpoint_imports_and_is_idempotent(client: TestClient, db) -> None:
    """The endpoint converts, imports and reports; the same dump twice is a duplicate."""
    save_id = ensure_save(db)
    raw = dump_bytes(dump_document())

    first = client.post("/api/v1/imports/fmscout", content=raw, headers={"content-type": "application/json"})
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["import"]["duplicate"] is False
    assert body["report"]["players_converted"] == 2
    assert body["report"]["absent_fields"]

    second = client.post("/api/v1/imports/fmscout", content=raw, headers={"content-type": "application/json"})
    assert second.status_code == 201
    assert second.json()["import"]["duplicate"] is True

    assert db.query(ImportJob).filter(ImportJob.fm_save_id == save_id).count() == 1
    assert db.query(PlayerInstance).filter(PlayerInstance.fm_save_id == save_id).count() == 2
    assert db.query(PlayerSnapshot).count() == 2
    source = db.query(DataSource).filter(DataSource.fm_save_id == save_id).one()
    assert source.source == "fmsuperscout"


def test_generic_scan_endpoint_auto_detects_dumps(client: TestClient, db) -> None:
    """Dropping a dump on the normal import endpoint works, and the response names the adapter."""
    ensure_save(db)
    response = client.post(
        "/api/v1/imports/scan",
        content=dump_bytes(dump_document()),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["adapted_by"]["adapter"] == "fmscout"
    assert body["players_created"] == 2
    assert body["snapshots_created"] == 2


def test_preview_does_not_write(client: TestClient, db) -> None:
    """Preview returns the mapping report and the converted sample without touching the database."""
    ensure_save(db)
    response = client.post(
        "/api/v1/imports/fmscout/preview",
        content=dump_bytes(dump_document()),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["report"]["players_converted"] == 2
    assert len(body["sample_players"]) == 2
    assert db.query(ImportJob).count() == 0
    assert db.query(PlayerInstance).count() == 0


def test_preview_rejects_other_payloads(client: TestClient, db) -> None:
    """A scan payload is not a dump; preview says so with 422 instead of half-converting it."""
    ensure_save(db)
    response = client.post(
        "/api/v1/imports/fmscout/preview",
        content=json.dumps({"schema_version": "1.0", "source": "manual"}).encode(),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "not_fmscout_dump"


def test_user_club_is_flagged_from_meta(client: TestClient, db) -> None:
    """meta.myClub identifies the managed squad, which the squad module depends on."""
    save_id = ensure_save(db)
    client.post(
        "/api/v1/imports/fmscout",
        content=dump_bytes(dump_document()),
        headers={"content-type": "application/json"},
    )
    clubs = {club.name: club for club in db.query(Club).filter(Club.fm_save_id == save_id)}
    assert clubs["Northbridge United"].is_user_club is True
    assert clubs["Kingsport City"].is_user_club is False


def test_adapter_info_endpoint_documents_the_mapping(client: TestClient) -> None:
    """The endpoint exposes upstream identity, license and the field policy for review."""
    response = client.get("/api/v1/imports/fmscout/adapter")
    assert response.status_code == 200
    body = response.json()
    assert body["upstream"]["license"] == "MIT"
    assert "minutes_played" in body["absent_fields"]
    assert body["attribute_map"]["OffTheBall"] == "off_the_ball"
    assert "Corners" in body["unmapped_attributes"]
    assert datetime.fromisoformat(DUMP_GENERATED).tzinfo == timezone.utc
