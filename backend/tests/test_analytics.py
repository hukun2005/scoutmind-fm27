"""Acceptance tests for the deterministic analytics: statistics, similarity and valuation."""

from __future__ import annotations

from datetime import datetime, timezone

from app.analytics.players import development, history
from app.analytics.transfers import TransferFilter, similar_transfers, transfer_price_stats
from app.analytics.valuation import estimate_value
from app.models import PlayerInstance, Transfer

from tests.helpers import import_document, player_row, scan_document, transfer_row

FEES = (10_000_000, 20_000_000, 30_000_000, 40_000_000, 50_000_000, 60_000_000, 70_000_000, 80_000_000)


def _seed_market(db, save) -> None:
    players = [
        player_row(
            f"P{index}",
            f"Player {index}",
            ca=140 + index,
            pa=170,
            position="ST",
            contract_end=None if index == 3 else "2029-06-30",
        )
        for index in range(8)
    ]
    transfers = [
        transfer_row(f"T{index}", f"P{index}", f"Player {index}", fee=fee, age=20 + index % 3, ca=140 + index)
        for index, fee in enumerate(FEES)
    ]
    transfers.append(transfer_row("T99", "P0", "Pending Player", fee=50_000_000, status="pending"))
    import_document(db, scan_document(players=players, transfers=transfers))


def test_price_stats_prefers_quantiles_and_excludes_non_completed(db, save):
    """Median and quartiles are computed over completed, priced transfers only."""
    _seed_market(db, save)
    stats = transfer_price_stats(db, save.id, TransferFilter())
    assert stats["sample_size"] == 8
    assert stats["median"] == 45_000_000
    assert stats["p25"] == 27_500_000
    assert stats["p75"] == 62_500_000
    assert stats["excluded"]["non_completed"] == 1
    assert stats["coverage"]["fee"] == 1.0
    assert stats["algorithm_version"] == "transfer-stats-1"


def test_price_stats_filters_by_age(db, save):
    """Age filters narrow the sample and are echoed in the response."""
    _seed_market(db, save)
    stats = transfer_price_stats(db, save.id, TransferFilter(min_age=20, max_age=20))
    assert stats["sample_size"] == 3
    assert stats["filters"]["min_age"] == 20


def test_similarity_reports_effective_weights_and_missing_fields(db, save):
    """A target without a contract end loses that factor and says so."""
    _seed_market(db, save)
    instance = db.query(PlayerInstance).filter(PlayerInstance.save_local_uid == "P3").one()
    outcome = similar_transfers(db, instance.id, limit=5)
    assert outcome.sample_size > 0
    assert "contract_remaining_months" in outcome.missing_fields
    assert outcome.effective_weights["contract"] == 0.0
    assert abs(sum(outcome.effective_weights.values()) - 1.0) < 1e-6


def test_valuation_refuses_small_samples(db, save):
    """Fewer than five comparables means no range at all."""
    players = [player_row(f"P{index}", f"Striker {index}", ca=150, pa=170, position="ST") for index in range(4)]
    transfers = [
        transfer_row(f"T{index}", f"P{index}", f"Striker {index}", fee=10_000_000 + index, ca=150) for index in range(4)
    ]
    import_document(db, scan_document(players=players, transfers=transfers))
    instance = db.query(PlayerInstance).filter(PlayerInstance.save_local_uid == "P0").one()
    result = estimate_value(db, instance.id)
    assert result["insufficient_sample"] is True
    assert result["low"] is None and result["mid"] is None and result["high"] is None
    assert result["sample_size"] == 3
    assert any("最小样本" in warning for warning in result["warnings"])


def test_valuation_produces_range_from_comparables(db, save):
    """Enough comparables produce a low/mid/high range with an algorithm version."""
    _seed_market(db, save)
    instance = db.query(PlayerInstance).filter(PlayerInstance.save_local_uid == "P3").one()
    result = estimate_value(db, instance.id)
    assert result["insufficient_sample"] is False
    assert result["low"] is not None and result["mid"] is not None and result["high"] is not None
    assert result["low"] <= result["mid"] <= result["high"]
    assert result["algorithm_version"] == "valuation-1"


def test_history_and_development_track_ca_growth(db, save):
    """Two snapshots produce deltas and separate fact from correlation and speculation."""
    import_document(
        db,
        scan_document(
            scan_id="scan-1",
            when=datetime(2026, 8, 1, tzinfo=timezone.utc),
            players=[player_row("P1", "Growth Player", ca=140, value=10_000_000)],
        ),
    )
    import_document(
        db,
        scan_document(
            scan_id="scan-2",
            when=datetime(2026, 11, 1, tzinfo=timezone.utc),
            players=[player_row("P1", "Growth Player", ca=146, value=16_000_000)],
        ),
    )
    instance = db.query(PlayerInstance).filter(PlayerInstance.save_local_uid == "P1").one()
    timeline = history(db, instance.id)
    assert len(timeline["points"]) == 2
    report = development(db, instance.id)
    assert report["summary"]["ca_delta"] == 6
    assert report["summary"]["market_value_delta"] == 6_000_000
    kinds = {item["kind"] for item in report["attributions"]}
    assert {"fact", "correlation", "speculation"} <= kinds


def test_transfer_status_progression_updates_pending(db, save):
    """A pending transfer that later completes is updated instead of duplicated."""
    import_document(
        db,
        scan_document(scan_id="scan-1", players=[player_row("P1", "Deal Player")],
                      transfers=[transfer_row("T1", "P1", "Deal Player", fee=10_000_000, status="pending")]),
    )
    import_document(
        db,
        scan_document(scan_id="scan-2", when=datetime(2026, 12, 1, tzinfo=timezone.utc),
                      players=[player_row("P1", "Deal Player")],
                      transfers=[transfer_row("T1", "P1", "Deal Player", fee=10_000_000, status="completed")]),
    )
    assert db.query(Transfer).count() == 1
    assert db.query(Transfer).one().status == "completed"
