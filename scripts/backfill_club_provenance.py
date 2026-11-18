"""回填俱乐部来源信息（给解析器之前导入的俱乐部补 source/confidence/normalized_name）。

解析器上线前的俱乐部记录只有 uid 与名称，界面会显示"来源未知"。这些记录其实都来自同一个渠道：
球员行里的俱乐部名称（``fs-<slug>`` / ``name:<slug>``），所以按该渠道回填，并写入归一化名称，
让之后的名称匹配能命中同一条记录。

用法::

    .\\backend\\.venv\\Scripts\\python.exe scripts\\backfill_club_provenance.py
    .\\backend\\.venv\\Scripts\\python.exe scripts\\backfill_club_provenance.py --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from sqlalchemy import select  # noqa: E402

from app.clubs import SOURCE_PLAYER_FIELD, SOURCE_CONFIDENCE, normalize_name  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Club  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="回填俱乐部的来源与归一化名称")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    with SessionLocal() as session:
        rows = list(session.scalars(select(Club).where(Club.source.is_(None))))
        print(f"待回填 {len(rows)} 条俱乐部记录")
        for club in rows:
            normalized = club.normalized_name or normalize_name(club.name)
            if args.dry_run:
                print(f"  [dry-run] #{club.id} {club.name} -> {SOURCE_PLAYER_FIELD} / {normalized}")
                continue
            club.normalized_name = normalized or None
            club.source = SOURCE_PLAYER_FIELD
            club.confidence = SOURCE_CONFIDENCE[SOURCE_PLAYER_FIELD]
        if not args.dry_run:
            session.commit()
            print("已回填并提交")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
