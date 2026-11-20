"""SM-027：身份合并的存档边界。"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    FmSave,
    IdentityConflict,
    IdentityMatch,
    Player,
    PlayerInstance,
    User,
)


def _save(db, user, name: str, active: bool = False) -> FmSave:
    save = FmSave(user_id=user.id, name=name, game_version="27.1", game_build="x", is_active=active)
    db.add(save)
    db.commit()
    return save


def _player(db, name: str) -> Player:
    player = Player(full_name=name, normalized_name=name.lower().replace(" ", "-"))
    db.add(player)
    db.commit()
    return player


def _instance(db, save, player, uid: str) -> PlayerInstance:
    instance = PlayerInstance(player_id=player.id, fm_save_id=save.id, save_local_uid=uid)
    db.add(instance)
    db.commit()
    return instance


def _setup(db, save) -> tuple[IdentityConflict, Player, Player, PlayerInstance, PlayerInstance, PlayerInstance, IdentityMatch, IdentityMatch]:
    user = db.scalar(select(User).where(User.username == "local"))
    keep = _player(db, "Keep Player")
    drop = _player(db, "Drop Player")
    a_keep = _instance(db, save, keep, "UID-A")
    a_drop = _instance(db, save, drop, "UID-B")
    other = _save(db, user, "另一个存档")
    b_drop = _instance(db, other, drop, "UID-B")
    match_a = IdentityMatch(player_id=drop.id, fm_save_id=save.id, strategy="uid", confidence=0.9, evidence_json="{}")
    match_b = IdentityMatch(player_id=drop.id, fm_save_id=other.id, strategy="uid", confidence=0.9, evidence_json="{}")
    db.add_all([match_a, match_b])
    conflict = IdentityConflict(
        fm_save_id=save.id,
        save_local_uid="UID-A",
        reason="uid_reuse",
        existing_player_id=keep.id,
        incoming_player_id=drop.id,
        existing_name="Keep Player",
        incoming_name="Drop Player",
        existing_birth_date=date(2000, 1, 1),
        incoming_birth_date=date(2000, 1, 2),
        status="open",
        evidence_json="{}",
    )
    db.add(conflict)
    db.commit()
    return conflict, keep, drop, a_keep, a_drop, b_drop, match_a, match_b


def test_merge_only_touches_current_save(client: TestClient, db, save) -> None:
    conflict, keep, drop, a_keep, a_drop, b_drop, match_a, match_b = _setup(db, save)
    response = client.post(
        f"/api/v1/identity/conflicts/{conflict.id}/resolve",
        json={"decision": "same", "keep": "existing"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["merged"]["instances_moved"] == 1
    assert response.json()["merged"]["matches_moved"] == 1

    db.expire_all()
    assert db.get(PlayerInstance, a_drop.id).player_id == keep.id, "当前存档实例迁到保留身份"
    assert db.get(PlayerInstance, b_drop.id).player_id == drop.id, "其他存档实例不受影响"
    assert db.get(IdentityMatch, match_a.id).player_id == keep.id
    assert db.get(IdentityMatch, match_b.id).player_id == drop.id, "其他存档的匹配证据不能被改"
    assert db.get(IdentityConflict, conflict.id).status == "resolved"


def test_merge_failure_rolls_back_everything(client: TestClient, db, save, monkeypatch: pytest.MonkeyPatch) -> None:
    conflict, keep, drop, a_keep, a_drop, b_drop, match_a, match_b = _setup(db, save)

    original_commit = Session.commit

    def fail_commit(self):
        raise RuntimeError("simulated commit failure")

    monkeypatch.setattr(Session, "commit", fail_commit)
    response = client.post(
        f"/api/v1/identity/conflicts/{conflict.id}/resolve",
        json={"decision": "same", "keep": "existing"},
    )
    monkeypatch.setattr(Session, "commit", original_commit)
    assert response.status_code == 500, response.text

    db.expire_all()
    assert db.get(PlayerInstance, a_drop.id).player_id == drop.id, "失败必须回滚实例迁移"
    assert db.get(IdentityMatch, match_a.id).player_id == drop.id, "失败必须回滚匹配证据"
    assert db.get(IdentityConflict, conflict.id).status == "open"
