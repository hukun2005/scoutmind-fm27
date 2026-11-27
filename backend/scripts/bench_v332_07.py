"""V3.3.2-07 学习/报价规模基准：1k、10k、60k 成交案例。

在临时 SQLite 库中生成合成成交案例（``source='synthetic_bench'``），只测读取路径：
学习状态、案例分页 P95、俱乐部画像与买入报价生成。不会写入真实存档。

用法::

    python backend/scripts/bench_v332_07.py --sizes 1000,10000,60000 \
        --output docs/reports/v332_07_bench.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
import tracemalloc
from datetime import date
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from sqlalchemy import insert, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db import build_engine  # noqa: E402
from app.models import (  # noqa: E402
    Base,
    Club,
    FmSave,
    Player,
    PlayerInstance,
    PlayerSnapshot,
    Transfer,
    User,
)
from app.services import transfer_director, transfer_strategy  # noqa: E402
from app.utils import utcnow  # noqa: E402

POOL = 200
CLUBS = 20


def _median_ms(fn, runs: int = 5) -> float:
    fn()
    samples = []
    for _ in range(runs):
        started = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - started) * 1000)
    return round(statistics.median(samples), 1)


def _seed(db, size: int) -> tuple[int, int]:
    user = User(username=f"bench07-{size}")
    db.add(user)
    db.commit()
    save = FmSave(user_id=user.id, name=f"bench-{size}", is_active=True, game_build="26620374")
    db.add(save)
    db.commit()

    clubs = [Club(fm_save_id=save.id, uid=f"bench-club-{index}", name=f"Bench Club {index}") for index in range(CLUBS)]
    db.add_all(clubs)
    db.commit()

    pool = []
    for index in range(POOL):
        player = Player(full_name=f"Bench Player {index}", normalized_name=f"bench player {index}")
        db.add(player)
        db.flush()
        instance = PlayerInstance(
            player_id=player.id,
            fm_save_id=save.id,
            save_local_uid=f"bench-{index}",
            club_id=clubs[index % CLUBS].id,
            position="ST",
        )
        db.add(instance)
        db.flush()
        snapshot = PlayerSnapshot(
            player_instance_id=instance.id,
            observed_at=utcnow(),
            game_date=date(2026, 7, 1),
            age=25,
            ca=150,
            market_value=10_000_000,
            contract_end=date(2029, 6, 30),
            club_id=clubs[index % CLUBS].id,
            position="ST",
            source="synthetic_bench",
        )
        db.add(snapshot)
        db.flush()
        instance.latest_snapshot_id = snapshot.id
        pool.append(instance.id)
    db.commit()

    now = utcnow()
    rows = []
    for index in range(size):
        fee = 5_000_000 + (index % 40) * 500_000
        rows.append(
            {
                "fm_save_id": save.id,
                "source_record_id": f"bench-{size}-{index}",
                "player_instance_id": pool[index % POOL],
                "player_name": f"Bench Case {index}",
                "from_club_id": clubs[index % CLUBS].id,
                "to_club_id": clubs[(index + 1) % CLUBS].id,
                "transfer_type": "loan" if index % 7 == 0 else "permanent",
                "status": "completed",
                "transfer_date": date(2026, 1, 1),
                "currency": "EUR",
                "fee_paid": fee,
                "base_fee": fee,
                "player_age_at_transfer": 25,
                "contract_remaining_months": 24,
                "source": "benchmark_fixture",
                "created_at": now,
                "updated_at": now,
            }
        )
        if len(rows) >= 2000:
            db.execute(insert(Transfer), rows)
            db.commit()
            rows = []
    if rows:
        db.execute(insert(Transfer), rows)
        db.commit()
    return save.id, pool[0]


def _run(size: int, output_dir: str) -> dict:
    database_path = Path(output_dir) / f"bench07_{size}.db"
    engine = build_engine(f"sqlite:///{database_path.as_posix()}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = session_factory()
    save_id, target_id = _seed(db, size)
    target = db.get(PlayerInstance, target_id)

    tracemalloc.start()
    started = time.perf_counter()
    status = transfer_strategy.learning_status(db, save_id)
    status_ms = round((time.perf_counter() - started) * 1000, 1)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    list_p95 = _median_ms(lambda: transfer_strategy.list_cases(db, save_id, limit=50, offset=0))
    habits_ms = _median_ms(lambda: transfer_strategy.club_habits(db, save_id, 1))
    quote_ms = _median_ms(lambda: transfer_director.generate_purchase_offers(db, target), runs=3)

    result = {
        "size": size,
        "cases": status["totals"]["cases"],
        "learning_status_ms": status_ms,
        "learning_peak_mb": round(peak / 1024 / 1024, 1),
        "list_cases_p50_ms": list_p95,
        "club_habits_ms": habits_ms,
        "purchase_quote_ms": quote_ms,
        "adjustment_applied": transfer_director.generate_purchase_offers(db, target)["strategy_adjustment"]["applied"],
    }
    db.close()
    engine.dispose()
    database_path.unlink(missing_ok=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", default="1000,10000,60000")
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    sizes = [int(item) for item in args.sizes.split(",") if item.strip()]
    results = []
    with tempfile.TemporaryDirectory(prefix="sm07-bench-") as tmp:
        for size in sizes:
            results.append(_run(size, tmp))
            print(json.dumps(results[-1], ensure_ascii=False), flush=True)
    payload = {"scenario": "v332_07_learning_and_quotes", "results": results}
    if args.output:
        Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
