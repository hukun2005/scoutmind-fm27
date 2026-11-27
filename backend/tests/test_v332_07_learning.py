"""V3.3.2-07 B-01~B-03：成交案例标准化、置信度分级、相似匹配与俱乐部画像。

夹具中的成交均为测试数据，不构成真实 FM27 学习成果。
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.models import (
    Club,
    FmSave,
    Player,
    PlayerInstance,
    PlayerSnapshot,
    Transfer,
)
from app.services import transfer_strategy as strategy
from app.utils import utcnow


def _club(db: Session, save: FmSave, *, uid: str, name: str) -> Club:
    club = Club(fm_save_id=save.id, uid=uid, name=name)
    db.add(club)
    db.commit()
    return club


def _player(
    db: Session,
    save: FmSave,
    *,
    uid: str,
    age: int = 25,
    value: int = 10_000_000,
    position: str = "ST",
    club: Club | None = None,
) -> PlayerInstance:
    player = Player(full_name=f"Player {uid}", normalized_name=f"player {uid}")
    db.add(player)
    db.commit()
    instance = PlayerInstance(
        player_id=player.id,
        fm_save_id=save.id,
        save_local_uid=uid,
        club_id=club.id if club is not None else None,
        position=position,
    )
    db.add(instance)
    db.commit()
    snapshot = PlayerSnapshot(
        player_instance_id=instance.id,
        observed_at=utcnow(),
        game_date=date(2026, 7, 1),
        age=age,
        market_value=value,
        club_id=club.id if club is not None else None,
        position=position,
        source="fm27_live_reader",
    )
    db.add(snapshot)
    db.commit()
    instance.latest_snapshot_id = snapshot.id
    db.commit()
    return instance


def _transfer(
    db: Session,
    save: FmSave,
    *,
    record_id: str,
    instance: PlayerInstance | None = None,
    name: str = "Case Player",
    fee: float = 10_000_000,
    status: str = "completed",
    transfer_type: str = "permanent",
    from_club: Club | None = None,
    to_club: Club | None = None,
    age: int = 25,
    contract_remaining: int = 24,
    currency: str = "EUR",
    currency_original: str | None = None,
    transfer_date: date = date(2026, 1, 1),
    source: str = "test_fixture",
) -> Transfer:
    row = Transfer(
        fm_save_id=save.id,
        source_record_id=record_id,
        player_instance_id=instance.id if instance is not None else None,
        player_name=name,
        from_club_id=from_club.id if from_club is not None else None,
        to_club_id=to_club.id if to_club is not None else None,
        from_club_name=from_club.name if from_club is not None else None,
        to_club_name=to_club.name if to_club is not None else None,
        transfer_type=transfer_type,
        status=status,
        transfer_date=transfer_date,
        currency=currency,
        currency_original=currency_original,
        fee_paid=fee,
        base_fee=fee,
        player_age_at_transfer=age,
        contract_remaining_months=contract_remaining,
        source=source,
    )
    db.add(row)
    db.commit()
    return row


def test_cases_only_from_completed_transfers(db: Session, save: FmSave) -> None:
    _transfer(db, save, record_id="c-1", status="completed")
    _transfer(db, save, record_id="c-2", status="pending")
    _transfer(db, save, record_id="c-3", status="agreed")
    result = strategy.list_cases(db, save.id)
    assert result["total"] == 1
    assert result["items"][0]["transfer_status"] == "completed"


def test_case_carries_provenance(db: Session, save: FmSave) -> None:
    _transfer(db, save, record_id="p-1", fee=9_000_000)
    case = strategy.list_cases(db, save.id)["items"][0]
    for key in ("case_id", "save_id", "data_source", "case_origin", "observed_at"):
        assert case[key] is not None
    assert case["save_id"] == save.id
    assert case["case_origin"] == "imported"
    assert case["usable_for_stats"] is True


def test_confidence_tiers() -> None:
    assert strategy.confidence_tier(0)["level"] == "none"
    assert strategy.confidence_tier(1)["level"] == "insufficient"
    assert strategy.confidence_tier(2)["level"] == "insufficient"
    assert strategy.confidence_tier(3)["level"] == "preliminary"
    assert strategy.confidence_tier(5)["level"] == "limited"
    assert strategy.confidence_tier(10)["level"] == "stable"
    assert strategy.confidence_tier(10)["label"] == "可进行更稳定的统计分析"


def test_same_position_alone_is_not_similar() -> None:
    case = {
        "player_position": "ST",
        "player_age": 33,
        "player_value": 50_000_000,
        "contract_remaining": 12,
        "transfer_type": "permanent",
    }
    target = {
        "position": "ST",
        "age": 20,
        "market_value": 1_000_000,
        "contract_remaining_months": 60,
        "listed": None,
        "loan_listed": None,
    }
    score = strategy._match_score(case, target)
    assert score["match_pct"] < strategy.SIMILARITY_THRESHOLD


def test_similarity_weights_are_configurable(monkeypatch) -> None:
    assert strategy.SIMILARITY_WEIGHTS == {
        "position": 30.0,
        "age": 20.0,
        "value": 20.0,
        "contract": 15.0,
        "availability": 15.0,
    }
    case = {"player_position": "ST", "player_age": 33, "player_value": 50_000_000,
            "contract_remaining": 12, "transfer_type": "permanent"}
    target = {"position": "ST", "age": 20, "market_value": 1_000_000,
              "contract_remaining_months": 60, "listed": None, "loan_listed": None}
    baseline = strategy._match_score(case, target)["match_pct"]
    monkeypatch.setitem(strategy.SIMILARITY_WEIGHTS, "position", 100.0)
    for key in ("age", "value", "contract", "availability"):
        monkeypatch.setitem(strategy.SIMILARITY_WEIGHTS, key, 0.0)
    assert strategy._match_score(case, target)["match_pct"] == 100.0
    assert baseline != 100.0


def test_club_habits_are_club_scoped(db: Session, save: FmSave) -> None:
    selling = _club(db, save, uid="club-sell", name="Selling FC")
    other = _club(db, save, uid="club-other", name="Other FC")
    for index in range(3):
        _transfer(db, save, record_id=f"s-{index}", from_club=selling, to_club=other,
                  transfer_type="loan" if index == 0 else "permanent", contract_remaining=10)
    _transfer(db, save, record_id="o-1", from_club=other, to_club=selling)

    habits = strategy.club_habits(db, save.id, selling.id)
    assert habits["available"] is True
    assert habits["observations"]["completed"] == 4
    assert habits["observations"]["loans"] == 1
    assert habits["club_name"] == "Selling FC"
    selling_pattern = next(item for item in habits["patterns"] if item["key"] == "loan_preference")
    assert selling_pattern["sample_size"] == 1


def test_club_habits_insufficient_sample(db: Session, save: FmSave) -> None:
    club = _club(db, save, uid="club-sparse", name="Sparse FC")
    _transfer(db, save, record_id="sparse-1", from_club=club)
    habits = strategy.club_habits(db, save.id, club.id)
    assert habits["available"] is False
    assert habits["patterns"] == []
    assert habits["message"] == "暂无足够数据"


def test_learning_status_counts_and_tiers(db: Session, save: FmSave) -> None:
    for index in range(3):
        _transfer(db, save, record_id=f"ls-{index}", fee=10_000_000 + index * 500_000)
    status = strategy.learning_status(db, save.id)
    assert status["totals"]["cases"] == 3
    assert status["confidence"]["level"] == "preliminary"
    assert status["data_version"].startswith("cases:3:")
    assert status["available"] is True


def test_fee_and_age_bands_are_reported(db: Session, save: FmSave) -> None:
    _transfer(db, save, record_id="band-1", fee=3_000_000, age=20)
    _transfer(db, save, record_id="band-2", fee=8_000_000, age=25)
    _transfer(db, save, record_id="band-3", fee=20_000_000, age=31)
    patterns = {item["key"]: item for item in strategy.insights(db, save.id)["patterns"]}
    assert patterns["fee_band"]["bands"]["低于 500 万"] == 1
    assert patterns["fee_band"]["bands"]["500–1500 万"] == 1
    assert patterns["fee_band"]["bands"]["1500–4000 万"] == 1
    assert patterns["fee_band"]["quantiles"]["p50"] == 8_000_000
    assert patterns["age_band"]["bands"]["18–21 岁"] == 1
    assert patterns["age_band"]["bands"]["22–25 岁"] == 1
    assert patterns["age_band"]["bands"]["30 岁及以上"] == 1


def test_similar_candidates_are_capped(db: Session, save: FmSave, monkeypatch) -> None:
    for index in range(2):
        case_instance = _player(db, save, uid=f"cap-{index}")
        _transfer(db, save, record_id=f"cap-{index}", instance=case_instance, fee=10_000_000)
    target = _player(db, save, uid="cap-target")
    monkeypatch.setattr(strategy, "SIMILARITY_CANDIDATE_LIMIT", 1)
    result = strategy.similar_cases(db, save.id, target.id, limit=10)
    assert result["candidate_limit"] == 1
    assert result["total"] <= 1


def test_demo_cases_are_excluded_from_statistics(db: Session, save: FmSave) -> None:
    _transfer(db, save, record_id="demo-1", source="synthetic_demo")
    listing = strategy.list_cases(db, save.id)
    assert listing["total"] == 1
    assert listing["items"][0]["case_origin"] == "demo"
    assert listing["items"][0]["usable_for_stats"] is False
    status = strategy.learning_status(db, save.id)
    assert status["available"] is False
    assert status["totals"]["demo_cases"] == 1
    assert status["patterns"] == []
    assert "演示数据" in status["message"]


def test_cross_save_cases_are_isolated(db: Session, save: FmSave) -> None:
    other = FmSave(user_id=save.user_id, name="另一个存档", is_active=False)
    db.add(other)
    db.commit()
    _transfer(db, other, record_id="other-1")
    _transfer(db, save, record_id="mine-1")
    assert strategy.list_cases(db, save.id)["total"] == 1
    assert strategy.list_cases(db, other.id)["total"] == 1
    assert strategy.learning_status(db, save.id)["totals"]["cases"] == 1
