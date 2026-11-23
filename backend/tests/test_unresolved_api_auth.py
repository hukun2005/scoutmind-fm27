"""SM-118：Unresolved API 的权限、存档隔离与人工确认语义。"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.ingestion.importer import ScanImporter
from app.ingestion.protocol import ScanPayload
from app.models import (
    FmSave,
    IdentityMatch,
    PlayerInstance,
    UnresolvedPlayerAction,
    UnresolvedPlayerCandidate,
    UnresolvedPlayerObservation,
)
from tests.helpers import import_document, player_row, scan_document
from tests.test_unresolved_persistence import unresolved_row

PREFIX = "/api/v1"


def _import_into(db: Session, save_id: int, document: dict):
    outcome = ScanImporter(db, raw_dir=settings.raw_import_dir).import_payload(
        save_id, ScanPayload.model_validate(document)
    )
    db.commit()
    return outcome


def _seed(db: Session, save: FmSave, scan_id: str = "api-scan") -> None:
    import_document(
        db,
        scan_document(
            scan_id=scan_id,
            players=[
                player_row("9001", "Existing Player", age=24),
                unresolved_row("Candidate One", ca=130, pa=150, position="ST"),
                unresolved_row("Candidate Two", ca=110, pa=130, position="CB"),
            ],
        ),
    )


def _candidates(db: Session) -> list[UnresolvedPlayerCandidate]:
    return list(db.scalars(select(UnresolvedPlayerCandidate).order_by(UnresolvedPlayerCandidate.id)))


def test_list_returns_evidence_not_identities(client: TestClient, db: Session, save) -> None:
    _seed(db, save)
    response = client.get(f"{PREFIX}/unresolved-players")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["counts"] == {"pending": 2, "review_required": 0, "resolved": 0, "dismissed": 0}
    item = body["items"][0]
    assert item["uid"]["status"] == "sentinel"
    assert item["uid"]["raw_uid"] == "4294967295"
    assert item["latest_observation"]["ca"] in {110, 130}
    assert item["resolution"] is None
    assert item["suggestions_are_advisory"] is True
    assert "confirmed" not in item["status"]


def test_list_filters_and_empty_state(client: TestClient, db: Session, save) -> None:
    _seed(db, save)
    response = client.get(f"{PREFIX}/unresolved-players", params={"min_ca": 120})
    assert [item["display_name"] for item in response.json()["items"]] == ["Candidate One"]

    response = client.get(f"{PREFIX}/unresolved-players", params={"position": "CB"})
    assert [item["display_name"] for item in response.json()["items"]] == ["Candidate Two"]

    response = client.get(f"{PREFIX}/unresolved-players", params={"name": "Candidate One"})
    assert response.json()["total"] == 1

    response = client.get(f"{PREFIX}/unresolved-players", params={"name": "No Such Player"})
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0
    assert body["counts"] == {"pending": 2, "review_required": 0, "resolved": 0, "dismissed": 0}


def test_detail_lists_suggestions_and_history(client: TestClient, db: Session, save) -> None:
    _seed(db, save)
    candidate = _candidates(db)[0]
    response = client.get(f"{PREFIX}/unresolved-players/{candidate.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == candidate.id
    assert body["evidence_summary"]["scan_id"] == "api-scan"
    assert body["suggestions"]["player_matches"] == []
    assert body["history"] == []
    assert "永久保留" in body["retention"]


def test_observations_endpoint_pages(client: TestClient, db: Session, save) -> None:
    _seed(db, save)
    candidate = _candidates(db)[0]
    response = client.get(f"{PREFIX}/unresolved-players/{candidate.id}/observations")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["uid_status"] == "sentinel"
    assert body["items"][0]["scan_id"] == "api-scan"


def test_resolve_requires_explicit_confirmation(client: TestClient, db: Session, save) -> None:
    _seed(db, save)
    candidate = _candidates(db)[0]
    instance = db.scalar(select(PlayerInstance).where(PlayerInstance.save_local_uid == "9001"))
    assert instance is not None

    response = client.post(
        f"{PREFIX}/unresolved-players/{candidate.id}/resolve",
        json={"player_instance_id": instance.id, "confirm": False},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "confirmation_required"
    assert db.get(UnresolvedPlayerCandidate, candidate.id).status == "pending"


def test_resolve_links_identity_and_keeps_observations(client: TestClient, db: Session, save) -> None:
    _seed(db, save)
    candidate = _candidates(db)[0]
    instance = db.scalar(select(PlayerInstance).where(PlayerInstance.save_local_uid == "9001"))
    assert instance is not None

    response = client.post(
        f"{PREFIX}/unresolved-players/{candidate.id}/resolve",
        json={"player_instance_id": instance.id, "confirm": True, "note": "人工核对姓名与生日"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "resolved"
    assert body["player_instance_id"] == instance.id
    assert body["player_id"] == instance.player_id
    assert body["audit_action_id"] > 0

    updated = db.get(UnresolvedPlayerCandidate, candidate.id)
    assert updated.status == "resolved"
    assert updated.resolution_method == "manual_attached"
    assert db.scalar(select(func.count()).select_from(UnresolvedPlayerObservation)) == 2
    matches = list(db.scalars(select(IdentityMatch).where(IdentityMatch.strategy == "unresolved_manual_link")))
    assert len(matches) == 1
    assert matches[0].fm_save_id == save.id
    actions = list(db.scalars(select(UnresolvedPlayerAction)))
    assert [item.action for item in actions] == ["resolve"]


def test_duplicate_resolve_is_rejected(client: TestClient, db: Session, save) -> None:
    _seed(db, save)
    candidate = _candidates(db)[0]
    instance = db.scalar(select(PlayerInstance).where(PlayerInstance.save_local_uid == "9001"))
    assert instance is not None
    payload = {"player_instance_id": instance.id, "confirm": True}
    assert client.post(f"{PREFIX}/unresolved-players/{candidate.id}/resolve", json=payload).status_code == 200
    second = client.post(f"{PREFIX}/unresolved-players/{candidate.id}/resolve", json=payload)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "unresolved_already_decided"
    manual_links = db.scalar(
        select(func.count())
        .select_from(IdentityMatch)
        .where(IdentityMatch.strategy == "unresolved_manual_link")
    )
    assert manual_links == 1
    assert db.scalar(select(func.count()).select_from(UnresolvedPlayerAction)) == 1


def test_dismiss_keeps_observations(client: TestClient, db: Session, save) -> None:
    _seed(db, save)
    candidate = _candidates(db)[1]
    response = client.post(
        f"{PREFIX}/unresolved-players/{candidate.id}/dismiss",
        json={"reason": "不是目标球员", "note": "人工判断"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "dismissed"
    assert response.json()["observations_kept"] == 1
    assert db.get(UnresolvedPlayerCandidate, candidate.id).status == "dismissed"
    assert db.scalar(select(func.count()).select_from(UnresolvedPlayerObservation)) == 2

    again = client.post(
        f"{PREFIX}/unresolved-players/{candidate.id}/dismiss", json={"reason": "重复忽略"}
    )
    assert again.status_code == 409


def test_candidate_of_another_save_is_not_reachable(client: TestClient, db: Session, save) -> None:
    """A candidate id from another save must 404 under the active save, not leak."""
    _seed(db, save)
    other = FmSave(user_id=save.user_id, name="另一个存档", game_version="27.1", is_active=False)
    db.add(other)
    db.commit()
    _import_into(db, other.id, scan_document(scan_id="other-scan", players=[unresolved_row("Other Save Player")]))
    other_candidate = db.scalar(
        select(UnresolvedPlayerCandidate).where(UnresolvedPlayerCandidate.fm_save_id == other.id)
    )
    assert other_candidate is not None

    for path in (
        f"{PREFIX}/unresolved-players/{other_candidate.id}",
        f"{PREFIX}/unresolved-players/{other_candidate.id}/observations",
    ):
        response = client.get(path)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "unresolved_not_found"

    response = client.post(
        f"{PREFIX}/unresolved-players/{other_candidate.id}/dismiss", json={"reason": "越权"}
    )
    assert response.status_code == 404

    listed = client.get(f"{PREFIX}/unresolved-players").json()
    assert all(item["id"] != other_candidate.id for item in listed["items"])


def test_foreign_save_id_is_rejected(client: TestClient, db: Session, save) -> None:
    from app.models import User

    stranger = User(username="stranger", display_name="另一个用户")
    db.add(stranger)
    db.commit()
    foreign = FmSave(user_id=stranger.id, name="别人的存档", is_active=True)
    db.add(foreign)
    db.commit()

    response = client.get(f"{PREFIX}/unresolved-players", params={"save_id": foreign.id})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "save_not_found"


def test_resolve_target_must_belong_to_same_save(client: TestClient, db: Session, save) -> None:
    _seed(db, save)
    candidate = _candidates(db)[0]
    other = FmSave(user_id=save.user_id, name="第二个存档", is_active=False)
    db.add(other)
    db.commit()
    _import_into(db, other.id, scan_document(scan_id="other-target", players=[player_row("7777", "Foreign Player")]))
    foreign_instance = db.scalar(
        select(PlayerInstance).where(PlayerInstance.fm_save_id == other.id)
    )
    assert foreign_instance is not None

    response = client.post(
        f"{PREFIX}/unresolved-players/{candidate.id}/resolve",
        json={"player_instance_id": foreign_instance.id, "confirm": True},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "target_not_in_save"
    assert db.get(UnresolvedPlayerCandidate, candidate.id).status == "pending"
