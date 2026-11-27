"""Watchlist, automatic watch rules and alert generation."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..analytics.players import PlayerFilter, latest_snapshot_subquery, list_players
from ..models import Alert, Club, Player, PlayerInstance, PlayerSnapshot, Watchlist, WatchlistItem, WatchRule
from ..utils import iso, utcnow

WATCH_STATUSES = ("watching", "preparing", "paused", "done")

DEFAULT_WATCHLIST = "默认关注"


def get_or_create_watchlist(session: Session, user_id: int, save_id: int) -> Watchlist:
    """Return the default watchlist for one user and save, creating it on first use."""
    watchlist = session.scalar(
        select(Watchlist).where(
            Watchlist.user_id == user_id,
            Watchlist.fm_save_id == save_id,
            Watchlist.name == DEFAULT_WATCHLIST,
        )
    )
    if watchlist is None:
        watchlist = Watchlist(user_id=user_id, fm_save_id=save_id, name=DEFAULT_WATCHLIST)
        session.add(watchlist)
        session.flush()
    return watchlist


def list_items(
    session: Session,
    save_id: int,
    list_id: int | None = None,
    query: str | None = None,
    status: str | None = None,
) -> list[dict[str, object]]:
    """All watched players of one save with their latest summary.

    使用 ``latest_snapshot_subquery`` 一次取回实例、球员与最新快照，避免按行查询（N+1）。
    缺失字段保持 ``None``，由前端显示「暂无数据」，不补 0。
    """
    stmt = (
        select(WatchlistItem, Watchlist.name.label("list_name"))
        .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
        .where(Watchlist.fm_save_id == save_id)
    )
    if list_id is not None:
        stmt = stmt.where(Watchlist.id == list_id)
    if status:
        stmt = stmt.where(WatchlistItem.status == status)
    rows = session.execute(stmt.order_by(WatchlistItem.created_at.desc())).all()

    instance_ids = [item.player_instance_id for item, _name in rows]
    instances = {
        instance.id: instance
        for instance in session.scalars(
            select(PlayerInstance).where(PlayerInstance.id.in_(instance_ids))
        )
    } if instance_ids else {}
    players = {
        player.id: player
        for player in session.scalars(
            select(Player).where(Player.id.in_({instance.player_id for instance in instances.values()}))
        )
    } if instances else {}
    instance_names = {
        instance_id: players[instance.player_id].full_name
        for instance_id, instance in instances.items()
        if instance.player_id in players
    }

    # 姓名筛选在内存中完成，避免为此扫描全部快照。
    if query:
        needle = query.strip().lower()
        rows = [
            (item, name)
            for item, name in rows
            if needle in instance_names.get(item.player_instance_id, "").lower()
        ]
        instance_ids = [item.player_instance_id for item, _name in rows]

    latest = latest_snapshot_subquery(instance_ids if instance_ids else None)
    snapshots = {
        row.instance_id: row
        for row in session.execute(select(latest).where(latest.c.instance_id.in_(instance_ids))).all()
    } if instance_ids else {}

    clubs = {
        club_id: name
        for club_id, name in session.execute(
            select(Club.id, Club.name).where(Club.fm_save_id == save_id)
        ).all()
    }
    payload: list[dict[str, object]] = []
    for item, list_name in rows:
        instance_id = item.player_instance_id
        snapshot = snapshots.get(instance_id)
        instance = instances.get(instance_id)
        player = players.get(instance.player_id) if instance else None
        club_id = (snapshot.club_id if snapshot else None) or (instance.club_id if instance else None)
        payload.append(
            {
                "id": item.id,
                "instance_id": instance_id,
                "list_id": item.watchlist_id,
                "list_name": list_name,
                "player": {
                    "instance_id": instance_id,
                    "name": snapshot.full_name if snapshot else (player.full_name if player else None),
                    "age": snapshot.age if snapshot else None,
                    "position": snapshot.position if snapshot else (instance.position if instance else None),
                    "ca": snapshot.ca if snapshot else None,
                    "pa": snapshot.pa if snapshot else None,
                    "market_value": snapshot.market_value if snapshot else None,
                    "contract_end": snapshot.contract_end.isoformat() if snapshot and snapshot.contract_end else None,
                    "club": clubs.get(club_id) if club_id else None,
                    "source": snapshot.source if snapshot else None,
                },
                "status": item.status or "watching",
                "tag": item.tag,
                "note": item.note,
                "source": item.source,
                "added_at": iso(item.created_at),
            }
        )
    return payload


def list_groups(session: Session, user_id: int, save_id: int) -> list[dict[str, object]]:
    """Named lists of one save with their item counts; the default list is created on first use."""
    get_or_create_watchlist(session, user_id, save_id)
    rows = session.execute(
        select(Watchlist.id, Watchlist.name, func.count(WatchlistItem.id))
        .outerjoin(WatchlistItem, WatchlistItem.watchlist_id == Watchlist.id)
        .where(Watchlist.user_id == user_id, Watchlist.fm_save_id == save_id)
        .group_by(Watchlist.id, Watchlist.name)
        .order_by(Watchlist.id)
    ).all()
    return [
        {
            "id": int(row[0]),
            "name": str(row[1]),
            "count": int(row[2] or 0),
            "is_default": str(row[1]) == DEFAULT_WATCHLIST,
        }
        for row in rows
    ]


def create_list(session: Session, user_id: int, save_id: int, name: str) -> Watchlist:
    """Create one named watchlist; names are unique per user and save."""
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("名单名称不能为空")
    if len(cleaned) > 64:
        raise ValueError("名单名称最长 64 个字符")
    existing = session.scalar(
        select(Watchlist).where(
            Watchlist.user_id == user_id,
            Watchlist.fm_save_id == save_id,
            Watchlist.name == cleaned,
        )
    )
    if existing is not None:
        raise ValueError("已存在同名名单")
    watchlist = Watchlist(user_id=user_id, fm_save_id=save_id, name=cleaned)
    session.add(watchlist)
    session.flush()
    return watchlist


def resolve_list(session: Session, user_id: int, save_id: int, list_id: int | None) -> Watchlist:
    """Resolve a list id to an owned list of the save; ``None`` selects the default list."""
    if list_id is None:
        return get_or_create_watchlist(session, user_id, save_id)
    watchlist = session.get(Watchlist, list_id)
    if watchlist is None or watchlist.user_id != user_id or watchlist.fm_save_id != save_id:
        raise ValueError("关注名单不存在")
    return watchlist


def add_item(
    session: Session,
    user_id: int,
    save_id: int,
    instance_id: int,
    tag: str | None,
    note: str | None,
    list_id: int | None = None,
    status: str = "watching",
) -> WatchlistItem:
    """Follow a player, raising ``ValueError`` when the instance is unknown or already followed."""
    instance = session.get(PlayerInstance, instance_id)
    if instance is None or instance.fm_save_id != save_id:
        raise ValueError("player instance not found in this save")
    watchlist = resolve_list(session, user_id, save_id, list_id)
    if status not in WATCH_STATUSES:
        raise ValueError("关注状态无效")
    existing = session.scalar(
        select(WatchlistItem)
        .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
        .where(Watchlist.fm_save_id == save_id, WatchlistItem.player_instance_id == instance_id)
    )
    if existing is not None:
        raise ValueError("该球员已在关注名单中，可直接在列表内移动名单")
    item = WatchlistItem(
        watchlist_id=watchlist.id,
        player_instance_id=instance_id,
        tag=tag,
        note=note,
        status=status,
        source="manual",
    )
    session.add(item)
    session.flush()
    return item


def update_item(
    session: Session,
    item_id: int,
    tag: str | None = None,
    note: str | None = None,
    list_id: int | None = None,
    status: str | None = None,
    user_id: int | None = None,
) -> WatchlistItem:
    """Update the list, status, tag or note of a watchlist item."""
    item = session.get(WatchlistItem, item_id)
    if item is None:
        raise ValueError("watchlist item not found")
    if status is not None:
        if status not in WATCH_STATUSES:
            raise ValueError("关注状态无效")
        item.status = status
    if list_id is not None and list_id != item.watchlist_id:
        current = session.get(Watchlist, item.watchlist_id)
        if current is None:
            raise ValueError("关注名单不存在")
        target = resolve_list(session, user_id if user_id is not None else current.user_id, current.fm_save_id, list_id)
        duplicate = session.scalar(
            select(WatchlistItem).where(
                WatchlistItem.watchlist_id == target.id,
                WatchlistItem.player_instance_id == item.player_instance_id,
            )
        )
        if duplicate is not None:
            raise ValueError("该球员已在目标名单中")
        item.watchlist_id = target.id
    if tag is not None:
        item.tag = tag
    if note is not None:
        item.note = note
    session.flush()
    return item


def delete_item(session: Session, item_id: int) -> None:
    """Stop following a player."""
    item = session.get(WatchlistItem, item_id)
    if item is None:
        raise ValueError("watchlist item not found")
    session.delete(item)
    session.flush()


def refresh(session: Session, user_id: int, save_id: int) -> dict[str, int]:
    """Apply the default watch rules and raise alerts that do not exist yet.

    Rules are deterministic and documented in the response: an under-21 with PA >= 150 is auto-followed, a contract
    ending within six months, a 25% market-value move, and three flat CA readings all produce alerts.
    """
    watchlist = get_or_create_watchlist(session, user_id, save_id)
    _ensure_rules(session, watchlist)
    created_items = 0
    created_alerts = 0
    candidates = list_players(session, save_id, PlayerFilter(sort="-pa"), limit=200, offset=0)["items"]
    for player in candidates:
        instance_id = int(player["instance_id"])
        if (
            player.get("age") is not None
            and int(player["age"]) <= 21
            and player.get("pa") is not None
            and int(player["pa"]) >= 150
        ):
            exists = session.scalar(
                select(WatchlistItem).where(
                    WatchlistItem.watchlist_id == watchlist.id,
                    WatchlistItem.player_instance_id == instance_id,
                )
            )
            if exists is None:
                session.add(
                    WatchlistItem(
                        watchlist_id=watchlist.id,
                        player_instance_id=instance_id,
                        tag="自动关注",
                        source="rule",
                    )
                )
                created_items += 1
        created_alerts += _contract_alert(session, save_id, instance_id)
        created_alerts += _value_alert(session, save_id, instance_id)
        created_alerts += _stalled_alert(session, save_id, instance_id)
    session.flush()
    return {"created": created_items, "alerts": created_alerts}


def list_alerts(session: Session, save_id: int, unread_only: bool = False) -> list[dict[str, object]]:
    """Alerts for one save, newest first."""
    query = select(Alert).where(Alert.fm_save_id == save_id)
    if unread_only:
        query = query.where(Alert.read_at.is_(None))
    rows = session.scalars(query.order_by(Alert.created_at.desc()))
    return [
        {
            "id": row.id,
            "instance_id": row.player_instance_id,
            "type": row.alert_type,
            "severity": row.severity,
            "title": row.title,
            "message": row.message,
            "created_at": iso(row.created_at),
            "read_at": iso(row.read_at),
        }
        for row in rows
    ]


def mark_read(session: Session, alert_id: int) -> None:
    """Mark one alert as read."""
    alert = session.get(Alert, alert_id)
    if alert is None:
        raise ValueError("alert not found")
    alert.read_at = utcnow()
    session.flush()


def _ensure_rules(session: Session, watchlist: Watchlist) -> None:
    existing = {row.rule_type for row in session.scalars(select(WatchRule).where(WatchRule.watchlist_id == watchlist.id))}
    defaults = (
        ("青训潜力自动关注", "u21_high_pa", {"max_age": 21, "min_pa": 150}),
        ("合同到期提醒", "contract_expiry", {"months": 6}),
        ("身价异常波动", "value_change", {"ratio": 0.25}),
        ("成长停滞提醒", "growth_stalled", {"snapshots": 3}),
    )
    for name, rule_type, conditions in defaults:
        if rule_type in existing:
            continue
        import json

        session.add(
            WatchRule(
                watchlist_id=watchlist.id,
                name=name,
                rule_type=rule_type,
                conditions_json=json.dumps(conditions, ensure_ascii=False),
                enabled=True,
            )
        )
    session.flush()


def _add_alert(
    session: Session,
    save_id: int,
    instance_id: int,
    alert_type: str,
    severity: str,
    title: str,
    message: str,
) -> int:
    exists = session.scalar(
        select(Alert).where(
            Alert.fm_save_id == save_id,
            Alert.player_instance_id == instance_id,
            Alert.alert_type == alert_type,
            Alert.title == title,
        )
    )
    if exists is not None:
        return 0
    session.add(
        Alert(
            fm_save_id=save_id,
            player_instance_id=instance_id,
            alert_type=alert_type,
            severity=severity,
            title=title,
            message=message,
        )
    )
    return 1


def _snapshots(session: Session, instance_id: int, limit: int = 3) -> list[PlayerSnapshot]:
    rows = list(
        session.scalars(
            select(PlayerSnapshot)
            .where(PlayerSnapshot.player_instance_id == instance_id)
            .order_by(PlayerSnapshot.observed_at.desc())
            .limit(limit)
        )
    )
    return rows


def _contract_alert(session: Session, save_id: int, instance_id: int) -> int:
    snapshot = _snapshots(session, instance_id, 1)
    if not snapshot or snapshot[0].contract_end is None:
        return 0
    current = snapshot[0]
    reference = current.game_date or current.observed_at.date()
    days = (current.contract_end - reference).days
    if days > 183:
        return 0
    return _add_alert(
        session,
        save_id,
        instance_id,
        "contract_expiry",
        "high" if days <= 90 else "medium",
        "合同即将到期",
        f"合同在 {current.contract_end.isoformat()} 到期（约 {max(days, 0)} 天），需评估续约或出售",
    )


def _value_alert(session: Session, save_id: int, instance_id: int) -> int:
    rows = _snapshots(session, instance_id, 2)
    if len(rows) < 2:
        return 0
    latest, previous = rows[0], rows[1]
    if latest.market_value is None or not previous.market_value:
        return 0
    change = (latest.market_value - previous.market_value) / previous.market_value
    if abs(change) < 0.25:
        return 0
    direction = "上涨" if change > 0 else "下跌"
    return _add_alert(
        session,
        save_id,
        instance_id,
        "value_change",
        "medium",
        f"身价{direction} {abs(change):.0%}",
        f"身价从 {previous.market_value} 变为 {latest.market_value}（{direction} {abs(change):.0%}），需复核原因",
    )


def _stalled_alert(session: Session, save_id: int, instance_id: int) -> int:
    rows = _snapshots(session, instance_id, 3)
    if len(rows) < 3:
        return 0
    values = [row.ca for row in rows]
    if any(value is None for value in values):
        return 0
    if len(set(values)) != 1:
        return 0
    span = (rows[0].observed_at - rows[-1].observed_at).days
    if span < 90:
        return 0
    return _add_alert(
        session,
        save_id,
        instance_id,
        "growth_stalled",
        "low",
        "成长停滞",
        f"最近 {len(rows)} 次快照 CA 均为 {values[0]}，跨度 {span} 天，建议检查出场时间与训练安排",
    )
