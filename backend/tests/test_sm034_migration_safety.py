"""SM-034：迁移安全预检。"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

# scripts/ lives at the repository root, one level above backend/
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.check_migration_safety import inspect_database  # noqa: E402


def _make_db(path: Path, rows: list[tuple[str, int]]) -> None:
    connection = sqlite3.connect(path)
    connection.execute("create table alembic_version (version_num varchar(32) not null)")
    connection.execute("insert into alembic_version values ('d2f7a91b64e0')")
    connection.execute("create table import_jobs (id integer primary key, scan_id text, fm_save_id integer)")
    for index, (scan_id, save_id) in enumerate(rows, start=1):
        connection.execute("insert into import_jobs values (?, ?, ?)", (index, scan_id, save_id))
    connection.commit()
    connection.close()


def test_duplicate_scan_id_across_saves_blocks_downgrade(tmp_path: Path) -> None:
    database = tmp_path / "duplicate.db"
    _make_db(database, [("scan-1", 1), ("scan-1", 2), ("scan-2", 1)])
    result = inspect_database(database)
    assert result["duplicate_scan_id_groups"] == 1
    assert result["downgrade_below_992_safe"] is False
    assert "禁止" in result["recommendation"]


def test_unique_scan_ids_are_safe(tmp_path: Path) -> None:
    database = tmp_path / "clean.db"
    _make_db(database, [("scan-1", 1), ("scan-2", 2)])
    result = inspect_database(database)
    assert result["duplicate_scan_id_groups"] == 0
    assert result["downgrade_below_992_safe"] is True


def test_missing_database_is_reported(tmp_path: Path) -> None:
    result = inspect_database(tmp_path / "missing.db")
    assert result["exists"] is False


def test_duplicate_scan_id_within_same_save_also_blocks_global_unique_downgrade(tmp_path: Path) -> None:
    database = tmp_path / "same-save-duplicate.db"
    _make_db(database, [("scan-1", 1), ("scan-1", 1)])
    result = inspect_database(database)
    assert result["duplicate_scan_id_groups"] == 1
    assert result["downgrade_below_992_safe"] is False


def test_missing_import_jobs_table_fails_closed(tmp_path: Path) -> None:
    database = tmp_path / "missing-table.db"
    connection = sqlite3.connect(database)
    connection.execute("create table alembic_version (version_num varchar(32) not null)")
    connection.execute("insert into alembic_version values ('d2f7a91b64e0')")
    connection.commit()
    connection.close()

    result = inspect_database(database)
    assert result["downgrade_below_992_safe"] is False
    assert result["duplicate_scan_id_groups"] is None
    assert "import_jobs" in result["error"]


def test_missing_required_column_fails_closed(tmp_path: Path) -> None:
    database = tmp_path / "missing-column.db"
    connection = sqlite3.connect(database)
    connection.execute("create table alembic_version (version_num varchar(32) not null)")
    connection.execute("insert into alembic_version values ('d2f7a91b64e0')")
    connection.execute("create table import_jobs (id integer primary key, scan_id text)")
    connection.commit()
    connection.close()

    result = inspect_database(database)
    assert result["downgrade_below_992_safe"] is False
    assert "fm_save_id" in result["error"]
