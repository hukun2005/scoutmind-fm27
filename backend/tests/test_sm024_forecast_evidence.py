"""SM-024：球员成长预测可靠性。"""

from __future__ import annotations

from datetime import date, datetime, time

import pytest
from sqlalchemy import select

from app.analytics.forecast import backtest, forecast_player
from app.models import Player, PlayerInstance, PlayerSnapshot


def _instance(db, save, uid: str) -> PlayerInstance:
    player = Player(full_name=f"Forecast {uid}", normalized_name=f"forecast-{uid.lower()}")
    db.add(player)
    db.commit()
    instance = PlayerInstance(player_id=player.id, fm_save_id=save.id, save_local_uid=uid)
    db.add(instance)
    db.commit()
    return instance


def _snapshot(db, instance, *, when: datetime, wage: int | None, market: int | None,
              contract_end: date | None, ca: int = 140, pa: int = 170) -> None:
    db.add(
        PlayerSnapshot(
            player_instance_id=instance.id,
            observed_at=when,
            game_date=when.date(),
            age=24,
            ca=ca,
            pa=pa,
            market_value=market,
            wage=wage,
            contract_end=contract_end,
            source="manual",
        )
    )
    db.commit()


def _forecast_instance(db, save, dates_ca: list[tuple[date, int]], *, pa: int = 160) -> PlayerInstance:
    instance = _instance(db, save, "F" + str(len(dates_ca)) + str(dates_ca[0][1]))
    for when, ca in dates_ca:
        _snapshot(db, instance, when=datetime.combine(when, time(12)), wage=10_000, market=5_000_000,
                  contract_end=date(2030, 6, 30), ca=ca, pa=pa)
    return instance


def test_single_snapshot_has_no_forecast(db, save) -> None:
    instance = _forecast_instance(db, save, [(date(2026, 1, 1), 120)])
    body = forecast_player(db, instance.id)
    assert body["forecast"]["one_year"] is None
    assert body["forecast"]["three_years"] is None
    assert body["basis"]["confidence"] == "low"


def test_two_snapshots_no_three_year_forecast(db, save) -> None:
    instance = _forecast_instance(db, save, [(date(2026, 1, 1), 120), (date(2026, 7, 1), 126)])
    body = forecast_player(db, instance.id)
    assert body["forecast"]["one_year"] is not None
    assert body["forecast"]["three_years"] is None
    assert body["basis"]["confidence"] in {"low", "medium"}


def test_same_day_repeats_are_not_independent_observations(db, save) -> None:
    instance = _forecast_instance(db, save, [(date(2026, 1, 1), 120)])
    for hour, ca in ((13, 124), (14, 126)):
        _snapshot(db, instance, when=datetime(2026, 1, 1, hour), wage=10_000, market=5_000_000, contract_end=date(2030, 6, 30), ca=ca, pa=160)
    body = forecast_player(db, instance.id)
    assert body["basis"]["snapshots"] >= 1
    assert body["forecast"]["three_years"] is None, "同一天重复扫描不能凑成 3 个时间点"
    assert any("重复观察" in gap for gap in body["gaps"])


def test_ca_above_pa_is_flagged_and_not_extrapolated(db, save) -> None:
    instance = _forecast_instance(db, save, [(date(2026, 1, 1), 170), (date(2026, 7, 1), 175), (date(2027, 1, 1), 180)], pa=160)
    body = forecast_player(db, instance.id)
    assert body["basis"]["anomalies"], "CA>PA 必须标记"
    one = body["forecast"]["one_year"]
    assert one["high"] <= 180, "预测不能继续远离 PA 上限"


def test_age_curve_fallback_is_labelled_assumption(db, save) -> None:
    instance = _forecast_instance(db, save, [(date(2026, 1, 1), 100)])
    body = forecast_player(db, instance.id)
    assert body["basis"]["statistical_assumption"] is True
    assert "假设" in body["basis"]["method"]


def test_high_confidence_requires_five_points_and_one_year(db, save) -> None:
    five = _forecast_instance(
        db, save,
        [(date(2025, 1, 1), 100), (date(2025, 7, 1), 104), (date(2026, 1, 1), 108), (date(2026, 7, 1), 112), (date(2027, 1, 1), 116)],
    )
    body = forecast_player(db, five.id)
    assert body["basis"]["confidence"] == "high"
    assert body["forecast"]["three_years"] is not None


def test_backtest_uses_only_past_points(db, save) -> None:
    instance = _forecast_instance(db, save, [(date(2024, 1, 1), 100), (date(2025, 1, 1), 110), (date(2026, 1, 1), 130)])
    result = backtest(db, save.id, min_snapshots=3)
    assert result["available"] is True
    assert result["evaluated"] == 1
    # 用前两点预测 130：斜率 10/年，预测 120，误差 10（而不是用 130 去"预测"自己）
    assert result["mae"] == pytest.approx(10.0, abs=0.1), "年化换算按 365.25 天，允许 0.1 误差"
