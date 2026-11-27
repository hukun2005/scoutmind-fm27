"""V3.3.2-05.2 俱乐部关联修复、健康度与全局聚合。

设计原则：

* 只用可验证的引用（存档内 ``clubs.uid`` / ``clubs.id``）建立关联；
* 绝不按姓名猜俱乐部，也不跨存档引用；
* 回填只补空值或修复悬空引用，不覆盖已验证的正确关系；
* 所有查询以 ``fm_save_id`` 隔离，结果分页，不把整库对象加载到前端。

状态区分（不能混为一谈）：

``LINKED``              关联到本存档内存在的俱乐部；
``NO_CLUB``             来源明确表示没有俱乐部（当前数据源不提供此标记，通常为 0）；
``UNRESOLVED``          来源提供了俱乐部引用，但当前无法解析到本存档俱乐部；
``INVALID_REFERENCE``   ``player_instances.club_id`` 指向不存在或跨存档的俱乐部；
``MISSING_SOURCE_FIELD`` 来源本次没有提供俱乐部字段，不能判定为关联失败。
"""

from __future__ import annotations

import json
import time
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from ..models import (
    Club,
    DataRepairAudit,
    FmSave,
    Player,
    PlayerInstance,
    PlayerSnapshot,
    SquadAssignment,
    TransferOpportunity,
)
from ..utils import iso, utcnow

RULE_ID = "v3.3.2-05.2"
REPAIR_BATCH_SIZE = 5000
ASSIGNMENT_MIN_CONFIDENCE = 0.8

LINKED = "LINKED"
NO_CLUB = "NO_CLUB"
UNRESOLVED = "UNRESOLVED"
INVALID_REFERENCE = "INVALID_REFERENCE"
MISSING_SOURCE_FIELD = "MISSING_SOURCE_FIELD"

SOURCE_PAYLOAD = "player_club_field"
SOURCE_BACKFILL = "snapshot_backfill"
SOURCE_CSV = "squad_csv"
SOURCE_LEGACY = "legacy"
SOURCE_REPAIR = "backfill_reference"

STATE_LABELS = {
    LINKED: "已关联俱乐部",
    NO_CLUB: "真实无俱乐部",
    UNRESOLVED: "引用暂无法解析",
    INVALID_REFERENCE: "引用无效",
    MISSING_SOURCE_FIELD: "数据源未提供俱乐部字段",
}

STATE_NOTES = {
    NO_CLUB: "当前数据源不提供自由球员/退役标记，无法确认真实无俱乐部。",
    MISSING_SOURCE_FIELD: "导入报文没有提供俱乐部字段；这不是关联失败，也不应自动猜测。",
    UNRESOLVED: "来源提供了俱乐部引用，但存档内没有可验证的俱乐部记录；修复会重新核对。",
    INVALID_REFERENCE: "球员指向了不存在或属于其他存档的俱乐部；修复会重新绑定或清空。",
}


def _save_or_raise(db: Session, save_id: int) -> FmSave:
    save = db.get(FmSave, save_id)
    if save is None:
        raise ValueError("存档不存在")
    return save


def _club_index(db: Session, save_id: int) -> tuple[dict[int, Club], dict[str, int]]:
    """本存档的俱乐部：id -> Club 与 uid -> id。孤立引用只能在本表内验证。"""
    rows = list(db.scalars(select(Club).where(Club.fm_save_id == save_id)))
    return {club.id: club for club in rows}, {club.uid: club.id for club in rows if club.uid}


def _normalize_uid(value: str | None) -> str | None:
    """UID 只做安全标准化：去首尾空白；不做大小写/模糊匹配（那属于猜测）。"""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _resolve_snapshot_club(
    snapshot: PlayerSnapshot | None, valid_ids: set[int], uid_index: dict[str, int]
) -> int | None:
    """从一次观测里取可验证的俱乐部 id：先 id，再原始 uid；都没有返回 None。"""
    if snapshot is None:
        return None
    if snapshot.club_id is not None and snapshot.club_id in valid_ids:
        return snapshot.club_id
    uid = _normalize_uid(snapshot.club_uid)
    if uid is not None:
        return uid_index.get(uid)
    return None


def _opportunity_type_counts(db: Session, save_id: int, club_ids: list[int]) -> dict[int, dict[str, int]]:
    if not club_ids:
        return {}
    rows = db.execute(
        select(
            PlayerInstance.club_id,
            TransferOpportunity.opportunity_type,
            func.count(func.distinct(TransferOpportunity.player_instance_id)),
        )
        .join(TransferOpportunity, TransferOpportunity.player_instance_id == PlayerInstance.id)
        .where(
            TransferOpportunity.fm_save_id == save_id,
            TransferOpportunity.active.is_(True),
            PlayerInstance.club_id.in_(club_ids),
        )
        .group_by(PlayerInstance.club_id, TransferOpportunity.opportunity_type)
    ).all()
    result: dict[int, dict[str, int]] = {}
    for club_id, opportunity_type, count in rows:
        if club_id is None:
            continue
        result.setdefault(int(club_id), {})[str(opportunity_type)] = int(count)
    return result


def _player_counts(db: Session, save_id: int, club_ids: list[int]) -> dict[int, int]:
    if not club_ids:
        return {}
    rows = db.execute(
        select(PlayerInstance.club_id, func.count())
        .where(PlayerInstance.fm_save_id == save_id, PlayerInstance.club_id.in_(club_ids))
        .group_by(PlayerInstance.club_id)
    ).all()
    return {int(club_id): int(count) for club_id, count in rows if club_id is not None}


def health(db: Session, save_id: int) -> dict[str, Any]:
    """关联健康度：状态分类、关联率、来源分布与机会覆盖。"""
    _save_or_raise(db, save_id)
    clubs_by_id, uid_index = _club_index(db, save_id)
    valid_ids = set(clubs_by_id)
    total = int(
        db.scalar(select(func.count()).select_from(PlayerInstance).where(PlayerInstance.fm_save_id == save_id)) or 0
    )

    linked = 0
    invalid = 0
    if valid_ids:
        linked = int(
            db.scalar(
                select(func.count())
                .select_from(PlayerInstance)
                .where(PlayerInstance.fm_save_id == save_id, PlayerInstance.club_id.in_(valid_ids))
            )
            or 0
        )
    invalid = int(
        db.scalar(
            select(func.count())
            .select_from(PlayerInstance)
            .where(
                PlayerInstance.fm_save_id == save_id,
                PlayerInstance.club_id.is_not(None),
                PlayerInstance.club_id.notin_(valid_ids) if valid_ids else PlayerInstance.club_id.is_not(None),
            )
        )
        or 0
    )

    # 空 club_id 且来源提供过引用（最新快照 id/uid 或高置信 CSV 归属）→ UNRESOLVED。
    assignment_exists = (
        select(SquadAssignment.id)
        .where(
            SquadAssignment.fm_save_id == save_id,
            SquadAssignment.player_instance_id == PlayerInstance.id,
            SquadAssignment.club_id.is_not(None),
            SquadAssignment.confidence >= ASSIGNMENT_MIN_CONFIDENCE,
        )
        .exists()
    )
    unresolved = int(
        db.scalar(
            select(func.count())
            .select_from(PlayerInstance)
            .outerjoin(PlayerSnapshot, PlayerSnapshot.id == PlayerInstance.latest_snapshot_id)
            .where(
                PlayerInstance.fm_save_id == save_id,
                PlayerInstance.club_id.is_(None),
                or_(
                    PlayerSnapshot.club_id.is_not(None),
                    PlayerSnapshot.club_uid.is_not(None),
                    assignment_exists,
                ),
            )
        )
        or 0
    )
    missing_source = max(0, total - linked - invalid - unresolved)

    source_rows = db.execute(
        select(PlayerInstance.club_link_source, func.count())
        .where(PlayerInstance.fm_save_id == save_id, PlayerInstance.club_id.is_not(None))
        .group_by(PlayerInstance.club_link_source)
    ).all()
    sources = {(str(row[0]) if row[0] else "unknown"): int(row[1]) for row in source_rows}

    latest_observed_linked = int(
        db.scalar(
            select(func.count())
            .select_from(PlayerInstance)
            .join(PlayerSnapshot, PlayerSnapshot.id == PlayerInstance.latest_snapshot_id)
            .where(
                PlayerInstance.fm_save_id == save_id,
                PlayerSnapshot.club_id.in_(valid_ids) if valid_ids else PlayerInstance.id.is_(None),
            )
        )
        or 0
    )

    clubs_with_players = int(
        db.scalar(
            select(func.count(func.distinct(PlayerInstance.club_id))).where(
                PlayerInstance.fm_save_id == save_id, PlayerInstance.club_id.is_not(None)
            )
        )
        or 0
    )
    opportunities_total = int(
        db.scalar(
            select(func.count())
            .select_from(TransferOpportunity)
            .where(TransferOpportunity.fm_save_id == save_id, TransferOpportunity.active.is_(True))
        )
        or 0
    )
    opportunities_with_club = int(
        db.scalar(
            select(func.count())
            .select_from(TransferOpportunity)
            .join(PlayerInstance, PlayerInstance.id == TransferOpportunity.player_instance_id)
            .where(
                TransferOpportunity.fm_save_id == save_id,
                TransferOpportunity.active.is_(True),
                PlayerInstance.club_id.is_not(None),
            )
        )
        or 0
    )

    known_denominator = linked + unresolved + invalid
    club_link_rate = round(linked / known_denominator, 4) if known_denominator else None
    link_rate_of_total = round(linked / total, 4) if total else None

    if total == 0:
        status = "NO_DATA"
    elif linked == 0 and missing_source > 0:
        status = "BLOCKED_BY_SOURCE"
    elif unresolved or invalid:
        status = "DEGRADED"
    elif missing_source > 0:
        # 部分球员的来源报文没有俱乐部字段：关联率不能代表“关联失败”。
        status = "PARTIAL_SOURCE"
    else:
        status = "OK"

    return {
        "save_id": save_id,
        "status": status,
        "total_players": total,
        "linked": linked,
        "states": {
            LINKED: linked,
            NO_CLUB: 0,
            UNRESOLVED: unresolved,
            INVALID_REFERENCE: invalid,
            MISSING_SOURCE_FIELD: missing_source,
        },
        "state_labels": STATE_LABELS,
        "state_notes": STATE_NOTES,
        "club_link_rate": club_link_rate,
        "link_rate_of_total": link_rate_of_total,
        "latest_observed_linked": latest_observed_linked,
        "sources": sources,
        "clubs": {"total": len(clubs_by_id), "with_players": clubs_with_players, "valid": len(valid_ids)},
        "opportunities": {"total": opportunities_total, "with_club": opportunities_with_club},
    }


def repair(db: Session, save_id: int, dry_run: bool = False) -> dict[str, Any]:
    """分批修复可验证的俱乐部关联；幂等，可重复执行。

    只做四类可确定的操作：悬空引用重绑、空值回填（最新快照）、空值回填（高置信 CSV）、
    已关联但来源未知的补标注。无法验证的引用保持原样并计入 ``unresolved``。
    """
    _save_or_raise(db, save_id)
    started = time.perf_counter()
    clubs_by_id, uid_index = _club_index(db, save_id)
    valid_ids = set(clubs_by_id)

    counts = {
        "scanned": 0,
        "linked": 0,
        "already_linked": 0,
        "backfilled_snapshot": 0,
        "backfilled_assignment": 0,
        "repaired_reference": 0,
        "cleared_invalid": 0,
        "unresolved": 0,
        "failed": 0,
    }
    last_id = 0
    while True:
        rows = db.execute(
            select(PlayerInstance, PlayerSnapshot)
            .outerjoin(PlayerSnapshot, PlayerSnapshot.id == PlayerInstance.latest_snapshot_id)
            .where(PlayerInstance.fm_save_id == save_id, PlayerInstance.id > last_id)
            .order_by(PlayerInstance.id.asc())
            .limit(REPAIR_BATCH_SIZE)
        ).all()
        if not rows:
            break
        ids = [row[0].id for row in rows]
        assignments: dict[int, int] = {}
        if ids:
            for instance_id, club_id in db.execute(
                select(SquadAssignment.player_instance_id, SquadAssignment.club_id)
                .where(
                    SquadAssignment.fm_save_id == save_id,
                    SquadAssignment.player_instance_id.in_(ids),
                    SquadAssignment.club_id.is_not(None),
                    SquadAssignment.confidence >= ASSIGNMENT_MIN_CONFIDENCE,
                )
                .order_by(SquadAssignment.confidence.desc())
            ).all():
                if club_id is not None and int(club_id) in valid_ids:
                    assignments.setdefault(int(instance_id), int(club_id))
        try:
            for instance, snapshot in rows:
                counts["scanned"] += 1
                resolved = _resolve_snapshot_club(snapshot, valid_ids, uid_index)
                if instance.club_id is not None and instance.club_id in valid_ids:
                    counts["already_linked"] += 1
                    if instance.club_link_source is None:
                        instance.club_link_source = (
                            SOURCE_PAYLOAD if resolved == instance.club_id else SOURCE_LEGACY
                        )
                        # 关联时间是“现在建立/确认关联”的时刻，不能用观测时间：观测时间可能来自
                        # 游戏内日期或本地时区，会让增量扫描误判为刚变化。
                        instance.club_linked_at = utcnow()
                    continue
                if instance.club_id is not None:
                    # 悬空/跨存档引用：能验证就重绑，否则清空（不改其他数据）。
                    if resolved is not None:
                        instance.club_id = resolved
                        instance.club_link_source = SOURCE_REPAIR
                        instance.club_linked_at = utcnow()
                        counts["repaired_reference"] += 1
                        counts["linked"] += 1
                    else:
                        instance.club_id = None
                        instance.club_link_source = None
                        instance.club_linked_at = None
                        counts["cleared_invalid"] += 1
                    continue
                if resolved is not None:
                    instance.club_id = resolved
                    instance.club_link_source = SOURCE_BACKFILL
                    instance.club_linked_at = utcnow()
                    counts["backfilled_snapshot"] += 1
                    counts["linked"] += 1
                    continue
                assignment_club = assignments.get(instance.id)
                if assignment_club is not None:
                    instance.club_id = assignment_club
                    instance.club_link_source = SOURCE_CSV
                    instance.club_linked_at = utcnow()
                    counts["backfilled_assignment"] += 1
                    counts["linked"] += 1
                    continue
                counts["unresolved"] += 1
        except Exception:  # noqa: BLE001 - 单批失败不能中断整个回填
            db.rollback()
            counts["failed"] += len(rows)
        last_id = ids[-1]
        if not dry_run:
            db.commit()

    duration_ms = int((time.perf_counter() - started) * 1000)
    summary = {
        "save_id": save_id,
        "dry_run": dry_run,
        "rule_id": RULE_ID,
        **counts,
        "duration_ms": duration_ms,
    }
    if dry_run:
        db.rollback()
        return summary

    db.add(
        DataRepairAudit(
            fm_save_id=save_id,
            entity="instance",
            row_index=0,
            rule_id=RULE_ID,
            rule_version="1",
            level=1,
            field="club_id",
            before_json=None,
            after_json=json.dumps(summary, ensure_ascii=False, sort_keys=True),
            reason="俱乐部关联安全回填（仅可验证引用，幂等）",
            source="club_linkage_repair",
            decision="repaired",
            result="applied",
            requires_review=False,
            executed_at=utcnow(),
        )
    )
    db.commit()
    return summary


def latest_repair_audit(db: Session, save_id: int) -> dict[str, Any] | None:
    row = db.scalar(
        select(DataRepairAudit)
        .where(DataRepairAudit.fm_save_id == save_id, DataRepairAudit.rule_id == RULE_ID)
        .order_by(DataRepairAudit.id.desc())
        .limit(1)
    )
    if row is None:
        return None
    return {
        "audit_id": row.id,
        "executed_at": iso(row.executed_at),
        "decision": row.decision,
        "result": row.result,
        "summary": _loads(row.after_json),
    }


def _loads(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def clubs(db: Session, save_id: int, *, search: str | None = None, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    """全局俱乐部聚合：当前归属球员数与各机会类型计数，分页。"""
    _save_or_raise(db, save_id)
    conditions = [Club.fm_save_id == save_id]
    if search and search.strip():
        conditions.append(Club.name.ilike(f"%{search.strip()}%"))
    total = int(db.scalar(select(func.count()).select_from(Club).where(and_(*conditions))) or 0)
    rows = list(
        db.scalars(
            select(Club).where(and_(*conditions)).order_by(Club.name.asc()).limit(limit).offset(offset)
        )
    )
    club_ids = [club.id for club in rows]
    players = _player_counts(db, save_id, club_ids)
    opportunity_counts = _opportunity_type_counts(db, save_id, club_ids)
    unlinked_players = int(
        db.scalar(
            select(func.count())
            .select_from(PlayerInstance)
            .where(PlayerInstance.fm_save_id == save_id, PlayerInstance.club_id.is_(None))
        )
        or 0
    )
    return {
        "items": [
            {
                "club_id": club.id,
                "uid": club.uid,
                "name": club.name,
                "nation": club.nation,
                "league": club.league,
                "reputation": club.reputation,
                "source": club.source,
                "confidence": club.confidence,
                "players": players.get(club.id, 0),
                "opportunities": opportunity_counts.get(club.id, {}),
                "opportunities_total": sum(opportunity_counts.get(club.id, {}).values()),
            }
            for club in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
        "unlinked_players": unlinked_players,
    }


STATE_TYPE_MAP = {
    "listed": "listed",
    "loan_listed": "loan_listed",
    "release_listed": "release_listed",
    "contract_expiring": "contract_expiring",
    "ai_inferred": "ai_inferred",
}


def club_players(
    db: Session,
    save_id: int,
    club_id: int,
    *,
    state: str = "all",
    sort: str = "score",
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """指定俱乐部的球员（含当前机会类型），分页；不使用历史快照推断当前归属。"""
    _save_or_raise(db, save_id)
    club = db.get(Club, club_id)
    if club is None or club.fm_save_id != save_id:
        raise ValueError("俱乐部不存在")
    conditions = [PlayerInstance.fm_save_id == save_id, PlayerInstance.club_id == club_id]
    if search and search.strip():
        conditions.append(Player.full_name.ilike(f"%{search.strip()}%"))
    opportunity_type = STATE_TYPE_MAP.get(state)
    if state == "unlinked":
        return {"club_id": club_id, "items": [], "total": 0, "limit": limit, "offset": offset, "state": state}
    if opportunity_type:
        conditions.append(
            select(TransferOpportunity.id)
            .where(
                TransferOpportunity.fm_save_id == save_id,
                TransferOpportunity.player_instance_id == PlayerInstance.id,
                TransferOpportunity.active.is_(True),
                TransferOpportunity.opportunity_type == opportunity_type,
            )
            .exists()
        )

    score_subquery = (
        select(func.max(TransferOpportunity.overall_score))
        .where(
            TransferOpportunity.fm_save_id == save_id,
            TransferOpportunity.player_instance_id == PlayerInstance.id,
            TransferOpportunity.active.is_(True),
        )
        .correlate(PlayerInstance)
        .scalar_subquery()
    )
    base = (
        select(PlayerInstance, Player, PlayerSnapshot, score_subquery.label("overall"))
        .join(Player, Player.id == PlayerInstance.player_id)
        .join(PlayerSnapshot, PlayerSnapshot.id == PlayerInstance.latest_snapshot_id)
        .where(and_(*conditions))
    )
    if sort == "age":
        base = base.order_by(PlayerSnapshot.age.asc().nulls_last(), Player.full_name.asc())
    elif sort == "contract":
        base = base.order_by(PlayerSnapshot.contract_end.asc().nulls_last(), Player.full_name.asc())
    elif sort == "score":
        base = base.order_by(score_subquery.desc().nulls_last(), Player.full_name.asc())
    else:
        base = base.order_by(Player.full_name.asc())

    total = int(
        db.scalar(
            select(func.count())
            .select_from(PlayerInstance)
            .join(Player, Player.id == PlayerInstance.player_id)
            .join(PlayerSnapshot, PlayerSnapshot.id == PlayerInstance.latest_snapshot_id)
            .where(and_(*conditions))
        )
        or 0
    )
    rows = db.execute(base.limit(limit).offset(offset)).all()
    instance_ids = [row[0].id for row in rows]
    type_map: dict[int, list[str]] = {}
    if instance_ids:
        for instance_id, entry_type in db.execute(
            select(TransferOpportunity.player_instance_id, TransferOpportunity.opportunity_type)
            .where(
                TransferOpportunity.fm_save_id == save_id,
                TransferOpportunity.active.is_(True),
                TransferOpportunity.player_instance_id.in_(instance_ids),
            )
            .order_by(TransferOpportunity.player_instance_id)
        ).all():
            type_map.setdefault(int(instance_id), []).append(str(entry_type))

    return {
        "club_id": club_id,
        "club_name": club.name,
        "items": [
            {
                "instance_id": row[0].id,
                "player_name": row[1].full_name,
                "club_id": row[0].club_id,
                "club_name": club.name,
                "position": row[2].position,
                "age": row[2].age,
                "market_value": row[2].market_value,
                "contract_end": iso(row[2].contract_end),
                "overall_score": row[3],
                "opportunity_types": type_map.get(row[0].id, []),
                "club_link_source": row[0].club_link_source,
            }
            for row in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
        "state": state,
        "sort": sort,
    }


def unlinked_players(
    db: Session,
    save_id: int,
    *,
    state: str = "all",
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """没有俱乐部归属的球员，并区分“来源未提供”和“引用无法解析”。"""
    _save_or_raise(db, save_id)
    base_conditions = [PlayerInstance.fm_save_id == save_id, PlayerInstance.club_id.is_(None)]
    if search and search.strip():
        base_conditions.append(Player.full_name.ilike(f"%{search.strip()}%"))

    assignment_exists = (
        select(SquadAssignment.id)
        .where(
            SquadAssignment.fm_save_id == save_id,
            SquadAssignment.player_instance_id == PlayerInstance.id,
            SquadAssignment.club_id.is_not(None),
            SquadAssignment.confidence >= ASSIGNMENT_MIN_CONFIDENCE,
        )
        .exists()
    )
    unresolved_condition = or_(
        PlayerSnapshot.club_id.is_not(None),
        PlayerSnapshot.club_uid.is_not(None),
        assignment_exists,
    )
    conditions = list(base_conditions)
    if state == UNRESOLVED:
        conditions.append(unresolved_condition)
    elif state == MISSING_SOURCE_FIELD:
        conditions.append(~unresolved_condition)

    base = (
        select(PlayerInstance, Player, PlayerSnapshot)
        .join(Player, Player.id == PlayerInstance.player_id)
        .outerjoin(PlayerSnapshot, PlayerSnapshot.id == PlayerInstance.latest_snapshot_id)
        .where(and_(*conditions))
        .order_by(Player.full_name.asc())
    )
    total = int(
        db.scalar(
            select(func.count())
            .select_from(PlayerInstance)
            .join(Player, Player.id == PlayerInstance.player_id)
            .outerjoin(PlayerSnapshot, PlayerSnapshot.id == PlayerInstance.latest_snapshot_id)
            .where(and_(*conditions))
        )
        or 0
    )
    rows = db.execute(base.limit(limit).offset(offset)).all()
    instance_ids = [row[0].id for row in rows]
    assignment_clubs: dict[int, int] = {}
    if instance_ids:
        for instance_id, assignment_club in db.execute(
            select(SquadAssignment.player_instance_id, SquadAssignment.club_id)
            .where(
                SquadAssignment.fm_save_id == save_id,
                SquadAssignment.player_instance_id.in_(instance_ids),
                SquadAssignment.club_id.is_not(None),
                SquadAssignment.confidence >= ASSIGNMENT_MIN_CONFIDENCE,
            )
        ).all():
            assignment_clubs[int(instance_id)] = int(assignment_club)

    items = []
    for instance, player, snapshot in rows:
        has_reference = (
            (snapshot is not None and (snapshot.club_id is not None or snapshot.club_uid is not None))
            or instance.id in assignment_clubs
        )
        items.append(
            {
                "instance_id": instance.id,
                "player_name": player.full_name,
                "position": snapshot.position if snapshot is not None else instance.position,
                "age": snapshot.age if snapshot is not None else None,
                "state": UNRESOLVED if has_reference else MISSING_SOURCE_FIELD,
                "reason": "source_reference_unresolved" if has_reference else "source_field_missing",
                "club_uid": snapshot.club_uid if snapshot is not None else None,
            }
        )
    return {"items": items, "total": total, "limit": limit, "offset": offset, "state": state}
