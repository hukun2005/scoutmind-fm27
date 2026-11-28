"""V3.3.3-02 可重复性能基准（SQLite + 独立临时库）。

用法（在 backend 目录、使用项目 venv）::

    python scripts/perf_benchmark.py --players 10000 --transfers 50000 --label baseline
    python scripts/perf_benchmark.py --players 500000 --transfers 100000 --label baseline-500k

约束：
* 只写 ``%TEMP%`` 下的独立数据库，绝不连接真实存档；
* 结果包含每项 P50/P95/P99、CPU 时间、SQL 条数与结果指纹；
* 结果指纹用于证明优化前后返回内容一致（不是只看耗时）。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from tests.perf_support import (  # noqa: E402 - 先配置环境再导入 app
    apply_migrations,
    configure_environment,
    fresh_database_path,
    measure,
    seed_dataset,
    session_factory,
)


def _rss_mb() -> float | None:
    """进程常驻内存；psutil 可用时优先，Windows 上回退到 GetProcessMemoryInfo。"""
    try:
        import psutil  # type: ignore

        return round(psutil.Process().memory_info().rss / (1024 * 1024), 1)
    except Exception:  # noqa: BLE001
        pass
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        if ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return round(counters.WorkingSetSize / (1024 * 1024), 1)
    except Exception:  # noqa: BLE001
        return None
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="ScoutMind V3.3.3-02 performance benchmark")
    parser.add_argument("--players", type=int, default=10_000)
    parser.add_argument("--transfers", type=int, default=0)
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--label", default="run")
    parser.add_argument("--db", default="")
    parser.add_argument("--out", default="")
    parser.add_argument("--import-count", type=int, default=0, help="额外测量一次导入（0 表示不测）")
    parser.add_argument("--skip-seed", action="store_true", help="复用 --db 指向的已建库")
    args = parser.parse_args()

    db_path = Path(args.db) if args.db else fresh_database_path(f"scoutmind-perf-{args.players}-")
    configure_environment(db_path)

    if not args.skip_seed:
        if db_path.exists():
            db_path.unlink()
        apply_migrations(db_path, BACKEND_ROOT)

    from app.db import engine

    seed_started = time.perf_counter()
    info = seed_dataset(engine, args.players, args.transfers)
    seed_seconds = time.perf_counter() - seed_started

    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.models import AgentTask

    factory = session_factory()
    results: dict[str, object] = {
        "label": args.label,
        "players": args.players,
        "transfers": args.transfers,
        "clubs": info.clubs,
        "db_path": str(db_path),
        "seed_seconds": round(seed_seconds, 2),
        "rss_mb_after_seed": _rss_mb(),
        "cases": [],
    }

    with TestClient(create_app()) as client:

        def api_get(path: str):
            response = client.get(path)
            if response.status_code != 200:
                raise RuntimeError(f"{path} -> {response.status_code}: {response.text[:300]}")
            return response.json()

        deep_offset = min(20_000, max(0, args.players - 100))
        club_id = info.club_ids[1]
        detail_ids = [info.instance_ids[index] for index in range(0, args.players, max(1, args.players // 5))][:5]

        cases = [
            ("api_players_list_50", lambda: api_get("/api/v1/players?limit=50&sort=-updated_at")),
            ("api_players_search", lambda: api_get("/api/v1/players?limit=50&query=Player%2000123")),
            (
                "api_players_filter_multi",
                lambda: api_get("/api/v1/players?limit=50&position_group=FW&min_ca=140&max_age=25&sort=-ca"),
            ),
            ("api_players_filter_club", lambda: api_get(f"/api/v1/players?limit=50&club_id={club_id}")),
            ("api_players_deep_offset", lambda: api_get(f"/api/v1/players?limit=50&offset={deep_offset}")),
            (
                "api_player_detail_x5",
                lambda: [api_get(f"/api/v1/players/{instance_id}") for instance_id in detail_ids],
            ),
            ("api_transfers_list", lambda: api_get("/api/v1/transfers?limit=50&sort=-transfer_date")),
            ("api_transfers_position", lambda: api_get("/api/v1/transfers?limit=50&position_group=FW")),
            (
                "api_transfers_league_position",
                lambda: api_get("/api/v1/transfers?limit=50&league=League%203&position_group=DF"),
            ),
        ]

        for label, call in cases:
            results["cases"].append(measure(label, call, repeat=args.repeat, engine=engine).summary())

        # Agent 事件：写入 50 条并重放 500 条（不调用真实模型）。
        from app.agent_runtime.events import TaskEventBus

        session = factory()
        task = AgentTask(
            id=str(uuid.uuid4()),
            thread_id=str(uuid.uuid4()),
            user_id=info.user_id,
            fm_save_id=info.save_id,
            task_type="general",
            user_goal="benchmark",
            status="running",
        )
        session.add(task)
        session.commit()
        task_id = task.id
        session.close()

        bus = TaskEventBus()

        def append_50() -> int:
            worker = factory()
            try:
                for index in range(50):
                    bus.append(worker, task_id, "step_started", {"index": index, "tool": "bench"})
            finally:
                worker.close()
            return 50

        results["cases"].append(measure("agent_event_append_50", append_50, repeat=3, engine=engine).summary())

        def append_50_batched() -> int:
            """模拟节点层：同一事务内追加 50 条事件，只提交一次。"""
            worker = factory()
            try:
                for index in range(50):
                    bus.append(worker, task_id, "step_started", {"index": index, "tool": "bench"}, commit=False)
                worker.commit()
            finally:
                worker.close()
            return 50

        results["cases"].append(
            measure("agent_event_append_50_batched", append_50_batched, repeat=3, engine=engine).summary()
        )

        replay_session = factory()
        for index in range(500):
            bus.append(replay_session, task_id, "analysis_updated", {"index": index})
        replay_session.close()

        def replay_500() -> list[dict[str, object]]:
            worker = factory()
            try:
                return bus.list_after(worker, task_id, 0, 500)
            finally:
                worker.close()

        results["cases"].append(measure("agent_event_replay_500", replay_500, repeat=args.repeat, engine=engine).summary())

    if args.import_count:
        results["import"] = _import_benchmark(args.import_count, info.save_id)

    results["rss_mb_after_cases"] = _rss_mb()
    payload = json.dumps(results, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(payload, encoding="utf-8")
    print(payload)
    return 0


def _import_benchmark(count: int, save_id: int) -> dict[str, object]:
    """导入 N 名球员（含俱乐部与转会），测量吞吐与 SQL 条数。"""
    import tempfile
    from datetime import datetime, timezone

    from app.db import engine
    from app.ingestion.importer import ScanImporter
    from app.ingestion.protocol import ScanPayload
    from tests.helpers import club_row, player_row, scan_document, transfer_row

    from tests.perf_support import POSITIONS, session_factory

    rows = [
        player_row(
            f"IMP{index}",
            f"Imported Player {index:06d}",
            ca=100 + index % 100,
            pa=120 + index % 80,
            position=POSITIONS[index % len(POSITIONS)],
            club_uid="C1" if index % 2 else "C2",
            attributes={"finishing": 12.0, "passing": 13.0, "pace": 14.0},
        )
        for index in range(count)
    ]
    transfers = [
        transfer_row(f"IMP-T{index}", f"IMP{index % max(1, count)}", f"Imported Player {index % max(1, count):06d}", 1_000_000.0)
        for index in range(min(count, 5_000))
    ]
    document = scan_document(
        scan_id=f"perf-import-{int(time.time())}",
        when=datetime(2026, 11, 20, 12, tzinfo=timezone.utc),
        players=rows,
        transfers=transfers,
        clubs=[club_row("C1", "Bench United", user_club=True), club_row("C2", "Bench City")],
    )
    payload = ScanPayload.model_validate(document)

    def run_import() -> dict[str, object]:
        session = session_factory()()
        try:
            started = time.perf_counter()
            raw_dir = Path(tempfile.mkdtemp(prefix="scoutmind-perf-raw-"))
            outcome = ScanImporter(session, raw_dir=raw_dir).import_payload(save_id, payload)
            session.commit()
            return {
                "seconds": round(time.perf_counter() - started, 3),
                "snapshots": outcome.snapshots_created,
                "transfers": outcome.transfers_created,
                "status": outcome.status,
            }
        finally:
            session.close()

    first = run_import()
    second = run_import()  # 同 scan_id 幂等重放，不重复写入
    return {
        "players": count,
        "first": first,
        "replay": second,
        "players_per_second": round(count / max(0.001, float(first["seconds"])), 1),
        "rss_mb": _rss_mb(),
        "queries_engine": "see case-level query counts",
    }


if __name__ == "__main__":
    raise SystemExit(main())
