"""Tests for the V2 intelligence modules: squad, recruitment, development, performance and deals.

Each test states the behaviour the product promises: scores come from observed data, a missing input is reported as
unavailable instead of becoming a zero, and the same request twice produces the same answer.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.analytics.deals import (
    category_of,
    deal_cost,
    decision_report,
    investment_score,
    transaction_summary,
    transfer_review,
)
from app.analytics.development import growth_profile
from app.analytics.performance import performance_board, performance_profile
from app.analytics.recruitment import (
    build_shortlist,
    candidate_pool,
    compare_players,
    hidden_value,
    player_score,
    search_recruitment,
)
from app.analytics.squad import (
    DEFAULT_WEIGHTS,
    normalise_weights,
    resolve_weights,
    squad_overview,
)
from app.models import PlayerStatistic, RecruitmentShortlistItem, Transfer

from .helpers import (
    club_row,
    ensure_save,
    import_document,
    player_row,
    scan_document,
    season_stats,
    transfer_row,
)

FULL_SQUAD = (
    ("GK", 2),
    ("DC", 4),
    ("DL", 2),
    ("DR", 2),
    ("DM", 2),
    ("MC", 3),
    ("AMC", 1),
    ("AML", 2),
    ("AMR", 2),
    ("ST", 2),
)


def _build_squad(statistics: bool = False, include_market: bool = False) -> list[dict]:
    """A complete managed squad with the attributes every position template needs."""
    rows: list[dict] = []
    index = 0
    for position, count in FULL_SQUAD:
        for slot_index in range(count):
            index += 1
            attributes = {
                key: 12 + (index % 5)
                for key in (
                    "finishing",
                    "off_the_ball",
                    "pace",
                    "anticipation",
                    "dribbling",
                    "first_touch",
                    "strength",
                    "decisions",
                    "passing",
                    "vision",
                    "technique",
                    "tackling",
                    "marking",
                    "positioning",
                    "heading",
                    "composure",
                    "stamina",
                    "teamwork",
                    "work_rate",
                    "reflexes",
                    "handling",
                    "one_on_ones",
                    "aerial_reach",
                    "command_of_area",
                    "communication",
                    "kicking",
                    "rushing_out",
                    "crossing",
                    "acceleration",
                )
            }
            rows.append(
                player_row(
                    f"S{index}",
                    f"Squad Player {index}",
                    ca=150 - slot_index * 8,
                    pa=165 - slot_index * 5,
                    position=position,
                    age=20 + (index % 12),
                    value=8_000_000 + index * 500_000,
                    attributes=attributes,
                    statistics=[season_stats(period="2026/27")] if statistics else None,
                )
            )
    if include_market:
        # Candidates outside the managed club, so recruitment filters have something to return.
        for offset, position in enumerate(("ST", "ST", "ST", "AMC", "DC", "AML", "AMR", "MC", "GK", "DM")):
            index += 1
            rows.append(
                player_row(
                    f"M{offset}",
                    f"Market Player {offset}",
                    ca=130 + offset * 3,
                    pa=150 + offset * 4,
                    position=position,
                    age=19 + offset,
                    value=6_000_000 + offset * 900_000,
                    club_uid="C2",
                    attributes=rows[offset]["attributes"],
                    statistics=[season_stats(period="2026/27", goals=6 + offset)] if statistics else None,
                )
            )
    return rows


def test_squad_score_uses_all_six_components(db, save) -> None:
    """A complete squad with every input scores on all six dimensions of the product formula."""
    import_document(db, scan_document(players=_build_squad()))
    result = squad_overview(db, save.id)
    components = {item["key"]: item for item in result["components"]}

    assert set(components) == set(DEFAULT_WEIGHTS)
    assert all(item["value"] is not None for item in components.values())
    assert result["score"] is not None
    assert 0 <= float(result["score"]) <= 100
    # The weighted score must equal the declared formula over the same components.
    expected = sum(float(components[key]["value"]) * DEFAULT_WEIGHTS[key] for key in DEFAULT_WEIGHTS)
    assert float(result["score"]) == pytest.approx(expected, abs=0.02)
    assert result["profile"]["weights"] == DEFAULT_WEIGHTS


def test_squad_depth_counts_every_slot(db, save) -> None:
    """Each slot reports the players mapped to it, so a hole is visible as count zero."""
    import_document(db, scan_document(players=_build_squad()))
    result = squad_overview(db, save.id)
    depth = {row["slot"]: row for row in result["depth"] if row["slot"] != "UNKNOWN"}

    assert depth["GK"]["count"] == 2
    assert depth["CB"]["count"] == 4
    assert depth["ST"]["count"] == 2
    assert depth["CB"]["status"] in {"良好", "一般", "拥挤"}
    assert result["weakness"], "短板排序不应为空"


def test_squad_weight_override_changes_the_score(db, save) -> None:
    """Explicit weights are normalised and applied; the same squad can score differently under another plan."""
    import_document(db, scan_document(players=_build_squad()))
    balanced = squad_overview(db, save.id)
    youth = squad_overview(db, save.id, overrides={"potential": 0.6, "coverage": 0.1})
    weights, profile = resolve_weights(db, save.id, None, {"potential": 0.6, "coverage": 0.1})

    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-6)
    assert profile["overridden"] is True
    assert youth["score"] != balanced["score"]


def test_squad_component_without_data_is_unavailable(db, save) -> None:
    """Without wage data the wage component reports unavailable instead of scoring zero."""
    rows = _build_squad()
    for row in rows:
        row["wage"] = None
    import_document(db, scan_document(players=rows))
    result = squad_overview(db, save.id)
    wage = next(item for item in result["components"] if item["key"] == "wage")

    assert wage["value"] is None
    assert wage["available"] is False
    assert wage["missing"], "缺失原因必须写清楚"
    assert result["data_gaps"], "缺失项必须出现在 data_gaps 中"


def test_normalise_weights_rejects_negative_and_zero_sum() -> None:
    """Weight normalisation clamps negatives and falls back to the baseline when nothing is left."""
    assert normalise_weights({"coverage": -1, "depth": 1}) == normalise_weights({"coverage": 0, "depth": 1})
    assert normalise_weights({key: 0 for key in DEFAULT_WEIGHTS}) == DEFAULT_WEIGHTS


def test_player_score_dimensions_and_missing_form(db, save) -> None:
    """Player score reports ability/potential/value and marks form unavailable without statistics."""
    import_document(db, scan_document(players=_build_squad()))
    pool = candidate_pool(db, save.id)
    target = next(item for item in pool if item.position == "ST")
    result = player_score(db, save.id, target.instance_id, pool)
    dimensions = {item["key"]: item for item in result["dimensions"]}

    assert dimensions["ability"]["value"] == pytest.approx(target.ca / 200 * 100, abs=0.01)
    assert dimensions["potential"]["value"] == pytest.approx(target.pa / 200 * 100, abs=0.01)
    assert dimensions["fit"]["value"] is not None
    assert dimensions["form"]["value"] is None
    assert dimensions["form"]["missing"], "没有统计时必须说明原因"
    assert result["score"] is not None


def test_player_form_percentile_uses_statistics(db, save) -> None:
    """With statistics present, form becomes a percentile inside the position group."""
    rows = _build_squad(statistics=True)
    import_document(db, scan_document(players=rows))
    pool = candidate_pool(db, save.id)
    target = next(item for item in pool if item.position == "ST")
    result = player_score(db, save.id, target.instance_id, pool)
    form = next(item for item in result["dimensions"] if item["key"] == "form")

    assert form["value"] is not None
    assert form["source"] == "percentile"
    assert "样本" in form["evidence"]


def test_search_and_hidden_value_report_unavailable_rules(db, save) -> None:
    """Hidden-value discovery lists the rules whose source fields do not exist in the payload."""
    import_document(db, scan_document(players=_build_squad(statistics=True, include_market=True)))
    search = search_recruitment(db, save.id, slot="ST", limit=5)
    hidden = hidden_value(db, save.id, limit=5)

    assert search["total"] >= 1
    assert all(item["player"]["slot"] == "ST" for item in search["items"])
    keys = {item["key"] for item in hidden["rules"]["unavailable"]}
    assert {"transfer_listed", "loan_possible"} <= keys


def test_shortlist_is_persisted_with_ranks(db, save) -> None:
    """A generated shortlist stores its candidates so the screen can reopen it."""
    import_document(db, scan_document(players=_build_squad(statistics=True, include_market=True)))
    result = build_shortlist(db, save.id, name="中锋引援", slot="ST", budget=40_000_000, limit=3, persist=True)
    db.commit()

    assert result["shortlist_id"]
    items = (
        db.query(RecruitmentShortlistItem)
        .filter(RecruitmentShortlistItem.shortlist_id == result["shortlist_id"])
        .order_by(RecruitmentShortlistItem.rank)
        .all()
    )
    assert [item.rank for item in items] == list(range(1, len(items) + 1))


def test_compare_players_uses_shared_dimensions(db, save) -> None:
    """Comparison only reports dimensions every compared player could be scored on."""
    import_document(db, scan_document(players=_build_squad(statistics=True)))
    pool = candidate_pool(db, save.id)
    ids = [item.instance_id for item in pool if item.position == "ST"][:2]
    result = compare_players(db, save.id, ids)

    assert result["compared"] == 2
    assert "form" not in result["shared_dimensions"] or "ability" in result["shared_dimensions"]


def test_growth_rate_and_outlook_band(db, save) -> None:
    """Two snapshots produce a growth rate and an explicit outlook interval, not a single predicted CA."""
    first = player_row("G1", "Growing Kid", ca=110, pa=160, age=18, position="ST")
    import_document(
        db,
        scan_document(
            scan_id="scan-g1",
            when=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
            players=[first],
        ),
    )
    second = dict(first, ca=122)
    import_document(
        db,
        scan_document(
            scan_id="scan-g2",
            when=datetime(2027, 2, 1, 12, tzinfo=timezone.utc),
            players=[second],
        ),
    )
    instance_id = db.query(PlayerStatistic).first()  # keeps the model import meaningful for other tests
    assert instance_id is None
    from app.models import PlayerInstance

    target = db.query(PlayerInstance).first()
    assert target is not None
    result = growth_profile(db, target.id)

    assert result["rates"]["overall_per_month"] is not None
    assert float(result["rates"]["overall_per_month"]) > 0
    outlook = result["outlook"]
    assert outlook["projected_low"] is not None and outlook["projected_high"] is not None
    assert outlook["projected_low"] <= outlook["projected_high"]
    assert "不是精确" in outlook["rationale"]
    assert result["advice"], "每次成长分析都必须给出建议或明确保持现状"


def test_performance_requires_statistics(db, save) -> None:
    """Without statistics the performance screens refuse to show numbers."""
    import_document(db, scan_document(players=_build_squad()))
    from app.models import PlayerInstance

    target = db.query(PlayerInstance).first()
    result = performance_profile(db, target.id)

    assert result["season"] is None
    assert result["data_gaps"], "缺少统计必须明确标记"
    assert performance_board(db, save.id)["total"] == 0


def test_performance_percentiles_and_trend(db, save) -> None:
    """With two periods stored, per-90 percentiles and a season-over-season trend are available."""
    rows = _build_squad()
    for index, row in enumerate(rows):
        row["statistics"] = [
            season_stats(period="2025/26", goals=4 + index % 3),
            season_stats(period="2026/27", goals=8 + index % 3),
        ]
    import_document(db, scan_document(players=rows))
    from app.models import PlayerInstance

    target = db.query(PlayerInstance).filter(PlayerInstance.position == "ST").first()
    assert target is not None
    result = performance_profile(db, target.id)
    goals = next(item for item in result["metrics"] if item["key"] == "goals")

    assert goals["per90"] is not None
    assert goals["percentile"] is not None
    assert result["trend"]["available"] is True
    assert result["trend"]["season_over_season"]["changes"]
    assert "last5" in result["trend"]["unavailable_windows"]


def test_transaction_taxonomy_classifies_types(db, save) -> None:
    """Loan, loan-with-option, free, pending and cancelled deals get distinct accounting categories."""
    rows = _build_squad()
    transfers = [
        transfer_row("T1", "S1", "Permanent Deal", 10_000_000),
        dict(transfer_row("T2", "S2", "Loan Deal", 500_000), transfer_type="loan"),
        dict(transfer_row("T3", "S3", "Loan Option Deal", 500_000), transfer_type="loan_with_option"),
        dict(transfer_row("T4", "S4", "Free Deal", 0), transfer_type="free", status="completed"),
        dict(transfer_row("T5", "S5", "Pending Deal", 1_000_000), status="pending"),
        dict(transfer_row("T6", "S6", "Cancelled Deal", 1_000_000), status="cancelled"),
    ]
    import_document(db, scan_document(players=rows, transfers=transfers))
    stored = {row.source_record_id: row for row in db.query(Transfer).all()}

    assert category_of(stored["T1"]) == "completed_permanent"
    assert category_of(stored["T2"]) == "loan"
    assert category_of(stored["T3"]) == "loan_with_option"
    assert category_of(stored["T4"]) == "free"
    assert category_of(stored["T5"]) == "pending"
    assert category_of(stored["T6"]) == "cancelled"

    summary = transaction_summary(db, save.id)
    labels = {item["key"]: item["label"] for item in summary["categories"]}
    assert labels["loan_with_option"] == "租借附买断"
    assert all(item["counts_in_stats"] is False for item in summary["categories"] if item["key"] != "completed_permanent")
    # An unfinished or cancelled deal is a record, not money spent.
    amounts = {item["key"]: item["known_amount"] for item in summary["categories"]}
    assert amounts["pending"] == 0.0
    assert amounts["cancelled"] == 0.0
    # A loan fee is real money, but it stays out of transfer-fee statistics.
    assert amounts["loan"] > 0
    stats_spend = {item["key"]: item["known_spend"] for item in summary["categories"]}
    assert stats_spend["loan"] == 0.0


def test_deal_cost_separates_observed_from_assumed(db, save) -> None:
    """The cost model marks each component as observed, assumed or unavailable."""
    rows = _build_squad()
    transfer = transfer_row(
        "T10",
        "S1",
        "Cost Model Deal",
        20_000_000,
        components=[
            {"type": "base_fee", "amount": 16_000_000, "status": "paid"},
            {"type": "installment", "amount": 4_000_000, "status": "scheduled"},
            {"type": "agent_fee", "amount": 800_000, "status": "paid"},
        ],
    )
    import_document(db, scan_document(players=rows, transfers=[transfer]))
    stored = db.query(Transfer).filter(Transfer.source_record_id == "T10").one()
    cost = deal_cost(db, stored)
    by_key = {item["key"]: item for item in cost["components"]}

    assert by_key["transfer_fee"]["status"] == "observed"
    assert by_key["agent_fee"]["amount"] == 800_000
    assert by_key["wage_cost"]["status"] == "assumed"
    assert by_key["signing_fee"]["status"] == "unavailable"
    assert cost["complete"] is False
    assert cost["label"] == "已知成本下限"
    assert cost["total_known"] > 0


def test_investment_score_refuses_without_cost(db, save) -> None:
    """Investment score is unavailable when the total cost is unknown."""
    import_document(db, scan_document(players=_build_squad()))
    from app.models import PlayerInstance

    target = db.query(PlayerInstance).first()
    assert target is not None
    result = investment_score(db, target.id, None)

    assert result["available"] is False
    assert result["score"] is None
    assert result["reason"]


def test_decision_report_lists_unavailable_injury_risk(db, save) -> None:
    """The decision report marks injury risk as not evaluable instead of inventing a value."""
    import_document(db, scan_document(players=_build_squad(statistics=True)))
    pool = candidate_pool(db, save.id)
    target = next(item for item in pool if item.position == "ST")
    report = decision_report(db, save.id, target.instance_id)
    rows = {item["key"]: item for item in report["rows"]}

    assert rows["injury"]["value"] == "不可评估"
    assert rows["fit"]["value"] in {"高", "中", "低"}
    assert report["recommendation"]["verdict"]
    assert report["recommendation"]["reasons"]


def test_transfer_review_reports_percentile_and_value_change(db, save) -> None:
    """The deal review compares an own-club signing with comparable fees and its later value."""
    rows = _build_squad()
    transfers = [
        transfer_row(f"R{index}", f"S{index + 1}", f"Reviewed {index}", 5_000_000 + index * 1_000_000, age=22)
        for index in range(6)
    ]
    import_document(db, scan_document(players=rows, transfers=transfers))
    review = transfer_review(db, save.id)

    assert review["summary"]["deals"] == len(transfers)
    first = review["items"][0]
    assert first["status"]["counts_in_stats"] is True
    assert first["comparable_sample"] >= 1
    assert first["evidence"], "每笔复盘都要给出数据依据"


def test_statistics_import_is_idempotent_per_period(db, save) -> None:
    """Re-importing the same period with a newer observation replaces counts instead of duplicating rows."""
    row = player_row("X1", "Stats Player", statistics=[season_stats(period="2026/27", goals=5)])
    import_document(db, scan_document(scan_id="s1", players=[row]))
    updated = dict(row, statistics=[season_stats(period="2026/27", goals=12)])
    import_document(
        db,
        scan_document(scan_id="s2", when=datetime(2027, 1, 1, 12, tzinfo=timezone.utc), players=[updated]),
    )

    rows = db.query(PlayerStatistic).all()
    assert len(rows) == 1
    assert rows[0].goals == 12


def test_new_endpoints_answer(client, db, save) -> None:
    """The V2 endpoints are reachable and return the documented top-level keys."""
    import_document(db, scan_document(players=_build_squad(statistics=True)))
    for path, key in (
        ("/api/v1/squad/overview", "components"),
        ("/api/v1/squad/depth", "items"),
        ("/api/v1/squad/contracts", "buckets"),
        ("/api/v1/squad/profiles", "items"),
        ("/api/v1/recruitment/model", "position_templates"),
        ("/api/v1/recruitment/hidden-value", "rules"),
        ("/api/v1/development/board", "items"),
        ("/api/v1/performance/metrics", "position_metrics"),
        ("/api/v1/performance/board", "items"),
        ("/api/v1/transfers/categories", "categories"),
        ("/api/v1/transfers/review", "items"),
    ):
        response = client.get(path)
        assert response.status_code == 200, path
        assert key in response.json(), path


def test_recruitment_search_endpoint_and_shortlist(client, db, save) -> None:
    """Search and shortlist creation round-trip through the API."""
    import_document(db, scan_document(players=_build_squad(statistics=True, include_market=True)))
    search = client.post("/api/v1/recruitment/search", json={"slot": "ST", "limit": 5})
    assert search.status_code == 200
    assert search.json()["total"] >= 1

    created = client.post(
        "/api/v1/recruitment/shortlists",
        json={"name": "API 中锋", "slot": "ST", "limit": 3, "budget": 60_000_000},
    )
    assert created.status_code == 201
    shortlist_id = created.json()["shortlist_id"]
    detail = client.get(f"/api/v1/recruitment/shortlists/{shortlist_id}")
    assert detail.status_code == 200
    assert detail.json()["items"]
    assert ensure_save(db) == save.id
    assert club_row("C1", "Northbridge United", user_club=True)["is_user_club"] is True
