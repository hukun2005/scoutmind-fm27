"""V3.3.3-01 迁移：三条新表可升级、可降级、可再次升级（SQLite 往返）。"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.config import BACKEND_DIR, settings

NEW_TABLES = {"agent_tasks", "agent_task_events", "agent_approvals"}


def _config(monkeypatch, tmp_path: Path) -> tuple[Config, str]:
    database = tmp_path / "migration.db"
    url = f"sqlite:///{database.as_posix()}"
    monkeypatch.setattr(settings, "database_url", url, raising=False)
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", url)
    return config, url


def _tables(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def _indexes(url: str, table: str) -> set[str]:
    engine = create_engine(url)
    try:
        return {index["name"] for index in inspect(engine).get_indexes(table)}
    finally:
        engine.dispose()


def test_agent_runtime_tables_upgrade_downgrade_upgrade(monkeypatch, tmp_path) -> None:
    config, url = _config(monkeypatch, tmp_path)

    command.upgrade(config, "head")
    tables = _tables(url)
    assert NEW_TABLES <= tables
    assert "alembic_version" in tables

    # 先撤销 V3.3.3-02 新增索引，再撤销 V3.3.3-01 的三张表。
    command.downgrade(config, "b8e4d1c7f2a9")
    command.downgrade(config, "-1")
    tables = _tables(url)
    assert not (NEW_TABLES & tables)
    # 历史表必须保留：降级只能撤销本次新增。
    assert "agent_conversations" in tables
    assert "players" in tables

    command.upgrade(config, "head")
    assert NEW_TABLES <= _tables(url)
    assert "ix_transfer_save_status_date" in _indexes(url, "transfer_history")
    assert "ix_agent_tasks_save_user_created" in _indexes(url, "agent_tasks")
