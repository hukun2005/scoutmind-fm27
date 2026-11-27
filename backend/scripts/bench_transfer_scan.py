"""V3.3.2-05.2 分批扫描基准：1k / 10k / 60k 合成存档 + 真实存档副本只读验收。

用法::

    python scripts/bench_transfer_scan.py --sizes 1000,10000,60000
    python scripts/bench_transfer_scan.py --database-url sqlite:///path/to/copy.db --save-id 2

脚本只写临时库或明确传入的数据库副本；不会修改 ``SCOUTMIND_DATABASE_URL`` 指向的生产库。
输出为逐行 JSON，便于写进验收报告。覆盖不完整或出现异常时以非 0 退出。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import tracemalloc
from datetime import date, datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import create_engine, func, insert, select, text  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.db import Base  # noqa: E402
from app.models import (  # noqa: E402
    Club,
    FmSave,
    Player,
    PlayerAvailability,
    PlayerInstance,
    PlayerSnapshot,
    TransferOpportunity,
    User,
)
from app.services import club_linkage, transfer_radar  # noqa: E402
from app.utils import utcnow  # noqa: E402

GAME_DATE = date(2026, 7, 1)


def _seed(database_url: str, total: int) -> int:
    engine = create_engine(database_url, future=True)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True)()
    now = datetime(2026, 7, 1, 12, 0, 0)
    session.add(User(username="bench", display_name="Benchmark"))
    session.commit()
    save = FmSave(user_id=1, name=f"bench-{total}", game_version="27.0", game_build="bench", is_active=True)
    session.add(save)
    session.commit()
    club_count = max(20, total // 25)
    clubs = [Club(fm_save_id=save.id, uid=f"bench-club-{i}", name=f"Bench Club {i:04d}") for i in range(club_count)]
    session.add_all(clubs)
    session.commit()

    players, instances, snapshots, availabilities = [], [], [], []
    for index in range(total):
        players.append({"full_name": f"Bench Player {index:06d}", "normalized_name": f"bench player {index:06d}"})
    session.execute(insert(Player), players)
    session.commit()
    player_ids = [row[0] for row in session.execute(select(Player.id).order_by(Player.id).limit(total))]
    for index in range(total):
        club = clubs[index % club_count]
        instances.append(
            {
                "player_id": player_ids[index],
                "fm_save_id": save.id,
                "save_local_uid": f"bench-{index:06d}",
                "uid_occurrence": 0,
                "club_id": club.id,
                "created_at": now,
                "updated_at": now,
            }
        )
    session.execute(insert(PlayerInstance), instances)
    session.commit()
    instance_ids = [
        row[0]
        for row in session.execute(
            select(PlayerInstance.id).where(PlayerInstance.fm_save_id == save.id).order_by(PlayerInstance.id)
        )
    ]
    for index, instance_id in enumerate(instance_ids):
        club = clubs[index % club_count]
        snapshots.append(
            {
                "player_instance_id": instance_id,
                "observed_at": now,
                "imported_at": now,
                "game_date": GAME_DATE,
                "age": 20 + index % 15,
                "ca": 110 + index % 40,
                "pa": 150,
                "market_value": 5_000_000 + index % 50 * 100_000,
                "wage": 10_000,
                "contract_end": date(2026, 9, 30) if index % 5 == 0 else date(2028, 6, 30),
                "club_id": club.id,
                "club_uid": club.uid,
                "position": "ST" if index % 2 else "CB",
                "source": "bench",
                "created_at": now,
                "updated_at": now,
            }
        )
        availabilities.append(
            {
                "player_instance_id": instance_id,
                "observed_at": now,
                "listed": index % 7 == 0,
                "loan_listed": index % 11 == 0,
                "set_for_release": False,
                "source": "bench",
                "created_at": now,
                "updated_at": now,
            }
        )
    session.execute(insert(PlayerSnapshot), snapshots)
    session.execute(insert(PlayerAvailability), availabilities)
    session.commit()
    # 回填 latest_snapshot_id（基准数据用批量 SQL，避免逐行 ORM 提交）。
    session.execute(
        text(
            "update player_instances set latest_snapshot_id = ("
            "select max(id) from player_snapshots s where s.player_instance_id = player_instances.id"
            ") where fm_save_id = :save_id"
        ),
        {"save_id": save.id},
    )
    session.commit()
    save_id = save.id
    session.close()
    engine.dispose()
    return save_id


def _measure(database_url: str, save_id: int, batch_size: int) -> dict:
    engine = create_engine(database_url, future=True)
    session = sessionmaker(bind=engine, future=True)()
    batch_times: list[float] = []
    last = {"at": time.perf_counter()}

    def progress_cb(processed, total, matched, failed, last_id):
        now = time.perf_counter()
        batch_times.append(now - last["at"])
        last["at"] = now

    tracemalloc.start()
    started = time.perf_counter()
    result = transfer_radar.scan_batched(
        session, save_id, batch_size=batch_size, progress_cb=progress_cb
    )
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    active = int(
        session.scalar(
            select(func.count())
            .select_from(TransferOpportunity)
            .where(TransferOpportunity.fm_save_id == save_id, TransferOpportunity.active.is_(True))
        )
        or 0
    )
    listed_players = int(
        session.scalar(
            select(func.count(func.distinct(TransferOpportunity.player_instance_id))).where(
                TransferOpportunity.fm_save_id == save_id,
                TransferOpportunity.opportunity_type == "listed",
            )
        )
        or 0
    )
    expected_listed = int(
        session.scalar(
            select(func.count()).select_from(PlayerAvailability).where(PlayerAvailability.listed.is_(True))
        )
        or 0
    )
    session.close()
    engine.dispose()
    scanned = result["scanned_players"]
    return {
        "mode": "synthetic",
        "players": scanned,
        "batch_size": batch_size,
        "elapsed_seconds": round(elapsed, 3),
        "players_per_second": round(scanned / elapsed, 1) if elapsed else None,
        "batches": len(batch_times),
        "max_batch_seconds": round(max(batch_times), 3) if batch_times else None,
        "avg_batch_seconds": round(sum(batch_times) / len(batch_times), 3) if batch_times else None,
        "created": result["created"],
        "updated": result["updated"],
        "deactivated": result["deactivated"],
        "active_opportunities": active,
        "listed_players": listed_players,
        "expected_listed_players": expected_listed,
        "peak_memory_mb": round(peak / 1024 / 1024, 1),
        "coverage_ok": listed_players == expected_listed,
    }


def _real(database_url: str, save_id: int, batch_size: int) -> dict:
    engine = create_engine(database_url, future=True)
    session = sessionmaker(bind=engine, future=True)()
    before = club_linkage.health(session, save_id)
    started = time.perf_counter()
    result = transfer_radar.scan_batched(session, save_id, batch_size=batch_size)
    elapsed = time.perf_counter() - started
    after = club_linkage.health(session, save_id)
    session.close()
    engine.dispose()
    return {
        "mode": "real-copy",
        "players": result["scanned_players"],
        "batch_size": batch_size,
        "elapsed_seconds": round(elapsed, 3),
        "players_per_second": round(result["scanned_players"] / elapsed, 1) if elapsed else None,
        "created": result["created"],
        "updated": result["updated"],
        "deactivated": result["deactivated"],
        "active_opportunities": result["active_opportunities"],
        "club_link_before": before["states"],
        "club_link_rate_before": before["club_link_rate"],
        "club_link_after": after["states"],
        "club_link_rate_after": after["club_link_rate"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", default="1000,10000,60000", help="合成的球员规模列表")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--database-url", help="真实数据库副本 URL；给出时只跑该库")
    parser.add_argument("--save-id", type=int, help="真实库中的存档 id")
    parser.add_argument("--keep", action="store_true", help="保留临时库以便复查")
    args = parser.parse_args()

    failures = []
    if args.database_url:
        if not args.save_id:
            parser.error("--database-url 必须同时提供 --save-id")
        if "SCOUTMIND_DATABASE_URL" in os.environ:
            print(json.dumps({"warning": "忽略 SCOUTMIND_DATABASE_URL，只使用 --database-url"}, ensure_ascii=False))
        report = _real(args.database_url, args.save_id, args.batch_size)
        print(json.dumps(report, ensure_ascii=False))
        return 0

    for size in [int(part) for part in args.sizes.split(",") if part.strip()]:
        directory = Path(tempfile.mkdtemp(prefix=f"bench-{size}-"))
        database_url = f"sqlite:///{(directory / 'bench.db').as_posix()}"
        save_id = _seed(database_url, size)
        report = _measure(database_url, save_id, args.batch_size)
        report["target_players"] = size
        print(json.dumps(report, ensure_ascii=False), flush=True)
        if not report["coverage_ok"]:
            failures.append(size)
        if not args.keep:
            for path in directory.glob("*"):
                path.unlink()
            directory.rmdir()
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
