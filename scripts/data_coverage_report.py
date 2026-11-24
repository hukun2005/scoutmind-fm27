"""三层数据覆盖率报告（SM-125）：Native Reader 探测 → 上游 dump → ScoutMind 导入。

只输出计数与差异原因，不写球员姓名、内存地址、PID 或存档路径；这些敏感信息只留在本地原始文件里。

用法::

    python scripts/data_coverage_report.py \
        --probe artifacts/diagnostics/probe-report.json \
        --dump  C:/Users/.../dump.json \
        --scan  C:/Users/.../scan-fmreader-xxxx.json \
        --database backend/data/scoutmind.db --scan-id fmreader-xxxx \
        --output-json docs/evidence/data-coverage-report.json \
        --output-md   docs/evidence/data-coverage-report.md
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
for _candidate in (_ROOT / "backend", _ROOT):
    if str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

_ADDRESS = re.compile(r"0x[0-9a-fA-F]{4,}")
_PID = re.compile(r"\bpid[=:\s]*\d+", re.IGNORECASE)


def _scrub(text: str) -> str:
    """Remove host identifiers from the few free-form strings that reach the report."""
    text = _ADDRESS.sub("[address]", text)
    return _PID.sub("[pid]", text)


@dataclass
class StageCounts:
    """One layer's counts; every value comes from that layer's own artifact."""

    name: str
    source: str
    total: int | None = None
    valid: int | None = None
    sentinel: int | None = None
    zero: int | None = None
    unreadable: int | None = None
    duplicates: int | None = None
    imported: int | None = None
    rejected: int | None = None
    skipped: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "layer": self.name,
            "source": self.source,
            "total": self.total,
            "valid": self.valid,
            "sentinel": self.sentinel,
            "zero": self.zero,
            "unreadable": self.unreadable,
            "duplicates": self.duplicates,
            "imported": self.imported,
            "rejected": self.rejected,
            "skipped": self.skipped,
            **self.extra,
        }


def read_probe(path: Path) -> StageCounts:
    """Native Reader probe report (`probe --report`)."""
    document = json.loads(path.read_text(encoding="utf-8"))
    summary = document.get("uid_diagnostics") or {}
    return StageCounts(
        name="native_reader",
        source=path.name,
        total=summary.get("totalObjects"),
        valid=summary.get("validUids"),
        sentinel=summary.get("sentinelUids"),
        zero=summary.get("zeroUids"),
        unreadable=summary.get("unreadableUids"),
        duplicates=summary.get("duplicateAddresses"),
        extra={
            "unique_objects": summary.get("uniqueObjects"),
            "duplicate_valid_uids": summary.get("duplicateValidUids"),
            "free_agent_candidates": summary.get("freeAgentCandidates"),
            "probe_passed": (document.get("probe") or {}).get("passed"),
            "scan_readiness": document.get("scan_readiness"),
        },
    )


def read_dump(path: Path) -> StageCounts:
    """Upstream FMSuperScout dump: only ids are inspected, names are never read."""
    document = json.loads(path.read_text(encoding="utf-8"))
    players = document.get("players") or []
    sentinel = 0
    zero = 0
    missing = 0
    seen: set[int] = set()
    duplicates = 0
    for row in players:
        raw = row.get("id") if isinstance(row, dict) else None
        if raw is None:
            missing += 1
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError):
            zero += 1
            continue
        if value == 4294967295 or value == -1:
            sentinel += 1
        elif value == 0:
            zero += 1
        else:
            if value in seen:
                duplicates += 1
            seen.add(value)
    return StageCounts(
        name="upstream_dump",
        source=path.name,
        total=len(players),
        valid=len(seen),
        sentinel=sentinel,
        zero=zero,
        unreadable=missing,
        duplicates=duplicates,
        extra={"distinct_valid_uids": len(seen), "file_bytes": path.stat().st_size},
    )


def read_scan(path: Path) -> StageCounts:
    """Reader scan payload in protocol form; only identity counts and warnings are used."""
    document = json.loads(path.read_text(encoding="utf-8"))
    players = document.get("players") or []
    valid = 0
    unresolved = 0
    sentinel = 0
    zero = 0
    for row in players:
        if not isinstance(row, dict):
            continue
        identity = row.get("identity") or {}
        if row.get("save_local_uid"):
            valid += 1
        elif identity.get("kind") == "unresolved":
            unresolved += 1
            if identity.get("uid_status") == "sentinel":
                sentinel += 1
            elif identity.get("uid_status") == "invalid":
                zero += 1
    return StageCounts(
        name="scan_payload",
        source=path.name,
        total=len(players),
        valid=valid,
        sentinel=sentinel,
        zero=zero,
        imported=unresolved,
        extra={
            "unresolved_rows": unresolved,
            "schema_version": document.get("schema_version") or document.get("schemaVersion"),
            "warnings": len(document.get("warnings") or []),
        },
    )


def read_database(path: Path, scan_id: str) -> StageCounts:
    """Importer result for one scan, read through a read-only SQLite handle."""
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        def scalar(sql: str, params: tuple = ()) -> int:
            row = connection.execute(sql, params).fetchone()
            return int(row[0]) if row and row[0] is not None else 0

        job = connection.execute(
            "select id, status from import_jobs where scan_id = ? order by id desc limit 1", (scan_id,)
        ).fetchone()
        job_id = job[0] if job else None
        status = job[1] if job else None
        rejected = 0
        if job_id is not None:
            rejected = scalar(
                "select count(*) from import_rows where import_job_id = ? and entity != 'scan'", (job_id,)
            )
        unresolved_candidates = scalar(
            "select count(distinct candidate_id) from unresolved_player_observations where scan_id = ?", (scan_id,)
        )
        unresolved_observations = scalar(
            "select count(*) from unresolved_player_observations where scan_id = ?", (scan_id,)
        )
        snapshots = 0
        if job_id is not None:
            snapshots = scalar("select count(*) from player_snapshots where import_job_id = ?", (job_id,))
        return StageCounts(
            name="importer",
            source=f"sqlite:{path.name}",
            total=snapshots + unresolved_observations,
            valid=snapshots,
            imported=unresolved_observations,
            rejected=rejected,
            extra={
                "import_job_id": job_id,
                "import_status": status,
                "unresolved_candidates": unresolved_candidates,
                "unresolved_observations": unresolved_observations,
                "snapshots": snapshots,
                "canonical_rows": scalar(
                    "select count(*) from player_observation_canonicals"
                ),
            },
        )
    finally:
        connection.close()


def compare(readers: StageCounts | None, dump: StageCounts | None, scan: StageCounts | None, importer: StageCounts | None) -> list[dict[str, Any]]:
    """Differences between adjacent layers, each with an explicit reason rather than a silent drop."""
    differences: list[dict[str, Any]] = []
    if readers and dump and readers.total is not None:
        delta = (readers.total or 0) - (dump.total or 0)
        differences.append(
            {
                "from": "native_reader",
                "to": "upstream_dump",
                "reader_objects": readers.total,
                "dump_players": dump.total,
                "delta": delta,
                "reason": "upstream_not_exported" if delta > 0 else ("dump_added_rows" if delta < 0 else "match"),
                "note": "上游只导出已识别的球员对象；差值不是本阶段可以补齐的数据",
            }
        )
    if dump and scan:
        delta = (dump.total or 0) - (scan.total or 0)
        differences.append(
            {
                "from": "upstream_dump",
                "to": "scan_payload",
                "dump_players": dump.total,
                "scan_players": scan.total,
                "delta": delta,
                "reason": "mapping_dropped_rows" if delta != 0 else "match",
                "note": "mapper 只为没有姓名的行丢弃记录；差值应为 0",
            }
        )
    if scan and importer:
        delta = (scan.total or 0) - ((importer.valid or 0) + (importer.imported or 0))
        differences.append(
            {
                "from": "scan_payload",
                "to": "importer",
                "scan_players": scan.total,
                "imported_players": importer.valid,
                "unresolved_observations": importer.imported,
                "rejected_rows": importer.rejected,
                "delta": delta,
                "reason": (
                    "rejected_rows"
                    if (importer.rejected or 0) > 0
                    else ("skipped_duplicates" if delta > 0 else "match")
                ),
            }
        )
    return differences


def build_report(
    *,
    probe_path: Path | None,
    dump_path: Path | None,
    scan_path: Path,
    database_path: Path | None,
    scan_id: str | None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Assemble the coverage report document without touching any source file."""
    layers: list[StageCounts] = []
    readers = read_probe(probe_path) if probe_path else None
    dump = read_dump(dump_path) if dump_path else None
    scan = read_scan(scan_path)
    importer = None
    effective_scan_id = scan_id or _scan_id_of(scan_path)
    if database_path is not None:
        importer = read_database(database_path, effective_scan_id)
    for layer in (readers, dump, scan, importer):
        if layer is not None:
            layers.append(layer)

    return {
        "schema": "scoutmind.data-coverage.v1",
        "generated_at": (generated_at or datetime.now()).replace(microsecond=0).isoformat(),
        "scan_id": effective_scan_id,
        "inputs": {
            "probe": None if probe_path is None else probe_path.name,
            "dump": None if dump_path is None else dump_path.name,
            "scan": scan_path.name,
            "database": None if database_path is None else database_path.name,
        },
        "layers": [layer.as_dict() for layer in layers],
        "differences": compare(readers, dump, scan, importer),
        "notes": [
            "所有数字来自对应层自己的产物；缺失的层不会被补 0，也不会被排除出分母",
            "差值必须由上游导出范围、映射规则或导入拒绝解释；不得为了对齐而删除记录",
            "报告只含计数与原因，姓名/地址/PID 不落盘",
        ],
    }


def _scan_id_of(path: Path) -> str:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    scan = document.get("scan") or {}
    return str(scan.get("scan_id") or scan.get("scanId") or "")


def render_markdown(report: dict[str, Any]) -> str:
    """Human-readable projection of the same numbers (no new facts)."""
    lines = [
        "# 数据覆盖率报告（SM-125）",
        "",
        f"- 生成时间：{report['generated_at']}",
        f"- scan_id：`{report['scan_id']}`",
        f"- 输入：{json.dumps(report['inputs'], ensure_ascii=False)}",
        "",
        "## 各层计数",
        "",
        "| 层 | 总数 | 合法 UID | 哨兵 | 非法/缺失 | 重复 | 导入 | 拒绝 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for layer in report["layers"]:
        lines.append(
            "| {layer} | {total} | {valid} | {sentinel} | {bad} | {dupes} | {imported} | {rejected} |".format(
                layer=layer["layer"],
                total=_dash(layer["total"]),
                valid=_dash(layer["valid"]),
                sentinel=_dash(layer["sentinel"]),
                bad=_dash(_sum_optional(layer["zero"], layer["unreadable"])),
                dupes=_dash(layer["duplicates"]),
                imported=_dash(layer["imported"]),
                rejected=_dash(layer["rejected"]),
            )
        )
    lines += ["", "## 层间差异", ""]
    if not report["differences"]:
        lines.append("没有可比较的相邻层。")
    for item in report["differences"]:
        lines.append(
            f"- `{item['from']} → {item['to']}`：差值 {item['delta']}，原因 `{item['reason']}`"
            + (f"（{_scrub(item['note'])}）" if item.get("note") else "")
        )
    lines += ["", "## 说明", ""]
    lines += [f"- {_scrub(note)}" for note in report["notes"]]
    return "\n".join(lines) + "\n"


def _dash(value: Any) -> str:
    return "—" if value is None else str(value)


def _sum_optional(*values: Any) -> int | None:
    present = [int(value) for value in values if isinstance(value, (int, float))]
    return sum(present) if present else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成三层数据覆盖率报告（脱敏）")
    parser.add_argument("--probe", type=Path)
    parser.add_argument("--dump", type=Path)
    parser.add_argument("--scan", type=Path, required=True)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--scan-id")
    parser.add_argument("--output-json", type=Path, default=Path("docs/evidence/data-coverage-report.json"))
    parser.add_argument("--output-md", type=Path, default=Path("docs/evidence/data-coverage-report.md"))
    args = parser.parse_args(argv)

    report = build_report(
        probe_path=args.probe,
        dump_path=args.dump,
        scan_path=args.scan,
        database_path=args.database,
        scan_id=args.scan_id,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text(render_markdown(report), encoding="utf-8")
    print(f"已写入 {args.output_json} 与 {args.output_md}")
    for layer in report["layers"]:
        print(f"  {layer['layer']}: total={layer['total']} valid={layer['valid']} sentinel={layer['sentinel']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
