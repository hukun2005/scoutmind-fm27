"""V3.2.7 存档身份迁移：只新增、不改历史，历史存档标记为 LEGACY_UNVERIFIED。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

BACKEND_DIR = Path(__file__).resolve().parents[1]
PREVIOUS_REVISION = "b7e2c9d4a105"


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


def _seed_legacy_save(database_url: str) -> None:
    engine = create_engine(database_url, future=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                "insert into users (id, username, created_at, updated_at) "
                "values (1, 'legacy', '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
            )
        )
        connection.execute(
            text(
                "insert into fm_saves (id, user_id, name, game_build, is_active, created_at, updated_at) "
                "values (1, 1, 'Legacy Save', '26620374', 1, "
                "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
            )
        )
    engine.dispose()


def test_save_identity_tables_columns_and_legacy_marker(tmp_path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'migration.db').as_posix()}"

    _alembic(database_url, "upgrade", PREVIOUS_REVISION)
    _seed_legacy_save(database_url)
    _alembic(database_url, "upgrade", "head")

    engine = create_engine(database_url, future=True)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert {
        "save_identities",
        "save_evidences",
        "save_sessions",
        "save_identity_conflicts",
    } <= tables

    import_columns = {column["name"] for column in inspector.get_columns("import_jobs")}
    capture_columns = {column["name"] for column in inspector.get_columns("capture_runs")}
    assert {"save_identity_id", "save_session_id"} <= import_columns
    assert {"save_identity_id", "save_session_id"} <= capture_columns

    with engine.connect() as connection:
        identity = connection.execute(
            text(
                "select identity_status, identity_confidence, identity_kind "
                "from save_identities where fm_save_id = 1"
            )
        ).one()
        assert identity == ("unknown", "none", "unresolved")

        evidence = connection.execute(
            text(
                "select evidence_type, confidence from save_evidences "
                "where fm_save_id = 1"
            )
        ).one()
        assert evidence == ("LEGACY_UNVERIFIED", "none")
    engine.dispose()


def test_save_identity_downgrade_removes_only_new_schema(tmp_path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'downgrade.db').as_posix()}"
    _alembic(database_url, "upgrade", "head")
    _alembic(database_url, "downgrade", PREVIOUS_REVISION)

    engine = create_engine(database_url, future=True)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert "save_identities" not in tables
    assert "save_evidences" not in tables
    assert "save_sessions" not in tables
    assert "save_identity_conflicts" not in tables

    import_columns = {column["name"] for column in inspector.get_columns("import_jobs")}
    capture_columns = {column["name"] for column in inspector.get_columns("capture_runs")}
    assert "save_identity_id" not in import_columns
    assert "save_session_id" not in import_columns
    assert "save_identity_id" not in capture_columns
    assert "save_session_id" not in capture_columns
    engine.dispose()


def test_save_identity_columns_are_nullable(tmp_path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'nullable.db').as_posix()}"
    _alembic(database_url, "upgrade", "head")

    engine = create_engine(database_url, future=True)
    inspector = inspect(engine)
    for table in ("import_jobs", "capture_runs"):
        columns = {column["name"]: column for column in inspector.get_columns(table)}
        assert columns["save_identity_id"]["nullable"] is True
        assert columns["save_session_id"]["nullable"] is True
    engine.dispose()
