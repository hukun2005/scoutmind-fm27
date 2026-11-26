"""Automatic source / format / version detection for the data import hub (V3.3.0).

Detection is structural and read-only: it never writes to the database and never guesses a version.
The result tells the engine which parser to use and whether the payload may be imported at all.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field

#: Scan protocol major version supported by the backend (docs/DATA_PROTOCOL.md).
SUPPORTED_MAJOR = 1

#: Encodings tried in order; only strict decoding is accepted, never a lossy replacement.
ENCODING_CANDIDATES = ("utf-8-sig", "gb18030")

SQUAD_CSV_MARKERS = ("姓名", "name", "club", "俱乐部", "squad", "阵容")


@dataclass(frozen=True)
class Detection:
    """What one payload is, before anything is imported."""

    source: str
    format: str
    schema_version: str | None = None
    encoding: str = "utf-8"
    compatible: bool = True
    code: str | None = None
    message: str | None = None
    warnings: tuple[str, ...] = ()
    detail: dict[str, object] = field(default_factory=dict)

    def payload(self) -> dict[str, object]:
        """Serializable form used by the API and the repair audit."""
        return {
            "source": self.source,
            "format": self.format,
            "schema_version": self.schema_version,
            "encoding": self.encoding,
            "compatible": self.compatible,
            "code": self.code,
            "message": self.message,
            "warnings": list(self.warnings),
        }


class DetectionError(ValueError):
    """Raised when a payload cannot be decoded or identified at all."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def decode_text(raw: bytes) -> tuple[str, str, list[str]]:
    """Decode bytes with a strict, explicit encoding fallback.

    Returns ``(text, encoding, warnings)``. A BOM is stripped by ``utf-8-sig``; non-UTF-8 files fall back to
    ``gb18030`` (a superset of GBK) instead of silently replacing bytes with ``�``, which would corrupt names.
    """
    if not raw or not raw.strip():
        raise DetectionError("empty_payload", "文件内容为空")
    warnings: list[str] = []
    for encoding in ENCODING_CANDIDATES:
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        if encoding != "utf-8-sig":
            warnings.append(f"文件不是 UTF-8，已按 {encoding} 解码")
        return text.lstrip("\ufeff"), encoding, warnings
    raise DetectionError("unsupported_encoding", "文件编码无法识别（仅支持 UTF-8 与 GB18030）")


def _major(version: object) -> int | None:
    if not isinstance(version, str):
        return None
    try:
        return int(version.split(".", 1)[0])
    except ValueError:
        return None


def _detect_csv(text: str) -> Detection | None:
    """A squad roster CSV: first line carries recognizable column names and a delimiter."""
    first_line = next((line for line in text.splitlines() if line.strip()), "")
    if not first_line:
        return None
    try:
        dialect = csv.Sniffer().sniff(first_line, delimiters=",;\t")
    except csv.Error:
        return None
    headers = next(csv.reader(io.StringIO(first_line), dialect=dialect), [])
    lowered = {header.strip().lower() for header in headers}
    if any(marker in lowered for marker in SQUAD_CSV_MARKERS):
        return Detection(
            source="squad_csv",
            format="csv",
            compatible=False,
            code="roster_csv_route",
            message="这是阵容名单 CSV：请在「阵容名单」入口导入，不要当作扫描报文",
        )
    return None


def _detect_json_document(document: object, encoding: str, warnings: list[str]) -> Detection | None:
    if not isinstance(document, dict):
        return None
    if "schema_version" in document:
        version = document.get("schema_version")
        major = _major(version)
        if major != SUPPORTED_MAJOR:
            return Detection(
                source="scan_json",
                format="json",
                schema_version=str(version) if version is not None else None,
                encoding=encoding,
                compatible=False,
                code="unsupported_version",
                message=f"扫描协议版本 {version!r} 不受支持（后端支持 {SUPPORTED_MAJOR}.x）",
                warnings=tuple(warnings),
            )
        return Detection(
            source="scan_json",
            format="json",
            schema_version=str(version),
            encoding=encoding,
            warnings=tuple(warnings),
        )
    players = document.get("players")
    meta = document.get("meta")
    if isinstance(players, list) and isinstance(meta, dict):
        # Structural signature of an FMSuperScout dump (see ingestion/adapters/fmscout.detect).
        if not players or isinstance(players[0], dict) and sum(
            1 for marker in ("id", "name", "ca", "pa", "club", "attrs") if marker in players[0]
        ) >= 3:
            return Detection(
                source="fmscout_dump",
                format="json",
                encoding=encoding,
                warnings=tuple(warnings),
                detail={"adapter": "fmscout"},
            )
    return None


def _detect_ndjson(text: str, encoding: str, warnings: list[str]) -> Detection | None:
    first = next((line for line in text.splitlines() if line.strip()), "")
    if not first.startswith("{"):
        return None
    try:
        header = json.loads(first)
    except json.JSONDecodeError:
        return None
    if not isinstance(header, dict):
        return None
    if "schema_version" not in header and "scan_id" not in header:
        return None
    version = header.get("schema_version")
    major = _major(version)
    if version is not None and major != SUPPORTED_MAJOR:
        return Detection(
            source="scan_ndjson",
            format="ndjson",
            schema_version=str(version),
            encoding=encoding,
            compatible=False,
            code="unsupported_version",
            message=f"扫描协议版本 {version!r} 不受支持（后端支持 {SUPPORTED_MAJOR}.x）",
            warnings=tuple(warnings),
        )
    return Detection(
        source="scan_ndjson",
        format="ndjson",
        schema_version=str(version) if version is not None else None,
        encoding=encoding,
        warnings=tuple(warnings),
    )


def detect_payload(raw: bytes, *, filename: str | None = None) -> Detection:
    """Identify one uploaded payload without writing anything.

    Order matters: a JSON object wins over NDJSON, an FMSuperScout dump is only recognised by its structure, and a
    roster CSV is reported with an explicit redirect instead of being silently parsed as a scan.
    """
    text, encoding, warnings = decode_text(raw)
    stripped = text.strip()
    if not stripped:
        raise DetectionError("empty_payload", "文件内容为空")

    if stripped[0] in "{[":
        try:
            document = json.loads(stripped)
        except json.JSONDecodeError:
            document = None
        if isinstance(document, dict):
            detected = _detect_json_document(document, encoding, warnings)
            if detected is not None:
                return detected
        if isinstance(document, list):
            return Detection(
                source="unknown",
                format="json",
                encoding=encoding,
                compatible=False,
                code="unsupported_format",
                message="JSON 顶层必须是对象：不支持根节点为数组的文件",
                warnings=tuple(warnings),
            )

    detected = _detect_ndjson(text, encoding, warnings)
    if detected is not None:
        return detected

    csv_detected = _detect_csv(stripped)
    if csv_detected is not None:
        return csv_detected

    suffix = f"（{filename}）" if filename else ""
    return Detection(
        source="unknown",
        format="unknown",
        encoding=encoding,
        compatible=False,
        code="unsupported_format",
        message=f"无法识别的数据文件{suffix}：既不是扫描报文，也不是 FMSuperScout 导出或阵容名单 CSV",
        warnings=tuple(warnings),
    )
