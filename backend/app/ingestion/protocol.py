"""Pydantic models for the scan payload defined in ``docs/DATA_PROTOCOL.md``.

The protocol is deliberately permissive about unknown fields (minor version upgrades add fields) and strict about
the facts that decide provenance: source, scan identity, observation time and player identity.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .uid_status import UID_SENTINEL, UID_VALID, classify_uid

SOURCE_KINDS = (
    "fm27_live_reader",
    "fm_save_parser",
    "fmsuperscout",
    "manual",
    "ocr",
    "external",
    "estimated",
    "synthetic_fixture",
)

TRANSFER_TYPES = (
    "permanent",
    "loan",
    "loan_with_option",
    "loan_buyout",
    "free",
    "end_of_contract",
    "clause_release",
    "swap",
    "youth_promotion",
    "other",
)

#: ``agreed`` = deal agreed but not yet in force; ``bid_rejected`` = an offer that never became a transfer.
#: Neither may enter price statistics or spending totals.
TRANSFER_STATUSES = (
    "completed",
    "pending",
    "future",
    "agreed",
    "bid_rejected",
    "cancelled",
    "failed",
    "unknown",
)

#: Where a player's registration currently sits, as reported by a source that exposes loans.
TEAM_TYPES = ("senior", "reserve", "youth", "unknown")

#: Three-valued listing flags: absent (unknown), listed, not listed.
AVAILABILITY_FLAGS = ("listed", "loan_listed", "not_for_sale", "set_for_release")

FEE_COMPONENT_TYPES = (
    "base_fee",
    "installment",
    "addon",
    "signing_bonus",
    "agent_fee",
    "loan_fee",
    "sell_on",
    "buy_back",
    "buy_option",
    "wage_contribution",
)

STATISTIC_FIELDS = (
    "appearances",
    "starts",
    "minutes_played",
    "goals",
    "assists",
    "shots",
    "shots_on_target",
    "xg",
    "key_passes",
    "passes_attempted",
    "passes_completed",
    "dribbles",
    "tackles",
    "interceptions",
    "clearances",
    "aerials_won",
    "saves",
    "conceded",
    "clean_sheets",
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


SAFE_SCAN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class ScanMeta(BaseModel):
    """Identity and timing of one scan; ``scan_id`` is the idempotency key.

    ``scan_id`` also becomes part of a filename on disk, so it is restricted to a safe alphabet:
    no slashes, no backslashes, no drive letters, no ``..`` segments. The storage layer additionally
    generates its own filename and verifies the resolved path stays inside the save's raw directory.
    """

    model_config = ConfigDict(extra="ignore")

    scan_id: str = Field(min_length=1, max_length=64)
    observed_at: datetime
    game_date: date | None = None
    user_club_uid: str | None = None

    @field_validator("scan_id")
    @classmethod
    def _safe_scan_id(cls, value: str) -> str:
        """Reject anything that could be interpreted as a path instead of an id."""
        if not SAFE_SCAN_ID_PATTERN.fullmatch(value) or ".." in value:
            raise ValueError(
                "scan_id 只能包含字母、数字、点、下划线和连字符（1-64 位），且不能包含路径分隔符、盘符或 .."
            )
        return value

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


class SeasonStatisticsRecord(BaseModel):
    """Season aggregate performance reported for one player.

    The block is optional: a reader that cannot read match statistics omits it, and the backend then reports the
    affected performance screens as unavailable instead of showing zeros.
    """

    model_config = ConfigDict(extra="ignore")

    period: str = Field(min_length=1, max_length=32)
    competition: str | None = None
    appearances: int | None = Field(default=None, ge=0)
    starts: int | None = Field(default=None, ge=0)
    minutes_played: int | None = Field(default=None, ge=0)
    goals: int | None = Field(default=None, ge=0)
    assists: int | None = Field(default=None, ge=0)
    shots: int | None = Field(default=None, ge=0)
    shots_on_target: int | None = Field(default=None, ge=0)
    xg: float | None = Field(default=None, ge=0)
    key_passes: int | None = Field(default=None, ge=0)
    passes_attempted: int | None = Field(default=None, ge=0)
    passes_completed: int | None = Field(default=None, ge=0)
    dribbles: int | None = Field(default=None, ge=0)
    tackles: int | None = Field(default=None, ge=0)
    interceptions: int | None = Field(default=None, ge=0)
    clearances: int | None = Field(default=None, ge=0)
    aerials_won: int | None = Field(default=None, ge=0)
    saves: int | None = Field(default=None, ge=0)
    conceded: int | None = Field(default=None, ge=0)
    clean_sheets: int | None = Field(default=None, ge=0)


class AvailabilityRecord(BaseModel):
    """Listing, injury and registration state of one player at one observation.

    Every flag is three-valued: ``None`` says the source did not report it. A missing injury record never means
    "fit", and ``injury_proneness`` is a player attribute that says nothing about the current injury.
    """

    model_config = ConfigDict(extra="ignore")

    listed: bool | None = None
    loan_listed: bool | None = None
    not_for_sale: bool | None = None
    set_for_release: bool | None = None
    injury_proneness: int | None = Field(default=None, ge=0, le=20)
    injured: bool | None = None
    injury_start_date: date | None = None
    expected_return_date: date | None = None
    injury_note: str | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def _injury_consistency(self) -> "AvailabilityRecord":
        """Reject records that claim an injury date while also asserting the player is fit."""
        if self.injured is False and (self.injury_start_date or self.expected_return_date):
            raise ValueError("injured=false 不能同时带伤病日期")
        return self


class OwnershipRecord(BaseModel):
    """Who owns the player and where he is registered. Loan clauses stay ``None`` unless a source states them."""

    model_config = ConfigDict(extra="ignore")

    parent_club_uid: str | None = None
    loan_club_uid: str | None = None
    team_type: Literal["senior", "reserve", "youth", "unknown"] | None = None
    loan_start_date: date | None = None
    loan_end_date: date | None = None
    has_option: bool | None = None
    has_obligation: bool | None = None


class AgreedTransferRecord(BaseModel):
    """A deal that is agreed but not yet in force. Imported as a pending transfer, never as spending."""

    model_config = ConfigDict(extra="ignore")

    to_club_uid: str | None = None
    # Named ``transfer_date`` rather than ``date``: a field called ``date`` shadows the imported type.
    transfer_date: date | None = None


#: Upper bound for the evidence block of one unresolved identity, so a payload cannot bloat the database.
MAX_IDENTITY_EVIDENCE_JSON = 2000


class PlayerIdentityRecord(BaseModel):
    """Identity declaration of one player row.

    ``kind='save_local_uid'`` is the schema-1.0 identity: the upstream UID is trusted and must be a valid,
    non-sentinel handle. ``kind='unresolved'`` says the source could not name an identity (sentinel
    ``0xFFFFFFFF``, no ID at all, or a value that cannot be a UID); such a row becomes an unresolved
    observation and never creates a player instance.

    The two modes are mutually exclusive. An unresolved row must not carry ``save_local_uid``, and a valid
    row must never carry a sentinel: ``4294967295`` is "no identity", not the identity of fourteen players.
    """

    model_config = ConfigDict(extra="ignore")

    kind: Literal["save_local_uid", "unresolved"]
    value: str | None = Field(default=None, max_length=64)
    raw_uid: str | None = Field(default=None, max_length=64)
    reason: str | None = Field(default=None, max_length=64)
    uid_status: Literal["valid", "sentinel", "missing", "invalid"] | None = None
    source_record_id: str | None = Field(default=None, max_length=128)
    evidence: dict[str, Any] = Field(default_factory=dict)


def _identity_code(status: str) -> str:
    return {"sentinel": "sentinel_uid", "missing": "missing_uid"}.get(status, "invalid_uid")


def normalize_player_identity(row: dict[str, Any]) -> dict[str, Any]:
    """Resolve one row's identity mode into normalized protocol fields.

    Returns ``save_local_uid``, ``identity``, ``uid_status`` and ``uid_reason``. Raises
    :class:`RowValidationError` with a stable code when the row mixes modes or tries to pass a sentinel
    off as a legal UID. A legacy row that only carries a sentinel ``save_local_uid`` is preserved as an
    unresolved observation instead of being dropped or stored under the sentinel.
    """
    raw_identity = row.get("identity")
    declared_uid = row.get("save_local_uid")

    if raw_identity is None:
        assessment = classify_uid(declared_uid)
        if assessment.is_valid:
            return {
                "save_local_uid": assessment.raw_uid,
                "identity": {"kind": "save_local_uid", "value": assessment.raw_uid},
                "uid_status": UID_VALID,
                "uid_reason": None,
            }
        if assessment.status == "missing":
            raise RowValidationError("missing_uid", "球员缺少 save_local_uid 或 identity")
        return {
            "save_local_uid": None,
            "identity": {
                "kind": "unresolved",
                "raw_uid": assessment.raw_uid,
                "reason": assessment.reason or "invalid_uid",
                "uid_status": assessment.status,
                "evidence": {"protocol": "legacy_save_local_uid", "uid_status": assessment.status},
            },
            "uid_status": assessment.status,
            "uid_reason": assessment.reason,
        }

    if not isinstance(raw_identity, dict):
        raise RowValidationError("invalid_identity", "identity 必须是对象")
    kind = raw_identity.get("kind")
    if kind == "save_local_uid":
        value = raw_identity.get("value") or declared_uid
        if value is None or not str(value).strip():
            raise RowValidationError("missing_uid", "identity.kind=save_local_uid 但缺少 value")
        assessment = classify_uid(value)
        if not assessment.is_valid:
            raise RowValidationError(
                _identity_code(assessment.status),
                f"身份值 {assessment.raw_uid!r} 不能作为合法 UID（{assessment.reason}）",
            )
        declared = classify_uid(declared_uid)
        if declared_uid is not None and not declared.is_valid:
            raise RowValidationError(
                "identity_conflict", "save_local_uid 不是合法 UID，与 identity 声明冲突"
            )
        if declared_uid is not None and declared.raw_uid != assessment.raw_uid:
            raise RowValidationError("identity_conflict", "save_local_uid 与 identity.value 不一致")
        return {
            "save_local_uid": assessment.raw_uid,
            "identity": {"kind": "save_local_uid", "value": assessment.raw_uid},
            "uid_status": UID_VALID,
            "uid_reason": None,
        }

    if kind != "unresolved":
        raise RowValidationError("invalid_identity", f"未知 identity.kind {kind!r}")
    if declared_uid not in (None, ""):
        raise RowValidationError("identity_conflict", "unresolved 行不能同时携带 save_local_uid")

    raw_uid = raw_identity.get("raw_uid")
    assessment = classify_uid(raw_uid)
    if assessment.is_valid:
        raise RowValidationError(
            "identity_conflict", "identity.raw_uid 是合法 UID；合法身份必须使用 save_local_uid 模式"
        )
    reason = raw_identity.get("reason") or assessment.reason
    if not reason:
        raise RowValidationError("invalid_identity", "unresolved 行必须给出 reason")
    evidence = raw_identity.get("evidence") or {}
    if not isinstance(evidence, dict):
        raise RowValidationError("invalid_identity", "identity.evidence 必须是对象")
    source_record_id = raw_identity.get("source_record_id")
    if not evidence:
        raise RowValidationError("invalid_identity", "unresolved 行必须带来源证据（identity.evidence）")
    if assessment.status == "missing" and not (source_record_id or evidence):
        raise RowValidationError("invalid_identity", "缺少原始 UID 的观察记录必须带来源证据")
    if len(json.dumps(evidence, ensure_ascii=False, default=str)) > MAX_IDENTITY_EVIDENCE_JSON:
        raise RowValidationError("invalid_identity", "identity.evidence 过大")
    return {
        "save_local_uid": None,
        "identity": {
            "kind": "unresolved",
            "raw_uid": assessment.raw_uid,
            "reason": str(reason)[:64],
            "uid_status": assessment.status,
            "source_record_id": source_record_id,
            "evidence": evidence,
        },
        "uid_status": assessment.status,
        "uid_reason": str(reason)[:64],
    }


class PlayerRecord(BaseModel):
    """A player observation. Any field the scanner cannot read must be ``null``.

    A row is either a legal-UID observation (``save_local_uid`` and/or ``identity.kind='save_local_uid'``)
    or an unresolved observation (``identity.kind='unresolved'``). ``uid_status``/``uid_reason`` are
    derived from the identity mode and overwritten on validation, so a payload cannot declare them.
    """

    model_config = ConfigDict(extra="ignore")

    record_id: str | None = None
    save_local_uid: str | None = Field(default=None, max_length=64)
    identity: PlayerIdentityRecord | None = None
    uid_status: str = "valid"
    uid_reason: str | None = None
    game_unique_id: str | None = None
    name: str = Field(min_length=1, max_length=128)
    birth_date: date | None = None
    age: int | None = Field(default=None, ge=0, le=100)
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
    statistics: list[SeasonStatisticsRecord] = Field(default_factory=list)
    # Profile facts. height_cm/foot/world_reputation are informational; none of them feed a score on their own.
    height_cm: int | None = Field(default=None, ge=120, le=250)
    foot: Literal["left", "right", "both"] | None = None
    world_reputation: int | None = Field(default=None, ge=0)
    availability: AvailabilityRecord | None = None
    ownership: OwnershipRecord | None = None
    agreed_transfer: AgreedTransferRecord | None = None

    @field_validator("name")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be blank")
        return stripped

    @model_validator(mode="after")
    def _identity_mode(self) -> "PlayerRecord":
        """Normalize the identity mode; reuses the row-level rule so both entry points agree."""
        normalized = normalize_player_identity(
            {
                "save_local_uid": self.save_local_uid,
                "identity": self.identity.model_dump() if self.identity is not None else None,
            }
        )
        self.save_local_uid = normalized["save_local_uid"]
        self.identity = PlayerIdentityRecord.model_validate(normalized["identity"])
        self.uid_status = normalized["uid_status"]
        self.uid_reason = normalized["uid_reason"]
        return self

    @property
    def has_valid_uid(self) -> bool:
        """True when this row may be resolved to a save-local player instance."""
        return self.identity is not None and self.identity.kind == "save_local_uid" and bool(self.save_local_uid)


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
        "buy_option",
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
        "loan_with_option",
        "free",
        "end_of_contract",
        "clause_release",
        "swap",
        "youth_promotion",
        "other",
    ] = "other"
    status: Literal[
        "completed", "pending", "future", "agreed", "bid_rejected", "cancelled", "failed", "unknown"
    ] = "unknown"
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
        "fmsuperscout",
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
    """Validate one player row, raising :class:`RowValidationError` with a stable code.

    Legal-UID rows and unresolved rows both validate here; the caller decides what to persist from
    ``record.identity.kind``. ``save_local_uid`` is never synthesized and a sentinel never validates.
    """
    if not isinstance(row.get("name"), str) or not row["name"].strip():
        raise RowValidationError("missing_name", "球员缺少 name")
    try:
        normalized = normalize_player_identity(row)
    except RowValidationError:
        raise
    try:
        return PlayerRecord.model_validate({**row, **normalized})
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
    try:
        return ScanPayload.model_validate(data)
    except ValidationError as exc:
        # 字段级校验失败（例如 scan_id 含路径）是"报文不合法"，应返回 400 而不是 500。
        summary = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in exc.errors()[:5]
        )
        raise ProtocolError(f"扫描报文校验失败：{summary}") from exc


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
