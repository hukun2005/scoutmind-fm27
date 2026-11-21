"""迁移安全预检（SM-034）。

用途：在执行 `alembic downgrade` 前判断历史迁移是否会破坏数据。

背景：`992f85fb22b8` 的 downgrade 会把 `import_jobs.scan_id` 的唯一约束改回“全局唯一”，
但真实库允许同一 `scan_id` 出现在不同存档（唯一约束是 `(fm_save_id, scan_id)`）。
只要存在跨存档重复 `scan_id`，downgrade 到 `992f85fb22b8` 之前就会失败。
本脚本不修改数据库，只给出结论与建议。

用法：
    python scripts/check_migration_safety.py backend/data/scoutmind.db
    python scripts/check_migration_safety.py backend/data/scoutmind.db --json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

#: downgrade 会重新引入全局唯一 scan_id 的历史迁移。
RISKY_REVISION = "992f85fb22b8"


def inspect_database(path: Path) -> dict:
    """返回版本、重复 scan_id 与 downgrade 安全性。不写库。"""
    if not path.exists():
        return {"path": str(path), "exists": False, "error": "database not found"}
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        try:
            row = connection.execute("select version_num from alembic_version").fetchone()
            revision = row[0] if row else None
        except sqlite3.Error:
            revision = None
        try:
            duplicates = connection.execute(
                "select scan_id, count(distinct fm_save_id) as saves from import_jobs "
                "group by scan_id having saves > 1 order by saves desc limit 20"
            ).fetchall()
            total_duplicate_groups = connection.execute(
                "select count(*) from (select scan_id from import_jobs group by scan_id "
                "having count(distinct fm_save_id) > 1)"
            ).fetchone()[0]
        except sqlite3.Error as exc:
            duplicates = []
            total_duplicate_groups = 0
            error = str(exc)
        else:
            error = None
        try:
            imports = connection.execute("select count(*) from import_jobs").fetchone()[0]
        except sqlite3.Error:
            imports = None
    finally:
        connection.close()

    safe = total_duplicate_groups == 0
    return {
        "path": str(path),
        "exists": True,
        "revision": revision,
        "import_jobs": imports,
        "duplicate_scan_id_groups": total_duplicate_groups,
        "examples": [
            {"scan_id": scan_id, "saves": saves} for scan_id, saves in duplicates
        ],
        "downgrade_below_992_safe": safe,
        "risky_revision": RISKY_REVISION,
        "error": error,
        "recommendation": (
            "可以执行 downgrade；仍建议先备份。"
            if safe
            else "禁止 downgrade 到 992f85fb22b8 之前：会因全局唯一 scan_id 冲突失败。"
            "请保持当前版本，或先在单独环境中设计数据清理方案（会改写历史 scan_id，需业务确认）。"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="检查 SQLite 数据库的 downgrade 安全性")
    parser.add_argument("database", type=Path)
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()
    result = inspect_database(args.database)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"数据库：{result['path']}")
        print(f"迁移版本：{result.get('revision')}")
        print(f"导入记录：{result.get('import_jobs')}")
        print(f"跨存档重复 scan_id 组数：{result.get('duplicate_scan_id_groups')}")
        print(f"downgrade 安全性：{'安全' if result.get('downgrade_below_992_safe') else '不安全'}")
        print(result.get("recommendation", ""))
    return 0 if result.get("downgrade_below_992_safe") else 2


if __name__ == "__main__":
    raise SystemExit(main())
