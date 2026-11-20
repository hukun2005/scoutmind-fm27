"""SM-005：转会统计的 SQL 下推与大表性能。"""

from __future__ import annotations

import time
from datetime import date, timedelta

import pytest
from sqlalchemy import insert, select, text
from sqlalchemy.orm import Session

from app.analytics.deals import transaction_summary
from app.analytics.transfers import TransferFilter, transfer_price_stats
from app.models import FmSave, Transfer


def _bulk(db: Session, save_id: int, count: int, *, prefix: str = "T") -> None:
    """直接 Core 批量插入，避免 50 万行时逐行 ORM 开销。"""
    base = date(2020, 1, 1)
    rows = [
        {
            "fm_save_id": save_id,
            "source_record_id": f"{prefix}{index}",
            "player_name": f"Player {index}",
            "transfer_type": "permanent",
            "status": "completed",
            "transfer_date": base + timedelta(days=index % 2000),
            "currency": "EUR",
            "effective_fee": float(1_000_000 + index),
            "source": "manual",
        }
        for index in range(count)
    ]
    db.execute(insert(Transfer), rows)
    db.commit()


def test_transaction_summary_aggregates_in_sql(db: Session, save: FmSave) -> None:
    db.add_all(
        [
            Transfer(fm_save_id=save.id, source_record_id="S1", player_name="A", transfer_type="permanent",
                     status="completed", transfer_date=date(2026, 1, 1), currency="EUR", effective_fee=10.0,
                     source="manual"),
            Transfer(fm_save_id=save.id, source_record_id="S2", player_name="B", transfer_type="loan",
                     status="completed", transfer_date=date(2026, 2, 1), currency="EUR", effective_fee=2.0,
                     source="manual"),
            Transfer(fm_save_id=save.id, source_record_id="S3", player_name="C", transfer_type="permanent",
                     status="cancelled", transfer_date=date(2026, 3, 1), currency="EUR", effective_fee=99.0,
                     source="manual"),
        ]
    )
    db.commit()

    summary = transaction_summary(db, save.id)
    by_key = {item["key"]: item for item in summary["categories"]}
    assert summary["total"] == 3
    assert by_key["completed_permanent"]["known_amount"] == pytest.approx(10.0)
    assert by_key["loan"]["known_amount"] == pytest.approx(2.0)
    assert by_key["cancelled"]["known_amount"] == pytest.approx(0.0), "取消交易不计入实际支出"


@pytest.mark.parametrize("count", [50_000, 100_000, 500_000])
def test_price_stats_scale_with_sql_pushdown(db: Session, save: FmSave, count: int) -> None:
    """50k / 100k / 500k 行：统计必须在合理时间内完成且结果正确。"""
    _bulk(db, save.id, count, prefix=f"P{count}-")
    started = time.perf_counter()
    stats = transfer_price_stats(db, save.id, TransferFilter())
    elapsed = time.perf_counter() - started
    assert stats["sample_size"] == count
    assert stats["availability"]["transfer_history"] is True
    # 均值 = 1,000,000 + (0..count-1) 的平均值
    expected = 1_000_000 + (count - 1) / 2
    assert stats["mean"] == pytest.approx(expected, rel=1e-6)
    assert elapsed < 5.0, f"{count} 行统计耗时 {elapsed:.2f}s，SQL 下推可能失效"
