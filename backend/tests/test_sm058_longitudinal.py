"""SM-058/059/060：长期观测序列、成长回测与质量摘要。"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select

from app.analytics.longitudinal import build_series, growth_backtest, growth_report, quality_summary
from app.ingestion.importer import ScanImporter
from app.ingestion.protocol import ScanPayload
from app.models import FmSave, PlayerInstance, User

from tests.helpers import player_row, scan_document


def _import(db, save, scan_id: str, when: datetime, ca: int, *, wage: int | None = 1000):
    payload = scan_document(
        scan_id=scan_id,
        when=when,
        players=[player_row("U1", "Longitudinal One", age=20, ca=ca, pa=180, value=1_000_000, wage=wage)],
    )
    ScanImporter(db).import_payload(save.id, ScanPayload.model_validate(payload))
    db.commit()


def _instance(db, save) -> PlayerInstance:
    return db.scalar(select(PlayerInstance).where(PlayerInstance.fm_save_id == save.id))


def _five_dates(db, save) -> None:
    for index, ca in enumerate((100, 102, 104, 106, 108)):
        _import(
            db,
            save,
            f"sm058-{index}",
            datetime(2026, 7, 1 + index, 12, tzinfo=timezone.utc),
            ca,
        )


def test_same_game_date_is_one_independent_point(db, save) -> None:
    _import(db, save, "sm058-a", datetime(2026, 7, 1, 9, tzinfo=timezone.utc), 100)
    _import(db, save, "sm058-b", datetime(2026, 7, 1, 20, tzinfo=timezone.utc), 101)
    series = build_series(db, save.id, _instance(db, save).id)
    assert series.raw_snapshot_count == 2
    assert series.unique_game_dates == 1
    assert series.unique_observed_dates == 2
    assert series.points[0].ca == 101, "同日重复扫描只保留最后一次作为独立观测"


def test_missing_fields_stay_none_and_cross_save_isolated(db, save) -> None:
    _import(db, save, "sm058-c", datetime(2026, 7, 2, 12, tzinfo=timezone.utc), 100, wage=None)
    other_user = User(username="sm058-other", display_name="other")
    db.add(other_user)
    db.commit()
    other = FmSave(user_id=other_user.id, name="other", game_version="27.1", game_build="x", is_active=False)
    db.add(other)
    db.commit()
    _import(db, other, "sm058-d", datetime(2026, 7, 2, 12, tzinfo=timezone.utc), 150)
    series = build_series(db, save.id, _instance(db, save).id)
    assert series.points[0].wage is None
    with pytest.raises(ValueError):
        build_series(db, other.id, _instance(db, save).id)


def test_growth_report_and_time_split_backtest(db, save) -> None:
    _five_dates(db, save)
    instance = _instance(db, save)
    report = growth_report(db, save.id, instance.id)
    assert report["available"] is True
    assert report["unique_game_dates"] == 5
    assert report["ca_first"] == 100 and report["ca_last"] == 108
    assert report["ca_growth_per_year"] > 0
    result = growth_backtest(db, save.id, min_points=3)
    assert result["available"] is True
    assert result["evaluated"] >= 1
    assert result["unique_game_dates"] == 5
    assert result["raw_snapshot_count"] == 5


def test_growth_unavailable_with_one_date(db, save) -> None:
    _import(db, save, "sm058-one", datetime(2026, 7, 3, 12, tzinfo=timezone.utc), 100)
    report = growth_report(db, save.id, _instance(db, save).id)
    assert report["available"] is False
    assert "2" in report["reason"]
    backtest = growth_backtest(db, save.id)
    assert backtest["available"] is False


def test_quality_summary_tracks_coverage_duplicates_and_sources(db, save) -> None:
    _import(db, save, "sm060-a", datetime(2026, 7, 1, 9, tzinfo=timezone.utc), 100)
    _import(db, save, "sm060-b", datetime(2026, 7, 1, 20, tzinfo=timezone.utc), 101)
    _import(db, save, "sm060-c", datetime(2026, 7, 2, 12, tzinfo=timezone.utc), 102, wage=None)
    summary = quality_summary(db, save.id)
    assert summary["valid_snapshot_count"] == 3
    assert summary["unique_game_dates"] == 2
    assert summary["duplicate_game_date_rows"] == 1
    assert summary["coverage"]["ca"] == 1.0
    assert summary["coverage"]["wage"] < 1.0
    assert summary["source_distribution"]


def test_quality_summary_endpoint(client, db, save) -> None:
    _import(db, save, "sm060-api", datetime(2026, 7, 4, 12, tzinfo=timezone.utc), 100)
    response = client.get("/api/v1/data-quality/summary")
    assert response.status_code == 200, response.text
    assert response.json()["valid_snapshot_count"] >= 1