"""Longitudinal player series and growth quality (SM-058/059/060).

All queries are save-scoped. Game date and observation time are kept separate; repeated scans on
the same game date are collapsed to one independent growth observation (last observation wins),
while raw counts are still reported.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from statistics import mean
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import ImportJob, PlayerAttributeValue, PlayerInstance, PlayerSnapshot


@dataclass(frozen=True)
class SeriesPoint:
    """One independent game-date observation."""

    instance_id: int
    game_date: date
    observed_at: datetime
    ca: int | None
    pa: int | None
    wage: int | None
    market_value: int | None
    contract_end: date | None
    club_id: int | None
    position: str | None
    source: str | None
    reader_version: str | None
    game_build: str | None


@dataclass(frozen=True)
class SeriesBuild:
    """Collapsed series plus raw counts, so duplicates stay visible."""

    instance_id: int
    points: list[SeriesPoint]
    raw_snapshot_count: int
    unique_game_dates: int
    unique_observed_dates: int


def build_series(
    session: Session,
    save_id: int,
    instance_id: int,
    *,
    source: str | None = None,
) -> SeriesBuild:
    """Build a save-scoped series; one point per game date, latest observation wins."""
    instance = session.get(PlayerInstance, instance_id)
    if instance is None or instance.fm_save_id != save_id:
        raise ValueError("player not found in this save")
    query = (
        select(PlayerSnapshot, ImportJob.source, ImportJob.reader_version, ImportJob.game_build)
        .join(ImportJob, ImportJob.id == PlayerSnapshot.import_job_id, isouter=True)
        .where(PlayerSnapshot.player_instance_id == instance_id)
        .order_by(PlayerSnapshot.observed_at, PlayerSnapshot.id)
    )
    rows = list(session.execute(query))
    if source is not None:
        rows = [row for row in rows if row[1] == source]
    raw_count = len(rows)
    by_date: dict[date, SeriesPoint] = {}
    observed_times: set[datetime] = set()
    for snapshot, job_source, reader_version, game_build in rows:
        observed_times.add(snapshot.observed_at)
        game_date = snapshot.game_date or snapshot.observed_at.date()
        by_date[game_date] = SeriesPoint(
            instance_id=instance_id,
            game_date=game_date,
            observed_at=snapshot.observed_at,
            ca=snapshot.ca,
            pa=snapshot.pa,
            wage=snapshot.wage,
            market_value=snapshot.market_value,
            contract_end=snapshot.contract_end,
            club_id=snapshot.club_id,
            position=snapshot.position,
            source=job_source,
            reader_version=reader_version,
            game_build=game_build,
        )
    points = [by_date[key] for key in sorted(by_date)]
    return SeriesBuild(
        instance_id=instance_id,
        points=points,
        raw_snapshot_count=raw_count,
        unique_game_dates=len(points),
        unique_observed_dates=len(observed_times),
    )


def _coverage(points: list[SeriesPoint], attribute: str) -> float:
    if not points:
        return 0.0
    present = sum(1 for point in points if getattr(point, attribute) is not None)
    return present / len(points)


def growth_report(session: Session, save_id: int, instance_id: int) -> dict[str, Any]:
    """CA growth, attribute growth, potential realization, stagnation and coverage."""
    series = build_series(session, save_id, instance_id)
    points = series.points
    base = {
        "instance_id": instance_id,
        "raw_snapshot_count": series.raw_snapshot_count,
        "unique_game_dates": series.unique_game_dates,
        "unique_observed_dates": series.unique_observed_dates,
        "coverage": {
            "ca": _coverage(points, "ca"),
            "pa": _coverage(points, "pa"),
            "wage": _coverage(points, "wage"),
            "market_value": _coverage(points, "market_value"),
            "contract_end": _coverage(points, "contract_end"),
        },
    }
    if len(points) < 2:
        return {**base, "available": False, "reason": "至少需要 2 个独立 game_date 才能计算成长"}
    first, last = points[0], points[-1]
    if first.ca is None or last.ca is None:
        return {**base, "available": False, "reason": "CA 缺失，不能把缺失当成 0"}
    days = max(1, (last.game_date - first.game_date).days)
    ca_growth = (last.ca - first.ca) / (days / 365.25)

    attribute_growth: dict[str, float] = {}
    first_values = _attribute_values(session, save_id, first)
    last_values = _attribute_values(session, save_id, last)
    for name in sorted(set(first_values) & set(last_values)):
        attribute_growth[name] = last_values[name] - first_values[name]

    realizations = [point.ca / point.pa for point in points if point.ca is not None and point.pa]
    stagnation = None
    ca_points = [point for point in points if point.ca is not None]
    if len(ca_points) >= 3:
        stagnation = ca_points[-1].ca == ca_points[-3].ca
    return {
        **base,
        "available": True,
        "ca_first": first.ca,
        "ca_last": last.ca,
        "ca_growth_per_year": ca_growth,
        "attribute_growth": attribute_growth,
        "potential_realization": mean(realizations) if realizations else None,
        "stagnation": stagnation,
        "missing_rate": {
            key: 1 - value for key, value in base["coverage"].items()
        },
    }


def _attribute_values(session: Session, save_id: int, point: SeriesPoint) -> dict[str, float]:
    from ..models import PlayerAttribute

    rows = session.execute(
        select(PlayerAttribute.name, PlayerAttributeValue.value)
        .join(PlayerAttributeValue, PlayerAttributeValue.attribute_id == PlayerAttribute.id)
        .join(PlayerSnapshot, PlayerSnapshot.id == PlayerAttributeValue.player_snapshot_id)
        .join(PlayerInstance, PlayerInstance.id == PlayerSnapshot.player_instance_id)
        .where(
            PlayerInstance.fm_save_id == save_id,
            PlayerSnapshot.player_instance_id == point.instance_id,
            PlayerSnapshot.game_date == point.game_date,
        )
    )
    return {name: float(value) for name, value in rows}


def growth_backtest(session: Session, save_id: int, *, min_points: int = 3) -> dict[str, Any]:
    """Strict time-split backtest of CA growth; unavailable when real data is insufficient."""
    instances = list(
        session.scalars(select(PlayerInstance.id).where(PlayerInstance.fm_save_id == save_id))
    )
    series = [build_series(session, save_id, instance_id) for instance_id in instances]
    series = [item for item in series if len(item.points) >= min_points]
    all_dates = sorted({point.game_date for item in series for point in item.points})
    raw_snapshots = sum(item.raw_snapshot_count for item in series)
    observed_dates = len({point.observed_at.date() for item in series for point in item.points})
    if len(all_dates) < 4 or not series:
        return {
            "available": False,
            "reason": "没有足够的独立 game_date 做时间切分回测",
            "raw_snapshot_count": raw_snapshots,
            "unique_game_dates": len(all_dates),
            "unique_observed_dates": observed_dates,
            "evaluated": 0,
        }
    cutoff = all_dates[int(len(all_dates) * 0.7)]
    errors: list[float] = []
    for item in series:
        train = [point for point in item.points if point.game_date < cutoff and point.ca is not None]
        validation = [point for point in item.points if point.game_date >= cutoff and point.ca is not None]
        if len(train) < 2 or not validation:
            continue
        growth = (train[-1].ca - train[0].ca) / max(1, (train[-1].game_date - train[0].game_date).days)
        predicted = train[-1].ca
        for point in validation:
            days = max(1, (point.game_date - train[-1].game_date).days)
            predicted = predicted + growth * days
            errors.append(abs(point.ca - predicted))
    if not errors:
        return {
            "available": False,
            "reason": "训练/验证切分后没有可评估样本",
            "raw_snapshot_count": raw_snapshots,
            "unique_game_dates": len(all_dates),
            "unique_observed_dates": observed_dates,
            "evaluated": 0,
        }
    mae = mean(errors)
    rmse = (mean(error * error for error in errors)) ** 0.5
    return {
        "available": True,
        "mae": mae,
        "rmse": rmse,
        "interval_coverage": None,
        "raw_snapshot_count": raw_snapshots,
        "unique_game_dates": len(all_dates),
        "unique_observed_dates": observed_dates,
        "evaluated": len(errors),
        "cutoff_game_date": cutoff.isoformat(),
        "note": "区间覆盖率需要预测量化区间；本轮不伪造",
    }


def quality_summary(session: Session, save_id: int, import_job_id: int | None = None) -> dict[str, Any]:
    """Import-level data quality summary (SM-060), traceable to ImportJob/DataSource."""
    snapshot_query = (
        select(PlayerSnapshot, PlayerInstance.id, ImportJob.source, ImportJob.reader_version, ImportJob.game_build)
        .join(PlayerInstance, PlayerInstance.id == PlayerSnapshot.player_instance_id)
        .join(ImportJob, ImportJob.id == PlayerSnapshot.import_job_id, isouter=True)
        .where(PlayerInstance.fm_save_id == save_id)
    )
    if import_job_id is not None:
        snapshot_query = snapshot_query.where(PlayerSnapshot.import_job_id == import_job_id)
    rows = list(session.execute(snapshot_query))
    snapshots = [row[0] for row in rows]
    instances = {row[1] for row in rows}
    game_dates = {snapshot.game_date for snapshot in snapshots if snapshot.game_date is not None}
    observed_dates = {snapshot.observed_at.date() for snapshot in snapshots}
    duplicate_game_dates = 0
    seen: set[tuple[int, date]] = set()
    for snapshot, instance_id, *_ in rows:
        game_date = snapshot.game_date or snapshot.observed_at.date()
        key = (instance_id, game_date)
        if key in seen:
            duplicate_game_dates += 1
        else:
            seen.add(key)
    total = len(snapshots) or 1

    def coverage(attribute: str) -> float:
        return sum(1 for snapshot in snapshots if getattr(snapshot, attribute) is not None) / total

    sources: dict[str, int] = {}
    builds: set[str] = set()
    for _, _, source, _reader, game_build in rows:
        sources[source or "unknown"] = sources.get(source or "unknown", 0) + 1
        if game_build:
            builds.add(game_build)
    job = session.get(ImportJob, import_job_id) if import_job_id is not None else None
    return {
        "save_id": save_id,
        "import_job_id": import_job_id,
        "import_status": job.status if job is not None else None,
        "player_count": len(instances),
        "valid_snapshot_count": len(snapshots),
        "unique_game_dates": len(game_dates),
        "unique_observed_dates": len(observed_dates),
        "coverage": {
            "ca": coverage("ca"),
            "pa": coverage("pa"),
            "contract_end": coverage("contract_end"),
            "market_value": coverage("market_value"),
            "wage": coverage("wage"),
        },
        "field_anomaly_count": sum(
            1 for snapshot in snapshots
            if any(
                value is not None and value < 0
                for value in (snapshot.ca, snapshot.pa, snapshot.market_value, snapshot.wage)
            )
        ),
        "duplicate_game_date_rows": duplicate_game_dates,
        "source_distribution": sources,
        "game_builds": sorted(builds),
    }
