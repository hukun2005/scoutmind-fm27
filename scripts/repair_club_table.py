"""Repair the local ``clubs`` table after an interrupted SQLite batch migration.

An interrupted ``batch_alter_table`` can leave ``clubs`` as a table created with ``CREATE TABLE ... AS SELECT``,
which loses the primary key and the ``(fm_save_id, uid)`` uniqueness. Foreign keys from other tables then fail with
``foreign key mismatch``. This script rebuilds the table with its real schema, keeps the rows and de-duplicates by
``(fm_save_id, uid)``.

It is a local repair tool: fresh databases built by ``alembic upgrade head`` never need it.

Usage::

    .\\backend\\.venv\\Scripts\\python.exe scripts\\repair_club_table.py --check
    .\\backend\\.venv\\Scripts\\python.exe scripts\\repair_club_table.py --apply
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent.parent / "backend" / "data" / "scoutmind.db"

DDL = """
CREATE TABLE clubs_rebuilt (
    id INTEGER NOT NULL,
    fm_save_id INTEGER NOT NULL,
    uid VARCHAR(64) NOT NULL,
    name VARCHAR(128) NOT NULL,
    nation VARCHAR(64),
    league VARCHAR(128),
    reputation INTEGER,
    is_user_club BOOLEAN NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    normalized_name VARCHAR(128),
    source VARCHAR(32),
    confidence FLOAT,
    external_ids_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (id),
    CONSTRAINT uq_club_save_uid UNIQUE (fm_save_id, uid),
    FOREIGN KEY (fm_save_id) REFERENCES fm_saves (id)
)
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="重建 clubs 表（保留数据、补回主键与唯一约束）")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    connection = sqlite3.connect(args.db)
    ddl = connection.execute("select sql from sqlite_master where name='clubs'").fetchone()[0]
    has_pk = "PRIMARY KEY" in ddl.upper()
    duplicates = connection.execute(
        "select fm_save_id, uid, count(*) from clubs group by fm_save_id, uid having count(*) > 1"
    ).fetchall()
    total = connection.execute("select count(*) from clubs").fetchone()[0]
    print(f"clubs 行数: {total}；主键存在: {has_pk}；重复 (save, uid): {len(duplicates)}")
    if args.check:
        return 0 if has_pk and not duplicates else 1
    if not args.apply:
        print("加 --apply 才会实际重建")
        return 0

    connection.executescript("PRAGMA foreign_keys=OFF;")
    connection.execute("DROP TABLE IF EXISTS clubs_rebuilt")
    connection.execute(DDL)
    connection.execute(
        """
        INSERT INTO clubs_rebuilt (
            id, fm_save_id, uid, name, nation, league, reputation, is_user_club,
            created_at, updated_at, normalized_name, source, confidence, external_ids_json
        )
        SELECT id, fm_save_id, uid, name, nation, league, reputation, is_user_club,
               created_at, updated_at, normalized_name, source, confidence,
               COALESCE(external_ids_json, '{}')
        FROM clubs
        WHERE id IN (SELECT MIN(id) FROM clubs GROUP BY fm_save_id, uid)
        """
    )
    connection.execute("DROP TABLE clubs")
    connection.execute("ALTER TABLE clubs_rebuilt RENAME TO clubs")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_clubs_fm_save_id ON clubs (fm_save_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_clubs_normalized_name ON clubs (normalized_name)")
    connection.commit()
    connection.execute("PRAGMA foreign_keys=ON")
    remaining = connection.execute("select count(*) from clubs").fetchone()[0]
    print(f"重建完成，剩余 {remaining} 行（去重 {total - remaining} 行）")
    connection.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
