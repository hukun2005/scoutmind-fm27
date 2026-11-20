"""SM-025：Recruitment API 权限完整性。"""

from __future__ import annotations

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.agents import llm_planner, service
from app.models import Club, FmSave, Player, PlayerInstance, PlayerSnapshot, Transfer, User
from app.utils import utcnow

from tests.helpers import player_row, scan_document


def _user_save(db, username: str, name: str) -> tuple[User, FmSave]:
    user = User(username=username, display_name=username)
    db.add(user)
    db.commit()
    save = FmSave(user_id=user.id, name=name, game_version="27.1", game_build="x", is_active=True)
    db.add(save)
    db.commit()
    return user, save


def _player(db, save, uid: str) -> PlayerInstance:
    player = Player(full_name=f"Player {uid}", normalized_name=f"player-{uid.lower()}")
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
            age=23,
            ca=140,
            pa=165,
            market_value=10_000_000,
            wage=20_000,
            source="manual",
        )
    )
    db.commit()
    return instance


def test_search_body_save_id_of_other_user_is_rejected(client: TestClient, db, save) -> None:
    _, foreign = _user_save(db, "intruder-sm025a", "别人的存档")
    _player(db, foreign, "F1")
    response = client.post("/api/v1/recruitment/search", json={"save_id": foreign.id, "slot": "ST"})
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "save_not_found"


def test_compare_mixed_players_is_rejected(client: TestClient, db, save) -> None:
    _player(db, save, "OWN1")
    _, foreign = _user_save(db, "intruder-sm025b", "别人的存档")
    foreign_instance = _player(db, foreign, "F2")
    own_instance = db.scalar(select(PlayerInstance).where(PlayerInstance.fm_save_id == save.id))
    response = client.post(
        "/api/v1/recruitment/compare",
        json={"instance_ids": [own_instance.id, foreign_instance.id]},
    )
    assert response.status_code == 404, response.text


def test_compare_with_foreign_body_save_id_is_rejected(client: TestClient, db, save) -> None:
    _, foreign = _user_save(db, "intruder-sm025c", "别人的存档")
    first = _player(db, foreign, "F3")
    second = _player(db, foreign, "F3B")
    response = client.post(
        "/api/v1/recruitment/compare",
        json={"save_id": foreign.id, "instance_ids": [first.id, second.id]},
    )
    assert response.status_code == 404


def test_create_shortlist_body_save_id_of_other_user_is_rejected(client: TestClient, db, save) -> None:
    _, foreign = _user_save(db, "intruder-sm025d", "别人的存档")
    response = client.post(
        "/api/v1/recruitment/shortlists",
        json={"save_id": foreign.id, "name": "偷看名单", "slot": "ST"},
    )
    assert response.status_code == 404, response.text


def test_scouting_body_save_id_of_other_user_is_rejected(client: TestClient, db, save) -> None:
    _, foreign = _user_save(db, "intruder-sm025e", "别人的存档")
    response = client.post(
        "/api/v1/scouting/search",
        json={"save_id": foreign.id, "role_key": "advanced_forward"},
    )
    assert response.status_code == 404, response.text


def test_transfer_cost_and_investment_require_owner(client: TestClient, db, save) -> None:
    _, foreign = _user_save(db, "intruder-sm025f", "别人的存档")
    instance = _player(db, foreign, "F4")
    club = Club(fm_save_id=foreign.id, uid="foreign-club", name="Foreign Club")
    db.add(club)
    db.commit()
    transfer = Transfer(
        fm_save_id=foreign.id,
        source_record_id="F4",
        player_instance_id=instance.id,
        player_name="Player F4",
        to_club_id=club.id,
        transfer_type="permanent",
        status="completed",
        transfer_date=date(2026, 7, 1),
        currency="EUR",
        effective_fee=1_000_000,
        source="manual",
    )
    db.add(transfer)
    db.commit()
    assert client.get(f"/api/v1/transfers/{transfer.id}/cost").status_code == 404
    assert client.get(f"/api/v1/transfers/investment?instance_id={instance.id}&total_cost=1000").status_code == 404
    assert client.post(
        "/api/v1/transfers/deal-report", json={"save_id": foreign.id, "instance_id": instance.id}
    ).status_code == 404


def test_deal_report_foreign_instance_is_rejected(client: TestClient, db, save) -> None:
    _, foreign = _user_save(db, "intruder-sm025g", "别人的存档")
    instance = _player(db, foreign, "F5")
    response = client.post("/api/v1/transfers/deal-report", json={"instance_id": instance.id})
    assert response.status_code == 404, response.text


def test_own_second_save_works_for_search_compare_shortlist(client: TestClient, db, save) -> None:
    user = db.scalar(select(User).where(User.username == "local"))
    second = FmSave(user_id=user.id, name="我的第二存档", game_version="27.1", game_build="x", is_active=False)
    db.add(second)
    db.commit()
    response = client.post(
        f"/api/v1/imports/scan?save_id={second.id}",
        content=json.dumps(scan_document(scan_id="sm025-own2", players=[player_row("OWN2", "Own Two", position="ST"), player_row("OWN2B", "Own Two B", position="ST")])).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 201, response.text
    instances = list(
        db.scalars(
            select(PlayerInstance)
            .join(Player, Player.id == PlayerInstance.player_id)
            .where(PlayerInstance.fm_save_id == second.id)
        )
    )
    assert len(instances) == 2
    search = client.post("/api/v1/recruitment/search", json={"save_id": second.id, "slot": "ST"})
    assert search.status_code == 200, search.text
    compare = client.post(
        "/api/v1/recruitment/compare", json={"save_id": second.id, "instance_ids": [item.id for item in instances]}
    )
    assert compare.status_code == 200, compare.text
    shortlist = client.post(
        "/api/v1/recruitment/shortlists", json={"save_id": second.id, "name": "我的名单", "slot": "ST"}
    )
    assert shortlist.status_code == 201, shortlist.text


def test_ai_tools_cannot_change_save_scope() -> None:
    with pytest.raises(llm_planner.PlannerError):
        llm_planner.parse_plan(
            {"tool_calls": [{"tool": "recruitment_recommend", "arguments": {"slot": "ST", "save_id": 999}}]}
        )


def test_ai_service_rejects_foreign_save_for_tools(db, save) -> None:
    local = db.scalar(select(User).where(User.username == "local"))
    _, foreign = _user_save(db, "intruder-sm025h", "别人的存档")
    with pytest.raises(ValueError):
        service.answer_question(db, foreign.id, "推荐前锋", user_id=local.id)
