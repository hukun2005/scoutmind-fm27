"""SM-031：IdentityMatch 跨存档隔离。"""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import (
    FmSave,
    IdentityConflict,
    IdentityMatch,
    Player,
    PlayerInstance,
    User,
)


def _save(db, user, name: str) -> FmSave:
    save = FmSave(user_id=user.id, name=name, game_version="27.1", game_build="x", is_active=name == "A")
    db.add(save)
    db.commit()
    return save


def _setup(db, save_a):
    user = db.scalar(select(User).where(User.username == "local"))
    save_b = _save(db, user, "B")
    keep = Player(full_name="Shared Keep", normalized_name="shared-keep")
    drop = Player(full_name="Shared Drop", normalized_name="shared-drop")
    db.add_all([keep, drop])
    db.commit()
    a_keep = PlayerInstance(player_id=keep.id, fm_save_id=save_a.id, save_local_uid="K-A")
    a_drop = PlayerInstance(player_id=drop.id, fm_save_id=save_a.id, save_local_uid="D-A")
    b_keep = PlayerInstance(player_id=keep.id, fm_save_id=save_b.id, save_local_uid="K-B")
    b_drop = PlayerInstance(player_id=drop.id, fm_save_id=save_b.id, save_local_uid="D-B")
    db.add_all([a_keep, a_drop, b_keep, b_drop])
    db.commit()
    match_a = IdentityMatch(player_id=drop.id, fm_save_id=save_a.id, strategy="uid", confidence=0.9, evidence_json='{"save":"A"}')
    match_b = IdentityMatch(player_id=drop.id, fm_save_id=save_b.id, strategy="name", confidence=0.6, evidence_json='{"save":"B"}')
    db.add_all([match_a, match_b])
    conflict_a = IdentityConflict(
        fm_save_id=save_a.id,
        save_local_uid="K-A",
        reason="uid_reuse",
        existing_player_id=keep.id,
        incoming_player_id=drop.id,
        existing_name="Shared Keep",
        incoming_name="Shared Drop",
        status="open",
        evidence_json="{}",
    )
    conflict_b = IdentityConflict(
        fm_save_id=save_b.id,
        save_local_uid="K-B",
        reason="uid_reuse",
        existing_player_id=keep.id,
        incoming_player_id=drop.id,
        existing_name="Shared Keep",
        incoming_name="Shared Drop",
        status="open",
        evidence_json="{}",
    )
    db.add_all([conflict_a, conflict_b])
    db.commit()
    return save_b, conflict_a, conflict_b, match_a, match_b, a_drop, b_drop


def _strategies(payload) -> set[str]:
    result = set()
    for side in ("existing", "incoming"):
        for match in payload[side].get("recent_matches", []):
            result.add(match["strategy"])
    return result


def test_conflict_detail_only_shows_own_save_matches(client: TestClient, db, save) -> None:
    save_b, conflict_a, conflict_b, match_a, match_b, _, _ = _setup(db, save)
    detail_a = client.get(f"/api/v1/identity/conflicts/{conflict_a.id}").json()
    assert _strategies(detail_a) == {"uid"}, "存档 A 的详情只能看到 A 的匹配证据"

    detail_b = client.get(f"/api/v1/identity/conflicts/{conflict_b.id}?save_id={save_b.id}").json()
    assert _strategies(detail_b) == {"name"}, "存档 B 的详情只能看到 B 的匹配证据"


def test_merge_a_does_not_touch_b_match(client: TestClient, db, save) -> None:
    save_b, conflict_a, conflict_b, match_a, match_b, a_drop, b_drop = _setup(db, save)
    response = client.post(
        f"/api/v1/identity/conflicts/{conflict_a.id}/resolve",
        json={"decision": "same", "keep": "existing"},
    )
    assert response.status_code == 200, response.text
    db.expire_all()
    assert db.get(IdentityMatch, match_a.id).player_id != db.get(IdentityMatch, match_b.id).player_id
    assert db.get(IdentityMatch, match_b.id).fm_save_id == save_b.id
    # B 的匹配仍指向原 drop，A 的匹配迁到 keep
    assert db.get(IdentityMatch, match_b.id).strategy == "name"
    assert db.get(PlayerInstance, b_drop.id).player_id == db.get(IdentityMatch, match_b.id).player_id
