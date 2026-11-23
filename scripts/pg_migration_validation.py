"""PostgreSQL 16 migration validation (SM-040).

Run against a disposable PostgreSQL database:

    SCOUTMIND_PG_URL=postgresql+psycopg://postgres:postgres@localhost:5432/scoutmind_test \
        python scripts/pg_migration_validation.py

It performs a real upgrade/downgrade/upgrade cycle, creates old-schema rows, upgrades them,
checks counts, verifies duplicate scan_id isolation and transaction rollback, and prints a JSON
report with timings. It never touches a non-disposable database: the caller must pass
SCOUTMIND_PG_URL explicitly and the script refuses URLs without "test" in the database name.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import MetaData, Table, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
OLD_REVISION = "f3a9c57e21d8"


def run_alembic(*args: str, url: str) -> float:
    env = {**os.environ, "SCOUTMIND_DATABASE_URL": url}
    started = time.perf_counter()
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    elapsed = time.perf_counter() - started
    if result.returncode != 0:
        raise RuntimeError(f"alembic {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}")
    return elapsed


def scripted_head(url: str) -> str:
    """Read the head revision from the migration scripts instead of hard-coding it.

    A hard-coded revision makes every new migration fail this job for the wrong reason; the check
    that matters is "the database is at whatever head the scripts declare".
    """
    env = {**os.environ, "SCOUTMIND_DATABASE_URL": url}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"alembic heads failed:\n{result.stdout}\n{result.stderr}")
    heads = [line.split()[0] for line in result.stdout.splitlines() if line.strip()]
    if len(heads) != 1:
        raise RuntimeError(f"expected exactly one head, got {heads}")
    return heads[0]


def fill_value(column):
    name = column.name
    if name in {"created_at", "updated_at", "observed_at", "imported_at", "received_at", "detected_at"}:
        return datetime(2026, 1, 1, 12, 0)
    if name in {"game_date", "transfer_date", "birth_date", "contract_end"}:
        return date(2026, 1, 1)
    if name.endswith("_json"):
        return "{}"
    if column.type.python_type is bool:
        return False
    if column.type.python_type is int:
        return 1
    if column.type.python_type is float:
        return 0.0
    return "x"


def insert_minimal(connection, table_name: str, **overrides) -> None:
    table = Table(table_name, MetaData(), autoload_with=connection)
    values = {}
    for column in table.columns:
        if column.name in overrides:
            values[column.name] = overrides[column.name]
        elif column.nullable or column.server_default is not None or column.primary_key:
            continue
        else:
            values[column.name] = fill_value(column)
    connection.execute(table.insert().values(**values))


def count(connection, table: str) -> int:
    return int(connection.execute(text(f'select count(*) from "{table}"')).scalar_one())


def validate_schema(engine) -> dict:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    expected = {
        "users", "fm_saves", "players", "player_instances", "player_snapshots", "import_jobs",
        "transfer_history", "transfer_sources", "transfer_import_runs", "identity_conflicts",
        "identity_conflict_actions", "identity_matches", "field_evidence_samples", "player_observation_canonicals", "player_observation_canonical_actions", "capture_runs", "transfer_event_candidates", "alembic_version",
        "unresolved_player_candidates", "unresolved_player_observations", "unresolved_player_actions",
    }
    missing = sorted(expected - tables)
    columns = {row["name"] for row in inspector.get_columns("transfer_history")}
    required_columns = {"fee_raw", "addons_raw", "loan_fee_raw", "currency_original", "source_id"}
    missing_columns = sorted(required_columns - columns)
    indexes = {row["name"] for row in inspector.get_indexes("transfer_history")}
    required_indexes = {"ix_transfer_history_source_id"}
    missing_indexes = sorted(required_indexes - indexes)
    uniques = inspector.get_unique_constraints("import_jobs")
    scan_unique = [
        row for row in uniques if set(row["column_names"]) == {"fm_save_id", "scan_id"}
    ]
    foreign_keys = inspector.get_foreign_keys("transfer_history")
    source_fk = [row for row in foreign_keys if row["constrained_columns"] == ["source_id"]]
    return {
        "tables": len(tables),
        "missing_tables": missing,
        "missing_columns": missing_columns,
        "missing_indexes": missing_indexes,
        "scan_id_unique_on_save": bool(scan_unique),
        "transfer_source_fk": bool(source_fk),
    }


def main() -> int:
    url = os.environ.get("SCOUTMIND_PG_URL", "")
    if not url.startswith("postgresql"):
        print("SCOUTMIND_PG_URL must be a PostgreSQL URL", file=sys.stderr)
        return 2
    if "test" not in url.rsplit("/", 1)[-1].lower():
        print("refusing to run against a database whose name does not contain 'test'", file=sys.stderr)
        return 2
    engine = create_engine(url, future=True)
    report: dict = {"url": url, "steps": {}, "checks": {}}

    report["steps"]["upgrade_head_seconds"] = round(run_alembic("upgrade", "head", url=url), 2)
    report["checks"]["schema"] = validate_schema(engine)
    with engine.connect() as connection:
        revision = connection.execute(text("select version_num from alembic_version")).scalar_one()
    report["checks"]["revision"] = revision
    head = scripted_head(url)
    report["checks"]["head"] = head
    assert revision == head, (revision, head)
    assert report["checks"]["schema"]["missing_tables"] == []
    assert report["checks"]["schema"]["missing_columns"] == []
    assert report["checks"]["schema"]["missing_indexes"] == []
    assert report["checks"]["schema"]["scan_id_unique_on_save"] is True
    assert report["checks"]["schema"]["transfer_source_fk"] is True

    # 回到旧版本，创建旧 schema 数据，再升级。
    report["steps"]["downgrade_old_seconds"] = round(run_alembic("downgrade", OLD_REVISION, url=url), 2)
    with engine.begin() as connection:
        insert_minimal(connection, "users", id=1, username="pg-test", display_name="PG Test")
        insert_minimal(connection, "fm_saves", id=1, user_id=1, name="PG Save 1", game_version="27.1", game_build="x")
        insert_minimal(connection, "fm_saves", id=2, user_id=1, name="PG Save 2", game_version="27.1", game_build="x")
        insert_minimal(connection, "players", id=1, full_name="PG Player", normalized_name="pg-player")
        insert_minimal(connection, "player_instances", id=1, player_id=1, fm_save_id=1, save_local_uid="PG1")
        insert_minimal(connection, "import_jobs", id=1, fm_save_id=1, scan_id="legacy-1", status="completed")
        old_counts = {"players": count(connection, "players"), "import_jobs": count(connection, "import_jobs")}

    report["steps"]["upgrade_from_old_seconds"] = round(run_alembic("upgrade", "head", url=url), 2)
    with engine.connect() as connection:
        new_counts = {"players": count(connection, "players"), "import_jobs": count(connection, "import_jobs")}
    report["checks"]["old_counts"] = old_counts
    report["checks"]["new_counts"] = new_counts
    assert old_counts == new_counts, (old_counts, new_counts)

    # 同一 scan_id 在不同存档必须被允许（(fm_save_id, scan_id) 唯一）。
    with engine.begin() as connection:
        insert_minimal(connection, "import_jobs", id=2, fm_save_id=2, scan_id="legacy-1", status="completed")
        same_scan_across_saves = count(connection, "import_jobs")
    report["checks"]["duplicate_scan_id_across_saves_allowed"] = same_scan_across_saves
    assert same_scan_across_saves == 2

    # 事务失败必须完整回滚：engine.begin() 在异常时回滚整个事务。
    with engine.connect() as connection:
        before = count(connection, "player_instances")
    try:
        with engine.begin() as connection:
            insert_minimal(
                connection,
                "player_instances",
                player_id=999999,
                fm_save_id=1,
                save_local_uid="BROKEN",
            )
    except IntegrityError:
        pass
    with engine.connect() as connection:
        after = count(connection, "player_instances")
    report["checks"]["transaction_rollback"] = before == after
    assert before == after

    report["result"] = "PASS"
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
