"""SM-030：转会候选事件权限与关联校验。"""

from __future__ import annotations

from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import (
    Club,
    FmSave,
    Player,
    PlayerInstance,
    PlayerSnapshot,
    Transfer,
    TransferCandidate,
    User,
)


def _foreign_save(db) -> FmSave:
    user = User(username="intruder-sm030", display_name="别人")
    db.add(user)
    db.commit()
    save = FmSave(user_id=user.id, name="别人的存档", game_version="27.1", game_build="x", is_active=True)
    db.add(save)
    db.commit()
    return save


def _player(db, save, uid: str):
    player = Player(full_name=f"Candidate {uid}", normalized_name=f"candidate-{uid.lower()}")
    db.add(player)
    db.commit()
    instance = PlayerInstance(player_id=player.id, fm_save_id=save.id, save_local_uid=uid)
    db.add(instance)
    db.commit()
    db.add(
        PlayerSnapshot(
            player_instance_id=instance.id,
            observed_at=datetime(2026, 7, 1, 12),
            game_date=date(2026, 7, 1),
            age=23,
            ca=140,
            pa=160,
            market_value=5_000_000,
            wage=10_000,
            source="manual",
        )
    )
    db.commit()
    return instance


def _club(db, save, name: str) -> Club:
    uid = "club-" + name.lower().replace(" ", "-")
    club = db.scalar(select(Club).where(Club.fm_save_id == save.id, Club.uid == uid))
    if club is None:
        club = Club(fm_save_id=save.id, uid=uid, name=name)
        db.add(club)
        db.commit()
    return club


def _candidate(db, save, instance, from_club, to_club) -> TransferCandidate:
    row = TransferCandidate(
        fm_save_id=save.id,
        player_instance_id=instance.id,
        from_club_id=from_club.id if from_club else None,
        to_club_id=to_club.id if to_club else None,
        kind="permanent",
        detected_at=datetime(2026, 7, 1, 12),
        status="candidate",
        evidence_json="{}",
    )
    db.add(row)
    db.commit()
    return row


def _transfer(db, save, instance, club) -> Transfer:
    row = Transfer(
        fm_save_id=save.id,
        source_record_id=f"T-{instance.id}",
        player_instance_id=instance.id,
        player_name="Candidate",
        to_club_id=club.id,
        transfer_type="permanent",
        status="completed",
        transfer_date=date(2026, 7, 1),
        currency="EUR",
        effective_fee=1_000_000,
        source="manual",
    )
    db.add(row)
    db.commit()
    return row


def _own_setup(db, save):
    instance = _player(db, save, "OWN")
    a = _club(db, save, "Own A")
    b = _club(db, save, "Own B")
    return instance, a, b


def test_confirm_own_candidate(client: TestClient, db, save) -> None:
    instance, a, b = _own_setup(db, save)
    candidate = _candidate(db, save, instance, a, b)
    response = client.post(f"/api/v1/transfers/candidates/{candidate.id}/confirm", json={})
    assert response.status_code == 201, response.text
    assert response.json()["candidate"]["status"] == "confirmed"
    db.refresh(candidate)
    assert candidate.status == "confirmed"
    assert candidate.confirmed_transfer_id is not None


def test_dismiss_own_candidate(client: TestClient, db, save) -> None:
    instance, a, b = _own_setup(db, save)
    candidate = _candidate(db, save, instance, a, b)
    response = client.post(f"/api/v1/transfers/candidates/{candidate.id}/dismiss", json={"reason": "误报"})
    assert response.status_code == 200, response.text
    db.refresh(candidate)
    assert candidate.status == "dismissed"


def test_foreign_confirm_and_dismiss_are_404(client: TestClient, db, save) -> None:
    foreign = _foreign_save(db)
    instance = _player(db, foreign, "FOREIGN")
    a = _club(db, foreign, "Foreign A")
    b = _club(db, foreign, "Foreign B")
    candidate = _candidate(db, foreign, instance, a, b)
    assert client.post(f"/api/v1/transfers/candidates/{candidate.id}/confirm", json={}).status_code == 404
    assert client.post(f"/api/v1/transfers/candidates/{candidate.id}/dismiss", json={}).status_code == 404
    db.refresh(candidate)
    assert candidate.status == "candidate", "越权请求不能改变状态"


def test_linked_transfer_from_other_save_is_404(client: TestClient, db, save) -> None:
    instance, a, b = _own_setup(db, save)
    candidate = _candidate(db, save, instance, a, b)
    foreign = _foreign_save(db)
    foreign_instance = _player(db, foreign, "F2")
    foreign_club = _club(db, foreign, "Foreign C")
    foreign_transfer = _transfer(db, foreign, foreign_instance, foreign_club)
    response = client.post(
        f"/api/v1/transfers/candidates/{candidate.id}/confirm",
        json={"transfer_id": foreign_transfer.id},
    )
    assert response.status_code == 404, response.text
    db.refresh(candidate)
    assert candidate.status == "candidate" and candidate.confirmed_transfer_id is None


def test_repeat_confirm_is_409(client: TestClient, db, save) -> None:
    instance, a, b = _own_setup(db, save)
    candidate = _candidate(db, save, instance, a, b)
    assert client.post(f"/api/v1/transfers/candidates/{candidate.id}/confirm", json={}).status_code == 201
    second = client.post(f"/api/v1/transfers/candidates/{candidate.id}/confirm", json={})
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "candidate_not_open"


def test_invalid_transfer_id_changes_nothing(client: TestClient, db, save) -> None:
    instance, a, b = _own_setup(db, save)
    candidate = _candidate(db, save, instance, a, b)
    before = db.query(Transfer).count()
    response = client.post(
        f"/api/v1/transfers/candidates/{candidate.id}/confirm",
        json={"transfer_id": 99999999},
    )
    assert response.status_code == 404
    db.expire_all()
    assert db.query(Transfer).count() == before, "非法交易 ID 不能创建交易"
    assert db.get(TransferCandidate, candidate.id).status == "candidate"
    assert db.get(TransferCandidate, candidate.id).confirmed_transfer_id is None


def test_candidate_list_respects_foreign_save_id(client: TestClient, db, save) -> None:
    foreign = _foreign_save(db)
    instance = _player(db, foreign, "F3")
    a = _club(db, foreign, "Foreign D")
    b = _club(db, foreign, "Foreign E")
    _candidate(db, foreign, instance, a, b)
    response = client.get(f"/api/v1/transfers/candidates?save_id={foreign.id}")
    assert response.status_code == 404
