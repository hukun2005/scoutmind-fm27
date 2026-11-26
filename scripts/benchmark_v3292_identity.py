"""V3.2.9.2 Phase 5：全库身份扫描性能基准。

用法：

    python scripts/benchmark_v3292_identity.py --sizes 50000 100000 200000

每个规模使用独立的临时 SQLite 数据库；只测“身份扫描”本身，不包含导入与网络。
输出 JSON（stdout），字段：规模、耗时、每秒处理量、内存峰值、冲突数、审核项数、错误数。
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
import tracemalloc
from datetime import date, datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))


def _seed(connection, total: int) -> None:
    now = datetime(2026, 11, 26, 9, 0, 0).isoformat(" ")
    connection.exec_driver_sql(
        "insert into users (id, username, created_at, updated_at) values (1, 'bench', ?, ?)",
        (now, now),
    )
    connection.exec_driver_sql(
        "insert into fm_saves (id, user_id, name, game_build, is_active, created_at, updated_at) "
        "values (1, 1, 'Benchmark Save', '26620374', 1, ?, ?)",
        (now, now),
    )

    players: list[tuple] = []
    instances: list[tuple] = []
    for index in range(1, total + 1):
        # 每 20 个实例制造一对同名不同生日，用于验证冲突路径；其余为唯一姓名。
        if index % 20 == 0:
            name = f"Duplicate Pair {index // 20}"
            birth = date(1990, 1, 1)
        elif index % 20 == 1 and index > 1:
            name = f"Duplicate Pair {(index - 1) // 20}"
            birth = date(1995, 5, 5)
        else:
            name = f"Benchmark Player {index}"
            birth = date(1998, 1, 1)
        normalized = name.lower()
        players.append((index, name, normalized, birth.isoformat(), now, now))
        instances.append((index, index, 1, f"UID{index:08d}", 0, f"G-{index}", now, now))

    for start in range(0, len(players), 5000):
        connection.exec_driver_sql(
            "insert into players (id, full_name, normalized_name, birth_date, created_at, updated_at) "
            "values (?, ?, ?, ?, ?, ?)",
            players[start : start + 5000],
        )
    for start in range(0, len(instances), 5000):
        connection.exec_driver_sql(
            "insert into player_instances "
            "(id, player_id, fm_save_id, save_local_uid, uid_occurrence, game_unique_id, created_at, updated_at) "
            "values (?, ?, ?, ?, ?, ?, ?, ?)",
            instances[start : start + 5000],
        )


def run_one(total: int) -> dict[str, object]:
    from sqlalchemy import create_engine, func, select
    from sqlalchemy.orm import Session

    from app.models import Base, IdentityScanRun, PlayerIdentityReviewItem
    from app.services import identity_engine

    with tempfile.TemporaryDirectory(prefix="scoutmind-bench-") as directory:
        database_path = Path(directory) / "bench.db"
        engine = create_engine(f"sqlite:///{database_path.as_posix()}", future=True)
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            _seed(connection, total)

        session = Session(engine)
        try:
            tracemalloc.start()
            started = time.perf_counter()
            run = identity_engine.start_scan(
                session,
                1,
                scan_id=f"bench-{total}",
                batch_size=500,
                fingerprint="si:v1:file:bench",
                game_build="26620374",
                layout_version="FM27_1",
            )
            run = identity_engine.run_scan(session, run)
            elapsed = time.perf_counter() - started
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()

            reviews = int(
                session.scalar(select(func.count()).select_from(PlayerIdentityReviewItem).where(
                    PlayerIdentityReviewItem.fm_save_id == 1
                ))
                or 0
            )
            status = session.scalar(
                select(IdentityScanRun.status).where(IdentityScanRun.id == run.id)
            )
            return {
                "instances": total,
                "status": status,
                "elapsed_seconds": round(elapsed, 3),
                "instances_per_second": round(total / elapsed, 1) if elapsed else None,
                "peak_memory_mb": round(peak / (1024 * 1024), 2),
                "processed": run.processed_count,
                "matched": run.matched_count,
                "conflicts": run.conflict_count,
                "failed": run.failed_count,
                "review_items": reviews,
                "batch_size": run.batch_size,
            }
        finally:
            session.close()
            engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="V3.2.9.2 identity scan benchmark")
    parser.add_argument("--sizes", type=int, nargs="+", default=[50_000, 100_000, 200_000])
    args = parser.parse_args()

    results = [run_one(size) for size in args.sizes]
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
