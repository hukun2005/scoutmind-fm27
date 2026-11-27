"""V3.3.2-08 迁移：在线学习四张表可升级、可回滚、不丢既有数据。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

BACKEND_DIR = Path(__file__).resolve().parents[1]
PREVIOUS_REVISION = "b1f4d7e82c90"
HEAD_REVISION = "c7d2f8a41b60"
NEW_TABLES = {
    "transfer_learning_sessions",
    "transfer_learning_events",
    "club_transfer_profiles",
    "transfer_learning_activities",
}


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


def _seed(database_url: str) -> None:
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
    engine.dispose()


def test_learning_tables_upgrade_downgrade_roundtrip(tmp_path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'v332_08.db').as_posix()}"
    _alembic(database_url, "upgrade", PREVIOUS_REVISION)
    _seed(database_url)

    _alembic(database_url, "upgrade", "head")
    engine = create_engine(database_url, future=True)
    tables = set(inspect(engine).get_table_names())
    assert NEW_TABLES.issubset(tables)
    with engine.connect() as connection:
        assert connection.execute(text("select version_num from alembic_version")).scalar_one() == HEAD_REVISION
        assert connection.execute(text("select count(*) from players")).scalar_one() == 1
        assert connection.execute(text("select count(*) from transfer_feedback")).scalar_one() == 0

    with engine.begin() as connection:
        connection.execute(
            text(
                "insert into transfer_learning_events "
                "(fm_save_id, event_key, event_type, verification_status, source, "
                "learning_eligible, evidence_json, observed_at, created_at, updated_at) "
                "values (1, 'k1', 'TRANSFER_COMPLETED', 'CONFIRMED', 'fm27_live_reader', 1, '{}', "
                "'2026-01-01 00:00:00', '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
            )
        )

    _alembic(database_url, "downgrade", PREVIOUS_REVISION)
    tables = set(inspect(engine).get_table_names())
    assert not (NEW_TABLES & tables)
    assert "transfer_feedback" in tables
    with engine.connect() as connection:
        assert connection.execute(text("select count(*) from players")).scalar_one() == 1

    _alembic(database_url, "upgrade", "head")
    with engine.connect() as connection:
        assert connection.execute(text("select version_num from alembic_version")).scalar_one() == HEAD_REVISION
        assert connection.execute(text("select count(*) from transfer_learning_events")).scalar_one() == 0
    engine.dispose()
