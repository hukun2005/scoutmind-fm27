"""SM-028：回测的独立观测日与排序。"""

from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy import select

from app.analytics.forecast import backtest
from app.models import Player, PlayerInstance, PlayerSnapshot


def _instance(db, save, uid: str) -> PlayerInstance:
    player = Player(full_name=f"Backtest {uid}", normalized_name=f"backtest-{uid.lower()}")
    db.add(player)
    db.commit()
    instance = PlayerInstance(player_id=player.id, fm_save_id=save.id, save_local_uid=uid)
    db.add(instance)
    db.commit()
    return instance


def _snap(db, instance, *, observed: datetime, game_date: date | None, ca: int | None, pa: int = 180) -> None:
    db.add(
        PlayerSnapshot(
            player_instance_id=instance.id,
            observed_at=observed,
            game_date=game_date,
            age=20,
            ca=ca,
            pa=pa,
            market_value=5_000_000,
            wage=10_000,
            contract_end=date(2030, 6, 30),
            source="manual",
        )
    )
    db.commit()


def test_repeated_dates_do_not_count_toward_min_days(db, save) -> None:
    instance = _instance(db, save, "R1")
    _snap(db, instance, observed=datetime(2026, 1, 1, 12), game_date=date(2026, 1, 1), ca=100)
    _snap(db, instance, observed=datetime(2026, 1, 1, 13), game_date=date(2026, 1, 1), ca=102)
    _snap(db, instance, observed=datetime(2026, 7, 1, 12), game_date=date(2026, 7, 1), ca=106)
    result = backtest(db, save.id, min_snapshots=3)
    assert result["available"] is False, "两个独立观测日不够三个"
    assert result["raw_snapshots"] == 3
    assert result["distinct_days"] == 2
    assert result["evaluated"] == 0


def test_same_day_uses_last_observation(db, save) -> None:
    instance = _instance(db, save, "R2")
    _snap(db, instance, observed=datetime(2026, 1, 1, 12), game_date=date(2026, 1, 1), ca=100)
    _snap(db, instance, observed=datetime(2026, 1, 1, 18), game_date=date(2026, 1, 1), ca=104)
    _snap(db, instance, observed=datetime(2026, 7, 1, 12), game_date=date(2026, 7, 1), ca=110)
    _snap(db, instance, observed=datetime(2027, 1, 1, 12), game_date=date(2027, 1, 1), ca=120)
    result = backtest(db, save.id, min_snapshots=3)
    assert result["available"] is True
    assert result["raw_snapshots"] == 4 and result["distinct_days"] == 3
    # 同日保留 104：训练 104→110（6/年），预测 116，实际 120 → MAE 约 4（按 365.25 天）。
    assert result["mae"] == pytest.approx(4.0, abs=0.2)


def test_game_date_order_wins_over_insertion_order(db, save) -> None:
    instance = _instance(db, save, "R3")
    # 插入顺序与游戏日期相反；回测必须按 game_date 排序。
    _snap(db, instance, observed=datetime(2026, 11, 1, 12), game_date=date(2026, 1, 1), ca=130)
    _snap(db, instance, observed=datetime(2026, 6, 1, 12), game_date=date(2025, 1, 1), ca=110)
    _snap(db, instance, observed=datetime(2026, 1, 1, 12), game_date=date(2024, 1, 1), ca=100)
    result = backtest(db, save.id, min_snapshots=3)
    assert result["available"] is True
    assert result["evaluated"] == 1
    assert result["mae"] == pytest.approx(10.0, abs=0.2)


def test_missing_ca_is_excluded_from_counts(db, save) -> None:
    instance = _instance(db, save, "R4")
    _snap(db, instance, observed=datetime(2026, 1, 1, 12), game_date=date(2026, 1, 1), ca=None)
    _snap(db, instance, observed=datetime(2026, 7, 1, 12), game_date=date(2026, 7, 1), ca=110)
    _snap(db, instance, observed=datetime(2027, 1, 1, 12), game_date=date(2027, 1, 1), ca=120)
    result = backtest(db, save.id, min_snapshots=3)
    assert result["available"] is False
    assert result["raw_snapshots"] == 2, "没有 CA 的快照不进入回测计数"


def test_backtest_reports_consistent_sample_counts(db, save) -> None:
    instance = _instance(db, save, "R5")
    _snap(db, instance, observed=datetime(2026, 1, 1, 12), game_date=date(2026, 1, 1), ca=100)
    _snap(db, instance, observed=datetime(2026, 7, 1, 12), game_date=date(2026, 7, 1), ca=110)
    _snap(db, instance, observed=datetime(2027, 1, 1, 12), game_date=date(2027, 1, 1), ca=130)
    result = backtest(db, save.id, min_snapshots=3)
    assert result["evaluated"] == 1
    assert result["raw_snapshots"] >= result["distinct_days"] >= result["evaluated"]
    assert 0 <= result["interval_coverage"] <= 1
