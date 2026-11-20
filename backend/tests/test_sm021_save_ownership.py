"""SM-021：全 API 存档权限隔离。"""

from __future__ import annotations

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.agents import service as agent_service
from app.models import (
    Club,
    FmSave,
    Player,
    PlayerInstance,
    PlayerSnapshot,
    RecruitmentShortlist,
    Transfer,
    User,
)
from app.utils import utcnow

from tests.helpers import player_row, scan_document


def _other_user_save(db) -> tuple[User, FmSave]:
    other = User(username="intruder-sm021", display_name="另一个用户")
    db.add(other)
    db.commit()
    save = FmSave(user_id=other.id, name="别人的存档", game_version="27.1", game_build="x", is_active=True)
    db.add(save)
    db.commit()
    return other, save


def _seed_foreign(db, save, uid: str = "FOREIGN1") -> tuple[PlayerInstance, Transfer, RecruitmentShortlist]:
    user = db.scalar(select(User).where(User.username == "local"))
    player = Player(full_name=f"Foreign {uid}", normalized_name=f"foreign-{uid.lower()}")
    db.add(player)
    db.commit()
    instance = PlayerInstance(player_id=player.id, fm_save_id=save.id, save_local_uid=uid)
    db.add(instance)
    db.commit()
    db.add(
        PlayerSnapshot(
            player_instance_id=instance.id,
            observed_at=utcnow(),
            game_date=date(2026, 7, 1),
            age=24,
            ca=150,
            pa=170,
            market_value=10_000_000,
            wage=20_000,
            source="manual",
        )
    )
    club = Club(fm_save_id=save.id, uid=f"club-{uid.lower()}", name=f"Foreign Club {uid}")
    db.add(club)
    db.commit()
    transfer = Transfer(
        fm_save_id=save.id,
        source_record_id=f"F-{uid}",
        player_instance_id=instance.id,
        player_name=player.full_name,
        from_club_id=None,
        to_club_id=club.id,
        transfer_type="permanent",
        status="completed",
        transfer_date=date(2026, 7, 1),
        currency="EUR",
        effective_fee=9_000_000,
        source="manual",
    )
    db.add(transfer)
    shortlist = RecruitmentShortlist(fm_save_id=save.id, name="Foreign Shortlist")
    db.add(shortlist)
    db.commit()
    return instance, transfer, shortlist


def test_foreign_player_detail_is_rejected(client: TestClient, db, save) -> None:
    _, foreign_save = _other_user_save(db)
    instance, _, _ = _seed_foreign(db, foreign_save)
    response = client.get(f"/api/v1/recruitment/player/{instance.id}")
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "player_not_found"


def test_foreign_save_query_is_rejected(client: TestClient, db, save) -> None:
    _, foreign_save = _other_user_save(db)
    response = client.get(f"/api/v1/recruitment/hidden-value?save_id={foreign_save.id}")
    assert response.status_code == 404
    response = client.get(f"/api/v1/transfers/coverage?save_id={foreign_save.id}")
    assert response.status_code == 404
    response = client.get(f"/api/v1/clubs/1/transfer-intelligence?save_id={foreign_save.id}")
    assert response.status_code == 404


def test_foreign_transfer_roi_is_rejected(client: TestClient, db, save) -> None:
    _, foreign_save = _other_user_save(db)
    _, transfer, _ = _seed_foreign(db, foreign_save)
    response = client.get(f"/api/v1/transfers/{transfer.id}/roi")
    assert response.status_code == 404, response.text


def test_foreign_investment_is_rejected(client: TestClient, db, save) -> None:
    _, foreign_save = _other_user_save(db)
    instance, _, _ = _seed_foreign(db, foreign_save)
    response = client.get(f"/api/v1/players/{instance.id}/investment")
    assert response.status_code == 404


def test_foreign_shortlist_is_rejected(client: TestClient, db, save) -> None:
    _, foreign_save = _other_user_save(db)
    _, _, shortlist = _seed_foreign(db, foreign_save)
    response = client.get(f"/api/v1/recruitment/shortlists/{shortlist.id}")
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "shortlist_not_found"


def test_foreign_simulator_is_rejected(client: TestClient, db, save) -> None:
    _, foreign_save = _other_user_save(db)
    instance, _, _ = _seed_foreign(db, foreign_save)
    response = client.post("/api/v1/transfers/simulate", json={"instance_id": instance.id})
    assert response.status_code == 404


def test_foreign_forecast_is_rejected(client: TestClient, db, save) -> None:
    _, foreign_save = _other_user_save(db)
    instance, _, _ = _seed_foreign(db, foreign_save)
    response = client.get(f"/api/v1/players/{instance.id}/forecast")
    assert response.status_code == 404


def test_foreign_career_is_rejected(client: TestClient, db, save) -> None:
    _, foreign_save = _other_user_save(db)
    instance, _, _ = _seed_foreign(db, foreign_save)
    response = client.get(f"/api/v1/players/{instance.id}/career")
    assert response.status_code == 404


def test_own_second_save_still_accessible(client: TestClient, db, save) -> None:
    user = db.scalar(select(User).where(User.username == "local"))
    second = FmSave(user_id=user.id, name="我的第二个存档", game_version="27.1", game_build="x", is_active=False)
    db.add(second)
    db.commit()
    response = client.post(
        f"/api/v1/imports/scan?save_id={second.id}",
        content=json.dumps(scan_document(scan_id="sm021-own2", players=[player_row("OWN2", "Own Second")])).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 201, response.text
    instance = db.scalar(
        select(PlayerInstance)
        .join(Player, Player.id == PlayerInstance.player_id)
        .where(PlayerInstance.fm_save_id == second.id)
    )
    detail = client.get(f"/api/v1/recruitment/player/{instance.id}?save_id={second.id}")
    assert detail.status_code == 200, detail.text


def test_ai_service_rejects_foreign_save(db, save) -> None:
    _, foreign_save = _other_user_save(db)
    local = db.scalar(select(User).where(User.username == "local"))
    with pytest.raises(ValueError):
        agent_service.answer_question(db, foreign_save.id, "阵容怎么样", user_id=local.id)
