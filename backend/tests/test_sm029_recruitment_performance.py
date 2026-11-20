"""SM-029：Recruitment Engine 在 1 万 / 5 万球员规模下的查询与耗时。"""

from __future__ import annotations

import time
from datetime import date, datetime

import pytest
from sqlalchemy import event, insert, select

from app.analytics.recruitment import candidate_pool, compare_players, search_recruitment
from app.models import Club, FmSave, Player, PlayerInstance, PlayerSnapshot


def _batch(db, table, rows: list[dict], size: int = 40) -> None:
    """SQLite 变量上限可能是 999；按 40 行分批，避免 too many SQL variables。"""
    for start in range(0, len(rows), size):
        db.execute(insert(table), rows[start : start + size])


def _seed(db, save, count: int) -> None:
    """显式 id 批量插入，避免逐行 flush；数据是真实 SQLite 行，不是内存假对象。"""
    club = Club(id=1, fm_save_id=save.id, uid="perf-club", name="Perf FC", league="Test League")
    _batch(db, Club, [{"id": 1, "fm_save_id": save.id, "uid": "perf-club", "name": "Perf FC",
                               "league": "Test League", "is_user_club": False, "external_ids_json": "{}",
                               "created_at": datetime(2026, 1, 1), "updated_at": datetime(2026, 1, 1)}])
    players = [
        {"id": index, "full_name": f"Perf {index}", "normalized_name": f"perf-{index}",
         "created_at": datetime(2026, 1, 1), "updated_at": datetime(2026, 1, 1)}
        for index in range(1, count + 1)
    ]
    _batch(db, Player, players)
    instances = [
        {"id": index, "player_id": index, "fm_save_id": save.id, "save_local_uid": f"P{index}",
         "uid_occurrence": 0, "position": "ST" if index % 3 else "DC", "first_seen_at": datetime(2026, 1, 1), "last_seen_at": datetime(2026, 1, 1),
         "created_at": datetime(2026, 1, 1), "updated_at": datetime(2026, 1, 1)}
        for index in range(1, count + 1)
    ]
    _batch(db, PlayerInstance, instances)
    snapshots = [
        {
            "id": index,
            "player_instance_id": index,
            "observed_at": datetime(2026, 7, 1),
            "game_date": date(2026, 7, 1),
            "imported_at": datetime(2026, 7, 1),
            "age": 18 + index % 15,
            "ca": 80 + index % 80,
            "pa": 120 + index % 60,
            "market_value": 1_000_000 + (index % 50) * 1_000_000,
            "wage": 5_000 + (index % 20) * 2_000,
            "club_id": 1,
            "position": "ST" if index % 3 else "DC",
            "source": "manual",
            "created_at": datetime(2026, 7, 1),
            "updated_at": datetime(2026, 7, 1),
        }
        for index in range(1, count + 1)
    ]
    _batch(db, PlayerSnapshot, snapshots)
    db.commit()


def _measure(db, save, count: int) -> tuple[dict, int, float]:
    engine = db.get_bind()
    counter = {"n": 0}

    def before(conn, cursor, statement, parameters, context, executemany):
        counter["n"] += 1

    event.listen(engine, "before_cursor_execute", before)
    started = time.perf_counter()
    result = search_recruitment(
        db, save.id, slot="ST", min_age=18, max_age=32, max_value=60_000_000, limit=20, with_stats=True
    )
    elapsed = time.perf_counter() - started
    event.remove(engine, "before_cursor_execute", before)
    return result, counter["n"], elapsed


def test_search_scales_to_10k(db, save) -> None:
    _seed(db, save, 10_000)
    result, queries, elapsed = _measure(db, save, 10_000)
    assert len(result["items"]) == 20
    assert result["performance"]["pool_size"] <= 10_000
    assert queries <= 10, f"查询次数应保持常数，实际 {queries}"
    assert elapsed < 3.0
    print(f"10k: queries={queries} elapsed={elapsed:.3f}s pool={result['performance']['pool_size']}")


def test_search_scales_to_50k(db, save) -> None:
    _seed(db, save, 50_000)
    result, queries, elapsed = _measure(db, save, 50_000)
    assert len(result["items"]) == 20
    assert result["performance"]["pool_size"] <= 50_000
    assert queries <= 10, f"查询次数应保持常数（无 N+1），实际 {queries}"
    assert elapsed < 8.0
    scores = [item["score"] for item in result["items"] if item["score"] is not None]
    assert scores == sorted(scores, reverse=True), "必须按分数稳定降序"
    print(f"50k: queries={queries} elapsed={elapsed:.3f}s pool={result['performance']['pool_size']}")


def test_compare_at_50k_does_not_explode_queries(db, save) -> None:
    _seed(db, save, 50_000)
    ids = [item.id for item in db.scalars(select(PlayerInstance).limit(5))]
    engine = db.get_bind()
    counter = {"n": 0}

    def before(conn, cursor, statement, parameters, context, executemany):
        counter["n"] += 1

    event.listen(engine, "before_cursor_execute", before)
    started = time.perf_counter()
    result = compare_players(db, save.id, ids)
    elapsed = time.perf_counter() - started
    event.remove(engine, "before_cursor_execute", before)
    assert result["compared"] == 5
    assert counter["n"] <= 8
    assert elapsed < 8.0
    print(f"50k compare: queries={counter['n']} elapsed={elapsed:.3f}s")


def test_missing_values_are_not_zeroed_at_scale(db, save) -> None:
    _seed(db, save, 2_000)
    # 让部分球员缺少工资/身价：过滤时被排除，但不过滤时仍保留 NULL 语义。
    db.execute(
        PlayerSnapshot.__table__.update().where(PlayerSnapshot.id <= 100).values(wage=None, market_value=None)
    )
    db.commit()
    pool = candidate_pool(db, save.id)
    missing = [item for item in pool if item.wage is None]
    assert missing, "缺工资的球员必须仍在池中，不能被当成 0"
    assert all(item.wage is None for item in missing)
