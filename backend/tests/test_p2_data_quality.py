"""P2 数据质量回归：身份冲突、缺失属性评分、转会分页、游戏构建号映射。"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import func, select

from app.analytics import scoring
from app.analytics.scoring import score_attributes
from app.ingestion.protocol import ScanPayload
from app.ingestion.importer import ScanImporter
from app.models import IdentityConflict, ImportJob, Player, PlayerInstance, PlayerSnapshot

from tests.helpers import club_row, player_row, scan_document, transfer_row


def _import(db, save_id: int, document: dict):
    payload = ScanPayload.model_validate(document)
    outcome = ScanImporter(db).import_payload(save_id, payload)
    db.commit()
    return outcome


# -- TASK-006：身份识别 -----------------------------------------------------------------------------------------


def test_same_uid_and_birth_date_matches_single_instance(db, save) -> None:
    """UID 与出生日期都一致 → 只有一个实例、一个 Player。"""
    _import(db, save.id, scan_document(scan_id="id-1", players=[player_row("U1", "Same Person", age=22)]))
    _import(db, save.id, scan_document(scan_id="id-2", players=[player_row("U1", "Same Person", age=22)]))

    instances = db.scalar(select(func.count()).select_from(PlayerInstance))
    players = db.scalar(select(func.count()).select_from(Player))
    assert instances == 1
    assert players == 1


def test_same_uid_different_birth_date_records_conflict(db, save) -> None:
    """同一 UID、不同出生日期 → 新实例 + 冲突记录，不覆盖原身份。"""
    _import(db, save.id, scan_document(scan_id="c-1", players=[player_row("U2", "Young One", age=20)]))
    _import(db, save.id, scan_document(scan_id="c-2", players=[player_row("U2", "Old One", age=35)]))

    instances = db.scalar(select(func.count()).select_from(PlayerInstance))
    conflicts = db.scalars(select(IdentityConflict)).all()
    assert instances == 2, "出生日期不一致必须保留两个实例"
    assert len(conflicts) == 1
    assert conflicts[0].reason == "birth_date_mismatch"
    assert conflicts[0].resolution == "uid_occurrence"
    assert conflicts[0].existing_name != conflicts[0].incoming_name


def test_missing_birth_date_with_different_name_is_not_merged(db, save) -> None:
    """缺出生日期 + 姓名不同 → 不能凭 UID 合并；保留两个身份并记录冲突。"""
    row_a = player_row("U3", "First Player", age=22)
    row_a["birth_date"] = None
    row_b = player_row("U3", "Completely Different", age=30)
    row_b["birth_date"] = None

    _import(db, save.id, scan_document(scan_id="m-1", players=[row_a]))
    _import(db, save.id, scan_document(scan_id="m-2", players=[row_b]))

    instances = db.scalar(select(func.count()).select_from(PlayerInstance))
    conflicts = db.scalars(select(IdentityConflict)).all()
    assert instances == 2, "缺出生日期且异名时不得合并"
    assert len(conflicts) == 1
    assert conflicts[0].reason == "missing_birth_date_name_mismatch"
    assert conflicts[0].resolution == "kept_both"


def test_missing_birth_date_with_same_name_is_merged_conservatively(db, save) -> None:
    """缺出生日期但同名 → 允许按 UID 合并，但不会凭空写入出生日期。"""
    row = player_row("U4", "Stable Name", age=22)
    row["birth_date"] = None
    _import(db, save.id, scan_document(scan_id="s-1", players=[row]))
    _import(db, save.id, scan_document(scan_id="s-2", players=[row]))

    instances = db.scalar(select(func.count()).select_from(PlayerInstance))
    player = db.scalar(select(Player))
    assert instances == 1
    assert player.birth_date is None, "不得把未知出生日期填成任意值"


def test_identity_match_is_recorded_for_both_sides(db, save) -> None:
    """两类冲突都要留下 IdentityMatch 证据（strategy + confidence）。"""
    from app.models import IdentityMatch

    row_a = player_row("U5", "Alpha", age=22)
    row_a["birth_date"] = None
    row_b = player_row("U5", "Beta", age=30)
    row_b["birth_date"] = None
    _import(db, save.id, scan_document(scan_id="e-1", players=[row_a]))
    _import(db, save.id, scan_document(scan_id="e-2", players=[row_b]))

    strategies = {row.strategy for row in db.scalars(select(IdentityMatch)).all()}
    assert "uid_reuse_missing_birthdate" in strategies


# -- TASK-007：缺失属性评分 -------------------------------------------------------------------------------------


def test_zero_attribute_coverage_scores_none() -> None:
    """没有任何属性 → score 为 None（不可评估），而不是 0 分。"""
    result = score_attributes({}, {"passing": 1.0}, {"passing": "传球"})
    assert result["score"] is None
    assert result["evaluable"] is False
    assert result["coverage"] == 0.0
    assert any("不可评估" in item for item in result["weaknesses"])


def test_half_coverage_keeps_warning_and_score() -> None:
    """50% 覆盖率仍然给出分数，但保留覆盖率警告。"""
    result = score_attributes({"passing": 15.0}, {"passing": 0.5, "finishing": 0.5}, {"passing": "传球", "finishing": "射门"})
    assert result["score"] == pytest.approx(75.0)
    assert result["coverage"] == pytest.approx(0.5)
    assert result["evaluable"] is True
    assert any("50%" in item for item in result["weaknesses"])


def test_full_coverage_scoring_unchanged() -> None:
    """完整数据的评分逻辑不变：全部 20 分 → 100 分。"""
    result = score_attributes(
        {"passing": 20.0, "finishing": 20.0},
        {"passing": 0.5, "finishing": 0.5},
        {"passing": "传球", "finishing": "射门"},
    )
    assert result["score"] == pytest.approx(100.0)
    assert result["coverage"] == pytest.approx(1.0)


def test_evaluate_player_without_attributes_is_not_persisted(db, save) -> None:
    """没有属性的球员不写 player_scores，也不会返回 0 分。"""
    from app.models import PlayerScore

    _import(db, save.id, scan_document(scan_id="score-1", players=[player_row("S1", "No Attributes", age=22, attributes={})]))
    instance_id = db.scalar(select(PlayerInstance.id))
    result = scoring.evaluate_player(db, instance_id, "gk_goalkeeper")
    assert result["score"] is None
    assert result["evaluable"] is False
    assert db.scalar(select(func.count()).select_from(PlayerScore)) == 0


# -- TASK-008：转会分页 -----------------------------------------------------------------------------------------


def test_transfer_pagination_uses_sql_limit(db, save) -> None:
    """分页在 SQL 层完成：limit 生效且 total 是独立 COUNT。"""
    from app.analytics.transfers import TransferFilter, count_transfers, fetch_transfers

    transfers = [
        transfer_row(f"T{i}", f"P{i}", f"Player {i}", fee=1_000_000 + i)
        for i in range(50)
    ]
    players = [player_row(f"P{i}", f"Player {i}", age=22 + i % 10) for i in range(50)]
    _import(db, save.id, scan_document(scan_id="page-1", players=players, transfers=transfers))

    filters = TransferFilter()
    first = fetch_transfers(db, save.id, filters, limit=10, offset=0)
    second = fetch_transfers(db, save.id, filters, limit=10, offset=10)
    assert len(first) == 10
    assert len(second) == 10
    assert {row.id for row in first}.isdisjoint({row.id for row in second})
    assert count_transfers(db, save.id, filters) == 50


# -- TASK-009：构建号映射 ---------------------------------------------------------------------------------------


def test_fmscout_adapter_does_not_map_game_date_source_to_build() -> None:
    """gameDateSource 不是 Steam Build：缺失构建号时必须保持 None。"""
    from app.ingestion.adapters.fmscout import convert_document

    dump = {
        "meta": {
            "generated": "2026-11-18T10:00:00Z",
            "gameDateSource": "schedule",
            "gameDate": "2026-07-14",
            "game": "FM27",
            "gameVersion": "27.1.0",
            "supportedVersion": "27.0",
            "versionOk": False,
            "pluginVersion": "27.1.0+2505117",
        },
        "players": [],
        "clubs": [],
    }
    payload, _report = convert_document(dump)
    assert payload["game"]["build"] is None, "gameDateSource 不能被当成 Build ID"
    assert payload["game"]["version"] == "27.1.0"


def test_agreed_transfer_is_not_counted_as_completed() -> None:
    """未来生效的转会（agreed）不能进入历史成交统计。"""
    from app.ingestion.adapters.fmscout import convert_document

    dump = {
        "meta": {"generated": "2026-11-18T10:00:00Z", "game": "FM27", "gameVersion": "27.1.0"},
        "clubs": [{"id": 1, "name": "Club A"}, {"id": 2, "name": "Club B"}],
        "players": [
            {
                "id": 10,
                "name": "Moving Player",
                "club": "Club A",
                "clubId": 1,
                "ca": 140,
                "pa": 160,
                "transferTo": "Club B",
                "transferDate": "2027-06-30",
            }
        ],
        "transfers": [],
    }
    payload, report = convert_document(dump)
    assert payload["transfers"] in ([], None), "agreed 转会不得出现在已完成转会里"
    player = payload["players"][0]
    assert player["agreed_transfer"], "未来转会应保留在 agreed_transfer 字段"
    assert player["agreed_transfer"]["to_club_uid"], "agreed 转会必须带目标俱乐部"
