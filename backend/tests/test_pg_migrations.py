"""PostgreSQL schema/migration tests (SM-040).

Skipped unless SCOUTMIND_PG_TEST_URL points at a disposable PostgreSQL 16 database that has
already been migrated by scripts/pg_migration_validation.py (or alembic upgrade head).
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

PG_URL = os.environ.get("SCOUTMIND_PG_TEST_URL")

pytestmark = pytest.mark.skipif(not PG_URL, reason="SCOUTMIND_PG_TEST_URL not configured")


@pytest.fixture(scope="module")
def engine():
    engine = create_engine(PG_URL, future=True)
    yield engine
    engine.dispose()


def test_pg_head_schema(engine) -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    for table in ("players", "player_instances", "transfer_history", "transfer_sources", "identity_conflict_actions"):
        assert table in tables
    columns = {row["name"] for row in inspector.get_columns("transfer_history")}
    assert {"fee_raw", "addons_raw", "loan_fee_raw", "currency_original", "source_id"} <= columns
    indexes = {row["name"] for row in inspector.get_indexes("transfer_history")}
    assert "ix_transfer_history_source_id" in indexes
    uniques = inspector.get_unique_constraints("import_jobs")
    assert any(set(row["column_names"]) == {"fm_save_id", "scan_id"} for row in uniques)
    fks = inspector.get_foreign_keys("transfer_history")
    assert any(row["constrained_columns"] == ["source_id"] for row in fks)


def test_pg_transaction_rollback(engine) -> None:
    with engine.connect() as connection:
        before = connection.execute(text("select count(*) from player_instances")).scalar_one()
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "insert into player_instances (id, player_id, fm_save_id, save_local_uid, uid_occurrence) "
                    "values (999999, 888888, 1, 'TEST-BROKEN', 0)"
                )
            )
    except IntegrityError:
        pass
    with engine.connect() as connection:
        after = connection.execute(text("select count(*) from player_instances")).scalar_one()
    assert before == after


def test_pg_scan_id_is_unique_per_save_not_global(engine) -> None:
    """The live constraint must be (fm_save_id, scan_id); a global unique index is the old bug."""
    inspector = inspect(engine)
    uniques = inspector.get_unique_constraints("import_jobs")
    matching = [row for row in uniques if set(row["column_names"]) == {"fm_save_id", "scan_id"}]
    assert matching, "expected (fm_save_id, scan_id) uniqueness"
