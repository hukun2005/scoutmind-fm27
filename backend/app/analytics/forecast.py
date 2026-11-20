"""球员成长预测（SM-019）。

可解释的统计基线，不使用机器学习：

1. 用同一实例的历史快照做最小二乘斜率（CA/年）；样本不足时退回年龄曲线；
2. 预测值按 PA 封顶（PA 是上限，不是必然结果）；
3. 区间 = 观测到的分区间速率标准差（至少 ±1 CA），样本越少区间越宽；
4. 置信度由快照数量与观测跨度决定；1–2 个快照不给 1 年以上的预测；
5. 回测：对有 ≥3 个快照的实例，用前 N-1 个点预测最后一个点，报告 MAE/RMSE/区间覆盖率。
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import PlayerInstance, PlayerSnapshot

ALGORITHM_VERSION = "development-forecast-1"

MIN_SNAPSHOTS_FOR_TREND = 3
DEFAULT_RATE_BY_AGE = ((21, 4.0), (24, 2.5), (27, 1.0), (30, 0.3), (99, 0.0))


def _rate_by_age(age: int | None) -> float:
    if age is None:
        return 1.0
    for limit, rate in DEFAULT_RATE_BY_AGE:
        if age <= limit:
            return rate
    return 0.0


def _slope_per_year(points: list[tuple[date, int]]) -> tuple[float | None, float | None]:
    """返回（斜率/年，分区间速率的标准差）。"""
    if len(points) < 2:
        return None, None
    xs = [(item[0] - points[0][0]).days / 365.25 for item in points]
    ys = [float(item[1]) for item in points]
    n = len(points)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    denom = sum((x - mean_x) ** 2 for x in xs)
    if denom == 0:
        return None, None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denom
    interval_rates = []
    for index in range(1, n):
        months = (points[index][0] - points[index - 1][0]).days / 365.25
        if months > 0:
            interval_rates.append((ys[index] - ys[index - 1]) / months)
    if len(interval_rates) < 2:
        return slope, None
    mean_rate = sum(interval_rates) / len(interval_rates)
    variance = sum((rate - mean_rate) ** 2 for rate in interval_rates) / (len(interval_rates) - 1)
    return slope, variance ** 0.5


def forecast_player(session: Session, instance_id: int) -> dict[str, Any]:
    instance = session.get(PlayerInstance, instance_id)
    if instance is None:
        raise ValueError("player instance not found")
    snapshots = [
        row
        for row in session.scalars(
            select(PlayerSnapshot)
            .where(PlayerSnapshot.player_instance_id == instance_id)
            .order_by(PlayerSnapshot.observed_at)
        )
        if row.ca is not None
    ]
    if not snapshots:
        raise ValueError("no CA observations; cannot forecast")
    points = [((row.game_date or row.observed_at.date()), int(row.ca)) for row in snapshots]
    latest = snapshots[-1]
    age = latest.age
    pa = latest.pa
    ca_now = int(latest.ca)
    slope, spread = _slope_per_year(points)
    gaps: list[str] = []
    basis: str
    if slope is None or len(points) < MIN_SNAPSHOTS_FOR_TREND:
        rate = _rate_by_age(age)
        basis = "年龄曲线默认值"
        gaps.append(f"快照 {len(points)} 个，不足以估计个人成长速率")
        confidence = "low"
    else:
        rate = slope
        basis = "历史快照最小二乘斜率"
        confidence = "high" if len(points) >= 5 else "medium"
    if pa is None:
        gaps.append("缺少 PA，预测不设上限")
    uncertainty = max(1.0, spread if spread is not None else abs(rate) * 0.5 + 1.0)
    span = (points[-1][0] - points[0][0]).days / 365.25

    def project(years: int) -> dict[str, Any] | None:
        if len(points) < 2 and years > 1:
            return None
        mid = ca_now + rate * years
        if pa is not None:
            mid = min(mid, float(pa))
        mid = max(float(ca_now), mid)
        low = max(float(ca_now), mid - uncertainty * years ** 0.5)
        high = mid + uncertainty * years ** 0.5
        if pa is not None:
            high = min(high, float(pa))
        return {
            "years": years,
            "low": round(low, 1),
            "mid": round(mid, 1),
            "high": round(high, 1),
            "uncertainty": round(uncertainty * years ** 0.5, 2),
        }

    return {
        "instance_id": instance_id,
        "player_name": instance.player.full_name if instance.player else None,
        "current": {"ca": ca_now, "pa": pa, "age": age, "observed_at": latest.observed_at.isoformat()},
        "basis": {
            "method": basis,
            "rate_per_year": round(rate, 2),
            "snapshots": len(points),
            "span_years": round(span, 2),
            "uncertainty_per_year": round(uncertainty, 2),
            "confidence": confidence,
        },
        "forecast": {"one_year": project(1), "three_years": project(3)},
        "ceiling": {
            "pa": pa,
            "room": (pa - ca_now) if pa is not None else None,
            "note": "PA 是上限参考，不是确定的未来 CA" if pa is not None else "PA 未知",
        },
        "gaps": gaps,
        "algorithm_version": ALGORITHM_VERSION,
    }


def backtest(session: Session, save_id: int, *, min_snapshots: int = 3) -> dict[str, Any]:
    """用历史快照做滚动回测：前 N-1 个点预测最后一个点。"""
    instance_ids = [
        row for row in session.scalars(
            select(PlayerSnapshot.player_instance_id)
            .join(PlayerInstance, PlayerInstance.id == PlayerSnapshot.player_instance_id)
            .where(PlayerInstance.fm_save_id == save_id, PlayerSnapshot.ca.is_not(None))
            .group_by(PlayerSnapshot.player_instance_id)
            .having(func.count() >= min_snapshots)
        )
    ]
    errors: list[float] = []
    covered = 0
    evaluated = 0
    for instance_id in instance_ids:
        snapshots = [
            row
            for row in session.scalars(
                select(PlayerSnapshot)
                .where(PlayerSnapshot.player_instance_id == instance_id, PlayerSnapshot.ca.is_not(None))
                .order_by(PlayerSnapshot.observed_at)
            )
        ]
        if len(snapshots) < min_snapshots:
            continue
        train = snapshots[:-1]
        actual = snapshots[-1]
        points = [((row.game_date or row.observed_at.date()), int(row.ca)) for row in train]
        slope, spread = _slope_per_year(points)
        years = ((actual.game_date or actual.observed_at.date()) - (train[-1].game_date or train[-1].observed_at.date())).days / 365.25
        if years <= 0:
            continue
        rate = slope if slope is not None else _rate_by_age(train[-1].age)
        predicted = float(train[-1].ca) + rate * years
        if train[-1].pa is not None:
            predicted = min(predicted, float(train[-1].pa))
        predicted = max(float(train[-1].ca), predicted)
        uncertainty = max(1.0, spread if spread is not None else 1.0)
        errors.append(abs(predicted - float(actual.ca)))
        if predicted - uncertainty * years ** 0.5 <= float(actual.ca) <= predicted + uncertainty * years ** 0.5:
            covered += 1
        evaluated += 1
    if not errors:
        return {
            "available": False,
            "reason": f"没有满足 {min_snapshots} 个快照的球员，无法回测",
            "evaluated": 0,
            "algorithm_version": ALGORITHM_VERSION,
        }
    mae = sum(errors) / len(errors)
    rmse = (sum(error ** 2 for error in errors) / len(errors)) ** 0.5
    return {
        "available": True,
        "evaluated": evaluated,
        "mae": round(mae, 2),
        "rmse": round(rmse, 2),
        "interval_coverage": round(covered / evaluated, 4),
        "min_snapshots": min_snapshots,
        "note": "回测只用该存档已有的历史快照；样本少时指标波动大",
        "algorithm_version": ALGORITHM_VERSION,
    }
