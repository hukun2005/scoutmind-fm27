"""Read helpers for the V3.3.0 repair audit table."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import DataRepairAudit

DECISIONS = ("repaired", "quarantined")


def _audit_payload(row: DataRepairAudit) -> dict[str, Any]:
    return {
        "id": row.id,
        "save_id": row.fm_save_id,
        "job_id": row.import_job_id,
        "scan_id": row.scan_id,
        "entity": row.entity,
        "row": row.row_index,
        "rule": row.rule_id,
        "rule_version": row.rule_version,
        "level": row.level,
        "field": row.field,
        "before": row.before_json,
        "after": row.after_json,
        "reason": row.reason,
        "decision": row.decision,
        "result": row.result,
        "requires_review": row.requires_review,
        "executed_at": row.executed_at.isoformat() if row.executed_at else None,
    }


def list_repairs(
    session: Session,
    save_id: int,
    *,
    import_job_id: int | None = None,
    decision: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> dict[str, Any]:
    """Repairs of one save, optionally narrowed to one import batch or one decision."""
    query = select(DataRepairAudit).where(DataRepairAudit.fm_save_id == save_id)
    if import_job_id is not None:
        query = query.where(DataRepairAudit.import_job_id == import_job_id)
    if decision is not None:
        query = query.where(DataRepairAudit.decision == decision)
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    rows = list(
        session.scalars(
            query.order_by(DataRepairAudit.id.desc()).limit(limit).offset(offset)
        )
    )
    return {"items": [_audit_payload(row) for row in rows], "total": int(total or 0)}


def repair_summary(session: Session, save_id: int) -> dict[str, int]:
    """Cheap counts used by the data status panel."""
    rows = session.execute(
        select(DataRepairAudit.decision, func.count())
        .where(DataRepairAudit.fm_save_id == save_id)
        .group_by(DataRepairAudit.decision)
    ).all()
    counts = {decision: 0 for decision in DECISIONS}
    for decision, count in rows:
        counts[str(decision)] = int(count)
    pending = session.scalar(
        select(func.count())
        .select_from(DataRepairAudit)
        .where(
            DataRepairAudit.fm_save_id == save_id,
            DataRepairAudit.requires_review.is_(True),
            DataRepairAudit.decision == "quarantined",
        )
    )
    counts["pending_review"] = int(pending or 0)
    return counts
