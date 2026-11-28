"""Player queries, profiles, growth history and development attribution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import Select, and_, func, select
from sqlalchemy.orm import Session

from ..ingestion.attributes import position_group
from ..models import (
    Club,
    Player,
    PlayerAttribute,
    PlayerAttributeValue,
    PlayerInstance,
    PlayerSnapshot,
    Watchlist,
    WatchlistItem,
)
from ..utils import iso


@dataclass(frozen=True)
class PlayerFilter:
    """Filters accepted by the player list and scouting search."""

    query: str | None = None
    position: str | None = None
    position_group: str | None = None
    min_age: int | None = None
    max_age: int | None = None
    min_ca: int | None = None
    min_pa: int | None = None
    max_value: int | None = None
    max_wage: int | None = None
    club_id: int | None = None
    watchlist_only: bool = False
    sort: str = "-updated_at"


def _snapshot_columns() -> list:
    """两段最新快照查询共用的列清单，保证 UNION ALL 列顺序与类型一致。"""
    return [
        PlayerInstance.id.label("instance_id"),
        PlayerInstance.player_id,
        PlayerInstance.save_local_uid,
        PlayerInstance.club_id,
        PlayerInstance.position,
        PlayerInstance.fm_save_id,
        Player.full_name,
        Player.birth_date,
        Player.nationality,
        PlayerSnapshot.id.label("snapshot_id"),
        PlayerSnapshot.observed_at,
        PlayerSnapshot.game_date,
        PlayerSnapshot.age,
        PlayerSnapshot.ca,
        PlayerSnapshot.pa,
        PlayerSnapshot.market_value,
        PlayerSnapshot.wage,
        PlayerSnapshot.contract_end,
        PlayerSnapshot.minutes_played,
        PlayerSnapshot.appearances,
        PlayerSnapshot.goals,
        PlayerSnapshot.assists,
        PlayerSnapshot.data_completeness,
        PlayerSnapshot.source,
    ]


def latest_snapshot_subquery(instance_ids: list[int] | None = None):
    """One row per instance: its most recent snapshot joined with the instance and club.

    V3.3.2：优先使用 ``player_instances.latest_snapshot_id``（主键 JOIN，O(1)），
    只有引用为空的历史行才回退到按实例聚合。旧库/测试直接写入的快照因此保持原有行为，
    生产数据导入后不再为每次列表扫描全部历史快照。

    ``instance_ids`` 可把范围限制在一小批实例（例如关注名单）。
    """
    return _modern_snapshot_select(instance_ids).union_all(
        _legacy_snapshot_select(instance_ids)
    ).subquery()


def _modern_snapshot_select(instance_ids: list[int] | None = None):
    """引用 ``latest_snapshot_id`` 的快照（生产数据的常态，主键 JOIN）。"""
    query = (
        select(*_snapshot_columns())
        .join(PlayerSnapshot, PlayerSnapshot.id == PlayerInstance.latest_snapshot_id)
        .join(Player, Player.id == PlayerInstance.player_id)
        .where(PlayerInstance.latest_snapshot_id.is_not(None))
    )
    if instance_ids is not None:
        query = query.where(PlayerInstance.id.in_(instance_ids))
    return query


def _legacy_snapshot_select(instance_ids: list[int] | None = None):
    """引用为空的历史行：按实例聚合最新快照（旧库/测试直接写入的数据）。"""
    legacy_ids = select(PlayerInstance.id).where(PlayerInstance.latest_snapshot_id.is_(None))
    newest_stmt = (
        select(PlayerSnapshot.player_instance_id, func.max(PlayerSnapshot.observed_at).label("observed_at"))
        .where(PlayerSnapshot.player_instance_id.in_(legacy_ids))
        .group_by(PlayerSnapshot.player_instance_id)
    )
    if instance_ids is not None:
        newest_stmt = newest_stmt.where(PlayerSnapshot.player_instance_id.in_(instance_ids))
    newest = newest_stmt.subquery()
    return (
        select(*_snapshot_columns())
        .join(newest, newest.c.player_instance_id == PlayerInstance.id)
        .join(
            PlayerSnapshot,
            and_(
                PlayerSnapshot.player_instance_id == PlayerInstance.id,
                PlayerSnapshot.observed_at == newest.c.observed_at,
            ),
        )
        .join(Player, Player.id == PlayerInstance.player_id)
        .where(PlayerInstance.latest_snapshot_id.is_(None))
    )


def _apply_player_filters(query: Select, base: Any, filters: PlayerFilter, save_id: int) -> Select:
    """把球员筛选条件套到任意最新快照子查询上（列表、计数共用，避免两套口径）。"""
    if filters.query:
        query = query.where(base.c.full_name.like(f"%{filters.query.strip()}%"))
    if filters.position:
        query = query.where(base.c.position == filters.position)
    if filters.position_group:
        # 保持 V3.3.2 的既有筛选语义（不含 STC）；这是与行内 position_group 展示口径无关的
        # 历史行为，本性能任务不改变筛选结果。
        codes = [
            code
            for code, group in {
                "GK": "GK",
                "DC": "DF",
                "DL": "DF",
                "DR": "DF",
                "WBL": "DF",
                "WBR": "DF",
                "DM": "MF",
                "MC": "MF",
                "ML": "MF",
                "MR": "MF",
                "AMC": "MF",
                "AML": "FW",
                "AMR": "FW",
                "ST": "FW",
            }.items()
            if group == filters.position_group
        ]
        query = query.where(base.c.position.in_(codes))
    if filters.min_age is not None:
        query = query.where(base.c.age >= filters.min_age)
    if filters.max_age is not None:
        query = query.where(base.c.age <= filters.max_age)
    if filters.min_ca is not None:
        query = query.where(base.c.ca >= filters.min_ca)
    if filters.min_pa is not None:
        query = query.where(base.c.pa >= filters.min_pa)
    if filters.max_value is not None:
        query = query.where(base.c.market_value <= filters.max_value)
    if filters.max_wage is not None:
        query = query.where(base.c.wage <= filters.max_wage)
    if filters.club_id is not None:
        query = query.where(base.c.club_id == filters.club_id)
    if filters.watchlist_only:
        query = query.where(
            base.c.instance_id.in_(
                select(WatchlistItem.player_instance_id)
                .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
                .where(Watchlist.fm_save_id == save_id)
            )
        )
    return query


def filtered_players(save_id: int, filters: PlayerFilter) -> tuple[Select, Any]:
    """Base select over the latest snapshot per instance with every filter applied."""
    base = latest_snapshot_subquery()
    query = select(base).where(base.c.fm_save_id == save_id)
    return _apply_player_filters(query, base, filters, save_id), base





def list_players(
    session: Session, save_id: int, filters: PlayerFilter, limit: int = 50, offset: int = 0
) -> dict[str, object]:
    """Paginated player summaries plus field coverage for the filtered population."""
    query, base = filtered_players(save_id, filters)
    total = int(session.scalar(select(func.count()).select_from(query.subquery())) or 0)
    ordering = _ordering(filters.sort, base)
    rows = session.execute(query.order_by(ordering).limit(limit).offset(offset)).all()
    # 只加载当前页引用到的俱乐部：大存档可能有数千家俱乐部，加载量与页大小无关。
    clubs = _clubs_by_ids(session, (row.club_id for row in rows))
    watched = _watched_ids(session, save_id)
    items = [_row_summary(row, clubs, watched) for row in rows]
    return {"items": items, "total": total, "coverage": _coverage(session, save_id, filters)}


def player_instance_or_none(session: Session, instance_id: int) -> PlayerInstance | None:
    """Load one instance with its identity row."""
    return session.get(PlayerInstance, instance_id)


def player_profile(session: Session, instance_id: int) -> dict[str, object]:
    """Full profile: latest summary, attribute readings, history bounds and watchlist tags."""
    instance = session.get(PlayerInstance, instance_id)
    if instance is None:
        raise ValueError("player instance not found")
    snapshot = latest_snapshot(session, instance_id)
    clubs = _clubs_by_ids(session, (instance.club_id,))
    summary = _snapshot_summary(instance, snapshot, clubs, _watched_ids(session, instance.fm_save_id))
    attributes = (
        _attribute_rows(session, snapshot.id) if snapshot is not None else []
    )
    count = session.scalar(
        select(func.count()).select_from(PlayerSnapshot).where(PlayerSnapshot.player_instance_id == instance_id)
    )
    bounds = session.execute(
        select(func.min(PlayerSnapshot.observed_at), func.max(PlayerSnapshot.observed_at)).where(
            PlayerSnapshot.player_instance_id == instance_id
        )
    ).one()
    items = session.scalars(
        select(WatchlistItem)
        .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
        .where(Watchlist.fm_save_id == instance.fm_save_id, WatchlistItem.player_instance_id == instance_id)
    )
    tags = [item.tag for item in items if item.tag]
    notes = next((item.note for item in items if item.note), None)
    return {
        "summary": summary,
        "attributes": attributes,
        "snapshot_count": int(count or 0),
        "first_seen": bounds[0].date().isoformat() if bounds[0] else None,
        "last_seen": bounds[1].date().isoformat() if bounds[1] else None,
        "latest_snapshot_id": snapshot.id if snapshot is not None else None,
        "tags": tags,
        "notes": notes,
    }


def latest_snapshot(session: Session, instance_id: int) -> PlayerSnapshot | None:
    """Most recent snapshot of one instance, using the maintained reference when present."""
    instance = session.get(PlayerInstance, instance_id)
    if instance is not None and instance.latest_snapshot_id is not None:
        snapshot = session.get(PlayerSnapshot, instance.latest_snapshot_id)
        if snapshot is not None:
            return snapshot
    return session.scalar(
        select(PlayerSnapshot)
        .where(PlayerSnapshot.player_instance_id == instance_id)
        .order_by(PlayerSnapshot.observed_at.desc())
        .limit(1)
    )


def history(session: Session, instance_id: int, from_date: date | None = None, to_date: date | None = None) -> dict[str, object]:
    """Every snapshot with its attribute readings, oldest first."""
    query = select(PlayerSnapshot).where(PlayerSnapshot.player_instance_id == instance_id)
    if from_date:
        query = query.where(PlayerSnapshot.observed_at >= _start_of_day(from_date))
    if to_date:
        query = query.where(PlayerSnapshot.observed_at <= _end_of_day(to_date))
    snapshots = list(session.scalars(query.order_by(PlayerSnapshot.observed_at.asc())))
    points: list[dict[str, object]] = []
    attribute_total = 0
    attribute_present = 0
    for snapshot in snapshots:
        readings = _attribute_rows(session, snapshot.id)
        attribute_total += len(readings)
        attribute_present += sum(1 for row in readings if row["value"] is not None)
        points.append(
            {
                "snapshot_id": snapshot.id,
                "observed_at": iso(snapshot.observed_at),
                "game_date": snapshot.game_date.isoformat() if snapshot.game_date else None,
                "age": snapshot.age,
                "ca": snapshot.ca,
                "pa": snapshot.pa,
                "market_value": snapshot.market_value,
                "wage": snapshot.wage,
                "contract_end": snapshot.contract_end.isoformat() if snapshot.contract_end else None,
                "minutes_played": snapshot.minutes_played,
                "appearances": snapshot.appearances,
                "goals": snapshot.goals,
                "assists": snapshot.assists,
                "attributes": {row["key"]: row["value"] for row in readings},
            }
        )
    return {
        "points": points,
        "coverage": {
            "points": len(points),
            "attributes": round(attribute_present / attribute_total, 4) if attribute_total else 0.0,
        },
    }


def development(session: Session, instance_id: int) -> dict[str, object]:
    """Growth summary over all snapshots, with fact / correlation / speculation separated."""
    snapshots = list(
        session.scalars(
            select(PlayerSnapshot)
            .where(PlayerSnapshot.player_instance_id == instance_id)
            .order_by(PlayerSnapshot.observed_at.asc())
        )
    )
    instance = session.get(PlayerInstance, instance_id)
    if instance is None:
        raise ValueError("player instance not found")
    if not snapshots:
        return {
            "summary": {"snapshots": 0, "ca_delta": None, "market_value_delta": None, "minutes_delta": None},
            "records": [],
            "attributions": [
                {"kind": "fact", "factor": "历史快照", "evidence": "该球员没有任何快照，无法分析成长"}
            ],
            "data_gaps": ["没有快照数据"],
        }
    first, last = snapshots[0], snapshots[-1]
    records: list[dict[str, object]] = []
    for previous, current in zip(snapshots, snapshots[1:]):
        records.append(
            {
                "period_start": (previous.game_date or previous.observed_at.date()).isoformat(),
                "period_end": (current.game_date or current.observed_at.date()).isoformat(),
                "ca_delta": _delta(previous.ca, current.ca),
                "market_value_delta": _delta(previous.market_value, current.market_value),
                "minutes": _delta(previous.minutes_played, current.minutes_played),
                "appearances": _delta(previous.appearances, current.appearances),
                "goals": _delta(previous.goals, current.goals),
                "assists": _delta(previous.assists, current.assists),
            }
        )
    ca_delta = _delta(first.ca, last.ca)
    value_delta = _delta(first.market_value, last.market_value)
    minutes_delta = _delta(first.minutes_played, last.minutes_played)
    positive_minutes = [record for record in records if (record["minutes"] or 0) > 0]
    rising_ca = [record for record in positive_minutes if (record["ca_delta"] or 0) > 0]
    attributions: list[dict[str, object]] = []
    attributions.append(
        {
            "kind": "fact",
            "factor": "能力变化",
            "evidence": f"{len(snapshots)} 次快照中 CA 从 {first.ca if first.ca is not None else '—'} 变为 {last.ca if last.ca is not None else '—'}（{ca_delta:+d}）"
            if ca_delta is not None
            else "快照缺少 CA 字段，无法给出能力变化事实",
        }
    )
    if positive_minutes:
        attributions.append(
            {
                "kind": "correlation",
                "factor": "出场时间与 CA 变化",
                "evidence": f"{len(records)} 个区间中 {len(rising_ca)} 个同时出现出场时间增加与 CA 上升（样本 {len(snapshots)}）",
            }
        )
    else:
        attributions.append(
            {
                "kind": "correlation",
                "factor": "出场时间与 CA 变化",
                "evidence": "快照未提供出场时间，无法检查二者是否同向变化",
            }
        )
    attributions.append(
        {
            "kind": "speculation",
            "factor": "训练与伤病影响",
            "evidence": "数据源未提供训练强度、教练评价和伤病记录，任何归因都属于推测",
        }
    )
    gaps: list[str] = []
    if all(snapshot.contract_end is None for snapshot in snapshots):
        gaps.append("合同到期日缺失")
    if all(snapshot.minutes_played is None for snapshot in snapshots):
        gaps.append("出场时间缺失")
    return {
        "summary": {
            "snapshots": len(snapshots),
            "ca_delta": ca_delta,
            "market_value_delta": value_delta,
            "minutes_delta": minutes_delta,
            "window_start": (first.game_date or first.observed_at.date()).isoformat(),
            "window_end": (last.game_date or last.observed_at.date()).isoformat(),
            "current_age": last.age,
            "current_club": _club_name_for(session, last.club_id),
        },
        "records": records,
        "attributions": attributions,
        "data_gaps": gaps,
    }


def coverage_for_save(session: Session, save_id: int) -> dict[str, float]:
    """Field coverage across all latest snapshots of a save (cached per save + data revision)."""
    from ..services import query_cache

    return query_cache.cached(
        session, save_id, "coverage", None, lambda: _coverage_for_save(session, save_id)
    )


def _coverage_for_save(session: Session, save_id: int) -> dict[str, float]:
    base = latest_snapshot_subquery()
    row = session.execute(
        select(
            func.count(),
            func.count(base.c.ca),
            func.count(base.c.pa),
            func.count(base.c.market_value),
            func.count(base.c.contract_end),
        ).where(base.c.fm_save_id == save_id)
    ).one()
    total = int(row[0] or 0)
    if not total:
        return {"ca": 0.0, "pa": 0.0, "market_value": 0.0, "contract_end": 0.0}
    return {
        "ca": round(int(row[1] or 0) / total, 4),
        "pa": round(int(row[2] or 0) / total, 4),
        "market_value": round(int(row[3] or 0) / total, 4),
        "contract_end": round(int(row[4] or 0) / total, 4),
    }


def _coverage(session: Session, save_id: int, filters: PlayerFilter) -> dict[str, float]:
    return coverage_for_save(session, save_id)


def _ordering(sort: str, base: Any):
    desc = sort.startswith("-")
    key = sort.lstrip("-")
    columns = {
        "age": base.c.age,
        "ca": base.c.ca,
        "pa": base.c.pa,
        "market_value": base.c.market_value,
        "updated_at": base.c.observed_at,
        "name": base.c.full_name,
    }
    column = columns.get(key, base.c.observed_at)
    return column.desc() if desc else column.asc()


def _row_summary(row, clubs: dict[int, Club], watched: set[int]) -> dict[str, object]:
    club = clubs.get(row.club_id) if row.club_id else None
    return {
        "instance_id": row.instance_id,
        "player_id": row.player_id,
        # 存档内稳定 ID：阵容 CSV 用它直接关联，避免只按姓名匹配。
        "save_local_uid": row.save_local_uid,
        "name": row.full_name,
        "age": row.age,
        "birth_date": row.birth_date.isoformat() if row.birth_date else None,
        "nationality": row.nationality,
        "position": row.position,
        "position_group": position_group(row.position),
        "club": club.name if club else None,
        "club_id": row.club_id,
        "ca": row.ca,
        "pa": row.pa,
        "market_value": row.market_value,
        "wage": row.wage,
        "contract_end": row.contract_end.isoformat() if row.contract_end else None,
        "observed_at": iso(row.observed_at),
        "game_date": row.game_date.isoformat() if row.game_date else None,
        "data_completeness": row.data_completeness,
        "source": row.source,
        "is_watched": row.instance_id in watched,
    }


def _snapshot_summary(
    instance: PlayerInstance, snapshot: PlayerSnapshot | None, clubs: dict[int, Club], watched: set[int]
) -> dict[str, object]:
    club = clubs.get(instance.club_id) if instance.club_id else None
    return {
        "instance_id": instance.id,
        "player_id": instance.player_id,
        "name": instance.player.full_name,
        "age": snapshot.age if snapshot else None,
        "birth_date": instance.player.birth_date.isoformat() if instance.player.birth_date else None,
        "nationality": instance.player.nationality,
        "position": instance.position or (snapshot.position if snapshot else None),
        "position_group": position_group(instance.position or (snapshot.position if snapshot else None)),
        "club": club.name if club else None,
        "club_id": instance.club_id,
        "ca": snapshot.ca if snapshot else None,
        "pa": snapshot.pa if snapshot else None,
        "market_value": snapshot.market_value if snapshot else None,
        "wage": snapshot.wage if snapshot else None,
        "contract_end": snapshot.contract_end.isoformat() if snapshot and snapshot.contract_end else None,
        "height_cm": snapshot.height_cm if snapshot else None,
        "foot": snapshot.foot if snapshot else None,
        "observed_at": iso(snapshot.observed_at) if snapshot else None,
        "data_completeness": snapshot.data_completeness if snapshot else None,
        "source": snapshot.source if snapshot else None,
        "is_watched": instance.id in watched,
    }


def _attribute_rows(session: Session, snapshot_id: int) -> list[dict[str, object]]:
    rows = session.execute(
        select(PlayerAttributeValue, PlayerAttribute)
        .join(PlayerAttribute, PlayerAttribute.id == PlayerAttributeValue.attribute_id)
        .where(PlayerAttributeValue.player_snapshot_id == snapshot_id)
        .order_by(PlayerAttribute.category, PlayerAttribute.sort_order)
    ).all()
    return [
        {
            "key": attribute.key,
            "name": attribute.name_zh,
            "category": attribute.category,
            "value": value.value,
        }
        for value, attribute in rows
    ]


def _clubs_by_ids(session: Session, club_ids) -> dict[int, Club]:
    """按主键加载少量俱乐部（当前页/单个球员），避免整存档全量加载。"""
    ids = sorted({club_id for club_id in club_ids if club_id})
    if not ids:
        return {}
    return {club.id: club for club in session.scalars(select(Club).where(Club.id.in_(ids)))}


def _watched_ids(session: Session, save_id: int) -> set[int]:
    return {
        row
        for row in session.scalars(
            select(WatchlistItem.player_instance_id)
            .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
            .where(Watchlist.fm_save_id == save_id)
        )
    }


def _club_name_for(session: Session, club_id: int | None) -> str | None:
    if club_id is None:
        return None
    club = session.get(Club, club_id)
    return club.name if club else None


def _delta(before: int | float | None, after: int | float | None) -> int | None:
    if before is None or after is None:
        return None
    return int(after) - int(before)


def _start_of_day(value: date):
    from datetime import datetime

    return datetime(value.year, value.month, value.day)


def _end_of_day(value: date):
    from datetime import datetime, time

    return datetime.combine(value, time(23, 59, 59))

