"""阵容 CSV 导入：把 FM27 阵容名单变成球员与俱乐部/梯队的归属关系。

真实 FMSuperScout 导出没有俱乐部 ID、没有租借与所有权字段（见 ``docs/FMSCOUT_FIELD_COVERAGE.md``），
因此阵容归属只能来自用户导入的名单。这里的规则：

* **稳定 ID 优先**：CSV 给了球员 ID 且能对上 ``save_local_uid`` / ``game_unique_id``，直接关联，置信度 1.0；
* 没有 ID 时用多字段打分：姓名完全一致是前提，再加出生日期、国籍、俱乐部同名加分；
* 低于 :data:`AUTO_LINK_THRESHOLD` 的行**不建立归属**，只作为待确认项返回；低于 :data:`REVIEW_THRESHOLD`
  直接判为未匹配；
* 俱乐部走 :class:`ClubResolver`，与扫描报文共用同一套稳定 ID 与来源标记。
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..clubs import SOURCE_CSV, ClubResolver, normalize_name
from ..models import Club, FmSave, Player, PlayerInstance, PlayerSnapshot, SquadAssignment
from ..utils import iso, utcnow

#: Assignments at or above this score are written automatically.
AUTO_LINK_THRESHOLD = 0.8
#: Below the auto threshold but above this one, the row is reported for manual confirmation (never applied).
REVIEW_THRESHOLD = 0.5

SQUAD_TYPES = ("senior", "reserve", "youth", "unknown")
LOAN_STATUSES = ("none", "loaned_out", "loaned_in", "unknown")

#: Accepted header spellings. Comparison is normalised (lowercase, punctuation stripped).
HEADER_ALIASES = {
    "name": {"name", "player", "playername", "姓名", "球员", "球员姓名"},
    "player_id": {"id", "playerid", "uid", "球员id", "球员编号", "编号"},
    "club": {"club", "team", "clubname", "俱乐部", "球队", "所属俱乐部"},
    "squad": {"squad", "teamtype", "squadtype", "阵容", "阵容类别", "梯队", "队伍"},
    "loan": {"loan", "loanstatus", "status", "租借", "租借状态"},
    "birth_date": {"birthdate", "dob", "出生日期", "生日"},
    "nation": {"nation", "nationality", "国籍"},
}

SQUAD_TYPE_ALIASES = {
    "senior": "senior",
    "first": "senior",
    "firstteam": "senior",
    "一线队": "senior",
    "一线": "senior",
    "reserve": "reserve",
    "reserves": "reserve",
    "预备队": "reserve",
    "预备": "reserve",
    "youth": "youth",
    "u18": "youth",
    "u19": "youth",
    "u21": "youth",
    "academy": "youth",
    "青年队": "youth",
    "青年": "youth",
    "u18队": "youth",
}

LOAN_ALIASES = {
    "": "none",
    "none": "none",
    "no": "none",
    "否": "none",
    "无": "none",
    "-": "none",
    "loanedout": "loaned_out",
    "out": "loaned_out",
    "outonloan": "loaned_out",
    "外租": "loaned_out",
    "租出": "loaned_out",
    "loanedin": "loaned_in",
    "in": "loaned_in",
    "租入": "loaned_in",
    "租借加盟": "loaned_in",
}


@dataclass
class CsvRowResult:
    """One CSV row and what happened to it."""

    index: int
    name: str
    club: str | None
    squad_type: str
    loan_status: str
    status: str  # assigned | review | unmatched | invalid
    confidence: float | None
    instance_id: int | None
    matched_by: list[str] = field(default_factory=list)
    reason: str | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)

    def payload(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "name": self.name,
            "club": self.club,
            "squad_type": self.squad_type,
            "loan_status": self.loan_status,
            "status": self.status,
            "confidence": self.confidence,
            "instance_id": self.instance_id,
            "matched_by": self.matched_by,
            "reason": self.reason,
            "candidates": self.candidates,
        }


@dataclass
class CsvImportResult:
    """Aggregate of one CSV import."""

    rows: list[CsvRowResult] = field(default_factory=list)
    clubs_created: int = 0
    assignments_written: int = 0
    assignments_skipped: int = 0
    duplicate: bool = False
    warnings: list[str] = field(default_factory=list)
    detected_columns: dict[str, str] = field(default_factory=dict)

    def payload(self) -> dict[str, Any]:
        counts = {"assigned": 0, "review": 0, "unmatched": 0, "invalid": 0}
        for row in self.rows:
            counts[row.status] = counts.get(row.status, 0) + 1
        return {
            "counts": counts,
            "total": len(self.rows),
            "clubs_created": self.clubs_created,
            "assignments_written": self.assignments_written,
            "assignments_skipped": self.assignments_skipped,
            "duplicate": self.duplicate,
            "warnings": self.warnings,
            "detected_columns": self.detected_columns,
            "rows": [row.payload() for row in self.rows],
        }


def _normalise_header(value: str) -> str:
    return "".join(ch for ch in value.strip().lower() if ch.isalnum())


def _map_headers(fieldnames: list[str]) -> dict[str, str]:
    """Map our canonical keys to the actual CSV header names."""
    mapping: dict[str, str] = {}
    for raw in fieldnames:
        if raw is None:
            continue
        key = _normalise_header(raw)
        for canonical, aliases in HEADER_ALIASES.items():
            if key in {_normalise_header(alias) for alias in aliases}:
                mapping.setdefault(canonical, raw)
    return mapping


def _squad_type(value: str | None) -> str:
    if not value:
        return "unknown"
    key = _normalise_header(value)
    return SQUAD_TYPE_ALIASES.get(key, "unknown")


def _loan_status(value: str | None) -> str:
    if value is None:
        return "unknown"
    key = _normalise_header(value)
    if key in LOAN_ALIASES:
        return LOAN_ALIASES[key]
    return "unknown"


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    text = value.strip().replace("/", "-")
    for candidate in (text[:10], text):
        try:
            return date.fromisoformat(candidate)
        except ValueError:
            continue
    return None


def import_squad_csv(session: Session, save_id: int, raw: bytes) -> CsvImportResult:
    """Parse and apply one squad CSV.

    The call is idempotent per player: re-importing the same file updates the same ``squad_assignments`` rows
    instead of creating duplicates.
    """
    save = session.get(FmSave, save_id)
    if save is None:
        raise ValueError("存档不存在")
    text = raw.decode("utf-8-sig", errors="replace")
    sample = text[:4096]
    delimiter = "\t" if sample.count("\t") > sample.count(",") else (";" if sample.count(";") > sample.count(",") else ",")
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if not reader.fieldnames:
        raise ValueError("CSV 没有表头")
    columns = _map_headers(list(reader.fieldnames))
    if "name" not in columns:
        raise ValueError("CSV 缺少球员姓名列（可用列名：姓名 / Name / Player）")

    result = CsvImportResult(detected_columns=columns)
    if "player_id" not in columns:
        result.warnings.append("CSV 没有球员 ID 列：只能用姓名/生日/国籍/俱乐部匹配，低置信度行不会被自动关联")
    if "club" not in columns:
        result.warnings.append("CSV 没有俱乐部列：无法建立俱乐部归属，只能作为待确认项")

    resolver = ClubResolver(session, save_id)
    known_clubs_before = session.scalar(
        select(PlayerSnapshot.club_id).where(PlayerSnapshot.club_id.is_not(None)).limit(1)
    )

    for index, raw_row in enumerate(reader, start=1):
        name = (raw_row.get(columns.get("name", "")) or "").strip()
        if not name:
            result.rows.append(CsvRowResult(index, "", None, "unknown", "unknown", "invalid", None, None,
                                            reason="姓名为空"))
            continue
        club_raw = (raw_row.get(columns.get("club", "")) or "").strip() or None
        squad_type = _squad_type(raw_row.get(columns.get("squad", "")))
        loan_status = _loan_status(raw_row.get(columns.get("loan", "")))
        birth = _parse_date(raw_row.get(columns.get("birth_date", "")))
        nation = (raw_row.get(columns.get("nation", "")) or "").strip() or None
        player_id = (raw_row.get(columns.get("player_id", "")) or "").strip() or None

        match = _match_player(session, save_id, player_id, name, birth, nation, club_raw)
        row = CsvRowResult(index, name, club_raw, squad_type, loan_status, "unmatched", match["confidence"],
                           match["instance_id"], match["matched_by"], match["reason"], match["candidates"])
        if match["instance_id"] is None:
            result.rows.append(row)
            continue
        confidence = match["confidence"] or 0.0
        if confidence < AUTO_LINK_THRESHOLD:
            row.status = "review" if confidence >= REVIEW_THRESHOLD else "unmatched"
            row.reason = row.reason or (
                f"置信度 {confidence:.2f} 低于自动关联阈值 {AUTO_LINK_THRESHOLD}，需要人工确认"
            )
            result.rows.append(row)
            continue

        club = None
        if club_raw:
            resolved = resolver.resolve(name=club_raw, source=SOURCE_CSV)
            if resolved is not None:
                club = resolved.club
                if resolved.created:
                    result.clubs_created += 1
        _upsert_assignment(
            session,
            save_id,
            match["instance_id"],
            club,
            club_raw,
            squad_type,
            loan_status,
            confidence,
            raw_row,
        )
        row.status = "assigned"
        row.instance_id = match["instance_id"]
        result.assignments_written += 1
        result.rows.append(row)

    session.flush()
    if known_clubs_before is None and result.clubs_created:
        result.warnings.append("本次 CSV 首次建立了俱乐部记录；请确认俱乐部数据来源与可信度")
    return result


def _match_player(
    session: Session,
    save_id: int,
    player_id: str | None,
    name: str,
    birth: date | None,
    nation: str | None,
    club: str | None,
) -> dict[str, Any]:
    """Match a CSV row to a player instance: stable id first, then a multi-field score.

    Scoring only runs for rows whose name matches exactly (case/accent-insensitive). Everything below the
    auto-link threshold is returned for review and is **not** written.
    """
    if player_id:
        by_uid = session.scalar(
            select(PlayerInstance).where(
                PlayerInstance.fm_save_id == save_id,
                PlayerInstance.save_local_uid == player_id,
            )
        )
        if by_uid is None:
            by_uid = session.scalar(
                select(PlayerInstance).where(
                    PlayerInstance.fm_save_id == save_id,
                    PlayerInstance.game_unique_id == player_id,
                )
            )
        if by_uid is not None:
            return {
                "instance_id": by_uid.id,
                "confidence": 1.0,
                "matched_by": ["player_id"],
                "reason": None,
                "candidates": [],
            }

    normalized = normalize_name(name)
    same_name = [
        player
        for player in session.scalars(select(Player).where(func.lower(Player.full_name) == name.lower()))
        if normalize_name(player.full_name or "") == normalized
    ]
    if not same_name:
        return {
            "instance_id": None,
            "confidence": None,
            "matched_by": [],
            "reason": "没有同名球员",
            "candidates": [],
        }

    club_key = normalize_name(club) if club else ""
    scored: list[tuple[float, int, list[str]]] = []
    for player in same_name:
        instances = list(
            session.scalars(
                select(PlayerInstance).where(
                    PlayerInstance.fm_save_id == save_id,
                    PlayerInstance.player_id == player.id,
                )
            )
        )
        for instance in instances:
            score = 0.5
            matched = ["name"]
            if birth is not None and player.birth_date == birth:
                score += 0.3
                matched.append("birth_date")
            if nation and player.nationality and normalize_name(player.nationality) == normalize_name(nation):
                score += 0.1
                matched.append("nationality")
            latest = session.scalar(
                select(PlayerSnapshot)
                .where(PlayerSnapshot.player_instance_id == instance.id)
                .order_by(PlayerSnapshot.observed_at.desc())
                .limit(1)
            )
            if club_key and latest is not None and latest.club_id is not None:
                snapshot_club = session.get(Club, latest.club_id)
                if snapshot_club is not None and normalize_name(snapshot_club.name) == club_key:
                    score += 0.1
                    matched.append("club")
            scored.append((round(score, 2), instance.id, matched))

    if not scored:
        return {
            "instance_id": None,
            "confidence": None,
            "matched_by": [],
            "reason": "同名球员不在本存档中",
            "candidates": [],
        }
    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, best_id, matched = scored[0]
    if len(scored) > 1 and scored[1][0] == best_score:
        # 同名同分：不自动合并，交由人工确认。
        return {
            "instance_id": best_id,
            "confidence": min(best_score, REVIEW_THRESHOLD - 0.01),
            "matched_by": matched,
            "reason": f"存在 {len(scored)} 条同名候选且分数相同，需要人工确认",
            "candidates": [
                {"instance_id": instance_id, "confidence": score}
                for score, instance_id, _ in scored[:5]
            ],
        }
    return {
        "instance_id": best_id,
        "confidence": best_score,
        "matched_by": matched,
        "reason": None,
        "candidates": [
            {"instance_id": instance_id, "confidence": score}
            for score, instance_id, _ in scored[1:4]
        ],
    }

def _upsert_assignment(
    session: Session,
    save_id: int,
    instance_id: int,
    club,
    club_raw: str | None,
    squad_type: str,
    loan_status: str,
    confidence: float,
    raw_row: dict[str, Any],
) -> None:
    existing = session.scalar(
        select(SquadAssignment).where(
            SquadAssignment.fm_save_id == save_id,
            SquadAssignment.player_instance_id == instance_id,
            SquadAssignment.source == SOURCE_CSV,
        )
    )
    payload = {
        "club_id": club.id if club is not None else None,
        "club_name_raw": club_raw,
        "squad_type": squad_type,
        "loan_status": loan_status,
        "confidence": confidence,
        "observed_at": utcnow(),
        "raw_json": json.dumps(raw_row, ensure_ascii=False),
    }
    if existing is None:
        session.add(
            SquadAssignment(
                fm_save_id=save_id,
                player_instance_id=instance_id,
                source=SOURCE_CSV,
                **payload,
            )
        )
        return
    for key, value in payload.items():
        setattr(existing, key, value)


def csv_template() -> str:
    """A ready-to-fill template the operator can open in Excel."""
    return (
        "姓名,球员ID,俱乐部,阵容,租借,出生日期,国籍\n"
        "示例球员,9001,示例俱乐部,一线队,无,2004-02-06,England\n"
        "租入球员,9002,示例俱乐部,一线队,租入,2003-05-11,Brazil\n"
        "外租球员,9003,另一家俱乐部,预备队,外租,2002-09-01,Spain\n"
    )
