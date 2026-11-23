"""SM-122：把 Unresolved 诊断导出成脱敏 JSON（本地文件，禁止自动上传）。

保留：对象数量、UID 状态、分类状态、导入状态、读取/导入错误码、匹配证据**类型**、测试结果。
默认去掉：真实姓名、完整生日、存档名称、存档 ID、文件路径、PID、内存地址与任何原始证据值。

用法::

    python scripts/export_unresolved_redacted.py \
        --database backend/scoutmind.db \
        --output artifacts/diagnostics/unresolved-redacted.json

``--include-names`` 仅在本地需要核对时使用；导出物仍不应提交到仓库或公开渠道。
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

# The script may be started from the repository root or from backend/; make the backend package importable.
_REPO_ROOT = Path(__file__).resolve().parents[1]
for _candidate in (_REPO_ROOT / "backend", _REPO_ROOT):
    if str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import (
    FmSave,
    ImportJob,
    ImportRow,
    UnresolvedPlayerAction,
    UnresolvedPlayerCandidate,
    UnresolvedPlayerObservation,
)

SCHEMA = "scoutmind.unresolved.redacted.v1"

#: Values that must never appear in the export.
UPLOAD_NOTE = "本地完整报告不得自动上传或提交"

_ADDRESS = re.compile(r"0x[0-9a-fA-F]{4,}")
_PID = re.compile(r"\bpid[=:\s]*\d+", re.IGNORECASE)
_WINDOWS_PATH = re.compile(r"[A-Za-z]:\\[^\s\"']+")
_POSIX_PATH = re.compile(r"/(?:home|Users|tmp|var)/[^\s\"']+")


def _scrub(text: str) -> str:
    """Remove host identifiers from any free-form string that reaches the export."""
    text = _ADDRESS.sub("[address]", text)
    text = _PID.sub("[pid]", text)
    text = _WINDOWS_PATH.sub("[path]", text)
    text = _POSIX_PATH.sub("[path]", text)
    return text


def _iso(value: datetime | date | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(microsecond=0).isoformat()
    return value.isoformat()


def _evidence_keys(raw: str | None) -> list[str]:
    """Evidence *types* only: the key names, never their values."""
    if not raw:
        return []
    try:
        document = json.loads(raw)
    except (TypeError, ValueError):
        return ["unparseable"]
    if not isinstance(document, dict):
        return [type(document).__name__]
    keys: set[str] = set()
    for key, value in document.items():
        keys.add(str(key))
        if isinstance(value, dict):
            keys.update(f"{key}.{inner}" for inner in value)
    return sorted(keys)


def _suggestion_types(raw: str | None) -> list[str]:
    """Classify stored match evidence without copying names or values."""
    if not raw:
        return []
    try:
        document = json.loads(raw)
    except (TypeError, ValueError):
        return ["unparseable"]
    types: set[str] = set()
    if isinstance(document, dict):
        suggestions = document.get("suggestions")
        if isinstance(suggestions, list):
            for item in suggestions:
                if isinstance(item, dict):
                    for reason in item.get("reasons", []) or []:
                        text = str(reason)
                        if "出生日期一致" in text:
                            types.add("birth_date_exact")
                        elif "出生日期相差" in text:
                            types.add("birth_date_near")
                        elif "姓名一致" in text:
                            types.add("name_exact")
                        elif "缺少出生日期" in text:
                            types.add("missing_birth_date")
                        else:
                            types.add("other")
    return sorted(types)


def _directory_kinds(paths: list[str | None]) -> int:
    return len({str(item) for item in paths if item})


def export_redacted(
    database_path: Path,
    output_path: Path,
    *,
    include_names: bool = False,
    save_ids: list[int] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Write the redacted export and return the same document.

    The source database is opened through a ``mode=ro`` SQLite URI and never migrated, repaired or written.
    """
    source = Path(database_path)
    if not source.exists():
        raise FileNotFoundError(f"数据库不存在：{source}")

    connection = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    engine = create_engine("sqlite://", creator=lambda: connection)
    factory = sessionmaker(bind=engine)
    session: Session = factory()
    try:
        document = _build_document(session, include_names=include_names, save_ids=save_ids, generated_at=generated_at)
    finally:
        session.close()
        engine.dispose()
        connection.close()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    return document


def _build_document(
    session: Session,
    *,
    include_names: bool,
    save_ids: list[int] | None,
    generated_at: datetime | None,
) -> dict[str, Any]:
    save_query = select(FmSave).order_by(FmSave.id)
    if save_ids:
        save_query = save_query.where(FmSave.id.in_(save_ids))
    saves = list(session.scalars(save_query))
    alias = {save.id: f"save-{index}" for index, save in enumerate(saves, start=1)}

    candidates = list(
        session.scalars(
            select(UnresolvedPlayerCandidate)
            .where(UnresolvedPlayerCandidate.fm_save_id.in_(list(alias) or [-1]))
            .order_by(UnresolvedPlayerCandidate.fm_save_id, UnresolvedPlayerCandidate.id)
        )
    )
    observations = list(
        session.scalars(
            select(UnresolvedPlayerObservation)
            .where(UnresolvedPlayerObservation.fm_save_id.in_(list(alias) or [-1]))
            .order_by(UnresolvedPlayerObservation.id)
        )
    )
    jobs = list(
        session.scalars(
            select(ImportJob).where(ImportJob.fm_save_id.in_(list(alias) or [-1])).order_by(ImportJob.id)
        )
    )
    actions = list(
        session.scalars(
            select(UnresolvedPlayerAction)
            .where(UnresolvedPlayerAction.fm_save_id.in_(list(alias) or [-1]))
            .order_by(UnresolvedPlayerAction.id)
        )
    )

    by_save: dict[int, dict[str, Any]] = {
        save_id: {
            "save_alias": name,
            "candidates": 0,
            "observations": 0,
            "by_status": {},
            "by_uid_status": {},
            "actions": 0,
            "imports": 0,
        }
        for save_id, name in alias.items()
    }
    by_status: dict[str, int] = {}
    by_uid: dict[str, int] = {}
    for candidate in candidates:
        entry = by_save[candidate.fm_save_id]
        entry["candidates"] += 1
        by_status[candidate.status] = by_status.get(candidate.status, 0) + 1
        by_uid[candidate.uid_status] = by_uid.get(candidate.uid_status, 0) + 1
        entry["by_status"][candidate.status] = entry["by_status"].get(candidate.status, 0) + 1
        entry["by_uid_status"][candidate.uid_status] = entry["by_uid_status"].get(candidate.uid_status, 0) + 1
    for observation in observations:
        by_save[observation.fm_save_id]["observations"] += 1
    for action in actions:
        by_save[action.fm_save_id]["actions"] += 1
    for job in jobs:
        by_save[job.fm_save_id]["imports"] += 1

    candidate_rows = [
        {
            "candidate_alias": f"candidate-{candidate.id}",
            "save_alias": alias.get(candidate.fm_save_id, "save-unknown"),
            "status": candidate.status,
            "identity": {
                "uid_status": candidate.uid_status,
                "reason": candidate.uid_reason,
                "source_identity_kind": candidate.source_identity_kind,
            },
            "display_name": candidate.display_name if include_names else "[name withheld]",
            "birth_year": candidate.birth_date.year if candidate.birth_date else None,
            "nationality": candidate.nationality,
            "position": candidate.position,
            "observation_count": candidate.observation_count,
            "latest_ca": candidate.latest_ca,
            "latest_pa": candidate.latest_pa,
            "first_seen_at": _iso(candidate.first_seen_at),
            "last_seen_at": _iso(candidate.last_seen_at),
            "resolved": candidate.status == "resolved",
            "resolution_method": candidate.resolution_method,
            "evidence_types": _evidence_keys(candidate.evidence_summary_json),
            "suggestion_types": _suggestion_types(candidate.evidence_summary_json),
        }
        for candidate in candidates
    ]

    observation_rows = [
        {
            "observation_alias": f"observation-{observation.id}",
            "candidate_alias": f"candidate-{observation.candidate_id}",
            "scan_id": _scrub(observation.scan_id),
            "row_index": observation.row_index,
            "uid_status": observation.uid_status,
            "observed_at": _iso(observation.observed_at),
            "game_date": _iso(observation.game_date),
            "has_club": bool(observation.club_name),
            "has_contract_end": observation.contract_end is not None,
            "ca": observation.ca,
            "pa": observation.pa,
            "evidence_types": _evidence_keys(observation.raw_evidence_json),
        }
        for observation in observations
    ]

    rejected_by_job: dict[int, list[str]] = {}
    warnings_by_job: dict[int, list[str]] = {}
    if jobs:
        rows = session.execute(
            select(ImportRow.import_job_id, ImportRow.code).where(
                ImportRow.import_job_id.in_([job.id for job in jobs]),
                ImportRow.entity != "scan",
            )
        ).all()
        for job_id, code in rows:
            rejected_by_job.setdefault(job_id, []).append(str(code))
        for job in jobs:
            warnings_by_job[job.id] = [str(item) for item in _json_list(job.warnings_json)]

    import_rows = [
        {
            "job_alias": f"import-{job.id}",
            "save_alias": alias.get(job.fm_save_id, "save-unknown"),
            "status": job.status,
            "source": job.source,
            "schema_version": job.schema_version,
            "player_count": job.player_count,
            "transfer_count": job.transfer_count,
            "warning_count": len(warnings_by_job.get(job.id, [])),
            "warning_kinds": _warning_kinds(warnings_by_job.get(job.id, [])),
            "rejected_row_count": len(rejected_by_job.get(job.id, [])),
            "rejected_codes": sorted(set(rejected_by_job.get(job.id, []))),
        }
        for job in jobs
    ]

    action_rows = [
        {
            "action_alias": f"action-{action.id}",
            "candidate_alias": f"candidate-{action.candidate_id}",
            "action": action.action,
            "decision": action.decision,
            "previous_status": action.previous_status,
            "new_status": action.new_status,
            "created_at": _iso(action.created_at),
        }
        for action in actions
    ]

    duplicate_scans = {}
    for observation in observations:
        key = (observation.fm_save_id, observation.scan_id, observation.row_index)
        duplicate_scans[key] = duplicate_scans.get(key, 0) + 1
    duplicates = sum(1 for count in duplicate_scans.values() if count > 1)

    return {
        "schema": SCHEMA,
        "generated_at": (generated_at or datetime.now()).replace(microsecond=0).isoformat(),
        "source": {
            "database": "[redacted-path]",
            "opened_read_only": True,
            "saves_exported": len(saves),
            "note": UPLOAD_NOTE,
        },
        "totals": {
            "candidates": len(candidates),
            "observations": len(observations),
            "imports": len(jobs),
            "actions": len(actions),
            "duplicate_observations": duplicates,
            "by_status": by_status,
            "by_uid_status": by_uid,
        },
        "saves": [by_save[save.id] for save in saves],
        "candidates": candidate_rows,
        "observations": observation_rows,
        "imports": import_rows,
        "actions": action_rows,
    }


def _json_list(raw: str | None) -> list[Any]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) else []


#: Coarse warning categories. Free-form warning text can contain names or ids, so only the kind is exported.
_WARNING_KINDS = (
    ("unresolved", ("unresolved", "无 UID", "无身份", "哨兵")),
    ("identity", ("UID", "出生日期", "姓名")),
    ("unknown_attribute", ("未知属性",)),
    ("coverage_gap", ("转会", "租借", "梯队", "parentClub", "所有权")),
    ("import_failure", ("导入失败",)),
)


def _warning_kinds(warnings: list[str]) -> dict[str, int]:
    """Count warnings by category without copying their text."""
    counts: dict[str, int] = {}
    for warning in warnings:
        kind = "other"
        for name, markers in _WARNING_KINDS:
            if any(marker in warning for marker in markers):
                kind = name
                break
        counts[kind] = counts.get(kind, 0) + 1
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="导出脱敏的 Unresolved 诊断 JSON")
    parser.add_argument("--database", type=Path, default=Path("backend/scoutmind.db"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/diagnostics/unresolved-redacted.json"),
    )
    parser.add_argument("--include-names", action="store_true", help="本地核对用：保留真实姓名")
    parser.add_argument("--save-id", type=int, action="append", dest="save_ids")
    args = parser.parse_args(argv)

    document = export_redacted(
        args.database,
        args.output,
        include_names=args.include_names,
        save_ids=args.save_ids,
    )
    totals = document["totals"]
    print(f"已写入 {args.output}")
    print(
        "候选 {candidates} · 观察 {observations} · 导入 {imports} · UID 状态 {by_uid_status}".format(**totals)
    )
    print(f"姓名：{'保留（--include-names）' if args.include_names else '已脱敏'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
