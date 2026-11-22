"""Deterministic data-quality rule engine (V3.2 SM-066A).

Rules are read-only: they inspect existing snapshots/import jobs and return findings. They never
mutate raw observations and never infer missing values as zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ImportJob, PlayerInstance, PlayerSnapshot


@dataclass(frozen=True)
class RuleDefinition:
    """A rule shown in the catalog and used by the report."""

    rule_id: str
    title: str
    severity: str
    category: str
    description: str
    remediation: str


RULES: tuple[RuleDefinition, ...] = (
    RuleDefinition("missing_ca", "CA 缺失", "warning", "coverage", "快照没有 CA，成长/评分不可用", "重新扫描或补充数据源；缺失保持 NULL，不填 0"),
    RuleDefinition("missing_pa", "PA 缺失", "warning", "coverage", "快照没有 PA，潜力实现不可用", "重新扫描或补充数据源；缺失保持 NULL"),
    RuleDefinition("missing_contract", "合同到期缺失", "warning", "coverage", "合同到期为空，无法判断合同风险", "从合同页或可靠导出补充"),
    RuleDefinition("missing_market_value", "身价缺失", "info", "coverage", "身价为空，估值/净支出分析受限", "补充身价来源"),
    RuleDefinition("missing_wage", "工资缺失", "info", "coverage", "工资为空，工资占比分析受限", "补充工资来源"),
    RuleDefinition("same_day_conflict", "同日快照冲突", "error", "consistency", "同一球员同一 game_date 的 CA/PA/工资/身价/合同不一致", "保留全部原始快照；人工确认 canonical，不删除历史"),
    RuleDefinition("duplicate_same_day", "同日重复扫描", "warning", "duplication", "同一球员同一 game_date 有多条快照", "按 game_date 折叠为独立观测；原始快照保留"),
    RuleDefinition("negative_value", "负值异常", "error", "validity", "CA/PA/身价/工资出现负值", "检查读取偏移/对象类型；不得改偏移掩盖"),
    RuleDefinition("stale_observation", "观测时间与游戏日期偏差", "warning", "timeliness", "现实观测日期比 game_date 晚超过 30 天", "确认存档时间与扫描时间"),
    RuleDefinition("import_count_mismatch", "导入批次计数不一致", "warning", "lineage", "ImportJob.player_count 与批次实际实例数不一致", "检查导入器计数口径与 warnings"),
    RuleDefinition("unknown_source", "来源未知", "info", "lineage", "快照没有可追溯的 ImportJob/source", "补齐来源或重新导入"),
    RuleDefinition("empty_save", "存档没有快照", "info", "coverage", "该存档没有任何球员快照", "先导入一次真实扫描"),
)

RULE_BY_ID = {rule.rule_id: rule for rule in RULES}
STALE_DAYS = 30


def rule_catalog() -> list[dict[str, str]]:
    """Return the rule catalog as serializable dictionaries."""
    return [rule.__dict__.copy() for rule in RULES]


def _finding(rule_id: str, count: int, message: str, *, players: int = 0,
             samples: Iterable[int] = ()) -> dict[str, Any]:
    rule = RULE_BY_ID[rule_id]
    return {
        "rule_id": rule.rule_id,
        "title": rule.title,
        "severity": rule.severity,
        "category": rule.category,
        "count": count,
        "affected_player_count": players,
        "message": message,
        "sample_snapshot_ids": list(samples)[:10],
        "remediation": rule.remediation,
    }


def run_quality_rules(
    session: Session,
    save_id: int,
    *,
    import_job_id: int | None = None,
) -> dict[str, Any]:
    """Evaluate all rules for one save (optionally one import job); read-only."""
    query = (
        select(PlayerSnapshot, PlayerInstance.id, ImportJob.source)
        .join(PlayerInstance, PlayerInstance.id == PlayerSnapshot.player_instance_id)
        .outerjoin(ImportJob, ImportJob.id == PlayerSnapshot.import_job_id)
        .where(PlayerInstance.fm_save_id == save_id)
        .order_by(PlayerSnapshot.observed_at, PlayerSnapshot.id)
    )
    if import_job_id is not None:
        query = query.where(PlayerSnapshot.import_job_id == import_job_id)
    rows = list(session.execute(query))
    findings: list[dict[str, Any]] = []
    if not rows:
        findings.append(_finding("empty_save", 0, "该存档没有可检查的快照"))
        return _envelope(save_id, import_job_id, findings, rows)

    snapshots = [row[0] for row in rows]
    total = len(snapshots)
    missing = {
        "missing_ca": sum(1 for snapshot in snapshots if snapshot.ca is None),
        "missing_pa": sum(1 for snapshot in snapshots if snapshot.pa is None),
        "missing_contract": sum(1 for snapshot in snapshots if snapshot.contract_end is None),
        "missing_market_value": sum(1 for snapshot in snapshots if snapshot.market_value is None),
        "missing_wage": sum(1 for snapshot in snapshots if snapshot.wage is None),
    }
    for rule_id, count in missing.items():
        if count:
            findings.append(_finding(rule_id, count, f"{count}/{total} 条快照缺少该字段"))

    negative = [
        snapshot for snapshot in snapshots
        if any(value is not None and value < 0 for value in (snapshot.ca, snapshot.pa, snapshot.market_value, snapshot.wage))
    ]
    if negative:
        findings.append(_finding("negative_value", len(negative), f"{len(negative)} 条快照含负值", samples=[item.id for item in negative]))

    stale = [
        snapshot for snapshot in snapshots
        if snapshot.game_date is not None
        and (snapshot.observed_at.date() - snapshot.game_date) > timedelta(days=STALE_DAYS)
    ]
    if stale:
        findings.append(_finding("stale_observation", len(stale), f"{len(stale)} 条快照的观测日期比 game_date 晚超过 {STALE_DAYS} 天", samples=[item.id for item in stale]))

    unknown_sources = [snapshot for snapshot, _, source in rows if not source or source == "unknown"]
    if unknown_sources:
        findings.append(_finding("unknown_source", len(unknown_sources), f"{len(unknown_sources)} 条快照没有可追溯来源", samples=[item.id for item in unknown_sources]))

    by_day: dict[tuple[int, date], list[PlayerSnapshot]] = {}
    for snapshot, instance_id, _ in rows:
        game_date = snapshot.game_date or snapshot.observed_at.date()
        by_day.setdefault((instance_id, game_date), []).append(snapshot)
    duplicates = {key: values for key, values in by_day.items() if len(values) > 1}
    if duplicates:
        duplicate_rows = sum(len(values) - 1 for values in duplicates.values())
        findings.append(_finding(
            "duplicate_same_day", duplicate_rows,
            f"{len(duplicates)} 个球员-日期组存在重复扫描（{duplicate_rows} 条重复行）",
            players=len({key[0] for key in duplicates}),
            samples=[snapshot.id for values in duplicates.values() for snapshot in values[1:]],
        ))

    conflicts = []
    for values in duplicates.values():
        signatures = {
            (snapshot.ca, snapshot.pa, snapshot.wage, snapshot.market_value, snapshot.contract_end)
            for snapshot in values
        }
        if len(signatures) > 1:
            conflicts.append(values)
    if conflicts:
        findings.append(_finding(
            "same_day_conflict", len(conflicts),
            f"{len(conflicts)} 个球员-日期组同日内容不一致",
            players=len({values[0].player_instance_id for values in conflicts}),
            samples=[snapshot.id for values in conflicts for snapshot in values],
        ))

    if import_job_id is not None:
        job = session.get(ImportJob, import_job_id)
        actual = len({row[1] for row in rows})
        if job is not None and job.player_count != actual:
            findings.append(_finding(
                "import_count_mismatch", abs(job.player_count - actual),
                f"player_count={job.player_count}，实际实例数={actual}",
            ))

    return _envelope(save_id, import_job_id, findings, rows)


def _envelope(save_id: int, import_job_id: int | None, findings: list[dict[str, Any]], rows: list) -> dict[str, Any]:
    severity_counts = {"error": 0, "warning": 0, "info": 0}
    for finding in findings:
        severity_counts[finding["severity"]] = severity_counts.get(finding["severity"], 0) + 1
    ordered = sorted(
        findings,
        key=lambda item: ({"error": 0, "warning": 1, "info": 2}.get(item["severity"], 3), item["rule_id"]),
    )
    return {
        "save_id": save_id,
        "import_job_id": import_job_id,
        "checked_snapshot_count": len(rows),
        "severity_counts": severity_counts,
        "findings": ordered,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
    }
