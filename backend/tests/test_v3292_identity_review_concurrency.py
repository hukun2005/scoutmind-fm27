"""V3.2.9.2 Phase 3：身份审核并发保护、历史追加与同名候选完整性。"""

from __future__ import annotations

import json
from datetime import date

import pytest
from sqlalchemy import func, select

from app.models import PlayerIdentityReviewAction, PlayerIdentityReviewItem, User
from app.services import identity_engine
from app.services import identity_errors as errors
from app.services.identity_errors import IdentityGovernanceError
from app.services.identity_review import ensure_review_item, resolve_review

from tests.v329_helpers import make_instance


def _reviewer(db) -> User:
    return db.scalar(select(User).where(User.username == "local"))


def _item(db, save, *, uid="A1", name="Same Name", birth=date(1995, 1, 1), reason="same_name_same_birth_date"):
    left = make_instance(db, save, uid=uid, name=name, birth=birth)
    right = make_instance(db, save, uid=uid + "-2", name=name, birth=birth)
    item = ensure_review_item(
        db,
        save.id,
        item_type="same_name",
        subject_uid=None,
        player_ids=[left.player_id, right.player_id],
        reason=reason,
        primary_player_id=left.player_id,
        payload={},
    )
    db.flush()
    return item


def test_concurrent_review_only_one_writer_succeeds(db, save) -> None:
    reviewer = _reviewer(db)
    item = _item(db, save)
    assert item.version == 1

    resolve_review(db, item, user=reviewer, decision="defer", expected_version=1)
    db.commit()

    with pytest.raises(IdentityGovernanceError) as excinfo:
        resolve_review(db, item, user=reviewer, decision="different", expected_version=1)

    assert excinfo.value.code == errors.REVIEW_VERSION_CONFLICT
    db.refresh(item)
    assert item.status == "Deferred"
    assert item.version == 2
    assert db.scalar(select(func.count()).select_from(PlayerIdentityReviewAction)) == 1


def test_review_version_conflict_returns_conflict(db, save) -> None:
    reviewer = _reviewer(db)
    item = _item(db, save)
    resolve_review(db, item, user=reviewer, decision="defer", expected_version=1)
    db.flush()

    with pytest.raises(IdentityGovernanceError) as excinfo:
        resolve_review(db, item, user=reviewer, decision="independent", expected_version=1)

    assert excinfo.value.code == errors.REVIEW_VERSION_CONFLICT
    assert excinfo.value.status_code == 409


def test_resolved_item_cannot_be_overwritten(db, save) -> None:
    reviewer = _reviewer(db)
    item = _item(db, save)
    resolve_review(db, item, user=reviewer, decision="different", expected_version=1)
    db.flush()

    with pytest.raises(IdentityGovernanceError) as excinfo:
        resolve_review(db, item, user=reviewer, decision="same", expected_version=2)

    assert excinfo.value.code == errors.REVIEW_ALREADY_RESOLVED


def test_review_history_is_append_only(db, save) -> None:
    reviewer = _reviewer(db)
    item = _item(db, save)
    resolve_review(db, item, user=reviewer, decision="defer", expected_version=1)
    resolve_review(db, item, user=reviewer, decision="different", expected_version=2)
    db.commit()

    actions = list(
        db.scalars(select(PlayerIdentityReviewAction).order_by(PlayerIdentityReviewAction.id))
    )
    assert len(actions) == 2
    assert actions[0].previous_status == "PendingHumanReview"
    assert actions[0].new_status == "Deferred"
    assert actions[0].previous_version == 1
    assert actions[0].new_version == 2
    assert actions[1].previous_status == "Deferred"
    assert actions[1].new_status == "Rejected"
    assert actions[1].previous_version == 2
    assert actions[1].new_version == 3

    actions[0].note = "rewritten"
    with pytest.raises(ValueError):
        db.commit()
    db.rollback()


def test_admin_correction_creates_new_history(db, save) -> None:
    reviewer = _reviewer(db)
    item = _item(db, save)
    resolve_review(db, item, user=reviewer, decision="defer", expected_version=1)
    resolve_review(db, item, user=reviewer, decision="independent", expected_version=2)
    db.commit()

    assert db.scalar(select(func.count()).select_from(PlayerIdentityReviewAction)) == 2
    db.refresh(item)
    assert item.status == "KeptIndependent"
    assert item.version == 3


def test_failed_review_transaction_rolls_back(db, save, monkeypatch) -> None:
    reviewer = _reviewer(db)
    item = _item(db, save)
    db.commit()
    item_id = item.id

    def _boom(*_args, **_kwargs):
        raise IdentityGovernanceError(errors.CANONICAL_LINK_CONFLICT, "模拟确认写入失败")

    monkeypatch.setattr("app.services.identity_engine.confirm_candidate_links", _boom)

    with pytest.raises(IdentityGovernanceError):
        resolve_review(db, item, user=reviewer, decision="same", expected_version=1)
    db.rollback()

    fresh = db.get(PlayerIdentityReviewItem, item_id)
    assert fresh is not None
    assert fresh.status == "PendingHumanReview"
    assert fresh.version == 1
    assert db.scalar(select(func.count()).select_from(PlayerIdentityReviewAction)) == 0


def test_duplicate_review_request_is_idempotent(db, save) -> None:
    reviewer = _reviewer(db)
    item = _item(db, save)

    first = resolve_review(
        db, item, user=reviewer, decision="defer", expected_version=1, request_key="req-1"
    )
    second = resolve_review(
        db, item, user=reviewer, decision="defer", expected_version=1, request_key="req-1"
    )
    db.commit()

    assert first.id == second.id
    assert db.scalar(select(func.count()).select_from(PlayerIdentityReviewAction)) == 1
    db.refresh(item)
    assert item.version == 2


def test_batch_review_does_not_overwrite_concurrent_changes(db, save) -> None:
    reviewer = _reviewer(db)
    first = _item(db, save, uid="B1", name="Batch One")
    second = _item(db, save, uid="B2", name="Batch Two")

    resolve_review(db, first, user=reviewer, decision="defer", expected_version=1)
    resolve_review(db, second, user=reviewer, decision="defer", expected_version=1)
    db.commit()

    # 第二个条目被另一个审核者先改了版本；批量操作携带旧版本必须失败，不能覆盖。
    with pytest.raises(IdentityGovernanceError) as excinfo:
        resolve_review(db, second, user=reviewer, decision="different", expected_version=1)
    assert excinfo.value.code == errors.REVIEW_VERSION_CONFLICT

    db.refresh(second)
    assert second.status == "Deferred"
    assert second.version == 2


def _scan(db, save, scan_id: str) -> None:
    run = identity_engine.start_scan(
        db,
        save.id,
        scan_id=scan_id,
        fingerprint="si:v1:file:abc123",
        game_build="26620374",
        layout_version="FM27_1",
    )
    identity_engine.run_scan(db, run)


def test_same_name_candidate_set_is_complete(db, save) -> None:
    first = make_instance(db, save, uid="S1", name="Mixed Person", birth=date(1995, 1, 1))
    second = make_instance(db, save, uid="S2", name="Mixed Person", birth=date(1995, 1, 1))
    third = make_instance(db, save, uid="S3", name="Mixed Person", birth=date(1985, 5, 5))

    _scan(db, save, "scan-mixed")

    items = list(db.scalars(select(PlayerIdentityReviewItem)))
    assert len(items) == 1, "同一参与者集合只允许一条审核项"
    item = items[0]
    assert item.item_type == "same_name"
    assert item.conflict_reason == "same_name_different_birth_date"
    assert set(json.loads(item.candidate_player_ids_json)) == {
        first.player_id,
        second.player_id,
        third.player_id,
    }
    assert item.status == "PendingHumanReview"


def test_multiple_same_birth_candidates_preserved(db, save) -> None:
    players = [
        make_instance(db, save, uid=f"T{birth}", name="Twin Set", birth=date(1995, 1, 1))
        for birth in ("A", "B", "C")
    ]

    _scan(db, save, "scan-twins")

    items = list(db.scalars(select(PlayerIdentityReviewItem)))
    assert len(items) == 1
    assert items[0].conflict_reason == "same_name_same_birth_date"
    assert len(json.loads(items[0].candidate_player_ids_json)) == len(players)


def test_different_birth_candidates_preserved(db, save) -> None:
    left = make_instance(db, save, uid="D1", name="Distinct Pair", birth=date(1995, 1, 1))
    right = make_instance(db, save, uid="D2", name="Distinct Pair", birth=date(1985, 1, 1))

    _scan(db, save, "scan-distinct")

    item = db.scalar(select(PlayerIdentityReviewItem))
    assert item is not None
    assert set(json.loads(item.candidate_player_ids_json)) == {left.player_id, right.player_id}


def test_insufficient_evidence_requires_manual_review(db, save) -> None:
    make_instance(db, save, uid="U1", name="Unknown Birthday", birth=None)
    make_instance(db, save, uid="U2", name="Unknown Birthday", birth=None)

    _scan(db, save, "scan-unknown")

    item = db.scalar(select(PlayerIdentityReviewItem))
    assert item is not None
    assert item.item_type == "same_name"
    assert item.conflict_reason == "same_name_unknown_birth_date"
    assert item.status == "PendingHumanReview"


def test_api_version_conflict_returns_409(client, db, save) -> None:
    reviewer = _reviewer(db)
    item = _item(db, save)
    db.commit()

    first = client.post(
        f"/api/v1/identity/center/queue/{item.id}/resolve",
        json={"decision": "defer", "expected_version": 1},
    )
    assert first.status_code == 200, first.text
    assert first.json()["version"] == 2

    stale = client.post(
        f"/api/v1/identity/center/queue/{item.id}/resolve",
        json={"decision": "different", "expected_version": 1},
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"]["code"] == errors.REVIEW_VERSION_CONFLICT
    assert reviewer is not None
