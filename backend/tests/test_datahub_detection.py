"""V3.3.0 detection: source, format, version and encoding are identified without writing anything."""

from __future__ import annotations

import json

import pytest

from app.datahub.detection import DetectionError, detect_payload

from tests.helpers import scan_document


def _json_bytes(document: dict) -> bytes:
    return json.dumps(document, ensure_ascii=False).encode("utf-8")


def test_detects_scan_json():
    detection = detect_payload(_json_bytes(scan_document(players=[])))
    assert detection.source == "scan_json"
    assert detection.format == "json"
    assert detection.schema_version == "1.0"
    assert detection.compatible is True
    assert detection.encoding == "utf-8-sig"


def test_detects_ndjson():
    header = scan_document(players=[])
    header.pop("players")
    header.pop("clubs")
    header.pop("transfers")
    body = json.dumps(header, ensure_ascii=False) + "\n" + json.dumps(
        {"entity": "player", "save_local_uid": "P1", "name": "A"}, ensure_ascii=False
    )
    detection = detect_payload(body.encode("utf-8"))
    assert detection.source == "scan_ndjson"
    assert detection.format == "ndjson"


def test_detects_fmsuperscout_dump():
    dump = {"meta": {"game": "FM27"}, "players": [{"id": "1", "name": "A", "ca": 120, "attrs": {}}]}
    detection = detect_payload(_json_bytes(dump))
    assert detection.source == "fmscout_dump"
    assert detection.compatible is True


def test_unsupported_schema_version_is_blocked():
    document = scan_document(players=[])
    document["schema_version"] = "2.0"
    detection = detect_payload(_json_bytes(document))
    assert detection.compatible is False
    assert detection.code == "unsupported_version"


def test_roster_csv_is_redirected():
    detection = detect_payload("姓名,俱乐部,阵容\n张三,北桥联,一线队\n".encode("utf-8"))
    assert detection.source == "squad_csv"
    assert detection.code == "roster_csv_route"
    assert detection.compatible is False


def test_unknown_format_is_reported():
    detection = detect_payload(b"this is not a scan payload at all")
    assert detection.source == "unknown"
    assert detection.code == "unsupported_format"


def test_gb18030_file_is_decoded_not_replaced():
    document = scan_document(players=[], clubs=[{"uid": "C1", "name": "北桥联", "league": "英超"}])
    document["scan"]["scan_id"] = "scan-gbk"
    raw = json.dumps(document, ensure_ascii=False).encode("gb18030")
    detection = detect_payload(raw)
    assert detection.source == "scan_json"
    assert detection.encoding == "gb18030"
    assert any("gb18030" in warning for warning in detection.warnings)


def test_empty_payload_raises():
    with pytest.raises(DetectionError) as excinfo:
        detect_payload(b"   ")
    assert excinfo.value.code == "empty_payload"
