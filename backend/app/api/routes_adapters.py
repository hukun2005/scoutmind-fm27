"""External-source import endpoints: the FMSuperScout adapter and its field-mapping report.

The adapter is a translator, not a second import path: a converted dump becomes an ordinary scan payload and goes
through the same validation, identity matching and idempotent import as any other scan.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..ingestion.adapters import fmscout
from ..ingestion.importer import ScanImporter
from ..ingestion.protocol import ProtocolError, ScanPayload
from ..models import FmSave
from .deps import get_active_save, get_current_user

router = APIRouter()

PREVIEW_PLAYERS = 5


@router.get("/imports/fmscout/adapter")
def adapter_info() -> dict[str, Any]:
    """What the adapter maps, what it ignores and which fields it can never fill."""
    return {
        "adapter": fmscout.ADAPTER_NAME,
        "version": fmscout.ADAPTER_VERSION,
        "upstream": {
            "name": "FMSuperScout",
            "url": "https://github.com/mavarobli/FMSuperScout",
            "license": "MIT",
            "note": "ScoutMind 只读取其导出的 JSON，不修改游戏、存档或 FMSuperScout 的文件",
        },
        "mapped_fields": list(fmscout.MAPPED_FIELDS),
        "absent_fields": list(fmscout.ABSENT_FIELDS),
        "ignored_fields": [
            {"field": key, "reason": reason} for key, reason in fmscout.IGNORED_FIELDS.items()
        ],
        "attribute_map": fmscout.ATTRIBUTE_MAP,
        "unmapped_attributes": sorted(fmscout.UNMAPPED_ATTRIBUTES),
    }


@router.post("/imports/fmscout/preview")
async def preview(request: Request) -> dict[str, Any]:
    """Convert a dump and report the mapping without writing anything to the database."""
    raw = await _read_upload(request)
    try:
        payload, report = fmscout.convert_dump(raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "not_fmscout_dump", "message": str(exc)}) from exc
    return {
        "report": report.payload(),
        "scan": payload["scan"],
        "counts": {
            "clubs": len(payload["clubs"]),
            "players": len(payload["players"]),
        },
        "sample_players": payload["players"][:PREVIEW_PLAYERS],
        "sample_clubs": payload["clubs"][:PREVIEW_PLAYERS],
    }


@router.post("/imports/fmscout", status_code=201)
async def import_dump(
    request: Request,
    save_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
    user=Depends(get_current_user),
) -> dict[str, Any]:
    """Convert an FMSuperScout dump and import it idempotently, returning the adapter report too."""
    target = _resolve_save(db, save_id or save.id, user.id)
    raw = await _read_upload(request)
    try:
        payload, report = fmscout.convert_dump(raw)
        validated = ScanPayload.model_validate(payload)
    except (ValueError, ProtocolError) as exc:
        raise HTTPException(status_code=422, detail={"code": "not_fmscout_dump", "message": str(exc)}) from exc
    outcome = ScanImporter(db).import_payload(target.id, validated, raw)
    return {
        "report": report.payload(),
        "import": {
            "job_id": outcome.job_id,
            "status": outcome.status,
            "duplicate": outcome.duplicate,
            "scan_id": outcome.scan_id,
            "save_id": outcome.save_id,
            "players_created": outcome.players_created,
            "players_updated": outcome.players_updated,
            "snapshots_created": outcome.snapshots_created,
            "snapshots_skipped": outcome.snapshots_skipped,
            "rows_rejected": outcome.rows_rejected,
            "warnings": outcome.warnings,
            "coverage": outcome.coverage,
        },
    }


def maybe_adapt(raw: bytes) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Detect and convert an FMSuperScout dump on the generic scan-import path.

    Returns ``(payload, report)`` when the bytes are a dump, ``None`` when they are a normal scan payload. Detection
    is structural and cheap: a scan payload always carries ``schema_version``.
    """
    if not raw.lstrip()[:1] in {b"{", b"["}:
        return None
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not fmscout.detect(document):
        return None
    payload, report = fmscout.convert_document(document, raw=raw)
    return payload, report.payload()


async def _read_upload(request: Request) -> bytes:
    """Accept a multipart ``file`` upload or a raw body, with the same size limit as the scan endpoint."""
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            raise HTTPException(status_code=422, detail={"code": "missing_file", "message": "缺少 file 字段"})
        raw = await upload.read()  # type: ignore[union-attr]
    else:
        raw = await request.body()
    if not raw:
        raise HTTPException(status_code=422, detail={"code": "empty_payload", "message": "文件内容为空"})
    if len(raw) > settings.max_import_bytes:
        raise HTTPException(status_code=413, detail={"code": "payload_too_large", "message": "文件超过大小限制"})
    return raw


def _resolve_save(db: Session, save_id: int, user_id: int) -> FmSave:
    target = db.get(FmSave, save_id)
    if target is None or target.user_id != user_id:
        raise HTTPException(status_code=404, detail={"code": "save_not_found", "message": "存档不存在"})
    return target
