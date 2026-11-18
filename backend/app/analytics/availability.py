"""Player status: listing flags, injury, loans and pending moves over time.

The rules the product spec insists on, encoded here:

* a listing flag is three-valued; a missing observation is ``None`` and is reported as a gap, not as "not listed";
* ``injury_proneness`` is a proneness rating and says nothing about whether the player is injured right now;
* a loan keeps the owner club; it never turns a player into a free agent;
* a purchase option that the source did not report stays ``None`` ("unknown"), never ``False``;
* a club change detected by comparing snapshots is only a candidate event until someone confirms it.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Club, LoanRecord, PlayerAvailability, PlayerInstance, TransferCandidate
from ..utils import iso

ALGORITHM_VERSION = "player-status-1"

#: Flags whose value history is tracked.
FLAG_KEYS = ("listed", "loan_listed", "not_for_sale", "set_for_release")

#: Labels used by the API and the UI.
FLAG_LABELS = {
    "listed": "挂牌出售",
    "loan_listed": "挂牌出租",
    "not_for_sale": "非卖品",
    "set_for_release": "已设置解约",
    "injured": "当前受伤",
}


def player_status(db: Session, instance_id: int) -> dict[str, Any]:
    """Current availability, its history, loan relationships and pending move candidates."""
    instance = db.get(PlayerInstance, instance_id)
    if instance is None:
        raise ValueError(f"球员实例 {instance_id} 不存在")
    rows = list(
        db.scalars(
            select(PlayerAvailability)
            .where(PlayerAvailability.player_instance_id == instance_id)
            .order_by(PlayerAvailability.observed_at)
        )
    )
    loans = list(
        db.scalars(
            select(LoanRecord)
            .where(LoanRecord.player_instance_id == instance_id)
            .order_by(LoanRecord.observed_at)
        )
    )
    candidates = list(
        db.scalars(
            select(TransferCandidate)
            .where(TransferCandidate.player_instance_id == instance_id)
            .order_by(TransferCandidate.detected_at.desc())
        )
    )
    latest = rows[-1] if rows else None
    current = _current_state(latest, db)
    return {
        "instance_id": instance_id,
        "player_name": _instance_name(db, instance_id),
        "current": current,
        "history": [_history_row(row, db) for row in rows],
        "changes": _changes(rows),
        "first_seen": _first_seen(rows),
        "loans": [_loan_row(loan, db) for loan in loans],
        "candidates": [_candidate_row(candidate, db) for candidate in candidates],
        "data_gaps": _gaps(rows, loans, candidates),
        "algorithm_version": ALGORITHM_VERSION,
    }


def _current_state(row: PlayerAvailability | None, db: Session) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "observed_at": iso(row.observed_at),
        "game_date": row.game_date.isoformat() if row.game_date else None,
        "flags": {key: getattr(row, key) for key in FLAG_KEYS},
        "injury": {
            "proneness": row.injury_proneness,
            # A proneness rating is not an injury: ``injured`` stays None when the source is silent.
            "injured": row.injured,
            "start_date": row.injury_start_date.isoformat() if row.injury_start_date else None,
            "expected_return": row.expected_return_date.isoformat() if row.expected_return_date else None,
            "note": row.injury_note,
        },
        "registration": {
            "parent_club": _club_name(db, row.parent_club_id),
            "loan_club": _club_name(db, row.loan_club_id),
            "team_type": row.team_type,
        },
        "agreed_transfer": {
            "to_club": _club_name(db, row.agreed_to_club_id),
            "date": row.agreed_transfer_date.isoformat() if row.agreed_transfer_date else None,
        }
        if row.agreed_to_club_id or row.agreed_transfer_date
        else None,
    }


def _history_row(row: PlayerAvailability, db: Session) -> dict[str, Any]:
    return {
        "observed_at": iso(row.observed_at),
        "flags": {key: getattr(row, key) for key in FLAG_KEYS},
        "injured": row.injured,
        "injury_proneness": row.injury_proneness,
        "parent_club": _club_name(db, row.parent_club_id),
        "loan_club": _club_name(db, row.loan_club_id),
        "source": row.source,
    }


def _changes(rows: list[PlayerAvailability]) -> list[dict[str, Any]]:
    """Every observed transition, with the two timestamps that bracket it."""
    changes: list[dict[str, Any]] = []
    for previous, current in zip(rows, rows[1:]):
        for key in (*FLAG_KEYS, "injured", "injury_proneness", "parent_club_id", "loan_club_id"):
            before = getattr(previous, key)
            after = getattr(current, key)
            if before == after or after is None:
                continue
            changes.append(
                {
                    "field": key,
                    "label": FLAG_LABELS.get(key, key),
                    "from": before,
                    "to": after,
                    "observed_at": iso(current.observed_at),
                    "previous_observed_at": iso(previous.observed_at),
                }
            )
    return changes


def _first_seen(rows: list[PlayerAvailability]) -> dict[str, Any]:
    """When each currently-reported state was first seen and last confirmed."""
    if not rows:
        return {}
    result: dict[str, Any] = {}
    latest = rows[-1]
    for key in (*FLAG_KEYS, "injured"):
        value = getattr(latest, key)
        if value is None:
            continue
        first = latest.observed_at
        for row in reversed(rows[:-1]):
            if getattr(row, key) != value:
                break
            first = row.observed_at
        result[key] = {"value": value, "first_seen_at": iso(first), "last_confirmed_at": iso(latest.observed_at)}
    return result


def _loan_row(loan: LoanRecord, db: Session) -> dict[str, Any]:
    return {
        "id": loan.id,
        "parent_club": _club_name(db, loan.parent_club_id) or loan.parent_club_name,
        "loan_club": _club_name(db, loan.loan_club_id) or loan.loan_club_name,
        "start_date": loan.start_date.isoformat() if loan.start_date else None,
        "end_date": loan.end_date.isoformat() if loan.end_date else None,
        # None means the source never stated it; the UI must show 未知, not 无条款.
        "has_option": loan.has_option,
        "has_obligation": loan.has_obligation,
        "status": loan.status,
        "observed_at": iso(loan.observed_at),
        "source": loan.source,
    }


def _candidate_row(candidate: TransferCandidate, db: Session) -> dict[str, Any]:
    return {
        "id": candidate.id,
        "from_club": _club_name(db, candidate.from_club_id),
        "to_club": _club_name(db, candidate.to_club_id),
        "kind": candidate.kind,
        "status": candidate.status,
        "detected_at": iso(candidate.detected_at),
        "previous_observed_at": iso(candidate.previous_observed_at) if candidate.previous_observed_at else None,
        "confirmed_transfer_id": candidate.confirmed_transfer_id,
    }


def _gaps(
    rows: list[PlayerAvailability], loans: list[LoanRecord], candidates: list[TransferCandidate]
) -> list[str]:
    """What this player's record still cannot answer, stated instead of guessed."""
    gaps: list[str] = []
    if not rows:
        gaps.append("没有任何挂牌/伤病观测记录")
        return gaps
    latest = rows[-1]
    if latest.injured is None:
        gaps.append("数据源未提供当前伤病状态，不能据此判断球员是否受伤")
    if latest.injury_proneness is None:
        gaps.append("数据源未提供伤病倾向")
    for loan in loans:
        if loan.has_option is None:
            gaps.append("租借买断条款未提供，标为未知（不是「无条款」）")
            break
    if any(candidate.status == "candidate" for candidate in candidates):
        gaps.append("存在仅由快照对比发现的俱乐部变化，尚未确认")
    return gaps


def _club_name(db: Session, club_id: int | None) -> str | None:
    if club_id is None:
        return None
    club = db.get(Club, club_id)
    return club.name if club else None


def _instance_name(db: Session, instance_id: int) -> str | None:
    instance = db.get(PlayerInstance, instance_id)
    if instance is None:
        return None
    return instance.player.full_name if instance.player else None
