"""球员成长预测（SM-019）。

可解释的统计基线，不使用机器学习：

1. 用同一实例的历史快照做最小二乘斜率（CA/年）；样本不足时退回年龄曲线；
2. 预测值按 PA 封顶（PA 是上限，不是必然结果）；
3. 区间 = 观测到的分区间速率标准差（至少 ±1 CA），样本越少区间越宽；
4. 置信度由快照数量与观测跨度决定；1–2 个快照不给 1 年以上的预测；
5. 回测：对有 ≥3 个快照的实例，用前 N-1 个点预测最后一个点，报告 MAE/RMSE/区间覆盖率。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import PlayerInstance, PlayerSnapshot
from .canonical import select_canonical_snapshots

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
    selected, canonical_meta = select_canonical_snapshots(
        session, instance.fm_save_id, instance_id, legacy_if_missing=True
    )
    snapshots = [row for row in selected if row.ca is not None]
    if not snapshots:
        raise ValueError("no CA observations; cannot forecast")
    latest = snapshots[-1]
    age = latest.age
    pa = latest.pa
    ca_now = int(latest.ca)
    gaps: list[str] = []
    # 同一天的多次扫描不是独立时间观察：按日期去重，保留当天最后一次。
    by_day: dict[date, int] = {}
    for row in snapshots:
        by_day[row.game_date or row.observed_at.date()] = int(row.ca)
    points = sorted(by_day.items())
    if len(points) < len(snapshots):
        gaps.append(f"同一天有 {len(snapshots) - len(points)} 条重复观察，已按日期去重")
    anomalies: list[str] = []
    if pa is not None and ca_now > pa:
        anomalies.append(f"CA {ca_now} 大于 PA {pa}：数据异常，预测不向上扩展")
    if pa is not None and any(ca > pa for _, ca in points):
        anomalies.append("历史 CA 曾超过 PA，PA 上限按数据异常处理")
    slope, spread = _slope_per_year(points)
    basis: str
    if slope is None or len(points) < MIN_SNAPSHOTS_FOR_TREND:
        rate = _rate_by_age(age)
        basis = "年龄曲线统计假设"
        gaps.append(f"独立观测日 {len(points)} 个，不足以估计个人成长速率；以下为年龄曲线假设")
        confidence = "low"
        assumption = True
    else:
        rate = slope
        basis = "历史快照最小二乘斜率"
        assumption = False
        # 置信度同时考虑快照数量、观测跨度与数据质量。
        span_years = (points[-1][0] - points[0][0]).days / 365.25
        if len(points) >= 5 and span_years >= 1.0 and not anomalies:
            confidence = "high"
        elif len(points) >= 3 and span_years >= 0.25 and not anomalies:
            confidence = "medium"
        else:
            confidence = "low"
            gaps.append("观测跨度或样本量不足，置信度降为 low")
    if pa is None:
        gaps.append("缺少 PA，预测不设上限")
    uncertainty = max(1.0, spread if spread is not None else abs(rate) * 0.5 + 1.0)
    span = (points[-1][0] - points[0][0]).days / 365.25

    def project(years: int) -> dict[str, Any] | None:
        if len(points) <= 1:
            return None
        if years > 1 and len(points) < MIN_SNAPSHOTS_FOR_TREND:
            return None
        base = ca_now if not anomalies or pa is None or ca_now <= pa else float(pa)
        mid = ca_now + rate * years if (pa is None or ca_now <= pa) else float(pa)
        if pa is not None:
            mid = min(mid, float(pa))
        mid = max(base, mid)
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
            "statistical_assumption": assumption,
            "anomalies": anomalies,
        },
        "forecast": {"one_year": project(1), "three_years": project(3)},
        "canonicalization": canonical_meta,
        "ceiling": {
            "pa": pa,
            "room": (pa - ca_now) if pa is not None else None,
            "note": "PA 是上限参考，不是确定的未来 CA" if pa is not None else "PA 未知",
        },
        "gaps": gaps,
        "algorithm_version": ALGORITHM_VERSION,
    }


def _observation_points(snapshots: list[PlayerSnapshot]) -> tuple[list[tuple[date, int]], int]:
    """按"游戏日期优先、observed_at 兜底"排序并去重。

    同一天多条快照只保留当天最后一次观测（observed_at 最大），这是明确、可解释的策略：
    一天内的多次扫描不是独立时间点，CA 差异按"当天最后状态"处理。
    返回（去重后的点，原始快照数）。
    """
    by_day: dict[date, tuple[datetime, int]] = {}
    for row in snapshots:
        day = row.game_date or row.observed_at.date()
        current = by_day.get(day)
        if current is None or row.observed_at >= current[0]:
            by_day[day] = (row.observed_at, int(row.ca))
    points = [(day, value) for day, (_observed, value) in sorted(by_day.items())]
    return points, len(snapshots)


def backtest(session: Session, save_id: int, *, min_snapshots: int = 3) -> dict[str, Any]:
    """用历史快照做滚动回测：门槛按"独立观测日"计算，训练只用到验证点之前的数据。

    `min_snapshots` 表示至少需要的**独立观测日**数（不是原始快照条数）。
    """
    instance_ids = list(
        session.scalars(
            select(PlayerSnapshot.player_instance_id)
            .join(PlayerInstance, PlayerInstance.id == PlayerSnapshot.player_instance_id)
            .where(PlayerInstance.fm_save_id == save_id, PlayerSnapshot.ca.is_not(None))
            .group_by(PlayerSnapshot.player_instance_id)
        )
    )
    errors: list[float] = []
    covered = 0
    raw_total = 0
    distinct_total = 0
    skipped_incomplete = 0
    legacy_instances = 0
    for instance_id in instance_ids:
        selected, canonical_meta = select_canonical_snapshots(
            session, save_id, instance_id, legacy_if_missing=True
        )
        snapshots = [row for row in selected if row.ca is not None]
        if canonical_meta["legacy_mode"]:
            legacy_instances += 1
        raw_total += len(snapshots)
        points, _ = _observation_points(snapshots)
        distinct_total += len(points)
        if len(points) < min_snapshots:
            skipped_incomplete += 1
            continue
        # 训练 = 除最后一个独立观测日外的所有点；验证 = 最后一个点。
        train_points = points[:-1]
        valid_day, actual_ca = points[-1]
        if len(train_points) < 2:
            skipped_incomplete += 1
            continue
        slope, spread = _slope_per_year(train_points)
        reference_day, reference_ca = train_points[-1]
        years = (valid_day - reference_day).days / 365.25
        if years <= 0:
            skipped_incomplete += 1
            continue
        # 训练中最后一条的 PA 作为上限（只用验证点之前的信息）。
        last_snapshot = max(
            (row for row in snapshots if (row.game_date or row.observed_at.date()) <= reference_day),
            key=lambda row: (row.game_date or row.observed_at.date(), row.observed_at),
        )
        rate = slope if slope is not None else _rate_by_age(last_snapshot.age)
        predicted = float(reference_ca) + rate * years
        if last_snapshot.pa is not None:
            predicted = min(predicted, float(last_snapshot.pa))
        predicted = max(float(reference_ca), predicted)
        uncertainty = max(1.0, spread if spread is not None else 1.0)
        errors.append(abs(predicted - float(actual_ca)))
        if predicted - uncertainty * years ** 0.5 <= float(actual_ca) <= predicted + uncertainty * years ** 0.5:
            covered += 1

    if not errors:
        return {
            "available": False,
            "reason": f"没有满足 {min_snapshots} 个独立观测日的球员，无法回测",
            "raw_snapshots": raw_total,
            "distinct_days": distinct_total,
            "evaluated": 0,
            "skipped_incomplete": skipped_incomplete,
            "legacy_instances": legacy_instances,
            "algorithm_version": ALGORITHM_VERSION,
        }
    mae = sum(errors) / len(errors)
    rmse = (sum(error ** 2 for error in errors) / len(errors)) ** 0.5
    return {
        "available": True,
        "evaluated": len(errors),
        "raw_snapshots": raw_total,
        "distinct_days": distinct_total,
        "skipped_incomplete": skipped_incomplete,
        "legacy_instances": legacy_instances,
        "min_snapshots": min_snapshots,
        "mae": round(mae, 2),
        "rmse": round(rmse, 2),
        "interval_coverage": round(covered / len(errors), 4),
        "note": "门槛按独立观测日；同日重复只保留最后一次；训练只用验证点之前的数据",
        "algorithm_version": ALGORITHM_VERSION,
    }
