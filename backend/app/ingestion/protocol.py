"""Pydantic models for the scan payload defined in ``docs/DATA_PROTOCOL.md``.

The protocol is deliberately permissive about unknown fields (minor version upgrades add fields) and strict about
the facts that decide provenance: source, scan identity, observation time and player identity.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SOURCE_KINDS = (
    "fm27_live_reader",
    "fm_save_parser",
    "manual",
    "ocr",
    "external",
    "estimated",
    "synthetic_fixture",
)

TRANSFER_TYPES = (
    "permanent",
    "loan",
    "free",
    "end_of_contract",
    "clause_release",
    "swap",
    "youth_promotion",
    "other",
)

TRANSFER_STATUSES = ("completed", "pending", "future", "cancelled", "failed", "unknown")

FEE_COMPONENT_TYPES = (
    "base_fee",
    "installment",
    "addon",
    "signing_bonus",
    "agent_fee",
    "loan_fee",
    "sell_on",
    "buy_back",
    "wage_contribution",
)

FEE_COMPONENT_STATUSES = ("paid", "scheduled", "triggered", "untriggered", "conditional_unknown", "unknown")

SUPPORTED_MAJOR_VERSION = 1


class ProtocolError(ValueError):
    """Raised when a payload cannot be interpreted as a ScoutMind scan."""


class ScanGame(BaseModel):
    """Game identity as reported by the reader."""

    model_config = ConfigDict(extra="ignore")

    version: str | None = None
    build: str | None = None
    app_id: str | None = None


class ScanMeta(BaseModel):
    """Identity and timing of one scan; ``scan_id`` is the idempotency key."""

    model_config = ConfigDict(extra="ignore")

    scan_id: str = Field(min_length=1, max_length=64)
    observed_at: datetime
    game_date: date | None = None
    user_club_uid: str | None = None

    @field_validator("observed_at")
    @classmethod
    def _normalize_utc(cls, value: datetime) -> datetime:
        """Store observations as naive UTC so SQLite and PostgreSQL compare the same way."""
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value


class ClubRecord(BaseModel):
    """A club row in the payload."""

    model_config = ConfigDict(extra="ignore")

    uid: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    nation: str | None = None
    league: str | None = None
    reputation: int | None = None
    is_user_club: bool = False


class PlayerRecord(BaseModel):
    """A player observation. Any field the scanner cannot read must be ``null``."""

    model_config = ConfigDict(extra="ignore")

    record_id: str | None = None
    save_local_uid: str = Field(min_length=1, max_length=64)
    game_unique_id: str | None = None
    name: str = Field(min_length=1, max_length=128)
    birth_date: date | None = None
    nationality: str | None = None
    position: str | None = None
    club_uid: str | None = None
    ca: int | None = Field(default=None, ge=0, le=400)
    pa: int | None = Field(default=None, ge=0, le=400)
    market_value: int | None = Field(default=None, ge=0)
    wage: int | None = Field(default=None, ge=0)
    contract_end: date | None = None
    minutes_played: int | None = Field(default=None, ge=0)
    appearances: int | None = Field(default=None, ge=0)
    goals: int | None = Field(default=None, ge=0)
    assists: int | None = Field(default=None, ge=0)
    attributes: dict[str, float] = Field(default_factory=dict)

    @field_validator("name", "save_local_uid")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be blank")
        return stripped


class FeeComponentRecord(BaseModel):
    """One component of a transfer fee."""

    model_config = ConfigDict(extra="ignore")

    type: Literal[
        "base_fee",
        "installment",
        "addon",
        "signing_bonus",
        "agent_fee",
        "loan_fee",
        "sell_on",
        "buy_back",
        "wage_contribution",
    ]
    amount: float | None = Field(default=None, ge=0)
    status: Literal["paid", "scheduled", "triggered", "untriggered", "conditional_unknown", "unknown"] = "unknown"
    due_date: date | None = None
    condition: str | None = None


class TransferRecord(BaseModel):
    """A transfer row. ``status='completed'`` is required before it can enter price statistics."""

    model_config = ConfigDict(extra="ignore")

    record_id: str = Field(min_length=1, max_length=64)
    player_record_id: str | None = None
    player_name: str = Field(min_length=1, max_length=128)
    transfer_type: Literal[
        "permanent",
        "loan",
        "free",
        "end_of_contract",
        "clause_release",
        "swap",
        "youth_promotion",
        "other",
    ] = "other"
    status: Literal["completed", "pending", "future", "cancelled", "failed", "unknown"] = "unknown"
    transfer_date: date
    season: str | None = None
    from_club_uid: str | None = None
    from_club_name: str | None = None
    to_club_uid: str | None = None
    to_club_name: str | None = None
    currency: str = "EUR"
    base_fee: float | None = Field(default=None, ge=0)
    fee_paid: float | None = Field(default=None, ge=0)
    addons_potential: float | None = Field(default=None, ge=0)
    player_age_at_transfer: int | None = Field(default=None, ge=10, le=60)
    player_ca_at_transfer: int | None = Field(default=None, ge=0, le=400)
    player_pa_at_transfer: int | None = Field(default=None, ge=0, le=400)
    contract_remaining_months: int | None = Field(default=None, ge=0, le=120)
    confidence: float | None = Field(default=None, ge=0, le=1)
    fee_components: list[FeeComponentRecord] = Field(default_factory=list)


class ScanPayload(BaseModel):
    """A complete scan document.

    Entity rows stay as raw mappings here so one malformed row can be rejected and reported without discarding the
    rest of a scan. :func:`validate_player_row` and :func:`validate_transfer_row` turn them into typed records.
    """

    model_config = ConfigDict(extra="ignore")

    schema_version: str = "1.0"
    source: Literal[
        "fm27_live_reader",
        "fm_save_parser",
        "manual",
        "ocr",
        "external",
        "estimated",
        "synthetic_fixture",
    ]
    reader_version: str | None = None
    game: ScanGame = Field(default_factory=ScanGame)
    scan: ScanMeta
    coverage: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    clubs: list[dict[str, Any]] = Field(default_factory=list)
    players: list[dict[str, Any]] = Field(default_factory=list)
    transfers: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("schema_version")
    @classmethod
    def _major_version(cls, value: str) -> str:
        try:
            major = int(value.split(".", 1)[0])
        except (ValueError, IndexError) as exc:
            raise ValueError(f"unsupported schema_version {value!r}") from exc
        if major != SUPPORTED_MAJOR_VERSION:
            raise ValueError(f"incompatible schema major {major}; backend supports {SUPPORTED_MAJOR_VERSION}.x")
        return value


class RowValidationError(ValueError):
    """Raised when one entity row inside a scan cannot be imported."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _first_error(exc: Exception) -> str:
    errors = getattr(exc, "errors", None)
    if callable(errors):
        try:
            details = errors()
        except TypeError:
            details = []
        if details:
            first = details[0]
            location = ".".join(str(part) for part in first.get("loc", ()))
            return f"{location}: {first.get('msg', 'invalid value')}" if location else str(first.get("msg"))
    return str(exc)


def validate_club_row(row: dict[str, Any]) -> ClubRecord:
    """Validate one club row, raising :class:`RowValidationError` with a stable code."""
    try:
        return ClubRecord.model_validate(row)
    except Exception as exc:  # pydantic ValidationError carries the field details
        raise RowValidationError("invalid_club", f"俱乐部数据无效：{_first_error(exc)}") from exc


def validate_player_row(row: dict[str, Any]) -> PlayerRecord:
    """Validate one player row, raising :class:`RowValidationError` with a stable code."""
    if not isinstance(row.get("save_local_uid"), str) or not row["save_local_uid"].strip():
        raise RowValidationError("missing_uid", "球员缺少 save_local_uid")
    if not isinstance(row.get("name"), str) or not row["name"].strip():
        raise RowValidationError("missing_name", "球员缺少 name")
    try:
        return PlayerRecord.model_validate(row)
    except Exception as exc:
        raise RowValidationError("invalid_player", f"球员数据无效：{_first_error(exc)}") from exc


def validate_transfer_row(row: dict[str, Any]) -> TransferRecord:
    """Validate one transfer row, raising :class:`RowValidationError` with a stable code."""
    if not isinstance(row.get("record_id"), str) or not row["record_id"].strip():
        raise RowValidationError("missing_record_id", "交易缺少 record_id")
    if row.get("transfer_date") in (None, ""):
        raise RowValidationError("missing_transfer_date", "交易缺少 transfer_date")
    try:
        return TransferRecord.model_validate(row)
    except Exception as exc:
        raise RowValidationError("invalid_transfer", f"交易数据无效：{_first_error(exc)}") from exc


def _payload_from_mapping(data: dict[str, Any]) -> ScanPayload:
    return ScanPayload.model_validate(data)


def parse_payload(raw: bytes) -> tuple[ScanPayload, list[str]]:
    """Parse a JSON or newline-delimited scan payload, returning the payload and structural warnings."""
    text = raw.decode("utf-8-sig", errors="strict").strip()
    if not text:
        raise ProtocolError("扫描文件为空")
    if text[0] == "{":
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            return _payload_from_mapping(data), []
    return _parse_ndjson(text)


def _parse_ndjson(text: str) -> tuple[ScanPayload, list[str]]:
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise ProtocolError("NDJSON 扫描文件为空")
    try:
        header = json.loads(lines[0])
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"无法解析扫描报文：{exc.msg}") from exc
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
    return _payload_from_mapping(document), warnings
