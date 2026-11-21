"""迁移安全预检（SM-034）。

本脚本只读。任何缺表、缺版本信息或 schema 错误均 fail-closed，
绝不把“无法检查”误判成“可以 downgrade”。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

RISKY_REVISION = "992f85fb22b8"


def inspect_database(path: Path) -> dict:
    """检查 SQLite 数据库；只有检查完整且无冲突时才返回安全。"""
    if not path.exists():
        return {
            "path": str(path), "exists": False, "revision": None,
            "duplicate_scan_id_groups": None, "downgrade_below_992_safe": False,
            "error": "database not found",
            "recommendation": "禁止 downgrade：数据库不存在，无法完成安全检查。",
        }

    connection = None
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        tables = {
            row[0] for row in connection.execute(
                "select name from sqlite_master where type='table'"
            )
        }
        if "alembic_version" not in tables or "import_jobs" not in tables:
            missing = sorted({"alembic_version", "import_jobs"} - tables)
            raise RuntimeError(f"缺少必要表：{', '.join(missing)}")

        version_rows = connection.execute(
            "select version_num from alembic_version"
        ).fetchall()
        if len(version_rows) != 1 or not version_rows[0][0]:
            raise RuntimeError("alembic_version 必须且只能包含一个有效版本")

        columns = {
            row[1] for row in connection.execute("pragma table_info(import_jobs)")
        }
        required = {"scan_id", "fm_save_id"}
        if not required.issubset(columns):
            raise RuntimeError(f"import_jobs 缺少列：{', '.join(sorted(required - columns))}")

        # SQLite UNIQUE(scan_id) 允许多个 NULL；NULL 不会造成旧全局唯一约束冲突。
        duplicates = connection.execute(
            "select scan_id, count(*) as rows_count "
            "from import_jobs where scan_id is not null "
            "group by scan_id having count(*) > 1 "
            "order by rows_count desc limit 20"
        ).fetchall()
        total = connection.execute(
            "select count(*) from ("
            "select scan_id from import_jobs where scan_id is not null "
            "group by scan_id having count(*) > 1)"
        ).fetchone()[0]
        imports = connection.execute("select count(*) from import_jobs").fetchone()[0]
        revision = version_rows[0][0]

        safe = total == 0
        return {
            "path": str(path), "exists": True, "revision": revision,
            "import_jobs": imports, "duplicate_scan_id_groups": total,
            "examples": [
                {"scan_id": scan_id, "rows": rows_count}
                for scan_id, rows_count in duplicates
            ],
            "downgrade_below_992_safe": safe,
            "risky_revision": RISKY_REVISION,
            "error": None,
            "recommendation": (
                "预检未发现 scan_id 冲突；仍须备份并确认迁移链。"
                if safe else
                f"禁止 downgrade 到 {RISKY_REVISION} 之前：旧版全局唯一 scan_id 将发生冲突。"
                "不得自动删除或改写历史 scan_id。"
            ),
        }
    except (sqlite3.Error, RuntimeError, OSError) as exc:
        return {
            "path": str(path), "exists": True, "revision": None,
            "duplicate_scan_id_groups": None, "downgrade_below_992_safe": False,
            "error": str(exc),
            "recommendation": "禁止 downgrade：安全预检未能完整执行（fail-closed）。",
        }
    finally:
        if connection is not None:
            connection.close()


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
        print(f"downgrade 安全性：{'预检通过' if result.get('downgrade_below_992_safe') else '不安全/不可判定'}")
        print(result["recommendation"])
    return 0 if result.get("downgrade_below_992_safe") else 2


if __name__ == "__main__":
    raise SystemExit(main())
