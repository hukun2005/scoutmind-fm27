"""V3.3.2-07 B-08：谈判结果反馈、去重、存档隔离与学习状态更新。"""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Club, FmSave, Player, PlayerInstance, PlayerSnapshot
from app.utils import utcnow

API = "/api/v1"


def _player(db: Session, save: FmSave, *, uid: str = "fb-1", name: str = "Feedback Player") -> PlayerInstance:
    club = Club(fm_save_id=save.id, uid=f"club-{uid}", name=f"Club {uid}")
    db.add(club)
    db.commit()
    player = Player(full_name=name, normalized_name=name.lower())
    db.add(player)
    db.commit()
    instance = PlayerInstance(
        player_id=player.id,
        fm_save_id=save.id,
        save_local_uid=uid,
        club_id=club.id,
        position="ST",
    )
    db.add(instance)
    db.commit()
    snapshot = PlayerSnapshot(
        player_instance_id=instance.id,
        observed_at=utcnow(),
        game_date=date(2026, 7, 1),
        age=25,
        ca=150,
        market_value=10_000_000,
        contract_end=date(2029, 6, 30),
        club_id=club.id,
        position="ST",
        source="fm27_live_reader",
    )
    db.add(snapshot)
    db.commit()
    instance.latest_snapshot_id = snapshot.id
    db.commit()
    return instance


def _payload(instance_id: int, **overrides) -> dict:
    body = {
        "instance_id": instance_id,
        "direction": "purchase",
        "outcome": "completed",
        "amount": 9_500_000,
        "note": "对方接受分期",
        "source": "user_confirmed",
    }
    body.update(overrides)
    return body


def test_feedback_completed_creates_case(client: TestClient, db: Session, save: FmSave) -> None:
    instance = _player(db, save)
    response = client.post(f"{API}/transfer-director/feedback", json=_payload(instance.id))
    assert response.status_code == 200
    body = response.json()
    assert body["duplicate"] is False
    assert body["learning_updated"] is True
    status = client.get(f"{API}/transfer-director/learning-status").json()
    assert status["totals"]["cases"] == 1
    assert status["totals"]["negotiation_cases"] == 1


def test_feedback_rejected_not_in_cases(client: TestClient, db: Session, save: FmSave) -> None:
    instance = _player(db, save)
    client.post(f"{API}/transfer-director/feedback", json=_payload(instance.id, outcome="rejected"))
    client.post(f"{API}/transfer-director/feedback", json=_payload(instance.id, outcome="cancelled"))
    status = client.get(f"{API}/transfer-director/learning-status").json()
    assert status["totals"]["cases"] == 0
    assert status["available"] is False


def test_feedback_dedupe(client: TestClient, db: Session, save: FmSave) -> None:
    instance = _player(db, save)
    first = client.post(f"{API}/transfer-director/feedback", json=_payload(instance.id)).json()
    second = client.post(f"{API}/transfer-director/feedback", json=_payload(instance.id)).json()
    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert second["feedback_id"] == first["feedback_id"]
    status = client.get(f"{API}/transfer-director/learning-status").json()
    assert status["totals"]["cases"] == 1


def test_feedback_invalidates_data_version(client: TestClient, db: Session, save: FmSave) -> None:
    instance = _player(db, save)
    before = client.get(f"{API}/transfer-director/learning-status").json()["data_version"]
    client.post(f"{API}/transfer-director/feedback", json=_payload(instance.id))
    after = client.get(f"{API}/transfer-director/learning-status").json()["data_version"]
    assert before != after


def test_feedback_save_scope(client: TestClient, db: Session, save: FmSave) -> None:
    other = FmSave(user_id=save.user_id, name="另一个存档", is_active=False)
    db.add(other)
    db.commit()
    foreign = _player(db, other, uid="foreign-1", name="Foreign Player")
    response = client.post(f"{API}/transfer-director/feedback", json=_payload(foreign.id))
    assert response.status_code == 404


def test_feedback_requires_real_amount_for_completed(client: TestClient, db: Session, save: FmSave) -> None:
    instance = _player(db, save)
    response = client.post(f"{API}/transfer-director/feedback", json=_payload(instance.id, amount=None))
    assert response.status_code == 422
    status = client.get(f"{API}/transfer-director/learning-status").json()
    assert status["totals"]["cases"] == 0
