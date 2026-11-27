"""V3.3.2-08 在线学习引擎测试。

所有构造数据均为测试夹具，不代表真实 FM27 学习成果。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.models import (
    Club,
    FmSave,
    NegotiationEvent,
    Player,
    PlayerAvailability,
    PlayerInstance,
    PlayerSnapshot,
    Transfer,
    TransferEventCandidate,
    TransferFeedback,
    TransferNegotiation,
)
from app.services import transfer_learning as learning
from app.utils import utcnow


def _club(db: Session, save: FmSave, *, uid: str, name: str, user: bool = False) -> Club:
    club = Club(fm_save_id=save.id, uid=uid, name=name, is_user_club=user)
    db.add(club)
    db.commit()
    return club


def _player(
    db: Session,
    save: FmSave,
    *,
    uid: str,
    club: Club | None = None,
    value: int | None = 10_000_000,
    age: int = 25,
    position: str = "ST",
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
    instance: PlayerInstance | None,
    name: str = "Case Player",
    fee: float | None = 10_000_000,
    status: str = "completed",
    transfer_type: str = "permanent",
    from_club: Club | None = None,
    to_club: Club | None = None,
    currency_original: str | None = "EUR",
    transfer_date: date = date(2026, 1, 1),
    source: str = "fm27_live_reader",
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
        currency="EUR",
        base_fee=fee,
        fee_paid=fee,
        player_age_at_transfer=25,
        source=source,
        currency_original=currency_original,
    )
    db.add(row)
    db.commit()
    return row


def _availability(
    db: Session,
    instance: PlayerInstance,
    *,
    observed_at: datetime,
    listed: bool | None = None,
    loan_listed: bool | None = None,
    set_for_release: bool | None = None,
) -> PlayerAvailability:
    row = PlayerAvailability(
        player_instance_id=instance.id,
        observed_at=observed_at,
        game_date=observed_at.date(),
        listed=listed,
        loan_listed=loan_listed,
        set_for_release=set_for_release,
        source="fm27_live_reader",
    )
    db.add(row)
    db.commit()
    return row


def test_first_cycle_learns_history_without_duplicates(save: FmSave, db: Session) -> None:
    """首次学习会吸收已有真实历史，但重复运行不会重复写入事件。"""
    seller = _club(db, save, uid="c1", name="Seller")
    buyer = _club(db, save, uid="c2", name="Buyer")
    player = _player(db, save, uid="p1", club=seller)
    _transfer(db, save, record_id="t1", instance=player, from_club=seller, to_club=buyer)
    _availability(db, player, observed_at=utcnow(), listed=True)

    result = learning.process_incremental(db, save.id)
    assert result["events_created"] == 1
    assert learning.list_events(db, save.id)["items"][0]["event_type"] == "TRANSFER_COMPLETED"

    again = learning.process_incremental(db, save.id)
    assert again["events_created"] == 0
    assert learning.list_events(db, save.id)["total"] == 1


def test_transfer_event_fields_and_currency(save: FmSave, db: Session) -> None:
    seller = _club(db, save, uid="c1", name="Seller")
    buyer = _club(db, save, uid="c2", name="Buyer")
    player = _player(db, save, uid="p1", club=seller)
    learning.process_incremental(db, save.id)
    _transfer(
        db, save, record_id="t1", instance=player, fee=25_000_000,
        from_club=seller, to_club=buyer, currency_original="gbp",
    )
    learning.process_incremental(db, save.id)
    event = learning.list_events(db, save.id)["items"][0]
    assert event["event_type"] == "TRANSFER_COMPLETED"
    assert event["transaction_type"] == "permanent"
    assert event["verification_status"] == "CONFIRMED"
    assert event["buying_club_id"] == buyer.id
    assert event["selling_club_id"] == seller.id
    assert event["amount"] == 25_000_000
    assert event["currency"] == "GBP"
    assert event["learning_eligible"] is True


def test_unknown_currency_is_not_default_eur(save: FmSave, db: Session) -> None:
    seller = _club(db, save, uid="c1", name="Seller")
    buyer = _club(db, save, uid="c2", name="Buyer")
    player = _player(db, save, uid="p1", club=seller)
    learning.process_incremental(db, save.id)
    _transfer(
        db, save, record_id="t1", instance=player,
        from_club=seller, to_club=buyer, currency_original=None,
    )
    learning.process_incremental(db, save.id)
    event = learning.list_events(db, save.id)["items"][0]
    assert event["currency"] is None
    assert event["currency_known"] is False


def test_agreed_transfer_is_not_price_sample(save: FmSave, db: Session) -> None:
    seller = _club(db, save, uid="c1", name="Seller")
    buyer = _club(db, save, uid="c2", name="Buyer")
    player = _player(db, save, uid="p1", club=seller)
    learning.process_incremental(db, save.id)
    _transfer(db, save, record_id="t1", instance=player, status="agreed", from_club=seller, to_club=buyer)
    learning.process_incremental(db, save.id)
    event = learning.list_events(db, save.id)["items"][0]
    assert event["event_type"] == "TRANSFER_CONFIRMED"
    assert event["learning_eligible"] is False


def test_synthetic_source_never_enters_learning(save: FmSave, db: Session) -> None:
    seller = _club(db, save, uid="c1", name="Seller")
    buyer = _club(db, save, uid="c2", name="Buyer")
    player = _player(db, save, uid="p1", club=seller)
    learning.process_incremental(db, save.id)
    _transfer(
        db, save, record_id="t1", instance=player, from_club=seller, to_club=buyer,
        source="synthetic_fixture",
    )
    result = learning.process_incremental(db, save.id)
    assert result["events_created"] == 0
    assert learning.list_events(db, save.id)["total"] == 0


def test_transfer_events_are_deduplicated(save: FmSave, db: Session) -> None:
    seller = _club(db, save, uid="c1", name="Seller")
    buyer = _club(db, save, uid="c2", name="Buyer")
    player = _player(db, save, uid="p1", club=seller)
    learning.process_incremental(db, save.id)
    _transfer(db, save, record_id="t1", instance=player, from_club=seller, to_club=buyer)
    first = learning.process_incremental(db, save.id)
    second = learning.process_incremental(db, save.id)
    assert first["events_created"] == 1
    assert second["events_created"] == 0
    assert learning.list_events(db, save.id)["total"] == 1


def test_availability_transitions(save: FmSave, db: Session) -> None:
    club = _club(db, save, uid="c1", name="Club")
    player = _player(db, save, uid="p1", club=club)
    start = utcnow()
    _availability(db, player, observed_at=start, listed=False, loan_listed=False, set_for_release=False)
    learning.process_incremental(db, save.id)

    _availability(db, player, observed_at=start + timedelta(hours=1), listed=True, loan_listed=False, set_for_release=False)
    _availability(db, player, observed_at=start + timedelta(hours=2), listed=True, loan_listed=True, set_for_release=False)
    _availability(db, player, observed_at=start + timedelta(hours=3), listed=False, loan_listed=True, set_for_release=False)
    _availability(db, player, observed_at=start + timedelta(hours=4), listed=False, loan_listed=True, set_for_release=True)
    learning.process_incremental(db, save.id, mode="incremental")

    types = [row["event_type"] for row in learning.list_events(db, save.id)["items"]]
    assert "PLAYER_LISTED" in types
    assert "PLAYER_LOAN_LISTED" in types
    assert "PLAYER_UNLISTED" in types
    assert "PLAYER_RELEASED" in types
    listed = next(row for row in learning.list_events(db, save.id)["items"] if row["event_type"] == "PLAYER_LISTED")
    assert listed["verification_status"] == "CONFIRMED"
    assert listed["learning_eligible"] is False


def test_club_change_candidate_is_unverified(save: FmSave, db: Session) -> None:
    seller = _club(db, save, uid="c1", name="Seller")
    buyer = _club(db, save, uid="c2", name="Buyer")
    player = _player(db, save, uid="p1", club=seller)
    learning.process_incremental(db, save.id)
    db.add(
        TransferEventCandidate(
            fm_save_id=save.id,
            player_instance_id=player.id,
            from_club_id=seller.id,
            to_club_id=buyer.id,
            game_date=date(2026, 8, 1),
            evidence_level="Unverified",
            status="pending",
        )
    )
    db.commit()
    learning.process_incremental(db, save.id)
    event = learning.list_events(db, save.id)["items"][0]
    assert event["event_type"] == "CLUB_CHANGE_OBSERVED"
    assert event["verification_status"] == "UNVERIFIED"
    assert event["amount"] is None
    assert event["learning_eligible"] is False


def test_save_isolation(save: FmSave, db: Session) -> None:
    other = FmSave(user_id=save.user_id, name="另一个存档", game_version="27.0", is_active=False)
    db.add(other)
    db.commit()

    club_a = _club(db, save, uid="same", name="Club")
    club_b = _club(db, other, uid="same", name="Club")
    player_a = _player(db, save, uid="p", club=club_a)
    player_b = _player(db, other, uid="p", club=club_b)
    learning.process_incremental(db, save.id)
    learning.process_incremental(db, other.id)
    _transfer(db, save, record_id="t1", instance=player_a)
    _transfer(db, other, record_id="t1", instance=player_b)

    learning.process_incremental(db, save.id)
    assert learning.list_events(db, save.id)["total"] == 1
    assert learning.list_events(db, other.id)["total"] == 0
    learning.process_incremental(db, other.id)
    assert learning.list_events(db, other.id)["total"] == 1


def test_focus_club_promotion_and_profile_counts(save: FmSave, db: Session) -> None:
    user_club = _club(db, save, uid="u", name="User Club", user=True)
    save.user_club_id = user_club.id
    db.commit()
    other = _club(db, save, uid="o", name="Other Club")
    player = _player(db, save, uid="p1", club=other, value=20_000_000)
    learning.process_incremental(db, save.id)
    _transfer(
        db, save, record_id="t1", instance=player, fee=30_000_000,
        from_club=other, to_club=user_club,
    )
    result = learning.process_incremental(db, save.id)
    assert result["focus_promoted"] == 1

    focus = learning.focus_clubs(db, save.id)["items"]
    assert [row["club_id"] for row in focus] == [other.id]
    profile = learning.club_profile(db, save.id, other.id)
    assert profile["sample_size"] == 1
    assert profile["selling"]["completed"] == 1
    assert profile["selling"]["fee_total"] == 30_000_000


def test_incremental_cycle_without_changes_writes_nothing(save: FmSave, db: Session) -> None:
    club = _club(db, save, uid="c1", name="Club")
    _player(db, save, uid="p1", club=club)
    learning.process_incremental(db, save.id)
    first = learning.process_incremental(db, save.id)
    second = learning.process_incremental(db, save.id)
    assert first["events_created"] == 0
    assert second["events_created"] == 0
    assert learning.status(db, save.id)["counts"]["events_observed"] == 0


def test_anomalous_amount_is_ignored(save: FmSave, db: Session) -> None:
    seller = _club(db, save, uid="c1", name="Seller")
    buyer = _club(db, save, uid="c2", name="Buyer")
    player = _player(db, save, uid="p1", club=seller)
    learning.process_incremental(db, save.id)
    row = _transfer(db, save, record_id="t1", instance=player, fee=-5, from_club=seller, to_club=buyer)
    row.base_fee = -5
    row.fee_paid = -5
    db.commit()
    learning.process_incremental(db, save.id)
    event = learning.list_events(db, save.id)["items"][0]
    assert event["amount"] is None
    profile = learning.club_profile(db, save.id, buyer.id)
    assert profile["buying"]["fee_total"] == 0


def test_learning_adjustment_applies_only_with_samples(save: FmSave, db: Session) -> None:
    seller = _club(db, save, uid="c1", name="Seller")
    buyer = _club(db, save, uid="c2", name="Buyer")
    target = _player(db, save, uid="target", club=seller, value=10_000_000)
    learning.process_incremental(db, save.id)
    for index in range(3):
        player = _player(db, save, uid=f"h{index}", club=seller, value=10_000_000)
        _transfer(
            db, save, record_id=f"t{index}", instance=player, fee=12_000_000,
            from_club=seller, to_club=buyer,
        )
    learning.process_incremental(db, save.id)

    adjustment = learning.learning_adjustment(db, save.id, target, 10_000_000, "purchase")
    assert adjustment["applied"] is True
    assert 0.85 <= adjustment["multiplier"] <= 1.15
    assert adjustment["sample_size"] == 3
    assert adjustment["club_id"] == seller.id

    scarce = learning.learning_adjustment(db, save.id, target, None, "purchase")
    assert scarce["applied"] is False


def test_api_status_pause_resume_and_events(save: FmSave, db: Session, client) -> None:
    seller = _club(db, save, uid="c1", name="Seller")
    buyer = _club(db, save, uid="c2", name="Buyer")
    player = _player(db, save, uid="p1", club=seller)
    learning.process_incremental(db, save.id)
    _transfer(db, save, record_id="t1", instance=player, from_club=seller, to_club=buyer)
    learning.process_incremental(db, save.id)

    status = client.get("/api/v1/transfer-learning/status").json()
    assert status["save_id"] == save.id
    assert status["counts"]["events_observed"] == 1
    assert status["counts"]["confirmed_transfers"] == 1

    paused = client.post("/api/v1/transfer-learning/pause").json()
    assert paused["status"] == "PAUSED"
    resumed = client.post("/api/v1/transfer-learning/resume").json()
    assert resumed["status"] in {"MONITORING", "PROCESSING", "LEARNING"}

    events = client.get("/api/v1/transfer-learning/events", params={"event_type": "TRANSFER_COMPLETED"}).json()
    assert events["total"] == 1

    clubs = client.get("/api/v1/transfer-learning/clubs").json()
    assert clubs["total"] >= 2
    detail = client.get(f"/api/v1/transfer-learning/clubs/{buyer.id}").json()
    assert detail["club_id"] == buyer.id

    invalid = client.get("/api/v1/transfer-learning/events", params={"event_type": "NOPE"})
    assert invalid.status_code == 422


def test_api_rejects_club_from_other_save(save: FmSave, db: Session, client) -> None:
    other = FmSave(user_id=save.user_id, name="另一个存档", game_version="27.0", is_active=False)
    db.add(other)
    db.commit()
    club = _club(db, other, uid="x", name="Hidden")
    response = client.get(f"/api/v1/transfer-learning/clubs/{club.id}")
    assert response.status_code == 404


def test_confirmed_negotiation_and_feedback_events(save: FmSave, db: Session) -> None:
    club = _club(db, save, uid="c1", name="Club")
    player = _player(db, save, uid="p1", club=club)
    learning.process_incremental(db, save.id)
    negotiation = TransferNegotiation(
        fm_save_id=save.id,
        player_instance_id=player.id,
        direction="purchase",
        status="COMPLETED",
        currency="EUR",
    )
    db.add(negotiation)
    db.commit()
    db.add(
        NegotiationEvent(
            negotiation_id=negotiation.id,
            fm_save_id=save.id,
            event_type="accepted",
            amount=9_000_000,
            source="user_confirmed",
            occurred_at=utcnow(),
        )
    )
    db.add(
        TransferFeedback(
            fm_save_id=save.id,
            player_instance_id=player.id,
            direction="purchase",
            outcome="rejected",
            amount=4_000_000,
            dedupe_key="feedback-1",
            source="user_confirmed",
        )
    )
    db.commit()
    learning.process_incremental(db, save.id)
    events = {row["event_type"] for row in learning.list_events(db, save.id)["items"]}
    assert "OFFER_ACCEPTED" in events
    assert "OFFER_REJECTED" in events
    for row in learning.list_events(db, save.id)["items"]:
        assert row["verification_status"] == "CONFIRMED"
        assert row["learning_eligible"] is False


def test_cancel_keeps_checkpoint_and_resume_continues(save: FmSave, db: Session) -> None:
    seller = _club(db, save, uid="c1", name="Seller")
    buyer = _club(db, save, uid="c2", name="Buyer")
    for index in range(100):
        player = _player(db, save, uid=f"p{index}", club=seller)
        _transfer(
            db, save, record_id=f"t{index}", instance=player,
            from_club=seller, to_club=buyer,
        )
    calls = {"count": 0}

    def cancel() -> bool:
        calls["count"] += 1
        return calls["count"] > 1

    result = learning.process_incremental(db, save.id, batch_size=50, cancel_cb=cancel)
    assert result["cancelled"] is True
    assert result["events_created"] == 50
    assert learning.status(db, save.id)["status"] == "PARTIAL"

    resumed = learning.process_incremental(db, save.id, batch_size=50)
    assert resumed["cancelled"] is False
    assert learning.list_events(db, save.id)["total"] == 100


def test_same_batch_duplicate_keys_are_skipped(save: FmSave, db: Session) -> None:
    seller = _club(db, save, uid="c1", name="Seller")
    buyer = _club(db, save, uid="c2", name="Buyer")
    player = _player(db, save, uid="p1", club=seller)
    row = _transfer(db, save, record_id="t1", instance=player, from_club=seller, to_club=buyer)
    first = learning._transfer_event(db, save.id, row)
    second = learning._transfer_event(db, save.id, row)
    assert first is not None and second is not None
    created, skipped = learning._persist_events(db, [first, second])
    assert len(created) == 1
    assert skipped == 1
