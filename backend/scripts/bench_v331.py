"""V3.3.1 性能基准：在隔离的合成 SQLite 数据库上测量关键查询。

数据全部是**合成数据**（名字为 ``Bench Player N``），不来自真实 FM27 存档；
结论只用于比较优化前后同一算法/同一数据量下的相对耗时。

用法::

    python scripts/bench_v331.py --players 3000 --transfers 1000

输出 JSON：每个场景的中位数耗时（毫秒），以及关注名单「逐行查询（旧）」与
「批量查询（新）」的对照。
"""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.analytics.players import PlayerFilter, latest_snapshot, list_players, player_profile
from app.analytics.recruitment import search_recruitment
from app.analytics.squad import position_depth, roster
from app.models import (
    Base,
    Club,
    FmSave,
    Player,
    PlayerInstance,
    PlayerSnapshot,
    Transfer,
    User,
    Watchlist,
    WatchlistItem,
)
from app.services import watchlist as watch_service

POSITIONS = ["GK", "CB", "LB", "RB", "DM", "CM", "AM", "LW", "RW", "ST"]


def _median(session_factory: sessionmaker, action, rounds: int = 3) -> float:
    timings: list[float] = []
    for _ in range(rounds):
        session = session_factory()
        started = time.perf_counter()
        action(session)
        timings.append((time.perf_counter() - started) * 1000)
        session.close()
    return round(statistics.median(timings), 2)


def _seed(session: Session, players: int, transfers: int) -> int:
    user = User(username="bench", display_name="基准")
    session.add(user)
    session.flush()
    save = FmSave(user_id=user.id, name="合成基准存档", is_active=True)
    session.add(save)
    session.flush()

    clubs = [
        Club(fm_save_id=save.id, uid=f"BENCH-C{i}", name=f"Bench Club {i}", is_user_club=(i == 0))
        for i in range(4)
    ]
    session.add_all(clubs)
    session.flush()

    observed = datetime(2026, 11, 1, 12, 0, 0)
    batch: list[object] = []
    for index in range(players):
        player = Player(
            full_name=f"Bench Player {index:05d}",
            normalized_name=f"bench player {index:05d}",
            birth_date=date(1998 + index % 12, 1 + index % 12, 1),
            nationality="Benchland",
        )
        session.add(player)
        session.flush()
        instance = PlayerInstance(
            player_id=player.id,
            fm_save_id=save.id,
            save_local_uid=f"BENCH-P{index:05d}",
            uid_occurrence=0,
            club_id=clubs[index % len(clubs)].id,
            position=POSITIONS[index % len(POSITIONS)],
            last_seen_at=observed,
        )
        session.add(instance)
        session.flush()
        batch.append(
            PlayerSnapshot(
                player_instance_id=instance.id,
                observed_at=observed,
                game_date=date(2026, 11, 1),
                age=18 + index % 20,
                ca=110 + (index * 7) % 80,
                pa=120 + (index * 11) % 80,
                market_value=1_000_000 + (index * 137_000) % 60_000_000,
                wage=5_000 + (index * 311) % 90_000,
                contract_end=date(2027 + index % 4, 6, 30),
                club_id=clubs[index % len(clubs)].id,
                position=POSITIONS[index % len(POSITIONS)],
                data_completeness=0.9,
                source="synthetic_fixture",
            )
        )
        if len(batch) >= 500:
            session.add_all(batch)
            session.flush()
            batch.clear()
    if batch:
        session.add_all(batch)

    for index in range(transfers):
        session.add(
            Transfer(
                fm_save_id=save.id,
                source_record_id=f"BENCH-T{index:05d}",
                player_name=f"Bench Player {index % players:05d}",
                from_club_name="Bench Club 0",
                to_club_name=f"Bench Club {1 + index % 3}",
                transfer_type="permanent",
                status="completed",
                transfer_date=date(2025, 1, 1) + timedelta(days=index % 700),
                currency="EUR",
                source="synthetic_fixture",
                effective_fee=1_000_000 + (index * 53_000) % 40_000_000,
                player_age_at_transfer=18 + index % 15,
                player_ca_at_transfer=110 + index % 70,
                player_pa_at_transfer=130 + index % 60,
            )
        )

    default_list = Watchlist(user_id=user.id, fm_save_id=save.id, name="默认关注")
    shortlist = Watchlist(user_id=user.id, fm_save_id=save.id, name="引援候选")
    session.add_all([default_list, shortlist])
    session.flush()
    instance_ids = [
        row[0]
        for row in session.execute(
            select(PlayerInstance.id).where(PlayerInstance.fm_save_id == save.id).limit(120)
        ).all()
    ]
    for offset, instance_id in enumerate(instance_ids):
        session.add(
            WatchlistItem(
                watchlist_id=(default_list if offset % 3 else shortlist).id,
                player_instance_id=instance_id,
                status="watching" if offset % 2 else "preparing",
                note="bench",
                source="manual",
            )
        )
    session.commit()
    return save.id


def _legacy_watchlist(session: Session, save_id: int) -> int:
    """旧实现：每个关注项单独取实例 + 最新快照（N+1）。"""
    items = session.execute(
        select(WatchlistItem)
        .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
        .where(Watchlist.fm_save_id == save_id)
    ).scalars().all()
    count = 0
    for item in items:
        instance = session.get(PlayerInstance, item.player_instance_id)
        if instance is None:
            continue
        snapshot = latest_snapshot(session, instance.id)
        if snapshot is not None:
            count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--players", type=int, default=3000)
    parser.add_argument("--transfers", type=int, default=1000)
    args = parser.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="scoutmind-bench-"))
    database_url = f"sqlite:///{(tmp / 'bench.db').as_posix()}"
    engine = create_engine(database_url, future=True)
    Base.metadata.create_all(engine)
    SessionFactory = sessionmaker(bind=engine, expire_on_commit=False)

    session = SessionFactory()
    save_id = _seed(session, args.players, args.transfers)
    first_instance = session.scalar(select(PlayerInstance.id).where(PlayerInstance.fm_save_id == save_id))
    owner_id = session.scalar(select(FmSave.user_id).where(FmSave.id == save_id))
    session.close()

    results: dict[str, object] = {
        "dataset": {"players": args.players, "transfers": args.transfers, "synthetic": True, "note": "全部为合成数据，不代表真实 FM27 存档"},
        "timings_ms": {
            "players_page_50": _median(SessionFactory, lambda s: list_players(s, save_id, PlayerFilter(sort="-ca"), limit=50, offset=0)),
            "players_name_filter": _median(SessionFactory, lambda s: list_players(s, save_id, PlayerFilter(query="Bench Player 001", sort="-ca"), limit=50, offset=0)),
            "player_profile": _median(SessionFactory, lambda s: player_profile(s, int(first_instance))),
            "squad_roster": _median(SessionFactory, lambda s: roster(s, save_id)),
            "squad_depth": _median(SessionFactory, lambda s: position_depth(roster(s, save_id))),
            "recruitment_search_st": _median(SessionFactory, lambda s: search_recruitment(s, save_id, slot="ST", limit=20)),
            "watchlist_bulk": _median(SessionFactory, lambda s: watch_service.list_items(s, save_id)),
            "watchlist_legacy_n_plus_1": _median(SessionFactory, lambda s: _legacy_watchlist(s, save_id)),
            "watchlist_lists": _median(SessionFactory, lambda s: watch_service.list_groups(s, int(owner_id), save_id)),
            "watchlist_status_filter": _median(SessionFactory, lambda s: watch_service.list_items(s, save_id, status="preparing")),
        },
        "query_plans": {},
    }

    with engine.connect() as connection:
        for label, sql in {
            "watchlist_by_save": "select * from watchlist_items wi join watchlists w on w.id = wi.watchlist_id where w.fm_save_id = 1",
            "watchlist_by_status": "select * from watchlist_items where watchlist_id = 1 and status = 'preparing'",
            "players_by_name": "select * from players where lower(full_name) like '%bench player 001%'",
        }.items():
            rows = connection.exec_driver_sql(f"explain query plan {sql}").fetchall()
            results["query_plans"][label] = [str(row[-1]) for row in rows]

    print(json.dumps(results, indent=2, ensure_ascii=False))
    engine.dispose()


if __name__ == "__main__":
    main()
