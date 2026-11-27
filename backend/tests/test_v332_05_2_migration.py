"""V3.3.2-05.2 迁移：新增列/表、部分唯一索引、数据保留与可回滚。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

BACKEND_DIR = Path(__file__).resolve().parents[1]
PREVIOUS_REVISION = "e7c2b9a41f60"
NEW_REVISION = "a9f2c6d31b84"


def _alembic(database_url: str, *args: str) -> None:
    env = os.environ.copy()
    env["SCOUTMIND_DATABASE_URL"] = database_url
    code = "from alembic.config import main; main([%s])" % ", ".join(repr(arg) for arg in args)
    subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND_DIR,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def _seed_existing_data(database_url: str) -> None:
    engine = create_engine(database_url, future=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                "insert into users (id, username, created_at, updated_at) "
                "values (1, 'local', '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
            )
        )
        connection.execute(
            text(
                "insert into fm_saves (id, user_id, name, game_build, is_active, created_at, updated_at) "
                "values (1, 1, 'Existing Save', '26620374', 1, '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
            )
        )
        connection.execute(
            text(
                "insert into clubs (id, fm_save_id, uid, name, is_user_club, source, confidence, created_at, updated_at) "
                "values (1, 1, 'club-1', 'Existing Club', 0, 'test', 1.0, "
                "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
            )
        )
        connection.execute(
            text(
                "insert into players (id, full_name, normalized_name, created_at, updated_at) "
                "values (1, 'Existing Player', 'existing player', '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
            )
        )
        connection.execute(
            text(
                "insert into player_instances "
                "(id, player_id, fm_save_id, save_local_uid, uid_occurrence, club_id, latest_snapshot_id, "
                "created_at, updated_at) "
                "values (1, 1, 1, 'EXIST-1', 0, 1, 1, '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
            )
        )
        connection.execute(
            text(
                "insert into player_snapshots "
                "(id, player_instance_id, observed_at, imported_at, source, club_id, created_at, updated_at) "
                "values (1, 1, '2026-01-01 10:00:00', '2026-01-01 00:00:00', 'test', 1, "
                "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
            )
        )
        connection.execute(
            text(
                "insert into transfer_opportunities "
                "(id, fm_save_id, player_instance_id, opportunity_type, verified_status, confidence, source, "
                "first_seen_at, last_seen_at, active, is_primary, detail_json, created_at, updated_at) "
                "values (1, 1, 1, 'listed', 'confirmed', 1.0, 'player_availability', "
                "'2026-01-01 00:00:00', '2026-01-01 00:00:00', 1, 1, '{}', "
                "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
            )
        )
    engine.dispose()


def test_upgrade_downgrade_upgrade_preserves_data(tmp_path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'v332_05_2.db').as_posix()}"
    _alembic(database_url, "upgrade", PREVIOUS_REVISION)
    _seed_existing_data(database_url)

    _alembic(database_url, "upgrade", "head")
    engine = create_engine(database_url, future=True)
    tables = set(inspect(engine).get_table_names())
    assert "background_tasks" in tables
    assert {"club_link_source", "club_linked_at"} <= {
        column["name"] for column in inspect(engine).get_columns("player_instances")
    }
    assert "club_uid" in {column["name"] for column in inspect(engine).get_columns("player_snapshots")}
    assert "scan_token" in {
        column["name"] for column in inspect(engine).get_columns("transfer_opportunities")
    }
    with engine.connect() as connection:
        assert connection.execute(text("select count(*) from players")).scalar_one() == 1
        assert connection.execute(text("select club_id from player_instances")).scalar_one() == 1
        assert connection.execute(text("select scan_token from transfer_opportunities")).scalar_one() is None
        assert connection.execute(text("select version_num from alembic_version")).scalar_one() == NEW_REVISION

    # 同存档同锁键的活跃任务由部分唯一索引兜底，不能只靠应用层。
    insert_task = text(
        "insert into background_tasks "
        "(task_id, fm_save_id, task_type, lock_key, status, progress, total, processed, matched, failed, "
        "checkpoint_json, result_json, attempt_count, created_at, updated_at) "
        "values (:task_id, 1, 'FULL_SCAN', 'scan', :status, 0, 0, 0, 0, 0, '{}', '{}', 0, "
        "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
    )
    with engine.begin() as connection:
        connection.execute(insert_task, {"task_id": "task-a", "status": "PENDING"})
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(insert_task, {"task_id": "task-b", "status": "RUNNING"})
    with engine.begin() as connection:
        # 终态不占用活跃锁。
        connection.execute(insert_task, {"task_id": "task-c", "status": "COMPLETED"})

    _alembic(database_url, "downgrade", PREVIOUS_REVISION)
    tables_after = set(inspect(engine).get_table_names())
    assert "background_tasks" not in tables_after
    assert "club_link_source" not in {
        column["name"] for column in inspect(engine).get_columns("player_instances")
    }
    assert "club_uid" not in {column["name"] for column in inspect(engine).get_columns("player_snapshots")}
    assert "scan_token" not in {
        column["name"] for column in inspect(engine).get_columns("transfer_opportunities")
    }
    with engine.connect() as connection:
        assert connection.execute(text("select count(*) from players")).scalar_one() == 1
        assert connection.execute(text("select count(*) from player_snapshots")).scalar_one() == 1
        assert connection.execute(text("select count(*) from transfer_opportunities")).scalar_one() == 1

    _alembic(database_url, "upgrade", "head")
    with engine.connect() as connection:
        assert connection.execute(text("select version_num from alembic_version")).scalar_one() == NEW_REVISION
        assert connection.execute(text("select club_id from player_instances")).scalar_one() == 1
    engine.dispose()
