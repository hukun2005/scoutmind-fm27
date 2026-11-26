"""Automatic Data Import Engine (V3.3.0).

One entry point that turns any supported payload into an atomic, idempotent, audited import:

    detect → parse → Level 1 repair → Level 2 repair → dedupe → validate → import → verify → audit

The actual database write stays in :class:`app.ingestion.importer.ScanImporter`; this engine only prepares the
document, filters unsafe rows and appends repair audits inside the same transaction.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..ingestion.adapters import fmscout
from ..ingestion.importer import ImportOutcome, ScanImporter
from ..ingestion.protocol import ProtocolError, ScanPayload
from ..models import ImportJob, PlayerInstance, PlayerSnapshot, Transfer
from ..services.write_safety import WriteFence
from .detection import Detection, DetectionError, decode_text, detect_payload
from .repair import Repair, dedupe_document, normalize_document, record_summary, resolve_level2
from .validation import Rejection, validate_header, validate_rows

STAGE_LABELS = (
    ("detect", "正在识别数据"),
    ("check", "正在检查数据"),
    ("match", "正在匹配球员和俱乐部"),
    ("repair", "正在自动修复"),
    ("import", "正在导入数据库"),
    ("verify", "正在验证导入结果"),
)


@dataclass
class EngineReport:
    """Everything the API layer needs to build the user-facing result."""

    status: str
    detection: Detection
    stages: list[dict[str, Any]] = field(default_factory=list)
    repairs: list[Repair] = field(default_factory=list)
    rejections: list[Rejection] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    outcome: ImportOutcome | None = None
    verification: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    adapted_by: dict[str, Any] | None = None
    dry_run: bool = False

    def payload(self) -> dict[str, Any]:
        import_block: dict[str, Any] = {"dry_run": self.dry_run}
        if self.outcome is not None:
            import_block.update(
                {
                    "job_id": self.outcome.job_id,
                    "save_id": self.outcome.save_id,
                    "scan_id": self.outcome.scan_id,
                    "duplicate": self.outcome.duplicate,
                    "status": self.outcome.status,
                }
            )
        body: dict[str, Any] = {
            "status": self.status,
            "stages": self.stages,
            "detection": self.detection.payload(),
            "counts": self.counts,
            "import": import_block,
            "verification": self.verification,
            "warnings": self.warnings,
            "repairs": [repair.payload() for repair in self.repairs[:50]],
            "repairs_total": len(self.repairs),
            "quarantine": [
                {
                    "row": rejection.row_index,
                    "entity": rejection.entity,
                    "code": rejection.code,
                    "message": rejection.message,
                }
                for rejection in self.rejections[:50]
            ],
            "quarantine_total": len(self.rejections),
        }
        if self.adapted_by is not None:
            body["adapted_by"] = self.adapted_by
        return body


def parse_document(raw: bytes, detection: Detection) -> tuple[dict[str, Any], list[str], dict[str, Any] | None]:
    """Turn bytes into a scan document using the parser selected by detection."""
    if detection.source == "fmscout_dump":
        payload, report = fmscout.convert_dump(raw)
        return payload, [], report.payload()

    text, _, _ = decode_text(raw)
    stripped = text.strip()
    if detection.source == "scan_json":
        return json.loads(stripped), [], None
    if detection.source == "scan_ndjson":
        return _document_from_ndjson(text)
    raise ProtocolError(f"不支持的来源：{detection.source}")


def _document_from_ndjson(text: str) -> tuple[dict[str, Any], list[str], None]:
    """Header line + one JSON object per entity, matching ``protocol.parse_payload`` semantics."""
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise ProtocolError("NDJSON 扫描文件为空")
    try:
        header = json.loads(lines[0])
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"无法解析 NDJSON 首行：{exc.msg}") from exc
    if not isinstance(header, dict):
        raise ProtocolError("NDJSON 首行必须是 header 对象")
    players: list[dict[str, Any]] = []
    transfers: list[dict[str, Any]] = []
    clubs: list[dict[str, Any]] = []
    warnings: list[str] = []
    for index, line in enumerate(lines[1:], start=1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            warnings.append(f"第 {index + 1} 行不是合法 JSON，已跳过：{exc.msg}")
            continue
        if not isinstance(row, dict):
            warnings.append(f"第 {index + 1} 行不是对象，已跳过")
            continue
        entity = row.get("entity")
        body = {key: value for key, value in row.items() if key != "entity"}
        if entity == "player":
            players.append(body)
        elif entity == "transfer":
            transfers.append(body)
        elif entity == "club":
            clubs.append(body)
        else:
            warnings.append(f"第 {index + 1} 行实体类型未知（{entity!r}），已跳过")
    document = dict(header)
    document["players"] = players
    document["transfers"] = transfers
    document["clubs"] = clubs
    document.setdefault("warnings", [])
    if isinstance(document["warnings"], list):
        document["warnings"] = list(document["warnings"]) + warnings
    return document, warnings, None


def _stages(
    *,
    detection: Detection,
    rejections: int,
    repairs: int,
    imported: bool,
    verification_status: str | None,
) -> list[dict[str, Any]]:
    statuses = {
        "detect": "pass" if detection.compatible else "blocked",
        "check": "warn" if rejections else "pass",
        "match": "pass",
        "repair": "warn" if repairs else "pass",
        "import": "pass" if imported else "skipped",
        "verify": verification_status or "skipped",
    }
    return [
        {"id": stage_id, "label": label, "status": statuses[stage_id]}
        for stage_id, label in STAGE_LABELS
    ]


def verify_import(session: Session, outcome: ImportOutcome, save_id: int) -> dict[str, Any]:
    """Post-import checks that do not trust the HTTP 200 alone.

    Every query is save-scoped; a cross-save row is an error, not a warning.
    """
    checks: list[dict[str, Any]] = []

    def check(check_id: str, ok_status: str, detail: str) -> str:
        checks.append({"id": check_id, "status": ok_status, "detail": detail})
        return ok_status

    job = session.get(ImportJob, outcome.job_id)
    job_status = check(
        "job_status",
        "pass" if job is not None and job.status in {"succeeded", "partial"} else "error",
        f"任务状态 {job.status if job is not None else 'missing'}",
    )
    save_status = check(
        "save_isolation",
        "pass" if job is not None and job.fm_save_id == save_id else "error",
        f"任务存档 {job.fm_save_id if job is not None else 'missing'} / 目标存档 {save_id}",
    )

    snapshots = int(
        session.scalar(
            select(func.count()).select_from(PlayerSnapshot).where(PlayerSnapshot.import_job_id == outcome.job_id)
        )
        or 0
    )
    snapshot_status = check(
        "snapshots_written",
        "pass" if snapshots >= outcome.snapshots_created else "warn",
        f"批次快照 {snapshots}（新建 {outcome.snapshots_created}）",
    )

    orphan_snapshots = int(
        session.scalar(
            select(func.count())
            .select_from(PlayerSnapshot)
            .join(PlayerInstance, PlayerInstance.id == PlayerSnapshot.player_instance_id)
            .where(
                PlayerSnapshot.import_job_id == outcome.job_id,
                PlayerInstance.fm_save_id != save_id,
            )
        )
        or 0
    )
    orphan_status = check(
        "snapshot_ownership",
        "pass" if orphan_snapshots == 0 else "error",
        f"跨存档快照 {orphan_snapshots}",
    )

    foreign_transfers = int(
        session.scalar(
            select(func.count())
            .select_from(Transfer)
            .where(Transfer.import_job_id == outcome.job_id, Transfer.fm_save_id != save_id)
        )
        or 0
    )
    transfer_status = check(
        "transfer_ownership",
        "pass" if foreign_transfers == 0 else "error",
        f"跨存档转会 {foreign_transfers}",
    )

    checks_status = [job_status, save_status, snapshot_status, orphan_status, transfer_status]
    if "error" in checks_status:
        overall = "FAIL"
    elif "warn" in checks_status:
        overall = "PARTIAL"
    else:
        overall = "PASS"
    return {
        "status": overall,
        "checks": checks,
        "snapshots_linked": snapshots,
        "transfers_linked": int(
            session.scalar(
                select(func.count()).select_from(Transfer).where(Transfer.import_job_id == outcome.job_id)
            )
            or 0
        ),
    }


class AutomaticDataImportEngine:
    """The single import path used by ``POST /api/v1/data-hub/import``."""

    def __init__(self, session: Session, raw_dir: Path | None = None) -> None:
        self.session = session
        self.raw_dir = raw_dir or settings.raw_import_dir

    def run(
        self,
        save_id: int,
        raw: bytes,
        *,
        identity_id: int | None = None,
        session_id: int | None = None,
        fence: WriteFence | None = None,
        operation_id: str | None = None,
        dry_run: bool = False,
        filename: str | None = None,
    ) -> EngineReport:
        """Full pipeline; raises ``DetectionError`` / ``ProtocolError`` for unusable payloads."""
        detection = detect_payload(raw, filename=filename)
        if not detection.compatible:
            return EngineReport(
                status="BLOCKED",
                detection=detection,
                stages=_stages(detection=detection, rejections=0, repairs=0, imported=False,
                               verification_status=None),
                counts={"created": 0, "updated": 0, "duplicates": 0, "repaired": 0, "quarantined": 0, "rejected": 0},
                warnings=[detection.message] if detection.message else [],
            )

        document, parse_warnings, adapted_by = parse_document(raw, detection)
        document, l1_repairs = normalize_document(document)
        document, l2_repairs = resolve_level2(self.session, save_id, document)
        document, duplicate_repairs, duplicates_removed = dedupe_document(document)

        payload, _header_code, header_message = validate_header(document)
        if payload is None:
            return EngineReport(
                status="BLOCKED",
                detection=detection,
                stages=_stages(detection=detection, rejections=0, repairs=0, imported=False,
                               verification_status=None),
                counts={"created": 0, "updated": 0, "duplicates": 0, "repaired": 0, "quarantined": 0, "rejected": 0},
                warnings=[header_message or "扫描报文无法解析"],
            )

        filtered, rejections = validate_rows(document)
        cleaned = ScanPayload.model_validate(filtered)
        repairs = list(l1_repairs) + list(l2_repairs) + list(duplicate_repairs)
        counts = {
            "created": 0,
            "updated": 0,
            "duplicates": duplicates_removed,
            "repaired": len(repairs),
            "quarantined": len(rejections),
            "rejected": 0,
            **record_summary(filtered),
        }
        report = EngineReport(
            status="PARTIAL" if rejections else "PASS",
            detection=detection,
            repairs=repairs,
            rejections=rejections,
            counts=counts,
            warnings=list(parse_warnings) + list(detection.warnings),
            adapted_by=adapted_by,
            dry_run=dry_run,
        )
        report.stages = _stages(
            detection=detection,
            rejections=len(rejections),
            repairs=len(repairs),
            imported=False,
            verification_status=None,
        )
        if dry_run:
            return report

        audit_specs: list[dict[str, object]] = []
        for repair in repairs:
            spec = repair.audit_spec()
            spec["source"] = detection.source
            audit_specs.append(spec)
        for rejection in rejections:
            spec = rejection.audit_spec()
            spec["source"] = detection.source
            audit_specs.append(spec)

        outcome = ScanImporter(self.session, raw_dir=self.raw_dir).import_payload(
            save_id,
            cleaned,
            raw,
            identity_id=identity_id,
            session_id=session_id,
            fence=fence,
            operation_id=operation_id,
            repair_audits=audit_specs,
        )
        report.outcome = outcome
        report.counts["created"] = outcome.players_created + outcome.transfers_created
        report.counts["updated"] = (
            outcome.players_updated + outcome.transfers_updated + outcome.loans_updated
            + outcome.statistics_updated
        )
        report.counts["rejected"] = outcome.rows_rejected
        verification = verify_import(self.session, outcome, save_id)
        report.verification = verification
        if outcome.duplicate:
            report.status = "PASS"
        elif outcome.status == "partial" or rejections or verification["status"] == "PARTIAL":
            report.status = "PARTIAL"
        elif verification["status"] == "FAIL":
            report.status = "PARTIAL"
        else:
            report.status = "PASS"
        report.stages = _stages(
            detection=detection,
            rejections=len(rejections),
            repairs=len(repairs),
            imported=True,
            verification_status=verification["status"].lower(),
        )
        return report


def run_dry_scan(session: Session, save_id: int, raw: bytes, *, filename: str | None = None) -> EngineReport:
    """Convenience wrapper for the read-only preview (no database write)."""
    return AutomaticDataImportEngine(session).run(save_id, raw, dry_run=True, filename=filename)
