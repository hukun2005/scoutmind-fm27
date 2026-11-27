"""V3.3.2 查询性能基准：同一脚本可在 V3.3.1（优化前）与 V3.3.2（优化后）代码上运行。

用法::

    SCOUTMIND_DATABASE_URL=sqlite:///C:/path/scoutmind.db \
        python backend/scripts/bench_v332.py --label before --output before.json

只读真实数据库副本；不会导入、写入或修改任何业务数据。每个场景预热 1 次，再取 3 次中位数。
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from sqlalchemy import select  # noqa: E402

from app.analytics import players as player_analytics  # noqa: E402
from app.analytics import squad as squad_analytics  # noqa: E402
from app.analytics.recruitment_recommend import recommend  # noqa: E402
try:  # V3.3.2 及以后
    from app.db import SessionFactory  # noqa: E402
except ImportError:  # V3.3.1 基线
    from app.db import SessionLocal as SessionFactory  # noqa: E402
from app.models import FmSave, PlayerInstance  # noqa: E402


def _profile(session, save_id: int, instance_id: int):
    """兼容 V3.3.1 (instance_id) 与 V3.3.2 (save_id, instance_id) 两种签名。"""
    try:
        return player_analytics.player_profile(session, save_id, instance_id)
    except TypeError:
        return player_analytics.player_profile(session, instance_id)


def _median_ms(fn, runs: int = 3, reset=None) -> float:
    fn()
    samples = []
    for _ in range(runs):
        if reset is not None:
            reset()
        started = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - started) * 1000)
    return round(statistics.median(samples), 1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="run")
    parser.add_argument("--output", default="")
    parser.add_argument("--save-id", type=int, default=0)
    parser.add_argument("--no-cache", action="store_true", help="每次计时前清空查询缓存，测真实数据库耗时")
    parser.add_argument(
        "--slot-scenario",
        action="store_true",
        help="额外测量带位置过滤的引援推荐（AI 足球总监实际使用的路径）",
    )
    args = parser.parse_args()

    reset = None
    if args.no_cache:
        try:
            from app.services import query_cache

            reset = query_cache.clear
        except ImportError:
            reset = None

    session = SessionFactory()
    try:
        if args.save_id:
            save_id = args.save_id
        else:
            save_id = session.scalar(select(FmSave.id).where(FmSave.is_active.is_(True)))
            if save_id is None:
                save_id = session.scalar(select(FmSave.id))
        if save_id is None:
            print("没有可用存档", file=sys.stderr)
            return 2
        instance_id = session.scalar(
            select(PlayerInstance.id).where(PlayerInstance.fm_save_id == save_id).limit(1)
        )
        if instance_id is None:
            print("存档没有球员", file=sys.stderr)
            return 2

        default_filter = player_analytics.PlayerFilter()
        search_filter = player_analytics.PlayerFilter(query="a")
        scenarios = {
            "players_page1": lambda: player_analytics.list_players(session, save_id, default_filter, limit=50),
            "players_search": lambda: player_analytics.list_players(session, save_id, search_filter, limit=50),
            "player_profile": lambda: _profile(session, save_id, instance_id),
            "coverage": lambda: player_analytics.coverage_for_save(session, save_id),
            "squad_overview": lambda: squad_analytics.squad_overview(session, save_id),
            "recruitment_page1": lambda: recommend(session, save_id, page_size=20),
        }
        if args.slot_scenario:
            scenarios["recruitment_slot_st"] = lambda: recommend(session, save_id, slot="ST", page_size=3)
        results = {}
        for name, fn in scenarios.items():
            try:
                results[name] = {"median_ms": _median_ms(fn, reset=reset)}
            except Exception as exc:  # 记录失败而不是伪造数字
                results[name] = {"error": f"{type(exc).__name__}: {str(exc)[:220]}"}
        payload = {
            "label": args.label,
            "database": str(os.environ.get("SCOUTMIND_DATABASE_URL", "")),
            "save_id": save_id,
            "instance_id": instance_id,
            "cache": "off" if args.no_cache else "on",
            "results": results,
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        print(text)
        if args.output:
            Path(args.output).write_text(text + "\n", encoding="utf-8")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
