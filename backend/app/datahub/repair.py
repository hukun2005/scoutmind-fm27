"""Automatic repair rules for the data import hub (V3.3.0).

Three levels, deliberately separated:

* **Level 1** — deterministic normalization applied to the parsed row dictionaries before validation.
  It never changes the business meaning of a value (format, whitespace, case, known aliases only).
* **Level 2** — evidence-based repairs that need the database (a club name that maps to exactly one club in the
  same save). Ambiguous names are never guessed.
* **Level 3** — everything that cannot be decided safely is left to :mod:`app.datahub.validation`, which
  quarantines the row and records ``decision='quarantined'``.

No rule in this module merges players by name, derives a birth date from an age, turns a loan into a permanent
transfer, or replaces an unknown fee with zero.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ingestion.protocol import validate_player_row, validate_transfer_row
from ..models import Club
from ..utils import normalize_name

BLANK_VALUES = {"", "-", "--", "n/a", "na", "null", "none"}

REQUIRED_FIELDS: dict[str, set[str]] = {
    "club": {"uid", "name"},
    "player": {"name"},
    "transfer": {"record_id", "player_name", "transfer_date"},
}

#: Legacy / third-party field names → canonical protocol field. Applied only when the canonical key is absent.
FIELD_ALIASES: dict[str, dict[str, str]] = {
    "player": {
        "current_ability": "ca",
        "potential_ability": "pa",
        "marketvalue": "market_value",
        "market_val": "market_value",
        "salary": "wage",
        "wage_current": "wage",
        "contract_expiry": "contract_end",
        "contract_end_date": "contract_end",
        "date_of_birth": "birth_date",
        "dob": "birth_date",
        "player_name": "name",
    },
    "transfer": {
        "fee": "base_fee",
        "transfer_fee": "base_fee",
        "date": "transfer_date",
        "player": "player_name",
    },
    "club": {"club_name": "name"},
}

DATE_FIELDS: dict[str, set[str]] = {
    "club": set(),
    "player": {"birth_date", "contract_end"},
    "transfer": {"transfer_date"},
}

INT_FIELDS: dict[str, set[str]] = {
    "club": {"reputation"},
    "player": {
        "age", "ca", "pa", "market_value", "wage", "minutes_played",
        "appearances", "goals", "assists", "height_cm", "world_reputation",
    },
    "transfer": {
        "player_age_at_transfer", "player_ca_at_transfer", "player_pa_at_transfer",
        "contract_remaining_months",
    },
}

FLOAT_FIELDS: dict[str, set[str]] = {
    "club": set(),
    "player": set(),
    "transfer": {"base_fee", "fee_paid", "addons_potential", "confidence"},
}

ENUM_MAPS: dict[str, dict[str, dict[str, str]]] = {
    "player": {
        "foot": {
            "left": "left", "l": "left", "左脚": "left",
            "right": "right", "r": "right", "右脚": "right",
            "both": "both", "b": "both", "either": "both", "双足": "both",
        },
    },
    "transfer": {
        "transfer_type": {
            "permanent": "permanent", "永久": "permanent",
            "loan": "loan", "租借": "loan",
            "loan_with_option": "loan_with_option", "loan_option": "loan_with_option",
            "loan with option": "loan_with_option",
            "free": "free", "free_transfer": "free", "自由转会": "free",
            "end_of_contract": "end_of_contract", "bosman": "end_of_contract",
            "clause_release": "clause_release", "swap": "swap",
            "youth_promotion": "youth_promotion", "other": "other",
        },
        "status": {
            "completed": "completed", "complete": "completed", "done": "completed", "已完成": "completed",
            "pending": "pending", "future": "future", "agreed": "agreed",
            "bid_rejected": "bid_rejected",
            "cancelled": "cancelled", "canceled": "cancelled",
            "failed": "failed", "unknown": "unknown",
        },
    },
}

DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d.%m.%Y", "%Y%m%d", "%d-%m-%Y")
_NUMBER_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?$")

STATISTIC_INT_FIELDS = {
    "appearances", "starts", "minutes_played", "goals", "assists", "shots", "shots_on_target",
    "key_passes", "passes_attempted", "passes_completed", "dribbles", "tackles", "interceptions",
    "clearances", "aerials_won", "saves", "conceded", "clean_sheets",
}
FEE_COMPONENT_FLOAT_FIELDS = {"amount"}


@dataclass(frozen=True)
class Repair:
    """One applied repair, ready to be written as a ``data_repair_audits`` row."""

    entity: str
    row_index: int
    rule_id: str
    field: str | None
    before: Any
    after: Any
    reason: str
    level: int = 1

    def audit_spec(self) -> dict[str, object]:
        return {
            "entity": self.entity,
            "row_index": self.row_index,
            "rule_id": self.rule_id,
            "rule_version": "1",
            "level": self.level,
            "field": self.field,
            "before_json": _dump(self.before),
            "after_json": _dump(self.after),
            "reason": self.reason,
            "decision": "repaired",
            "result": "applied",
            "requires_review": False,
        }

    def payload(self) -> dict[str, object]:
        return {
            "entity": self.entity,
            "row": self.row_index,
            "rule": self.rule_id,
            "field": self.field,
            "before": self.before,
            "after": self.after,
            "level": self.level,
            "reason": self.reason,
        }


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _strip_strings(value: Any) -> Any:
    """Recursively trim ASCII/Unicode whitespace and zero-width characters; keep structure."""
    if isinstance(value, str):
        return value.replace("\u200b", "").replace("\u3000", " ").strip()
    if isinstance(value, list):
        return [_strip_strings(item) for item in value]
    if isinstance(value, dict):
        return {key: _strip_strings(item) for key, item in value.items()}
    return value


def _parse_date(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate:
        return None
    if "T" in candidate:
        candidate = candidate.split("T", 1)[0]
    for pattern in DATE_FORMATS:
        try:
            return datetime.strptime(candidate, pattern).date().isoformat()
        except ValueError:
            continue
    return None


def _normalize_value(entity: str, field: str, value: Any) -> tuple[Any, str | None]:
    """Return ``(new_value, rule_id)``; ``rule_id`` is ``None`` when nothing changed."""
    if isinstance(value, str):
        if field not in REQUIRED_FIELDS.get(entity, set()) and value.strip().lower() in BLANK_VALUES:
            return None, "l1.blank_to_null"
    if field in DATE_FIELDS.get(entity, set()) and isinstance(value, str):
        parsed = _parse_date(value)
        if parsed is not None and parsed != value:
            return parsed, "l1.date_format"
    if field in INT_FIELDS.get(entity, set()) and isinstance(value, str):
        text = value.replace(" ", "")
        if _NUMBER_RE.fullmatch(text):
            try:
                return int(float(text)), "l1.numeric_string"
            except ValueError:
                return value, None
    if field in FLOAT_FIELDS.get(entity, set()) and isinstance(value, str):
        text = value.replace(" ", "")
        if _NUMBER_RE.fullmatch(text):
            try:
                return float(text), "l1.numeric_string"
            except ValueError:
                return value, None
    enum_map = ENUM_MAPS.get(entity, {}).get(field)
    if enum_map and isinstance(value, str):
        mapped = enum_map.get(value.strip().lower())
        if mapped is not None and mapped != value:
            return mapped, "l1.enum_case"
    if field == "currency" and isinstance(value, str):
        upper = value.strip().upper()
        if upper and upper != value:
            return upper, "l1.enum_case"
    return value, None


def _normalize_nested(entity: str, row: dict[str, Any], index: int) -> list[Repair]:
    """Normalize nested blocks whose values are typed (statistics, fee components)."""
    repairs: list[Repair] = []
    statistics = row.get("statistics")
    if isinstance(statistics, list):
        for block_index, block in enumerate(statistics):
            if not isinstance(block, dict):
                continue
            for field in list(block):
                if field in STATISTIC_INT_FIELDS and isinstance(block[field], str):
                    text = block[field].replace(" ", "")
                    if _NUMBER_RE.fullmatch(text):
                        before = block[field]
                        block[field] = int(float(text))
                        repairs.append(
                            Repair(entity, index, "l1.numeric_string", f"statistics[{block_index}].{field}",
                                   before, block[field], "统计字段数字字符串转数字")
                        )
    components = row.get("fee_components")
    if isinstance(components, list):
        for block_index, block in enumerate(components):
            if not isinstance(block, dict):
                continue
            for field in FEE_COMPONENT_FLOAT_FIELDS:
                if isinstance(block.get(field), str) and _NUMBER_RE.fullmatch(block[field].replace(" ", "")):
                    before = block[field]
                    block[field] = float(block[field].replace(" ", ""))
                    repairs.append(
                        Repair(entity, index, "l1.numeric_string", f"fee_components[{block_index}].{field}",
                               before, block[field], "费用分项数字字符串转数字")
                    )
            due = block.get("due_date")
            if isinstance(due, str):
                parsed = _parse_date(due)
                if parsed is not None and parsed != due:
                    repairs.append(
                        Repair(entity, index, "l1.date_format", f"fee_components[{block_index}].due_date",
                               due, parsed, "费用分项日期格式标准化")
                    )
                    block["due_date"] = parsed
    return repairs


def normalize_document(document: dict[str, Any]) -> tuple[dict[str, Any], list[Repair]]:
    """Apply every Level 1 rule to one parsed scan document.

    The document is copied deeply enough to avoid mutating caller state; repairs are returned in input row order.
    """
    result = dict(document)
    repairs: list[Repair] = []
    for entity, key in (("club", "clubs"), ("player", "players"), ("transfer", "transfers")):
        rows = document.get(key)
        if not isinstance(rows, list):
            continue
        normalized_rows: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                normalized_rows.append(row)
                continue
            before_values = {field: value for field, value in row.items() if isinstance(value, str)}
            clean = _strip_strings(row)
            for field, before in before_values.items():
                after = clean.get(field)
                if after != before:
                    repairs.append(
                        Repair(
                            entity, index, "l1.trim_whitespace", field, before, after,
                            "去除首尾空白与零宽字符",
                        )
                    )
            for alias, target in FIELD_ALIASES.get(entity, {}).items():
                if alias in clean and (target not in clean or clean.get(target) is None):
                    value = clean.pop(alias)
                    clean[target] = value
                    repairs.append(
                        Repair(entity, index, "l1.field_alias", alias, None, target, f"旧字段 {alias} → {target}")
                    )
            for field in list(clean):
                original = clean[field]
                new_value, rule = _normalize_value(entity, field, original)
                if rule is not None and new_value != original:
                    clean[field] = new_value
                    reason = {
                        "l1.blank_to_null": "空值标记转为 null",
                        "l1.date_format": "合法日期格式标准化",
                        "l1.numeric_string": "数字字符串转数字",
                        "l1.enum_case": "枚举值标准化",
                    }[rule]
                    repairs.append(Repair(entity, index, rule, field, original, new_value, reason))
            repairs.extend(_normalize_nested(entity, clean, index))
            normalized_rows.append(clean)
        result[key] = normalized_rows
    return result, repairs


def dedupe_document(document: dict[str, Any]) -> tuple[dict[str, Any], list[Repair], int]:
    """Remove rows whose normalized content repeats an earlier row of the same entity.

    Only *content-identical* rows are removed. Two snapshots of the same player at different times, or two real
    transfers with different fees, are never treated as duplicates.
    """
    result = dict(document)
    repairs: list[Repair] = []
    removed_total = 0
    for entity, key in (("club", "clubs"), ("player", "players"), ("transfer", "transfers")):
        rows = document.get(key)
        if not isinstance(rows, list):
            continue
        seen: dict[str, int] = {}
        kept: list[Any] = []
        removed = 0
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                kept.append(row)
                continue
            fingerprint = json.dumps(row, sort_keys=True, ensure_ascii=False, default=str)
            first = seen.get(fingerprint)
            if first is not None:
                removed += 1
                repairs.append(
                    Repair(
                        entity, index, "l1.duplicate_row", None, None, None,
                        f"与第 {first + 1} 行内容完全重复，已去除",
                    )
                )
                continue
            seen[fingerprint] = index
            kept.append(row)
        result[key] = kept
        removed_total += removed
    return result, repairs, removed_total


def _club_name_index(session: Session, save_id: int) -> dict[str, set[str]]:
    """Normalized club name → set of uids in one save (never crosses saves)."""
    index: dict[str, set[str]] = {}
    for uid, name in session.execute(
        select(Club.uid, Club.name).where(Club.fm_save_id == save_id)
    ):
        if uid and name:
            index.setdefault(normalize_name(name), set()).add(uid)
    return index


def resolve_level2(
    session: Session, save_id: int, document: dict[str, Any]
) -> tuple[dict[str, Any], list[Repair]]:
    """Evidence-based repairs that need the current save.

    A missing club uid is filled only when the club name matches exactly one club (declared in the payload or
    already stored in this save). Multiple matches stay untouched and are later reported as unresolved.
    """
    result = dict(document)
    repairs: list[Repair] = []
    name_index = _club_name_index(session, save_id)
    for row in document.get("clubs") or []:
        if isinstance(row, dict) and row.get("uid") and row.get("name"):
            name_index.setdefault(normalize_name(str(row["name"])), set()).add(str(row["uid"]))

    def _unique_uid(name: Any) -> str | None:
        if not isinstance(name, str) or not name.strip():
            return None
        matches = name_index.get(normalize_name(name), set())
        return next(iter(matches)) if len(matches) == 1 else None

    def _repair_entity(entity: str, key: str, uid_field: str, name_field: str) -> None:
        rows = result.get(key)
        if not isinstance(rows, list):
            return
        updated = list(rows)
        for index, raw in enumerate(rows):
            if not isinstance(raw, dict):
                continue
            row = dict(raw)
            if not row.get(uid_field):
                uid = _unique_uid(row.get(name_field))
                if uid:
                    row[uid_field] = uid
                    updated[index] = row
                    repairs.append(
                        Repair(entity, index, "l2.club_by_unique_name", uid_field, None, uid,
                               f"俱乐部名 {row.get(name_field)!r} 在本存档唯一命中，补全 uid", level=2)
                    )
        result[key] = updated

    _repair_entity("transfer", "transfers", "from_club_uid", "from_club_name")
    _repair_entity("transfer", "transfers", "to_club_uid", "to_club_name")
    _repair_entity("player", "players", "club_uid", "club_name")
    return result, repairs


def validate_resolved_rows(document: dict[str, Any]) -> list[str]:
    """Re-validate repaired rows so a repair can never introduce an invalid record.

    Returns human-readable problems; an empty list means every repaired row still validates through the
    same protocol validators used at import time.
    """
    problems: list[str] = []
    for row in document.get("players") or []:
        if isinstance(row, dict):
            try:
                validate_player_row(row)
            except Exception as exc:  # noqa: BLE001 - 只用于诊断，不吞掉真正异常类型
                problems.append(f"player: {exc}")
    for row in document.get("transfers") or []:
        if isinstance(row, dict):
            try:
                validate_transfer_row(row)
            except Exception as exc:  # noqa: BLE001
                problems.append(f"transfer: {exc}")
    return problems


def record_summary(document: dict[str, Any]) -> dict[str, int]:
    """Row counts after normalization and filtering."""
    return {
        "clubs": len(document.get("clubs") or []),
        "players": len(document.get("players") or []),
        "transfers": len(document.get("transfers") or []),
    }


__all__ = [
    "Repair",
    "dedupe_document",
    "normalize_document",
    "record_summary",
    "resolve_level2",
    "validate_resolved_rows",
]
