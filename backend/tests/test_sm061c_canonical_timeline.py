"""SM-061C：canonical 状态接入成长时间轴。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.analytics.longitudinal import build_series, growth_report
from app.ingestion.importer import ScanImporter
from app.ingestion.protocol import ScanPayload
from app.models import FmSave, PlayerInstance, PlayerObservationCanonical, PlayerSnapshot, User
from app.quality.dedup import build_canonicals

from tests.helpers import player_row, scan_document


def _import(db, save, scan_id: str, when: datetime, ca: int, attributes: dict | None = None):
    payload = scan_document(scan_id=scan_id, when=when, players=[player_row("C1", "Canonical One", ca=ca, attributes=attributes)])
    ScanImporter(db).import_payload(save.id, ScanPayload.model_validate(payload))
    db.commit()


def _instance(db, save) -> PlayerInstance:
    return db.scalar(select(PlayerInstance).where(PlayerInstance.fm_save_id == save.id))


def _two_days(db, save):
    _import(db, save, "c-a", datetime(2026, 7, 1, 9, tzinfo=timezone.utc), 100)
    _import(db, save, "c-b", datetime(2026, 7, 2, 9, tzinfo=timezone.utc), 102)
    build_canonicals(db, save.id, dry_run=False)


def test_resolved_enters_timeline(db, save) -> None:
    _two_days(db, save)
    series = build_series(db, save.id, _instance(db, save).id)
    assert series.canonical_point_count == 2
    assert [point.ca for point in series.points] == [100, 102]
    assert growth_report(db, save.id, _instance(db, save).id)["available"] is True


def test_resolved_manual_enters_timeline_and_survives_rescan(db, save) -> None:
    _two_days(db, save)
    canonical = db.scalar(select(PlayerObservationCanonical).where(PlayerObservationCanonical.game_date == datetime(2026, 7, 1).date()))
    first = db.scalar(select(PlayerSnapshot).where(PlayerSnapshot.id == canonical.canonical_snapshot_id))
    canonical.status = "resolved_manual"
    canonical.reason = "人工确认"
    db.commit()
    build_canonicals(db, save.id, dry_run=False)
    db.refresh(canonical)
    assert canonical.status == "resolved_manual"
    assert canonical.canonical_snapshot_id == first.id
    series = build_series(db, save.id, _instance(db, save).id)
    assert series.canonical_point_count == 2


def test_needs_review_and_excluded_are_not_used(db, save) -> None:
    _import(db, save, "c-a", datetime(2026, 7, 1, 9, tzinfo=timezone.utc), 100)
    _import(db, save, "c-b", datetime(2026, 7, 1, 20, tzinfo=timezone.utc), 105)
    build_canonicals(db, save.id, dry_run=False)
    series = build_series(db, save.id, _instance(db, save).id)
    assert series.points == []
    assert series.excluded_conflict_count == 1
    assert series.excluded_snapshot_count == 2

    canonical = db.scalar(select(PlayerObservationCanonical))
    canonical.status = "excluded"
    canonical.canonical_snapshot_id = None
    db.commit()
    series = build_series(db, save.id, _instance(db, save).id)
    assert series.points == []
    assert series.excluded_conflict_count == 1


def test_null_or_foreign_canonical_snapshot_is_rejected(db, save) -> None:
    _two_days(db, save)
    for canonical in db.scalars(select(PlayerObservationCanonical)):
        canonical.canonical_snapshot_id = None
    db.commit()
    assert build_series(db, save.id, _instance(db, save).id).points == []

    other_user = User(username="canon-other", display_name="other")
    db.add(other_user)
    db.commit()
    other = FmSave(user_id=other_user.id, name="other", game_version="27.1", game_build="x", is_active=False)
    db.add(other)
    db.commit()
    _import(db, other, "c-other", datetime(2026, 7, 3, 9, tzinfo=timezone.utc), 120)
    foreign = db.scalar(select(PlayerSnapshot).where(PlayerSnapshot.player_instance_id == _instance(db, other).id))
    canonical = db.scalar(select(PlayerObservationCanonical).where(PlayerObservationCanonical.game_date == datetime(2026, 7, 1).date()))
    canonical.canonical_snapshot_id = foreign.id
    db.commit()
    series = build_series(db, save.id, _instance(db, save).id)
    assert series.canonical_point_count == 0
    assert series.excluded_conflict_count >= 1


def test_missing_canonical_returns_pending_or_explicit_legacy(db, save) -> None:
    _import(db, save, "c-a", datetime(2026, 7, 1, 9, tzinfo=timezone.utc), 100)
    _import(db, save, "c-b", datetime(2026, 7, 2, 9, tzinfo=timezone.utc), 102)
    strict = build_series(db, save.id, _instance(db, save).id)
    assert strict.points == []
    assert strict.canonicalization_pending is True
    assert strict.legacy_mode is False
    legacy = build_series(db, save.id, _instance(db, save).id, legacy=True)
    assert legacy.legacy_mode is True
    assert legacy.canonical_point_count == 2
    assert legacy.canonicalization_pending is True


def test_development_and_forecast_exclude_conflict(db, save) -> None:
    from app.analytics.development import growth_profile
    from app.analytics.forecast import forecast_player

    _import(db, save, "c-a", datetime(2026, 7, 1, 9, tzinfo=timezone.utc), 100)
    _import(db, save, "c-b", datetime(2026, 7, 1, 20, tzinfo=timezone.utc), 105)
    build_canonicals(db, save.id, dry_run=False)
    profile = growth_profile(db, _instance(db, save).id)
    assert profile["points"] == []
    assert profile["canonicalization"]["excluded_conflict_count"] == 1
    try:
        forecast_player(db, _instance(db, save).id)
    except ValueError as exc:
        assert "no CA observations" in str(exc)
    else:
        raise AssertionError("conflict-only player must not be forecast")


def test_development_marks_legacy_when_canonical_missing(db, save) -> None:
    from app.analytics.development import growth_profile

    _import(db, save, "c-a", datetime(2026, 7, 1, 9, tzinfo=timezone.utc), 100)
    profile = growth_profile(db, _instance(db, save).id)
    assert profile["canonicalization"]["legacy_mode"] is True
    assert profile["canonicalization"]["canonicalization_pending"] is True


def test_growth_backtest_cutoff_does_not_train_on_future(db, save) -> None:
    from app.analytics.longitudinal import growth_backtest

    for index, ca in enumerate((100, 102, 104, 106, 108)):
        _import(db, save, f"cut-{index}", datetime(2026, 7, 1 + index, 12, tzinfo=timezone.utc), ca)
    build_canonicals(db, save.id, dry_run=False)
    result = growth_backtest(db, save.id, min_points=3)
    assert result["available"] is True
    assert result["cutoff_game_date"] < "2026-07-05"
    assert result["unique_game_dates"] == 5


def test_development_matches_canonical_series(db, save) -> None:
    from app.analytics.development import growth_profile

    _two_days(db, save)
    instance = _instance(db, save)
    series = build_series(db, save.id, instance.id)
    profile = growth_profile(db, instance.id)
    assert [point["date"] for point in profile["points"]] == [point.game_date.isoformat() for point in series.points]
    assert profile["canonicalization"]["canonical_point_count"] == series.canonical_point_count


def test_attribute_trends_use_canonical_snapshots(db, save) -> None:
    from app.analytics.development import growth_profile

    _import(db, save, "attr-a", datetime(2026, 7, 1, 9, tzinfo=timezone.utc), 100, {"pace": 10})
    _import(db, save, "attr-b", datetime(2026, 7, 2, 9, tzinfo=timezone.utc), 102, {"pace": 12})
    build_canonicals(db, save.id, dry_run=False)
    profile = growth_profile(db, _instance(db, save).id)
    assert profile["attribute_trends"]["available"] is True
    category = next(item for item in profile["attribute_trends"]["categories"] if item["category"] == "physical")
    assert category["delta"] == 2.0
