"""External-source import endpoints: the FMSuperScout adapter and its field-mapping report.

The adapter is a translator, not a second import path: a converted dump becomes an ordinary scan payload and goes
through the same validation, identity matching and idempotent import as any other scan.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..ingestion.adapters import fmscout
from ..ingestion.importer import ScanImporter
from ..ingestion.protocol import ProtocolError, ScanPayload
from ..models import FmSave, PlayerInstance
from .deps import get_active_save, get_current_user

router = APIRouter()

PREVIEW_PLAYERS = 5


@router.get("/imports/fmscout/adapter", summary="FMSuperScout 适配器信息")
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


@router.post("/imports/fmscout/preview", summary="字段映射预览（不写库）")
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


@router.post("/imports/fmscout/validate", summary="真实数据审查（P0-1，不写库）")
async def validate_dump(
    request: Request,
    save_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
    user=Depends(get_current_user),
) -> dict[str, Any]:
    """真实数据审查：按 P0-1 的报告格式逐项核对一份真实导出，不写库。"""
    raw = await _read_upload(request)
    try:
        payload, report = fmscout.convert_dump(raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "not_fmscout_dump", "message": str(exc)}) from exc

    players = payload["players"]
    ids = [row["save_local_uid"] for row in players]
    duplicates = sorted({uid for uid in ids if ids.count(uid) > 1})
    coverage = report.payload()["coverage"]
    known_counts = _existing_instances(db, save_id or save.id, ids)
    sections = [
        {
            "id": "file",
            "title": "[1] File",
            "rows": [
                {"label": "JSON valid", "value": "PASS"},
                {
                    "label": "Dump version",
                    "value": report.dump_game or "unknown",
                    "detail": "适配层按 FM26/FM27 编写" if report.dump_game else "导出里没有 meta.game",
                },
                {"label": "Generated time", "value": report.dump_generated or "unknown"},
                {"label": "Scan id", "value": report.scan_id},
                {"label": "Game date", "value": payload["scan"]["game_date"] or "unknown"},
            ],
        },
        {
            "id": "dataset",
            "title": "[2] Dataset",
            "rows": [
                {"label": "Total players", "value": report.players_total},
                {"label": "Clubs", "value": report.clubs_converted},
                {"label": "Unique player IDs", "value": len(set(ids))},
                {"label": "Duplicate IDs", "value": len(duplicates), "detail": ", ".join(duplicates[:5])},
                {"label": "Skipped ghost rows", "value": report.players_skipped},
                {"label": "Converted players", "value": report.players_converted},
            ],
        },
        {
            "id": "coverage",
            "title": "[3] Field coverage",
            "rows": [
                {"label": _coverage_label(key), "value": _percent(value)} for key, value in coverage.items()
            ],
        },
        {
            "id": "identity",
            "title": "[4] Identity / 与现有数据的关系",
            "rows": [
                {"label": "已在存档中的球员", "value": known_counts["existing"]},
                {"label": "将新建的球员", "value": known_counts["new"]},
                {"label": "缺少稳定 ID 的行", "value": known_counts["no_id"]},
                {
                    "label": "我的俱乐部（meta.myClub）",
                    "value": report.user_club or "未识别",
                    "detail": None if report.user_club else "阵容/球探模块需要它来确定本队",
                },
            ],
        },
        {
            "id": "risks",
            "title": "[5] Risks",
            "rows": [
                {"label": "未知字段", "value": len(report.unknown_fields), "detail": ", ".join(report.unknown_fields[:8])},
                {"label": "版本兼容", "value": "PASS" if report.compatibility.get("supported") else "RISK"},
                {"label": "忽略字段数", "value": len(report.ignored_fields)},
                {"label": "导出缺少的数据", "value": ", ".join(report.absent_fields)},
            ],
        },
    ]
    verdict = _verdict(report, duplicates, coverage, report.user_club)
    return {
        "sections": sections,
        "verdict": verdict,
        "report": report.payload(),
        "counts": {"clubs": len(payload["clubs"]), "players": len(players)},
    }


def _coverage_label(key: str) -> str:
    return {
        "ca": "CA / PA",
        "pa": "PA",
        "market_value": "Value",
        "wage": "Wage",
        "contract_end": "Contract",
        "birth_date": "Birth date",
        "age": "Age",
        "height_cm": "Height",
        "foot": "Foot",
        "world_reputation": "World reputation",
        "listed": "Transfer status",
        "injury_proneness": "Injury proneness",
        "injured": "Current injury",
        "parent_club": "Ownership / parent club",
        "loan_club": "Loan status",
        "agreed_transfer": "Agreed transfer",
        "club": "Club",
    }.get(key, key)


def _percent(value: object) -> str:
    number = float(value) if isinstance(value, (int, float)) else 0.0
    return f"{round(number * 100)}%"


def _existing_instances(db: Session, save_id: int, ids: list[str]) -> dict[str, int]:
    """How many rows already exist for this save; lets the operator spot a wrong save before importing.

    A real dump carries tens of thousands of ids, so the lookup is chunked: SQLite refuses queries with more than a
    few tens of thousands of bound parameters.
    """
    unique = list(dict.fromkeys(uid for uid in ids if uid))
    if not unique:
        return {"existing": 0, "new": 0, "no_id": 0}
    existing = 0
    chunk_size = 500
    for start in range(0, len(unique), chunk_size):
        chunk = unique[start : start + chunk_size]
        found = db.scalar(
            select(func.count())
            .select_from(PlayerInstance)
            .where(
                PlayerInstance.fm_save_id == save_id,
                PlayerInstance.save_local_uid.in_(chunk),
            )
        )
        existing += int(found or 0)
    return {
        "existing": existing,
        "new": len(unique) - existing,
        "no_id": sum(1 for uid in ids if not uid),
    }

def _verdict(
    report: fmscout.AdapterReport,
    duplicates: list[str],
    coverage: dict[str, float],
    user_club: str | None,
) -> dict[str, object]:
    """Human-readable conclusion: what blocks the import, what merely needs review."""
    blockers: list[str] = []
    review: list[str] = []
    if not report.players_converted:
        blockers.append("没有任何球员被转换，检查 meta/players 结构")
    if duplicates:
        blockers.append(f"存在 {len(duplicates)} 个重复球员 ID，导入会按后一行为准")
    if not report.compatibility.get("supported"):
        review.append("版本不在已验证范围，字段可能已变化")
    if report.unknown_fields:
        review.append("上游出现适配层不认识的字段")
    if coverage.get("ca", 0) < 0.9:
        review.append("CA 覆盖率低于 90%，评分与估值会大量缺失")
    if coverage.get("wage", 0) < 0.5:
        review.append("工资覆盖率低于 50%，成本模型只能用假设值")
    if coverage.get("injured", 0) == 0:
        review.append("导出没有当前伤病状态，伤病相关结论只能标记为不可评估")
    if coverage.get("club", 1) < 0.5:
        review.append(
            f"俱乐部覆盖 {_percent(coverage.get('club', 0))}：阵容深度、位置短板与俱乐部画像会大量为空"
        )
    if not user_club:
        review.append("导出没有 meta.myClub，导入后阵容模块会提示缺少本队")
    status = "blocked" if blockers else ("review" if review else "pass")
    return {"status": status, "blockers": blockers, "review": review, "ready_to_import": not blockers}


@router.post("/imports/fmscout", status_code=201, summary="转换并导入 FMSuperScout 导出")
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
