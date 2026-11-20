"""Dashboard overview and reader compatibility endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..analytics.players import coverage_for_save
from ..db import get_db
from ..models import Alert, Club, DataSource, FmSave, ImportJob, PlayerInstance, PlayerSnapshot, ReaderCompatibility, Transfer, Watchlist
from ..utils import iso
from .deps import get_active_save

router = APIRouter()

CANDIDATE_COMPATIBILITY = {
    "app_id": "4530370",
    "build_id": "26577676",
    "plugin_version": "27.0.1+2503222",
    "status": "candidate",
    "notes": "Windows Preview 候选组合，尚未在本机验证；未知构建必须拒绝扫描",
}


@router.get("/analytics/overview")
def overview(
    save_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Dashboard aggregates for one save."""
    target = save_id or save.id
    players = db.scalar(select(func.count()).select_from(PlayerInstance).where(PlayerInstance.fm_save_id == target))
    snapshots = db.scalar(
        select(func.count())
        .select_from(PlayerSnapshot)
        .join(PlayerInstance, PlayerInstance.id == PlayerSnapshot.player_instance_id)
        .where(PlayerInstance.fm_save_id == target)
    )
    transfers = db.scalar(select(func.count()).select_from(Transfer).where(Transfer.fm_save_id == target))
    clubs = db.scalar(select(func.count()).select_from(Club).where(Club.fm_save_id == target))
    value = db.scalar(
        select(func.coalesce(func.sum(Transfer.effective_fee), 0)).where(
            Transfer.fm_save_id == target, Transfer.status == "completed"
        )
    )
    watch = db.scalar(select(func.count()).select_from(Watchlist).where(Watchlist.fm_save_id == target))
    alerts = db.scalar(select(func.count()).select_from(Alert).where(Alert.fm_save_id == target, Alert.read_at.is_(None)))
    last_import = db.scalar(
        select(ImportJob).where(ImportJob.fm_save_id == target).order_by(ImportJob.received_at.desc()).limit(1)
    )
    sources = list(db.scalars(select(DataSource).where(DataSource.fm_save_id == target)))
    return {
        "save": {
            "id": save.id,
            "name": save.name,
            "game_version": save.game_version,
            "game_build": save.game_build,
            "is_active": save.is_active,
        },
        "players": int(players or 0),
        "snapshots": int(snapshots or 0),
        "transfers": int(transfers or 0),
        "clubs": int(clubs or 0),
        "completed_transfer_value": float(value or 0),
        "watchlist": int(watch or 0),
        "alerts": int(alerts or 0),
        "coverage": coverage_for_save(db, target),
        "last_import": None
        if last_import is None
        else {
            "id": last_import.id,
            "scan_id": last_import.scan_id,
            "status": last_import.status,
            "received_at": iso(last_import.received_at),
            "player_count": last_import.player_count,
            "transfer_count": last_import.transfer_count,
        },
        "data_sources": [
            {"source": source.source, "records": source.record_count, "last_seen_at": iso(source.last_seen_at)}
            for source in sources
        ],
        "trend": _trend(db, target),
    }


@router.get("/compatibility")
def compatibility(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Reader compatibility entries, sourced from the canonical config files.

    The database table is legacy: it used to be the only source, which is how it drifted to
    "candidate" while the engine gate and registry said "verified". The config files are now the
    single truth; a stale DB row is reported as a conflict instead of being served as truth.
    """
    from .routes_compat import build_compatibility_view

    view = build_compatibility_view()
    items = [
        {
            "app_id": build["app_id"],
            "build_id": build["build"],
            "plugin_version": build["plugin_version"],
            "status": build["status"],
            "notes": build.get("note") or "来自 verified-versions.json + compatibility-registry.json",
            "verified_at": None,
        }
        for build in view["builds"]
    ]
    issues = list(view["issues"])
    rows = list(db.scalars(select(ReaderCompatibility)))
    for row in rows:
        canonical = next((item for item in view["builds"] if item["build"] == row.build_id), None)
        if canonical is None:
            issues.append({"code": "db_only_build", "build": row.build_id, "message": "数据库里有、配置文件里没有"})
        elif canonical["status"] != row.status:
            issues.append(
                {
                    "code": "stale_db_status",
                    "build": row.build_id,
                    "message": f"数据库状态 {row.status} ≠ 配置 {canonical['status']}，以配置为准",
                }
            )
    if not items:
        items = [CANDIDATE_COMPATIBILITY]
    return {
        "items": items,
        "consistent": not issues,
        "issues": issues,
        "source": "config",
        "reader_versions": ["0.1.0"],
        "protocol_version": "1.0",
        "notes": "只有 status=verified 的组合允许扫描；candidate 必须先在本机 probe 通过",
    }


def _trend(db: Session, save_id: int) -> list[dict[str, Any]]:
    rows = db.execute(
        select(PlayerSnapshot.observed_at, func.avg(PlayerSnapshot.ca), func.sum(PlayerSnapshot.market_value))
        .join(PlayerInstance, PlayerInstance.id == PlayerSnapshot.player_instance_id)
        .where(PlayerInstance.fm_save_id == save_id)
        .group_by(PlayerSnapshot.observed_at)
        .order_by(PlayerSnapshot.observed_at)
    ).all()
    return [
        {
            "date": observed.date().isoformat() if hasattr(observed, "date") else str(observed),
            "ca_avg": round(float(avg_ca or 0), 2),
            "value_total": float(total_value or 0),
        }
        for observed, avg_ca, total_value in rows
    ]
