"""V3.2.9 Phase 5：新迁移的 upgrade / downgrade / 再 upgrade 与数据保留测试。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

BACKEND_DIR = Path(__file__).resolve().parents[1]
PREVIOUS_REVISION = "b5d9c2e7f4a1"
NEW_TABLES = {
    "player_uid_observations",
    "player_identity_links",
    "player_identity_review_items",
    "player_identity_review_actions",
    "identity_scan_runs",
    "cross_save_identity_candidates",
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


def _seed_existing_identity(database_url: str) -> None:
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
                "values (1, 1, 'Existing Save', '26620374', 1, "
                "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
            )
        )
        connection.execute(
            text(
                "insert into players (id, full_name, normalized_name, birth_date, created_at, updated_at) "
                "values (1, 'Existing Player', 'existing player', '1999-09-09', "
                "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
            )
        )
        connection.execute(
            text(
                "insert into player_instances (id, player_id, fm_save_id, save_local_uid, uid_occurrence, "
                "created_at, updated_at) "
                "values (1, 1, 1, 'EXIST-1', 0, '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
            )
        )
    engine.dispose()


def test_upgrade_downgrade_upgrade_preserves_existing_data(tmp_path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'v329.db').as_posix()}"
    _alembic(database_url, "upgrade", PREVIOUS_REVISION)
    _seed_existing_identity(database_url)

    _alembic(database_url, "upgrade", "head")
    engine = create_engine(database_url, future=True)
    tables = set(inspect(engine).get_table_names())
    assert NEW_TABLES <= tables
    with engine.connect() as connection:
        assert connection.execute(text("select count(*) from players")).scalar_one() == 1
        assert connection.execute(text("select save_local_uid from player_instances")).scalar_one() == "EXIST-1"
        version = connection.execute(text("select version_num from alembic_version")).scalar_one()
    assert version == "c3f5a1b7d9e2"
    assert "data_repair_audits" in tables
    repair_uniques = {
        frozenset(row["column_names"])
        for row in inspect(engine).get_unique_constraints("data_repair_audits")
    }
    assert frozenset(
        {"import_job_id", "entity", "row_index", "rule_id", "field"}
    ) in repair_uniques

    review_columns = {column["name"] for column in inspect(engine).get_columns("player_identity_review_items")}
    assert "version" in review_columns, "审核条目缺少乐观锁版本列"
    action_columns = {
        column["name"] for column in inspect(engine).get_columns("player_identity_review_actions")
    }
    assert {"previous_version", "new_version", "request_key"} <= action_columns

    _alembic(database_url, "downgrade", PREVIOUS_REVISION)
    tables_after = set(inspect(engine).get_table_names())
    assert not (NEW_TABLES & tables_after)
    assert "data_repair_audits" not in tables_after
    with engine.connect() as connection:
        assert connection.execute(text("select count(*) from players")).scalar_one() == 1
    engine.dispose()

    _alembic(database_url, "upgrade", "head")
    engine = create_engine(database_url, future=True)
    assert NEW_TABLES <= set(inspect(engine).get_table_names())
    assert "data_repair_audits" in set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        assert connection.execute(text("select count(*) from player_instances")).scalar_one() == 1
    engine.dispose()


def test_new_unique_constraints_are_present(tmp_path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'constraints.db').as_posix()}"
    _alembic(database_url, "upgrade", "head")
    engine = create_engine(database_url, future=True)
    inspector = inspect(engine)
    unique_pairs = {
        "player_uid_observations": {"fm_save_id", "observation_key"},
        "player_identity_links": {"fm_save_id", "link_key"},
        "player_identity_review_items": {"fm_save_id", "item_key"},
        "identity_scan_runs": {"fm_save_id", "scan_id"},
    }
    for table, expected in unique_pairs.items():
        uniques = {frozenset(row["column_names"]) for row in inspector.get_unique_constraints(table)}
        assert frozenset(expected) in uniques, f"{table} 缺少唯一约束"
    engine.dispose()
