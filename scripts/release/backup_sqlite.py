"""Consistent SQLite backup helper used by Backup-Database.ps1.

Uses the sqlite3 backup API, which is safe while the application holds the database open in WAL mode
(a plain file copy can capture a torn write). Verifies the copy with ``PRAGMA integrity_check``.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


def backup(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise SystemExit(f"数据库不存在：{source}")
    if destination.exists():
        raise SystemExit(f"目标已存在，拒绝覆盖：{destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True) as src, sqlite3.connect(
        destination.as_posix()
    ) as dst:
        src.backup(dst)
    with sqlite3.connect(destination.as_posix()) as check:
        result = check.execute("PRAGMA integrity_check").fetchone()[0]
    if result != "ok":
        raise SystemExit(f"备份完整性检查失败：{result}")
    size = destination.stat().st_size
    if size == 0:
        raise SystemExit("备份文件为空")
    print(f"OK {destination} {size}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Consistent SQLite backup for ScoutMind")
    parser.add_argument("--source", required=True)
    parser.add_argument("--destination", required=True)
    args = parser.parse_args(argv)
    backup(Path(args.source), Path(args.destination))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
