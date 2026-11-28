"""V3.3.2-07 迁移：transfer_feedback 新增表、去重唯一约束、可回滚且不丢数据。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

BACKEND_DIR = Path(__file__).resolve().parents[1]
PREVIOUS_REVISION = "a9f2c6d31b84"
NEW_REVISION = "b1f4d7e82c90"


def _head_revision() -> str:
    """动态解析当前 head：新增迁移不应让历史迁移测试失效，也不能放宽断言。"""
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        cwd=BACKEND_DIR,
        env=os.environ.copy(),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.split()[0]


HEAD_REVISION = _head_revision()


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
                "insert into players (id, full_name, normalized_name, created_at, updated_at) "
                "values (1, 'Existing Player', 'existing player', '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
            )
        )
        connection.execute(
            text(
                "insert into player_instances "
                "(id, player_id, fm_save_id, save_local_uid, uid_occurrence, latest_snapshot_id, "
                "created_at, updated_at) "
                "values (1, 1, 1, 'EXIST-1', 0, 1, '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
            )
        )
        connection.execute(
            text(
                "insert into player_snapshots "
                "(id, player_instance_id, observed_at, imported_at, source, created_at, updated_at) "
                "values (1, 1, '2026-01-01 10:00:00', '2026-01-01 00:00:00', 'test', "
                "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
            )
        )
    engine.dispose()


def test_upgrade_downgrade_upgrade_preserves_data(tmp_path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'v332_07.db').as_posix()}"
    _alembic(database_url, "upgrade", PREVIOUS_REVISION)
    _seed_existing_data(database_url)

    _alembic(database_url, "upgrade", "head")
    engine = create_engine(database_url, future=True)
    assert "transfer_feedback" in set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        assert connection.execute(text("select count(*) from players")).scalar_one() == 1
        assert connection.execute(text("select version_num from alembic_version")).scalar_one() == HEAD_REVISION

    insert_feedback = text(
        "insert into transfer_feedback "
        "(fm_save_id, player_instance_id, direction, outcome, amount, dedupe_key, source, "
        "created_at, updated_at) "
        "values (1, 1, 'purchase', 'completed', 9500000, :key, 'user_confirmed', "
        "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
    )
    with engine.begin() as connection:
        connection.execute(insert_feedback, {"key": "dedupe-a"})
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(insert_feedback, {"key": "dedupe-a"})

    _alembic(database_url, "downgrade", PREVIOUS_REVISION)
    assert "transfer_feedback" not in set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        assert connection.execute(text("select count(*) from players")).scalar_one() == 1

    _alembic(database_url, "upgrade", "head")
    with engine.connect() as connection:
        assert connection.execute(text("select version_num from alembic_version")).scalar_one() == HEAD_REVISION
        assert connection.execute(text("select count(*) from transfer_feedback")).scalar_one() == 0
    engine.dispose()
