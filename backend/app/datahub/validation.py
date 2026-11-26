"""Unified row validation for the data import hub (V3.3.0).

The rules are the existing scan protocol validators: this module never invents a second definition of a
valid player/transfer/club. It only classifies failures so the engine can quarantine them with a stable code.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..ingestion.protocol import (
    ProtocolError,
    RowValidationError,
    ScanPayload,
    validate_club_row,
    validate_player_row,
    validate_transfer_row,
)

#: Entity name → validator, kept in one place so the engine and tests agree.
VALIDATORS = {
    "club": validate_club_row,
    "player": validate_player_row,
    "transfer": validate_transfer_row,
}


@dataclass(frozen=True)
class Rejection:
    """One row that must not enter the official data set."""

    entity: str
    row_index: int
    code: str
    message: str
    row: dict[str, Any]

    def audit_spec(self) -> dict[str, object]:
        """Map this rejection to one Level 3 quarantine audit row."""
        return {
            "entity": self.entity,
            "row_index": self.row_index,
            "rule_id": f"l3.{self.code}",
            "rule_version": "1",
            "level": 3,
            "field": None,
            "before_json": json.dumps(self.row, ensure_ascii=False, default=str),
            "after_json": None,
            "reason": self.message,
            "decision": "quarantined",
            "result": "not_applied",
            "requires_review": True,
        }


def validate_header(document: dict[str, Any]) -> tuple[ScanPayload | None, str | None, str | None]:
    """Validate the envelope (schema version, scan identity, source).

    Returns ``(payload, code, message)``. ``payload`` is ``None`` when the document is unusable; the code is a
    stable reason (``unsupported_version`` / ``invalid_payload``) so the caller does not have to parse text.
    """
    try:
        return ScanPayload.model_validate(document), None, None
    except Exception as exc:  # pydantic.ValidationError is a ValueError subclass
        message = str(exc)
        if "schema major" in message or "unsupported schema_version" in message:
            return None, "unsupported_version", f"扫描协议版本不受支持：{message}"
        if isinstance(exc, ProtocolError):
            return None, "invalid_payload", str(exc)
        return None, "invalid_payload", f"扫描报文校验失败：{message}"


def validate_rows(document: dict[str, Any]) -> tuple[dict[str, Any], list[Rejection]]:
    """Split every entity list into valid rows and rejections, preserving original row indexes."""
    filtered = dict(document)
    rejections: list[Rejection] = []
    for entity, key in (("club", "clubs"), ("player", "players"), ("transfer", "transfers")):
        rows = document.get(key)
        if rows is None:
            filtered[key] = []
            continue
        if not isinstance(rows, list):
            rejections.append(
                Rejection(entity, 0, f"invalid_{entity}_list", f"{key} 必须是数组", row={"value": rows})
            )
            filtered[key] = []
            continue
        kept: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                rejections.append(
                    Rejection(entity, index, f"invalid_{entity}", f"{key}[{index}] 不是对象", row={"value": row})
                )
                continue
            try:
                VALIDATORS[entity](row)
            except RowValidationError as exc:
                rejections.append(Rejection(entity, index, exc.code, exc.message, row=row))
                continue
            kept.append(row)
        filtered[key] = kept
    return filtered, rejections


def rejection_summary(rejections: list[Rejection]) -> dict[str, int]:
    """Count rejections per entity for the response body."""
    summary: dict[str, int] = {}
    for rejection in rejections:
        summary[rejection.entity] = summary.get(rejection.entity, 0) + 1
    return summary
