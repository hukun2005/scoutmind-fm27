"""全局搜索：当前存档内的球员、俱乐部与转会记录。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..analytics.players import latest_snapshot_subquery
from ..db import get_db
from ..models import Club, FmSave, Transfer
from .deps import get_active_save

router = APIRouter()

SEARCH_TYPES = ("all", "players", "clubs", "transfers")


@router.get("/search")
def search(
    q: str = Query(default="", max_length=64),
    type: str = Query(default="all", pattern="^(all|players|clubs|transfers)$"),
    limit: int = Query(default=8, ge=1, le=20),
    save_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """按类型返回统一结构的结果；空查询直接返回空分类，不扫描数据表。"""
    term = (q or "").strip()
    target = save_id or save.id
    categories: dict[str, list[dict[str, Any]]] = {"players": [], "clubs": [], "transfers": []}
    if not term:
        return {
            "query": "",
            "type": type,
            "categories": categories,
            "total": 0,
            "limits": {"per_category": limit},
        }
    clubs = {club.id: club for club in db.scalars(select(Club).where(Club.fm_save_id == target))}
    if type in ("all", "players"):
        categories["players"] = _players(db, target, term, limit, clubs)
    if type in ("all", "clubs"):
        categories["clubs"] = _clubs(db, target, term, limit)
    if type in ("all", "transfers"):
        categories["transfers"] = _transfers(db, target, term, limit)
    return {
        "query": term,
        "type": type,
        "categories": categories,
        "total": sum(len(items) for items in categories.values()),
        "limits": {"per_category": limit},
    }


def _pattern(term: str) -> str:
    """把用户输入当作字面量：转义 LIKE 通配符，避免 `%` / `_` 变成全表匹配。"""
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _players(db: Session, save_id: int, term: str, limit: int, clubs: dict[int, Club]) -> list[dict[str, Any]]:
    base = latest_snapshot_subquery()
    rows = db.execute(
        select(base)
        .where(base.c.fm_save_id == save_id, base.c.full_name.like(_pattern(term), escape="\\"))
        .order_by(base.c.full_name.asc())
        .limit(limit)
    ).all()
    results: list[dict[str, Any]] = []
    for row in rows:
        club = clubs.get(row.club_id) if row.club_id else None
        club_name = club.name if club else None
        parts = [
            row.position or "位置未知",
            f"{row.age} 岁" if row.age is not None else "年龄未知",
            club_name or "自由球员",
        ]
        results.append(
            {
                "entity_type": "player",
                "entity_id": int(row.instance_id),
                "display_name": str(row.full_name),
                "subtitle": " · ".join(parts),
                "navigation_target": f"/players/{int(row.instance_id)}",
                "meta": {
                    "position": row.position,
                    "age": row.age,
                    "club": club_name,
                    "ca": row.ca,
                    "pa": row.pa,
                },
            }
        )
    return results


def _clubs(db: Session, save_id: int, term: str, limit: int) -> list[dict[str, Any]]:
    base = latest_snapshot_subquery()
    counts = {
        club_id: int(count)
        for club_id, count in db.execute(
            select(base.c.club_id, func.count())
            .where(base.c.fm_save_id == save_id, base.c.club_id.is_not(None))
            .group_by(base.c.club_id)
        ).all()
    }
    rows = db.scalars(
        select(Club).where(Club.fm_save_id == save_id, Club.name.like(_pattern(term), escape="\\")).order_by(Club.name.asc()).limit(limit)
    )
    results: list[dict[str, Any]] = []
    for club in rows:
        count = counts.get(club.id, 0)
        parts = [part for part in (club.nation, club.league) if part]
        if count:
            parts.append(f"{count} 名球员")
        results.append(
            {
                "entity_type": "club",
                "entity_id": club.id,
                "display_name": club.name,
                "subtitle": " · ".join(parts) if parts else "暂无国家和联赛信息",
                "navigation_target": f"/players?club_id={club.id}",
                "meta": {"nation": club.nation, "league": club.league, "player_count": count},
            }
        )
    return results


def _transfers(db: Session, save_id: int, term: str, limit: int) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(Transfer)
        .where(
            Transfer.fm_save_id == save_id,
            or_(
                Transfer.player_name.like(_pattern(term), escape="\\"),
                Transfer.from_club_name.like(_pattern(term), escape="\\"),
                Transfer.to_club_name.like(_pattern(term), escape="\\"),
            ),
        )
        .order_by(Transfer.transfer_date.desc(), Transfer.id.desc())
        .limit(limit)
    )
    results: list[dict[str, Any]] = []
    for transfer in rows:
        fee = transfer.effective_fee
        if fee is None:
            fee = transfer.fee_paid
        if fee is None and transfer.transfer_type == "loan":
            fee = transfer.loan_fee
        results.append(
            {
                "entity_type": "transfer",
                "entity_id": transfer.id,
                "display_name": transfer.player_name,
                "subtitle": f"{transfer.from_club_name or '未知俱乐部'} → {transfer.to_club_name or '未知俱乐部'} · {transfer.transfer_date.isoformat()}",
                "navigation_target": f"/transfers?query={transfer.player_name}",
                "meta": {
                    "status": transfer.status,
                    "transfer_type": transfer.transfer_type,
                    "from_club": transfer.from_club_name,
                    "to_club": transfer.to_club_name,
                    "currency": transfer.currency,
                    "fee": fee,
                },
            }
        )
    return results
