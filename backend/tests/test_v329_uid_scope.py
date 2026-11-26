"""V3.2.9 Phase 1：UID 作用域与唯一性测试。"""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select

from app.models import FmSave, PlayerUidObservation
from app.services import uid_scope
from app.services.uid_scope import UidScope

from tests.v329_helpers import make_instance


def _scope(save, **overrides) -> UidScope:
    values = {
        "save_id": save.id,
        "source_type": "live_reader",
        "save_identity_fingerprint": "si:v1:file:abc123",
        "session_key": "session-1",
        "game_build": "26620374",
        "layout_version": "FM27_1",
    }
    values.update(overrides)
    return UidScope(**values)


def test_valid_uid_observation_is_idempotent(db, save) -> None:
    scope = _scope(save)
    first = uid_scope.record_observation(
        db, scope, uid_raw="12345", player_instance_id=None, player_id=None, name="A", birth_date=date(2000, 1, 1)
    )
    second = uid_scope.record_observation(
        db, scope, uid_raw="12345", player_instance_id=None, player_id=None, name="A", birth_date=date(2000, 1, 1)
    )
    assert first.id == second.id
    assert first.status == uid_scope.STATUS_VALID
    assert first.uid == "12345"
    assert db.scalar(select(func.count()).select_from(PlayerUidObservation)) == 1


def test_sentinel_missing_and_zero_are_not_identities(db, save) -> None:
    scope = _scope(save)
    sentinel = uid_scope.record_observation(
        db, scope, uid_raw="4294967295", player_instance_id=None, player_id=None
    )
    missing = uid_scope.record_observation(db, scope, uid_raw=None, player_instance_id=None, player_id=None)
    zero = uid_scope.record_observation(db, scope, uid_raw="0", player_instance_id=None, player_id=None)

    assert sentinel.status == uid_scope.STATUS_MISSING
    assert sentinel.uid_reason == "sentinel_uid"
    assert sentinel.uid == "4294967295"  # 原始值保留为证据
    assert missing.status == uid_scope.STATUS_MISSING
    assert missing.uid is None
    assert zero.status == uid_scope.STATUS_MISSING
    assert zero.uid_reason == "invalid_uid"


def test_scope_change_creates_new_observation_not_overwrite(db, save) -> None:
    base = uid_scope.record_observation(
        db, _scope(save), uid_raw="777", player_instance_id=None, player_id=None
    )
    other_scope = uid_scope.record_observation(
        db,
        _scope(save, save_identity_fingerprint="si:v1:file:other", session_key="session-2"),
        uid_raw="777",
        player_instance_id=None,
        player_id=None,
    )
    assert base.id != other_scope.id
    assert base.save_identity_fingerprint == "si:v1:file:abc123"
    assert other_scope.save_identity_fingerprint == "si:v1:file:other"
    assert db.scalar(select(func.count()).select_from(PlayerUidObservation)) == 2


def test_same_uid_two_players_in_one_save_is_duplicate(db, save) -> None:
    make_instance(db, save, uid="9001", name="Alpha One", birth=date(1995, 3, 3))
    make_instance(db, save, uid="9001", name="Beta Two", birth=date(1988, 7, 7), occurrence=1)
    groups = uid_scope.duplicate_uid_groups(db, save.id)
    assert len(groups) == 1
    assert groups[0]["uid"] == "9001"
    assert groups[0]["player_count"] == 2

    summary = uid_scope.summary(db, save.id)
    assert summary["duplicate_uid_count"] == 1
    assert summary["distinct_save_local_uids"] == 1


def test_same_uid_in_different_saves_is_not_merged(db, save) -> None:
    make_instance(db, save, uid="SAME-UID", name="Cross Save Person", birth=date(1999, 9, 9))
    other = FmSave(user_id=save.user_id, name="另一个存档", game_build="26620374", is_active=False)
    db.add(other)
    db.flush()
    make_instance(db, other, uid="SAME-UID", name="Different Person", birth=date(1990, 1, 1))

    assert uid_scope.duplicate_uid_groups(db, save.id) == []
    assert uid_scope.duplicate_uid_groups(db, other.id) == []
    assert uid_scope.summary(db, save.id)["duplicate_uid_count"] == 0


def test_attribute_digest_excludes_memory_addresses(db, save) -> None:
    digest_a = uid_scope.attribute_record_digest(name="John Smith", birth_date=date(2000, 1, 1), uid="42")
    digest_b = uid_scope.attribute_record_digest(name="John Smith", birth_date=date(2000, 1, 1), uid="42")
    digest_c = uid_scope.attribute_record_digest(name="John Smith", birth_date=date(2001, 1, 1), uid="42")
    assert digest_a == digest_b
    assert digest_a != digest_c
    assert "0x" not in digest_a
