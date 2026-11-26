"""V3.2.9 Phase 3/9：人工审核队列、审计不可改与 Verified 门控测试。"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import func, select

from app.models import (
    FmSave,
    PlayerIdentityLink,
    PlayerIdentityReviewAction,
    PlayerIdentityReviewItem,
)
from app.services import identity_engine
from app.services import identity_errors as errors
from app.services.identity_errors import IdentityGovernanceError
from app.services.identity_review import ensure_review_item, resolve_review

from tests.v329_helpers import make_instance


def _make_conflict_pair(db, save):
    left = make_instance(db, save, uid="A1", name="Same Name", birth=date(1995, 1, 1))
    right = make_instance(db, save, uid="A2", name="Same Name", birth=date(1995, 1, 1))
    item = ensure_review_item(
        db,
        save.id,
        item_type="same_name",
        subject_uid=None,
        player_ids=[left.player_id, right.player_id],
        reason="same_name_same_birth_date",
        primary_player_id=left.player_id,
        payload={"uid_a": "A1", "uid_b": "A2"},
    )
    db.flush()
    return left, right, item


def test_confirm_same_person_creates_human_links_and_audit(db, save) -> None:
    left, right, item = _make_conflict_pair(db, save)
    from app.models import User

    reviewer = db.scalar(select(User).where(User.username == "local"))
    resolve_review(db, item, user=reviewer, decision="same", note="人工核对俱乐部与生日一致")
    db.commit()

    assert item.status == "Confirmed"
    links = list(
        db.scalars(
            select(PlayerIdentityLink).where(
                PlayerIdentityLink.player_instance_id.in_([left.id, right.id])
            )
        )
    )
    assert len(links) == 2
    assert {row.verification_status for row in links} == {"ConfirmedByHuman"}
    assert {row.canonical_player_id for row in links} == {left.player_id}

    action = db.scalar(select(PlayerIdentityReviewAction))
    assert action is not None
    assert action.decision == "same_person"
    assert action.previous_status == "PendingHumanReview"
    assert action.new_status == "Confirmed"


def test_different_people_and_independent_outcomes(db, save) -> None:
    from app.models import User

    reviewer = db.scalar(select(User).where(User.username == "local"))
    _, _, first = _make_conflict_pair(db, save)
    resolve_review(db, first, user=reviewer, decision="different")
    assert first.status == "Rejected"

    left = make_instance(db, save, uid="B1", name="Other Person", birth=date(1990, 1, 1))
    right = make_instance(db, save, uid="B2", name="Other Person", birth=date(1990, 1, 1))
    second = ensure_review_item(
        db,
        save.id,
        item_type="same_name",
        subject_uid=None,
        player_ids=[left.player_id, right.player_id],
        reason="same_name_same_birth_date",
        primary_player_id=left.player_id,
        payload={},
    )
    resolve_review(db, second, user=reviewer, decision="independent")
    assert second.status == "KeptIndependent"

    third = ensure_review_item(
        db,
        save.id,
        item_type="uid_duplicate",
        subject_uid="B1",
        player_ids=[left.player_id],
        reason="duplicate_uid_same_save",
        payload={},
    )
    resolve_review(db, third, user=reviewer, decision="defer")
    assert third.status == "Deferred"
    assert third.resolved_at is None


def test_resolved_item_cannot_be_overwritten(db, save) -> None:
    from app.models import User

    reviewer = db.scalar(select(User).where(User.username == "local"))
    _, _, item = _make_conflict_pair(db, save)
    resolve_review(db, item, user=reviewer, decision="different")
    with pytest.raises(IdentityGovernanceError) as excinfo:
        resolve_review(db, item, user=reviewer, decision="same")
    assert excinfo.value.code == errors.REVIEW_ALREADY_RESOLVED


def test_review_payload_cannot_set_verified(db, save) -> None:
    from app.models import User

    reviewer = db.scalar(select(User).where(User.username == "local"))
    _, _, item = _make_conflict_pair(db, save)
    with pytest.raises(IdentityGovernanceError) as excinfo:
        resolve_review(
            db, item, user=reviewer, decision="same", payload={"verification_status": "Verified"}
        )
    assert excinfo.value.code == errors.VERIFIED_NOT_SETTABLE
    assert item.status == "PendingHumanReview"


def test_review_actions_are_append_only(db, save) -> None:
    from app.models import User

    reviewer = db.scalar(select(User).where(User.username == "local"))
    _, _, item = _make_conflict_pair(db, save)
    resolve_review(db, item, user=reviewer, decision="different")
    db.commit()
    action = db.scalar(select(PlayerIdentityReviewAction))
    action.note = "rewritten"
    with pytest.raises(ValueError):
        db.commit()
    db.rollback()


def test_queue_api_and_save_isolation(client, db, save) -> None:
    _, _, item = _make_conflict_pair(db, save)
    db.commit()

    response = client.get("/api/v1/identity/center/queue")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == item.id
    assert body["items"][0]["history"] == []

    other = FmSave(user_id=save.user_id, name="另一个存档", is_active=False)
    db.add(other)
    db.commit()
    hidden = client.get(f"/api/v1/identity/center/queue/{item.id}?save_id={other.id}")
    assert hidden.status_code == 404

    resolved = client.post(
        f"/api/v1/identity/center/queue/{item.id}/resolve",
        json={"decision": "different", "note": "出生日期不同"},
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "Rejected"

    history = client.get("/api/v1/identity/center/history")
    assert history.status_code == 200
    assert history.json()["items"][0]["decision"] == "different_people"

    detail = client.get(f"/api/v1/identity/center/queue/{item.id}")
    assert detail.json()["status"] == "Rejected"


def test_api_rejects_verified_payload(client, db, save) -> None:
    _, _, item = _make_conflict_pair(db, save)
    db.commit()
    response = client.post(
        f"/api/v1/identity/center/queue/{item.id}/resolve",
        json={"decision": "same", "payload": {"status": "Verified"}},
    )
    assert response.status_code in (400, 409)
    assert response.json()["error"]["code"] == errors.VERIFIED_NOT_SETTABLE


def test_rescan_does_not_overwrite_human_decision(db, save) -> None:
    from app.models import User

    reviewer = db.scalar(select(User).where(User.username == "local"))
    make_instance(db, save, uid="C1", name="Rescan Person", birth=date(1995, 1, 1))
    make_instance(db, save, uid="C2", name="Rescan Person", birth=date(1985, 1, 1))
    run = identity_engine.start_scan(
        db, save.id, scan_id="scan-rescan", fingerprint="si:v1:file:abc123", game_build="26620374", layout_version="FM27_1"
    )
    identity_engine.run_scan(db, run)
    item = db.scalar(select(PlayerIdentityReviewItem))
    assert item is not None
    resolve_review(db, item, user=reviewer, decision="different")
    db.commit()

    run2 = identity_engine.start_scan(
        db, save.id, scan_id="scan-rescan-2", fingerprint="si:v1:file:abc123", game_build="26620374", layout_version="FM27_1"
    )
    identity_engine.run_scan(db, run2)
    db.refresh(item)
    assert item.status == "Rejected"
    assert db.scalar(select(func.count()).select_from(PlayerIdentityReviewItem)) == 1
