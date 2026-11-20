"""历史转会数据管道（SM-013）。

现实约束：FMSuperScout 导出与 native dump **都不包含历史转会数组**（详见 `docs/TRANSFER-DATA-SOURCES.md`）。
因此这里提供的是"人工/第三方 CSV 或 JSON"的独立导入通道，而不是从内存里凭空读交易：

* 只有数据源真的提供了历史交易，`transfer_history.available` 才为 true；
* 交易状态与类型是两个独立维度，未知值直接拒绝，绝不默认 completed；
* 重复导入按来源记录号去重，并额外做跨来源自然键检测（同球员/日期/双方/类型）；
* 原始行留存在 `transfer_history.raw_payload_json`，每次导入写 `transfer_import_runs` 报告；
* 附加条款逐条写入 `transfer_fee_components`，区分已支付/未触发，绝不并入基础转会费。
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Club, Player, PlayerInstance, Transfer, TransferFeeComponent, TransferImportRun, TransferSource
from ..utils import normalize_name, utcnow
from .amounts import parse_amount

TRANSFER_STATUSES = ("completed", "agreed", "pending", "cancelled", "failed", "unknown")
TRANSFER_TYPES = (
    "permanent",
    "loan",
    "loan_with_option",
    "loan_with_obligation",
    "free_transfer",
    "youth_transfer",
    "release",
    "swap",
    "buyback",
    "unknown",
)

#: 计为"历史成交"的状态（只有 completed 进入实际支出统计）。
COMPLETED_STATUS = "completed"

#: 不进入价格统计的类型（与 analytics.deals 的类别口径一致）。
NON_STAT_TYPES = ("loan", "loan_with_option", "free", "free_transfer", "release", "swap", "youth_transfer")

COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "player_name": ("player_name", "player", "name", "球员", "球员姓名"),
    "transfer_date": ("transfer_date", "date", "日期", "转会日期"),
    "status": ("status", "state", "状态"),
    "transfer_type": ("transfer_type", "type", "类型"),
    "from_club_name": ("from_club", "from", "from_club_name", "原俱乐部", "转出"),
    "to_club_name": ("to_club", "to", "to_club_name", "新俱乐部", "转入"),
    "base_fee": ("base_fee", "fee", "transfer_fee", "转会费"),
    "add_on_fee": ("add_on_fee", "addons", "附加条款"),
    "sell_on_pct": ("sell_on_pct", "sell_on", "二次转会分成"),
    "loan_fee": ("loan_fee", "租借费"),
    "wage_contribution": ("wage_contribution", "工资分摊"),
    "currency": ("currency", "币种"),
    "source_record_id": ("source_record_id", "record_id", "id", "记录号"),
    "announcement_date": ("announcement_date", "announced", "官宣日期"),
    "effective_date": ("effective_date", "effective", "生效日期"),
    "addon_status": ("addon_status", "附加条款状态"),
    "raw": ("raw", "raw_payload"),
}

FIELD_LIMITS = {"player_name": 128, "status": 16, "transfer_type": 32, "currency": 8}


@dataclass
class RowError:
    """一行被拒绝的原因。"""

    row: int
    code: str
    message: str
    raw: dict[str, Any] = field(default_factory=dict)

    def payload(self) -> dict[str, Any]:
        return {"row": self.row, "code": self.code, "message": self.message}


@dataclass
class TransferImportReport:
    """一次导入的完整报告。"""

    source: str
    source_kind: str
    total_rows: int = 0
    imported: int = 0
    duplicates: int = 0
    rejected: int = 0
    completed: int = 0
    agreed: int = 0
    pending: int = 0
    cancelled: int = 0
    loan_rows: int = 0
    addons_pending: int = 0
    addons_paid: int = 0
    errors: list[RowError] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    batch_id: int | None = None
    content_sha256: str | None = None

    def payload(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "source_kind": self.source_kind,
            "batch_id": self.batch_id,
            "content_sha256": self.content_sha256,
            "total_rows": self.total_rows,
            "imported": self.imported,
            "duplicates": self.duplicates,
            "rejected": self.rejected,
            "status_counts": {
                "completed": self.completed,
                "agreed": self.agreed,
                "pending": self.pending,
                "cancelled": self.cancelled,
            },
            "loan_rows": self.loan_rows,
            "addons": {"pending": self.addons_pending, "paid": self.addons_paid},
            "errors": [error.payload() for error in self.errors[:50]],
            "warnings": self.warnings,
            "transfer_history_available": self.completed > 0,
        }


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _float_optional(value: Any) -> float | None:
    """工资分摊/二转分成等非转会费字段：只接受纯数字，失败返回 None（不猜测）。"""
    text_value = _text(value)
    if text_value is None:
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", text_value.replace(",", ""))
    try:
        return float(cleaned) if cleaned not in {"", "-", "."} else None
    except ValueError:
        return None


def _date(value: Any) -> date | None:
    text = _text(value)
    if text is None:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _normalize_headers(row: dict[str, Any]) -> dict[str, Any]:
    """把 CSV/JSON 的列名映射成内部字段名（支持中英文同义词）。"""
    lookup: dict[str, str] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            lookup[alias.lower()] = canonical
    normalized: dict[str, Any] = {}
    for key, value in row.items():
        canonical = lookup.get(str(key).strip().lower(), str(key).strip())
        normalized[canonical] = value
    return normalized


def _rows_from_csv(raw: bytes) -> list[dict[str, Any]]:
    text = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV 没有表头")
    return [dict(row) for row in reader]


def _rows_from_json(raw: bytes) -> list[dict[str, Any]]:
    document = json.loads(raw.decode("utf-8"))
    if isinstance(document, dict):
        for key in ("transfers", "rows", "data"):
            if isinstance(document.get(key), list):
                return [dict(item) for item in document[key]]
        raise ValueError("JSON 需要 transfers / rows / data 数组")
    if isinstance(document, list):
        return [dict(item) for item in document]
    raise ValueError("JSON 顶层必须是数组或带 transfers 的对象")


def _club(db: Session, save_id: int, name: str | None) -> tuple[int | None, str | None]:
    if not name:
        return None, None
    club = db.scalar(select(Club).where(Club.fm_save_id == save_id, Club.name == name).limit(1))
    if club is None:
        # 名称模糊匹配：大小写/空白差异不算不同俱乐部。
        target = normalize_name(name)
        club = db.scalar(
            select(Club).where(Club.fm_save_id == save_id, func.lower(Club.name) == name.lower()).limit(1)
        )
        if club is None and target:
            club = next(
                (
                    item
                    for item in db.scalars(select(Club).where(Club.fm_save_id == save_id))
                    if normalize_name(item.name) == target
                ),
                None,
            )
    return (club.id if club else None), name


def _player_instance(db: Session, save_id: int, player_name: str) -> PlayerInstance | None:
    normalized = normalize_name(player_name)
    if not normalized:
        return None
    candidates = db.scalars(
        select(PlayerInstance)
        .join(Player, Player.id == PlayerInstance.player_id)
        .where(PlayerInstance.fm_save_id == save_id, Player.normalized_name == normalized)
    ).all()
    if len(candidates) == 1:
        return candidates[0]
    return None


def _natural_key(row: dict[str, Any]) -> tuple:
    return (
        normalize_name(str(row.get("player_name") or "")),
        str(row.get("transfer_date") or ""),
        normalize_name(str(row.get("from_club_name") or "")),
        normalize_name(str(row.get("to_club_name") or "")),
        str(row.get("transfer_type") or ""),
    )


def _validate(row: dict[str, Any], line: int, report: TransferImportReport) -> dict[str, Any] | None:
    player = _text(row.get("player_name"))
    if not player:
        report.errors.append(RowError(line, "missing_player", "缺少球员姓名"))
        return None
    status = (_text(row.get("status")) or "").lower()
    if status not in TRANSFER_STATUSES:
        report.errors.append(RowError(line, "invalid_status", f"交易状态必须是 {TRANSFER_STATUSES} 之一，收到 {status!r}"))
        return None
    if status == "unknown":
        report.errors.append(RowError(line, "unknown_status", "状态未知的记录不能写入成交历史，请先确认状态"))
        return None
    transfer_type = (_text(row.get("transfer_type")) or "").lower()
    if transfer_type not in TRANSFER_TYPES:
        report.errors.append(RowError(line, "invalid_type", f"交易类型必须是 {TRANSFER_TYPES} 之一，收到 {transfer_type!r}"))
        return None
    transfer_date = _date(row.get("transfer_date"))
    if transfer_date is None:
        report.errors.append(RowError(line, "invalid_date", "缺少或无法解析转会日期"))
        return None
    if _text(row.get("to_club_name")) is None and transfer_type != "release":
        report.errors.append(RowError(line, "missing_to_club", "缺少转入俱乐部（release 除外）"))
        return None
    currency_hint = _text(row.get("currency"))
    fees: dict[str, object] = {}
    for field, label in (("base_fee", "转会费"), ("add_on_fee", "附加条款"), ("loan_fee", "租借费")):
        parsed = parse_amount(row.get(field), currency_hint)
        if parsed.error:
            code = "missing_currency" if "缺少币种" in parsed.error else "invalid_amount"
            report.errors.append(RowError(line, code, f"{label}：{parsed.error}"))
            return None
        fees[field] = parsed
    if currency_hint is None and (fees["base_fee"].amount is not None or fees["add_on_fee"].amount is not None or fees["loan_fee"].amount is not None):
        report.errors.append(RowError(line, "missing_currency", "金额存在但没有 currency 列或货币符号"))
        return None

    currencies = {parsed.currency for parsed in fees.values() if parsed.currency}
    if currency_hint and currencies and currency_hint.upper() not in currencies:
        report.errors.append(
            RowError(line, "mixed_currency", f"currency 列是 {currency_hint}，但金额带 {sorted(currencies)} 符号")
        )
        return None
    if len(currencies) > 1:
        report.errors.append(RowError(line, "mixed_currency", f"同一行出现多个币种：{sorted(currencies)}"))
        return None
    currency = next(iter(currencies), None)
    if currency is None:
        currency = (currency_hint or "").upper()[: FIELD_LIMITS["currency"]] or None

    return {
        "player_name": player[: FIELD_LIMITS["player_name"]],
        "status": status,
        "transfer_type": transfer_type,
        "transfer_date": transfer_date,
        "announcement_date": _date(row.get("announcement_date")),
        "effective_date": _date(row.get("effective_date")),
        "from_club_name": _text(row.get("from_club_name")),
        "to_club_name": _text(row.get("to_club_name")),
        "base_fee": fees["base_fee"].amount,
        "add_on_fee": fees["add_on_fee"].amount,
        "loan_fee": fees["loan_fee"].amount,
        "base_fee_raw": fees["base_fee"].raw,
        "add_on_fee_raw": fees["add_on_fee"].raw,
        "loan_fee_raw": fees["loan_fee"].raw,
        "currency_original": currency_hint or (fees["base_fee"].currency if fees["base_fee"].currency else None),
        "wage_contribution": _float_optional(row.get("wage_contribution")),
        "sell_on_pct": _float_optional(row.get("sell_on_pct")),
        "addon_status": (_text(row.get("addon_status")) or "pending").lower(),
        "currency": currency or ("EUR" if currency_hint is None else currency_hint.upper())[: FIELD_LIMITS["currency"]],
        "source_record_id": _text(row.get("source_record_id")),
    }


def import_transfer_rows(
    db: Session,
    save_id: int,
    rows: Iterable[dict[str, Any]],
    *,
    source_name: str,
    source_kind: str,
    content_sha256: str | None = None,
) -> TransferImportReport:
    """导入一组历史交易行；返回带错误明细的报告，调用方负责 commit。"""
    report = TransferImportReport(source=source_name, source_kind=source_kind, content_sha256=content_sha256)
    source = db.scalar(select(TransferSource).where(TransferSource.name == source_name))
    if source is None:
        source = TransferSource(
            name=source_name,
            kind=source_kind,
            license="用户提供",
            supports_history=True,
            notes="由 /imports/transfers/history 导入",
        )
        db.add(source)
        db.flush()

    existing_natural = {
        _natural_key(
            {
                "player_name": transfer.player_name,
                "transfer_date": transfer.transfer_date.isoformat(),
                "from_club_name": transfer.from_club_name,
                "to_club_name": transfer.to_club_name,
                "transfer_type": transfer.transfer_type,
            }
        )
        for transfer in db.scalars(select(Transfer).where(Transfer.fm_save_id == save_id))
    }

    for index, raw_row in enumerate(rows, start=1):
        report.total_rows += 1
        normalized = _normalize_headers(raw_row)
        valid = _validate(normalized, index, report)
        if valid is None:
            report.rejected += 1
            continue

        record_id = valid["source_record_id"] or hashlib.sha256(
            json.dumps(normalized, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()[:24]
        duplicate = db.scalar(
            select(Transfer.id).where(Transfer.fm_save_id == save_id, Transfer.source_record_id == record_id)
        )
        if duplicate is None and _natural_key(valid) in existing_natural:
            duplicate = "natural"
        if duplicate is not None:
            report.duplicates += 1
            continue

        from_id, from_name = _club(db, save_id, valid["from_club_name"])
        to_id, to_name = _club(db, save_id, valid["to_club_name"])
        instance = _player_instance(db, save_id, valid["player_name"])
        effective_fee = valid["base_fee"]
        if valid["status"] == COMPLETED_STATUS and effective_fee is not None and valid["add_on_fee"]:
            # 已支付的附加条款才计入实际成交金额；未触发的只作为潜在金额保留。
            if valid["addon_status"] in {"paid", "triggered"}:
                effective_fee += valid["add_on_fee"]

        transfer = Transfer(
            fm_save_id=save_id,
            source_record_id=record_id,
            player_instance_id=instance.id if instance else None,
            player_name=valid["player_name"],
            from_club_id=from_id,
            to_club_id=to_id,
            from_club_name=from_name,
            to_club_name=to_name,
            transfer_type=valid["transfer_type"],
            status=valid["status"],
            transfer_date=valid["transfer_date"],
            announcement_date=valid["announcement_date"],
            effective_date=valid["effective_date"],
            season=_season(valid["transfer_date"]),
            currency=valid["currency"],
            currency_original=valid["currency_original"],
            base_fee=valid["base_fee"],
            fee_raw=valid["base_fee_raw"],
            addons_raw=valid["add_on_fee_raw"],
            loan_fee_raw=valid["loan_fee_raw"],
            effective_fee=effective_fee,
            addons_potential=valid["add_on_fee"],
            loan_fee=valid["loan_fee"],
            wage_contribution=valid["wage_contribution"],
            sell_on_clause_pct=valid["sell_on_pct"],
            source=source_name,
            source_id=source.id,
            confidence=0.8 if instance else 0.5,
            raw_payload_json=json.dumps(raw_row, ensure_ascii=False, default=str),
        )
        db.add(transfer)
        db.flush()
        existing_natural.add(_natural_key(valid))
        report.imported += 1
        report.__dict__[valid["status"]] = report.__dict__.get(valid["status"], 0) + 1
        if valid["transfer_type"].startswith("loan"):
            report.loan_rows += 1

        if valid["add_on_fee"]:
            paid = valid["addon_status"] in {"paid", "triggered"}
            db.add(
                TransferFeeComponent(
                    transfer_id=transfer.id,
                    component_type="addon",
                    amount=valid["add_on_fee"],
                    status="paid" if paid else "pending",
                    condition="导入数据源的附加条款",
                )
            )
            if paid:
                report.addons_paid += 1
            else:
                report.addons_pending += 1

    run = TransferImportRun(
        fm_save_id=save_id,
        source_id=source.id,
        source_kind=source_kind,
        content_sha256=content_sha256,
        total_rows=report.total_rows,
        imported=report.imported,
        duplicates=report.duplicates,
        rejected=report.rejected,
        report_json=json.dumps(report.payload(), ensure_ascii=False, default=str),
        status="completed",
    )
    db.add(run)
    db.flush()
    report.batch_id = run.id
    return report


def _season(value: date) -> str:
    start = value.year if value.month >= 7 else value.year - 1
    return f"{start}/{str(start + 1)[-2:]}"


def import_transfer_file(
    db: Session,
    save_id: int,
    raw: bytes,
    *,
    filename: str | None = None,
    source_name: str | None = None,
) -> TransferImportReport:
    """按扩展名/内容选择 CSV 或 JSON 解析器并导入。"""
    content_sha = hashlib.sha256(raw).hexdigest()
    name = (filename or "").lower()
    if name.endswith(".csv") or raw.lstrip()[:1] not in {b"{", b"["}:
        rows = _rows_from_csv(raw)
        kind = "csv"
    else:
        rows = _rows_from_json(raw)
        kind = "json"
    source = source_name or (filename or "manual")[:64]
    return import_transfer_rows(
        db, save_id, rows, source_name=source, source_kind=kind, content_sha256=content_sha
    )


def transfer_coverage(db: Session, save_id: int) -> dict[str, Any]:
    """历史转会覆盖率：只有真实 completed 记录才认为"历史可用"。"""
    counts = dict(
        db.execute(
            select(Transfer.status, func.count()).where(Transfer.fm_save_id == save_id).group_by(Transfer.status)
        ).all()
    )
    type_counts = dict(
        db.execute(
            select(Transfer.transfer_type, func.count())
            .where(Transfer.fm_save_id == save_id)
            .group_by(Transfer.transfer_type)
        ).all()
    )
    completed = int(counts.get("completed", 0))
    runs = list(
        db.scalars(
            select(TransferImportRun)
            .where(TransferImportRun.fm_save_id == save_id)
            .order_by(TransferImportRun.id.desc())
            .limit(10)
        )
    )
    return {
        "transfer_history": {
            "available": completed > 0,
            "completed": completed,
            "note": None if completed else "没有已验证的历史成交记录；agreed/pending 不算历史",
        },
        "status_counts": {key: int(value) for key, value in counts.items()},
        "type_counts": {key: int(value) for key, value in type_counts.items()},
        "sources": [
            {
                "batch_id": run.id,
                "source_kind": run.source_kind,
                "total_rows": run.total_rows,
                "imported": run.imported,
                "duplicates": run.duplicates,
                "rejected": run.rejected,
                "created_at": run.created_at.isoformat() if run.created_at else None,
            }
            for run in runs
        ],
        "coverage_note": "覆盖率只统计已导入的历史记录；缺失的来源必须在报告中注明，不能按 0 处理",
    }
