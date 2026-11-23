"""SM-115：候选与观察必须按存档隔离。"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.ingestion.importer import ScanImporter
from app.ingestion.protocol import ScanPayload
from app.models import FmSave, User, UnresolvedPlayerCandidate, UnresolvedPlayerObservation
from tests.helpers import import_document, scan_document
from tests.test_unresolved_persistence import unresolved_row


def _second_save(db: Session, user_id: int, name: str) -> FmSave:
    record = FmSave(user_id=user_id, name=name, game_version="27.1", game_build="26620374", is_active=False)
    db.add(record)
    db.commit()
    return record


def _import_into(db: Session, save_id: int, document: dict):
    outcome = ScanImporter(db, raw_dir=settings.raw_import_dir).import_payload(
        save_id, ScanPayload.model_validate(document)
    )
    db.commit()
    return outcome


def test_same_name_and_sentinel_do_not_cross_saves(db: Session, save) -> None:
    user = db.scalar(select(User).where(User.id == save.user_id))
    assert user is not None
    other = _second_save(db, user.id, "第二个存档")

    import_document(db, scan_document(scan_id="save-a-scan", players=[unresolved_row("Shared Name")]))
    _import_into(db, other.id, scan_document(scan_id="save-b-scan", players=[unresolved_row("Shared Name")]))

    assert db.scalar(select(func.count()).select_from(UnresolvedPlayerCandidate)) == 2
    candidates = list(db.scalars(select(UnresolvedPlayerCandidate).order_by(UnresolvedPlayerCandidate.id)))
    assert [item.fm_save_id for item in candidates] == [save.id, other.id]

    observations = list(db.scalars(select(UnresolvedPlayerObservation).order_by(UnresolvedPlayerObservation.id)))
    assert [item.fm_save_id for item in observations] == [save.id, other.id]
    assert [item.scan_id for item in observations] == ["save-a-scan", "save-b-scan"]

    per_save = dict(
        db.execute(
            select(UnresolvedPlayerCandidate.fm_save_id, func.count()).group_by(
                UnresolvedPlayerCandidate.fm_save_id
            )
        ).all()
    )
    assert per_save == {save.id: 1, other.id: 1}


def test_same_scan_id_in_two_saves_is_allowed(db: Session, save) -> None:
    user = db.scalar(select(User).where(User.id == save.user_id))
    assert user is not None
    other = _second_save(db, user.id, "第三存档")

    document = scan_document(scan_id="same-scan-id", players=[unresolved_row("Twin")])
    _import_into(db, save.id, document)
    outcome = _import_into(db, other.id, document)

    assert outcome.duplicate is False
    assert db.scalar(select(func.count()).select_from(UnresolvedPlayerObservation)) == 2
