"""SM-125：三层数据覆盖率报告的计数、差异原因与脱敏。"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.data_coverage_report import (  # noqa: E402
    build_report,
    read_dump,
    read_scan,
    render_markdown,
)

from tests.helpers import import_document, player_row, scan_document  # noqa: E402
from tests.test_unresolved_persistence import unresolved_row  # noqa: E402


def _write(path: Path, document: dict) -> Path:
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return path


def _dump(rows: list[dict]) -> dict:
    return {"meta": {"schema": "fmsuperscout-dump"}, "players": rows}


def test_dump_and_scan_counts_split_sentinel_rows(tmp_path: Path) -> None:
    dump = _write(
        tmp_path / "dump.json",
        _dump(
            [
                {"id": 101, "name": "A"},
                {"id": 4294967295, "name": "B"},
                {"id": 0, "name": "C"},
                {"id": 101, "name": "A again"},
                {"name": "D"},
            ]
        ),
    )
    scan = _write(
        tmp_path / "scan.json",
        {
            "schema_version": "1.1",
            "scan": {"scan_id": "scan-cov-1"},
            "players": [
                {"save_local_uid": "101", "name": "A", "identity": {"kind": "save_local_uid"}},
                {"name": "B", "identity": {"kind": "unresolved", "uid_status": "sentinel", "raw_uid": "4294967295"}},
                {"name": "C", "identity": {"kind": "unresolved", "uid_status": "invalid", "raw_uid": "0"}},
                {"name": "D", "identity": {"kind": "unresolved", "uid_status": "missing"}},
            ],
            "warnings": ["demo"],
        },
    )

    dump_counts = read_dump(dump)
    assert dump_counts.total == 5
    assert dump_counts.valid == 1
    assert dump_counts.sentinel == 1
    assert dump_counts.zero == 1
    assert dump_counts.unreadable == 1
    assert dump_counts.duplicates == 1

    scan_counts = read_scan(scan)
    assert scan_counts.total == 4
    assert scan_counts.valid == 1
    assert scan_counts.sentinel == 1
    assert scan_counts.zero == 1
    assert scan_counts.extra["unresolved_rows"] == 3


def test_report_explains_differences_instead_of_dropping_rows(tmp_path: Path) -> None:
    probe = _write(
        tmp_path / "probe.json",
        {
            "schema": "scoutmind.probe.diagnostics.v1",
            "probe": {"passed": True},
            "scan_readiness": True,
            "uid_diagnostics": {"totalObjects": 6, "validUids": 4, "sentinelUids": 2},
        },
    )
    dump = _write(tmp_path / "dump.json", _dump([{"id": 1}, {"id": 2}, {"id": 3}]))
    scan = _write(
        tmp_path / "scan.json",
        {
            "scan": {"scan_id": "scan-cov-2"},
            "players": [
                {"save_local_uid": "1"},
                {"save_local_uid": "2"},
                {"save_local_uid": "3"},
            ],
        },
    )

    report = build_report(probe_path=probe, dump_path=dump, scan_path=scan, database_path=None, scan_id="scan-cov-2")
    reasons = {(item["from"], item["to"]): item for item in report["differences"]}
    assert reasons[("native_reader", "upstream_dump")]["delta"] == 3
    assert reasons[("native_reader", "upstream_dump")]["reason"] == "upstream_not_exported"
    assert reasons[("upstream_dump", "scan_payload")]["delta"] == 0
    assert reasons[("upstream_dump", "scan_payload")]["reason"] == "match"
    # No importer layer: no claim is made about it.
    assert ("scan_payload", "importer") not in reasons
    markdown = render_markdown(report)
    assert "upstream_not_exported" in markdown
    assert "0x" not in markdown


def test_report_reads_importer_counts_from_database(db: Session, tmp_path: Path) -> None:
    document = scan_document(
        scan_id="scan-cov-3",
        players=[player_row("C1", "Coverage One"), unresolved_row("Coverage Free Agent")],
    )
    import_document(db, document)
    db.commit()
    scan = _write(tmp_path / "scan.json", document)
    report = build_report(
        probe_path=None,
        dump_path=None,
        scan_path=scan,
        database_path=Path(db.get_bind().url.database or ""),
        scan_id="scan-cov-3",
    )
    importer = next(layer for layer in report["layers"] if layer["layer"] == "importer")
    assert importer["imported"] == 1  # the unresolved observation
    assert importer["valid"] == 1  # the imported snapshot
    assert importer["rejected"] == 0
    assert importer["import_status"] == "succeeded"


def test_database_layer_reports_rejected_rows(db: Session, tmp_path: Path) -> None:
    document = scan_document(
        scan_id="scan-cov-4",
        players=[player_row("D1", "Rejected One"), {"name": "No Identity"}],
    )
    import_document(db, document)
    db.commit()
    scan = _write(tmp_path / "scan.json", document)
    report = build_report(
        probe_path=None,
        dump_path=None,
        scan_path=scan,
        database_path=Path(db.get_bind().url.database or ""),
        scan_id="scan-cov-4",
    )
    importer = next(layer for layer in report["layers"] if layer["layer"] == "importer")
    assert importer["rejected"] == 1
    assert importer["import_status"] == "partial"
    pair = {(item["from"], item["to"]): item for item in report["differences"]}
    assert pair[("scan_payload", "importer")]["delta"] == 1
    assert pair[("scan_payload", "importer")]["reason"] == "rejected_rows"
