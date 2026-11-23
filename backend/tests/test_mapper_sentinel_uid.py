"""SM-113（后端侧）：FMSuperScout 适配层对上游哨兵 id 的处理。

C# 映射器与这个适配器消费同一份上游 dump；两边必须给出同样的身份判定，否则同一次扫描会因入口不同
而得到不同的身份。
"""

from __future__ import annotations

from app.ingestion.adapters import fmscout


def _dump(players: list[dict]) -> dict:
    return {
        "meta": {"game": "FM27", "gameVersion": "27.1.0", "generated": "2026-11-23T10:00:00", "gameDate": "2026-11-01"},
        "players": players,
    }


def test_adapter_keeps_sentinel_players_without_writing_uid() -> None:
    document = _dump(
        [
            {"id": 11, "name": "Valid One", "club": "Club A", "ca": 150, "pa": 170, "worldRep": 6000},
            {"id": 4294967295, "name": "Free Agent A", "ca": 120, "pa": 140, "club": "", "worldRep": 0},
            {"id": 4294967295, "name": "Free Agent B", "ca": 121, "pa": 141, "club": "", "worldRep": 0},
            {"id": 0, "name": "Zero Id", "ca": 100, "pa": 110, "club": "Club B", "worldRep": 5000},
            {"name": "No Id", "ca": 101, "pa": 111, "club": "Club B", "worldRep": 5000},
        ]
    )
    payload, report = fmscout.convert_document(document)

    rows = payload["players"]
    assert len(rows) == 5
    assert report.players_valid_uid == 1
    assert report.players_unresolved == 4
    assert report.players_sentinel_uid == 2
    assert report.players_invalid_uid == 1  # id=0
    assert report.players_missing_uid == 1  # 完全没有 id

    valid = rows[0]
    assert valid["save_local_uid"] == "11"
    assert valid["identity"] == {"kind": "save_local_uid", "value": "11"}

    for row in rows[1:]:
        assert "save_local_uid" not in row, "哨兵/缺失/非法 id 不得写成 save_local_uid"
        identity = row["identity"]
        assert identity["kind"] == "unresolved"
        assert identity["source_record_id"].startswith("dump_row:")
        assert identity["evidence"]["source"] == "fmsuperscout_dump"

    sentinel = [
        row
        for row in rows
        if row["identity"]["kind"] == "unresolved" and row["identity"]["uid_status"] == "sentinel"
    ]
    assert {row["name"] for row in sentinel} == {"Free Agent A", "Free Agent B"}
    assert all(row["identity"]["raw_uid"] == "4294967295" for row in sentinel)

    zero = next(row for row in rows if row["name"] == "Zero Id")
    assert zero["identity"]["reason"] == "zero_uid"
    missing = next(row for row in rows if row["name"] == "No Id")
    assert missing["identity"]["uid_status"] == "missing"
    assert "raw_uid" not in missing["identity"] or missing["identity"]["raw_uid"] is None

    assert any("unresolved" in warning for warning in report.warnings)


def test_adapter_does_not_merge_two_sentinel_players() -> None:
    document = _dump(
        [
            {"id": 4294967295, "name": "Same Name", "ca": 120, "pa": 140, "club": "", "worldRep": 0},
            {"id": 4294967295, "name": "Same Name", "ca": 121, "pa": 141, "club": "", "worldRep": 0},
        ]
    )
    payload, report = fmscout.convert_document(document)
    assert len(payload["players"]) == 2
    assert all("save_local_uid" not in row for row in payload["players"])
    assert report.players_sentinel_uid == 2


def test_adapter_valid_rows_keep_working() -> None:
    document = _dump([{"id": 777, "name": "Normal", "club": "Club A", "ca": 140, "pa": 160, "worldRep": 5000}])
    payload, report = fmscout.convert_document(document)
    assert payload["schema_version"] == "1.1", "输出 identity 块时必须声明 1.1（1.x 兼容）"
    row = payload["players"][0]
    assert row["save_local_uid"] == "777"
    assert row["record_id"] == "777"
    assert report.players_valid_uid == 1
    assert report.players_unresolved == 0
