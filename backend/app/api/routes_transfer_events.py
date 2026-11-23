"""Transfer event candidate API (V3.2.2 SM-070)."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..analytics.transfer_events import detect_transfer_events
from ..db import get_db
from ..models import FmSave, TransferEventCandidate
from ..utils import iso
from .deps import get_active_save

router = APIRouter()


def _payload(row: TransferEventCandidate) -> dict[str, Any]:
    try:
        evidence = json.loads(row.evidence_json or "{}")
    except json.JSONDecodeError:
        evidence = {}
    return {
        "id": row.id,
        "player_instance_id": row.player_instance_id,
        "event_type": row.event_type,
        "from_club_id": row.from_club_id,
        "to_club_id": row.to_club_id,
        "game_date": row.game_date.isoformat(),
        "evidence_level": row.evidence_level,
        "status": row.status,
        "evidence": evidence,
        "created_at": iso(row.created_at),
    }


@router.get("/transfer-events", summary="转会事件候选")
def list_transfer_events(
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    query = select(TransferEventCandidate).where(TransferEventCandidate.fm_save_id == save.id)
    if status:
        query = query.where(TransferEventCandidate.status == status)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(TransferEventCandidate.game_date.desc(), TransferEventCandidate.id).offset(offset).limit(limit))
    return {"items": [_payload(row) for row in rows], "total": int(total)}


@router.post("/transfer-events/detect", summary="从 canonical 快照检测俱乐部变化候选")
def detect(
    dry_run: bool = Query(default=True),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    return detect_transfer_events(db, save.id, dry_run=dry_run)
