"""V3.3.2-08 AI Transfer Director 在线持续学习引擎。

只做四件事：

1. 按游标增量读取新落地的真实数据（转会、租借、挂牌、俱乐部变化候选、用户确认谈判）。
2. 生成可去重的学习事件，并区分 ``CONFIRMED / OBSERVED / INFERRED / UNVERIFIED / REJECTED``。
3. 增量更新全球俱乐部画像，并把与用户俱乐部发生交易的俱乐部升级为重点学习对象。
4. 为报价引擎提供“学习调整层”；样本不足时明确回退，不编造调整。

约束：

* 所有读写以 ``fm_save_id`` 隔离；不同存档的同一俱乐部是不同学习实体。
* 原生读取器不提供转会历史，``TRANSFER_COMPLETED`` 只能来自真实导入；没有导入就没有成交样本。
* 合成/演示数据永远不进入正式学习库。
* 无法确认球员身份的事件不进入学习统计。
"""

from __future__ import annotations

import bisect
import hashlib
import json
import math
from datetime import date, datetime
from typing import Any, Callable, Iterable

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import (
    Club,
    ClubTransferProfile,
    FmSave,
    ImportJob,
    LoanRecord,
    NegotiationEvent,
    Player,
    PlayerAvailability,
    PlayerInstance,
    PlayerSnapshot,
    Transfer,
    TransferEventCandidate,
    TransferFeedback,
    TransferLearningActivity,
    TransferLearningEvent,
    TransferLearningSession,
    TransferNegotiation,
)
from ..utils import iso, utcnow
from . import transfer_strategy

ENGINE_VERSION = "transfer-learning-1"

LEARNING_STATUSES = (
    "STOPPED",
    "INITIALIZING",
    "MONITORING",
    "PROCESSING",
    "LEARNING",
    "PAUSED",
    "RECOVERING",
    "PARTIAL",
    "FAILED",
)
STATUS_LABELS = {
    "STOPPED": "尚未开始",
    "INITIALIZING": "正在初始化",
    "MONITORING": "正在监视转会市场",
    "PROCESSING": "正在处理新事件",
    "LEARNING": "正在更新学习结果",
    "PAUSED": "自动学习已暂停",
    "RECOVERING": "正在恢复学习",
    "PARTIAL": "本次学习只完成了一部分",
    "FAILED": "本次学习未能完成",
}

MARKET_EVENTS = (
    "PLAYER_LISTED",
    "PLAYER_UNLISTED",
    "PLAYER_LOAN_LISTED",
    "PLAYER_RELEASED",
)
TRANSFER_EVENTS = ("TRANSFER_COMPLETED", "TRANSFER_CONFIRMED", "TRANSFER_STATUS_CHANGED")
LOAN_EVENTS = (
    "LOAN_COMPLETED",
    "LOAN_RETURNED",
    "LOAN_OPTION_RECORDED",
    "LOAN_OBLIGATION_RECORDED",
)
OFFER_EVENTS = (
    "OFFER_SUBMITTED",
    "OFFER_ACCEPTED",
    "OFFER_REJECTED",
    "COUNTER_OFFER_RECEIVED",
    "NEGOTIATION_CANCELLED",
)
OBSERVED_EVENTS = ("CLUB_CHANGE_OBSERVED",)
EVENT_TYPES = MARKET_EVENTS + TRANSFER_EVENTS + LOAN_EVENTS + OFFER_EVENTS + OBSERVED_EVENTS
VERIFICATION_STATUSES = ("CONFIRMED", "OBSERVED", "INFERRED", "UNVERIFIED", "REJECTED")

#: 只有真实成交/租借进入价格与频率统计。
ELIGIBLE_EVENTS = {"TRANSFER_COMPLETED", "LOAN_COMPLETED"}

#: 金额上限：超过视为解析异常，不使用该值。
AMOUNT_LIMIT = 1_000_000_000_000.0
MAX_LIST = 200
MAX_PLAYERS = 500
DEFAULT_BATCH = 500
ADJUSTMENT_MIN_SAMPLES = 3
ADJUSTMENT_BOUNDS = (0.85, 1.15)
UNKNOWN_CURRENCY = "UNKNOWN"


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------


def _loads(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _dumps(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _amount(value: float | None) -> float | None:
    """异常金额返回 None（负数、非有限值、超出上限）。"""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0 or number > AMOUNT_LIMIT:
        return None
    return number


def _currency(value: str | None) -> str | None:
    code = (value or "").strip().upper()
    if not code or code == UNKNOWN_CURRENCY:
        return None
    return code[:8]


def _fingerprint(*parts: Any) -> str:
    raw = "|".join("" if part is None else str(part) for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _is_synthetic(source: str | None) -> bool:
    return (source or "").lower().startswith(("synthetic", "demo", "fixture"))


def _identity(instance: PlayerInstance | None, fallback: str | None = None) -> str | None:
    if instance is not None:
        return f"{instance.save_local_uid}#{int(instance.uid_occurrence or 0)}"
    return fallback


def _chunks(items: list[int], size: int = 800) -> Iterable[list[int]]:
    for index in range(0, len(items), size):
        yield items[index: index + size]


# ---------------------------------------------------------------------------
# 会话与游标
# ---------------------------------------------------------------------------


def get_session(db: Session, save_id: int) -> TransferLearningSession | None:
    return db.scalar(
        select(TransferLearningSession).where(TransferLearningSession.fm_save_id == save_id)
    )


def _max_ids(db: Session, save_id: int) -> dict[str, int]:
    """当前存档各数据源的最大 ID（用于诊断与基线核对）。"""
    return {
        "last_transfer_id": int(db.scalar(select(func.max(Transfer.id)).where(Transfer.fm_save_id == save_id)) or 0),
        "last_loan_id": int(db.scalar(select(func.max(LoanRecord.id)).where(LoanRecord.fm_save_id == save_id)) or 0),
        "last_availability_id": int(
            db.scalar(
                select(func.max(PlayerAvailability.id))
                .join(PlayerInstance, PlayerInstance.id == PlayerAvailability.player_instance_id)
                .where(PlayerInstance.fm_save_id == save_id)
            )
            or 0
        ),
        "last_candidate_id": int(
            db.scalar(
                select(func.max(TransferEventCandidate.id)).where(
                    TransferEventCandidate.fm_save_id == save_id
                )
            )
            or 0
        ),
        "last_negotiation_event_id": int(
            db.scalar(
                select(func.max(NegotiationEvent.id)).where(NegotiationEvent.fm_save_id == save_id)
            )
            or 0
        ),
        "last_feedback_id": int(
            db.scalar(
                select(func.max(TransferFeedback.id)).where(TransferFeedback.fm_save_id == save_id)
            )
            or 0
        ),
        "last_import_job_id": int(
            db.scalar(select(func.max(ImportJob.id)).where(ImportJob.fm_save_id == save_id)) or 0
        ),
    }


def _ensure_session(db: Session, save_id: int) -> tuple[TransferLearningSession, bool]:
    session = get_session(db, save_id)
    if session is not None:
        return session, False
    cursor = {
        "last_transfer_id": 0,
        "last_loan_id": 0,
        "last_availability_id": 0,
        "last_candidate_id": 0,
        "last_negotiation_event_id": 0,
        "last_feedback_id": 0,
    }
    session = TransferLearningSession(
        fm_save_id=save_id,
        status="MONITORING",
        enabled=True,
        cursor_json=_dumps(cursor),
        last_import_job_id=int(
            db.scalar(select(func.max(ImportJob.id)).where(ImportJob.fm_save_id == save_id)) or 0
        )
        or None,
        last_monitor_at=_last_monitor_at(db, save_id),
    )
    db.add(session)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = get_session(db, save_id)
        if existing is None:
            raise
        return existing, False
    db.refresh(session)
    return session, True


def _cursor(session: TransferLearningSession) -> dict[str, int]:
    raw = _loads(session.cursor_json)
    defaults = {
        "last_transfer_id": 0,
        "last_loan_id": 0,
        "last_availability_id": 0,
        "last_candidate_id": 0,
        "last_negotiation_event_id": 0,
        "last_feedback_id": 0,
    }
    return {key: int(raw.get(key) or 0) for key in defaults}


def _last_monitor_at(db: Session, save_id: int) -> datetime | None:
    return db.scalar(
        select(func.max(ImportJob.finished_at)).where(
            ImportJob.fm_save_id == save_id, ImportJob.finished_at.is_not(None)
        )
    ) or db.scalar(
        select(func.max(ImportJob.received_at)).where(ImportJob.fm_save_id == save_id)
    )


def set_enabled(db: Session, save_id: int, enabled: bool) -> dict[str, Any]:
    session, _ = _ensure_session(db, save_id)
    session.enabled = bool(enabled)
    session.status = "MONITORING" if enabled else "PAUSED"
    db.commit()
    return status(db, save_id)


# ---------------------------------------------------------------------------
# 事件构造与写入
# ---------------------------------------------------------------------------


def _event(
    *,
    save_id: int,
    event_key: str,
    event_type: str,
    transaction_type: str | None,
    verification: str,
    player_instance_id: int | None,
    player_identity: str | None,
    buying_club_id: int | None,
    selling_club_id: int | None,
    amount: float | None,
    currency: str | None,
    game_date: date | None,
    observed_at: datetime,
    source: str,
    eligible: bool,
    evidence: dict[str, Any],
) -> TransferLearningEvent:
    return TransferLearningEvent(
        fm_save_id=save_id,
        event_key=event_key,
        event_type=event_type,
        transaction_type=transaction_type,
        verification_status=verification,
        player_instance_id=player_instance_id,
        player_identity=player_identity,
        buying_club_id=buying_club_id,
        selling_club_id=selling_club_id,
        amount=amount,
        currency=currency,
        game_date=game_date,
        observed_at=observed_at,
        source=source[:32],
        learning_eligible=eligible,
        evidence_json=_dumps(evidence),
    )


def _persist_events(
    db: Session, events: list[TransferLearningEvent]
) -> tuple[list[TransferLearningEvent], int]:
    """按存档内指纹去重写入；返回 (created_rows, skipped)。"""
    if not events:
        return [], 0
    save_id = events[0].fm_save_id
    keys = [row.event_key for row in events]
    existing: set[str] = set()
    for chunk in _chunks(keys):
        existing.update(
            db.scalars(
                select(TransferLearningEvent.event_key).where(
                    TransferLearningEvent.fm_save_id == save_id,
                    TransferLearningEvent.event_key.in_(chunk),
                )
            )
        )
    created: list[TransferLearningEvent] = []
    skipped = 0
    pending: list[TransferLearningEvent] = []
    for row in events:
        if row.event_key in existing:
            skipped += 1
            continue
        existing.add(row.event_key)
        pending.append(row)
    if not pending:
        return [], skipped
    # 常规路径：批量插入一次提交。指纹预检已过滤重复，60k 级导入不会被逐条
    # SAVEPOINT 放大成几万次往返。
    try:
        db.add_all(pending)
        db.commit()
        return pending, skipped
    except IntegrityError:
        db.rollback()
    # 并发兜底：唯一约束冲突时逐条写入，冲突行计入跳过。
    existing.clear()
    for chunk in _chunks([row.event_key for row in pending]):
        existing.update(
            db.scalars(
                select(TransferLearningEvent.event_key).where(
                    TransferLearningEvent.fm_save_id == save_id,
                    TransferLearningEvent.event_key.in_(chunk),
                )
            )
        )
    for row in pending:
        if row.event_key in existing:
            skipped += 1
            continue
        try:
            with db.begin_nested():
                db.add(row)
                db.flush()
        except IntegrityError:
            skipped += 1
            continue
        existing.add(row.event_key)
        created.append(row)
    db.commit()
    return created, skipped


def _profile_snapshot(instance_id: int | None, db: Session) -> dict[str, Any]:
    if instance_id is None:
        return {}
    row = db.execute(
        select(PlayerSnapshot)
        .where(PlayerSnapshot.player_instance_id == instance_id)
        .order_by(PlayerSnapshot.observed_at.desc(), PlayerSnapshot.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        return {}
    return {
        "age": row.age,
        "position": row.position,
        "market_value": row.market_value,
    }


def _batch_instances(db: Session, save_id: int, ids: set[int]) -> dict[int, PlayerInstance]:
    if not ids:
        return {}
    return {
        int(row.id): row
        for row in db.scalars(
            select(PlayerInstance).where(
                PlayerInstance.fm_save_id == save_id, PlayerInstance.id.in_(ids)
            )
        )
    }


def _batch_snapshot_evidence(
    db: Session, instances: dict[int, PlayerInstance]
) -> dict[int, dict[str, Any]]:
    snapshot_ids = {
        int(row.latest_snapshot_id) for row in instances.values() if row.latest_snapshot_id
    }
    if not snapshot_ids:
        return {}
    snapshots = {
        int(row.id): row
        for row in db.scalars(select(PlayerSnapshot).where(PlayerSnapshot.id.in_(snapshot_ids)))
    }
    evidence: dict[int, dict[str, Any]] = {}
    for instance_id, instance in instances.items():
        snapshot = snapshots.get(int(instance.latest_snapshot_id or 0))
        evidence[instance_id] = (
            {"age": snapshot.age, "position": snapshot.position, "market_value": snapshot.market_value}
            if snapshot is not None
            else {}
        )
    return evidence


def _batch_previous_availability(
    db: Session, rows: list[PlayerAvailability]
) -> dict[int, PlayerAvailability | None]:
    if not rows:
        return {}
    instance_ids = {row.player_instance_id for row in rows}
    max_id = max(row.id for row in rows)
    history = list(
        db.scalars(
            select(PlayerAvailability)
            .where(
                PlayerAvailability.player_instance_id.in_(instance_ids),
                PlayerAvailability.id <= max_id,
            )
            .order_by(PlayerAvailability.player_instance_id, PlayerAvailability.id)
        )
    )
    by_instance: dict[int, list[PlayerAvailability]] = {}
    for item in history:
        by_instance.setdefault(int(item.player_instance_id), []).append(item)
    id_lists = {key: [item.id for item in items] for key, items in by_instance.items()}
    previous: dict[int, PlayerAvailability | None] = {}
    for row in rows:
        items = by_instance.get(int(row.player_instance_id), [])
        position = bisect.bisect_left(id_lists.get(int(row.player_instance_id), []), row.id)
        previous[row.id] = items[position - 1] if position > 0 else None
    return previous


def _transfer_event(
    db: Session,
    save_id: int,
    row: Transfer,
    *,
    instances: dict[int, PlayerInstance] | None = None,
    snapshots: dict[int, dict[str, Any]] | None = None,
) -> TransferLearningEvent | None:
    if _is_synthetic(row.source):
        return None
    if row.player_instance_id is None:
        return None
    if instances is not None:
        instance = instances.get(int(row.player_instance_id))
    else:
        instance = db.get(PlayerInstance, row.player_instance_id)
    if instance is None or instance.fm_save_id != save_id:
        return None
    amount = _amount(row.fee_paid if row.fee_paid is not None else row.base_fee)
    if amount is None and row.effective_fee is not None:
        amount = _amount(row.effective_fee)
    currency = _currency(row.currency_original)
    identity = _identity(instance)
    if row.status == "completed":
        if row.transfer_type == "loan":
            event_type = "LOAN_COMPLETED"
            transaction_type = "loan"
        elif row.transfer_type == "free":
            event_type = "TRANSFER_COMPLETED"
            transaction_type = "free"
        else:
            event_type = "TRANSFER_COMPLETED"
            transaction_type = "permanent"
        verification = "CONFIRMED"
        eligible = True
    elif row.status == "agreed":
        event_type = "TRANSFER_CONFIRMED"
        transaction_type = "loan" if row.transfer_type == "loan" else "permanent"
        verification = "CONFIRMED"
        eligible = False
    else:
        return None
    clubs_known = row.from_club_id is not None or row.to_club_id is not None
    if not clubs_known:
        verification = "UNVERIFIED"
        eligible = False
    observed = row.updated_at or row.created_at or utcnow()
    evidence = {
        "transfer_id": row.id,
        "source_record_id": row.source_record_id,
        "status": row.status,
        "transfer_type": row.transfer_type,
        "fee_raw": row.fee_raw,
        "currency_original": row.currency_original,
        "clubs_known": clubs_known,
        **(
            snapshots.get(int(instance.id), {})
            if snapshots is not None
            else _profile_snapshot(row.player_instance_id, db)
        ),
    }
    return _event(
        save_id=save_id,
        event_key=_fingerprint(
            save_id, event_type, identity, row.from_club_id, row.to_club_id,
            row.transfer_date, amount, row.source_record_id,
        ),
        event_type=event_type,
        transaction_type=transaction_type,
        verification=verification,
        player_instance_id=instance.id,
        player_identity=identity,
        buying_club_id=row.to_club_id,
        selling_club_id=row.from_club_id,
        amount=amount,
        currency=currency,
        game_date=row.transfer_date,
        observed_at=observed,
        source=row.source or "import",
        eligible=eligible,
        evidence=evidence,
    )


def _availability_events(
    save_id: int,
    row: PlayerAvailability,
    previous: PlayerAvailability | None,
    instance: PlayerInstance | None,
) -> list[TransferLearningEvent]:
    if previous is None or instance is None or instance.fm_save_id != save_id:
        return []
    identity = _identity(instance)
    club_id = instance.club_id
    events: list[TransferLearningEvent] = []
    observed = row.observed_at or utcnow()
    game_date = row.game_date

    def add(flag: str, published: str, event_type: str) -> None:
        events.append(
            _event(
                save_id=save_id,
                event_key=_fingerprint(save_id, event_type, identity, club_id, flag, observed, published),
                event_type=event_type,
                transaction_type="loan" if flag == "loan_listed" else "release" if flag == "set_for_release" else "market",
                verification="CONFIRMED",
                player_instance_id=instance.id,
                player_identity=identity,
                buying_club_id=None,
                selling_club_id=club_id,
                amount=None,
                currency=None,
                game_date=game_date,
                observed_at=observed,
                source=row.source or "reader",
                eligible=False,
                evidence={
                    "availability_id": row.id,
                    "previous_availability_id": previous.id,
                    "flag": flag,
                    "previous": bool(getattr(previous, flag)),
                    "current": bool(getattr(row, flag)),
                },
            )
        )

    if previous.listed is False and row.listed is True:
        add("listed", "true", "PLAYER_LISTED")
    elif previous.listed is True and row.listed is False:
        add("listed", "false", "PLAYER_UNLISTED")
    if previous.loan_listed is False and row.loan_listed is True:
        add("loan_listed", "true", "PLAYER_LOAN_LISTED")
    elif previous.loan_listed is True and row.loan_listed is False:
        add("loan_listed", "false", "PLAYER_UNLISTED")
    if previous.set_for_release is False and row.set_for_release is True:
        add("set_for_release", "true", "PLAYER_RELEASED")
    return events


def _candidate_event(
    db: Session, save_id: int, row: TransferEventCandidate
) -> TransferLearningEvent | None:
    instance = db.get(PlayerInstance, row.player_instance_id)
    if instance is None or instance.fm_save_id != save_id:
        return None
    identity = _identity(instance)
    return _event(
        save_id=save_id,
        event_key=_fingerprint(
            save_id, "CLUB_CHANGE_OBSERVED", identity, row.from_club_id, row.to_club_id, row.game_date
        ),
        event_type="CLUB_CHANGE_OBSERVED",
        transaction_type="unknown",
        verification="UNVERIFIED",
        player_instance_id=instance.id,
        player_identity=identity,
        buying_club_id=row.to_club_id,
        selling_club_id=row.from_club_id,
        amount=None,
        currency=None,
        game_date=row.game_date,
        observed_at=row.updated_at or row.created_at or utcnow(),
        source="snapshot_diff",
        eligible=False,
        evidence={"candidate_id": row.id, "evidence_level": row.evidence_level},
    )


def _loan_events(db: Session, save_id: int, row: LoanRecord) -> list[TransferLearningEvent]:
    if row.player_instance_id is None:
        return []
    instance = db.get(PlayerInstance, row.player_instance_id)
    if instance is None or instance.fm_save_id != save_id:
        return []
    identity = _identity(instance)
    events: list[TransferLearningEvent] = []
    if row.has_option is True:
        events.append(
            _event(
                save_id=save_id,
                event_key=_fingerprint(save_id, "LOAN_OPTION_RECORDED", identity, row.source_record_id),
                event_type="LOAN_OPTION_RECORDED",
                transaction_type="loan",
                verification="CONFIRMED",
                player_instance_id=instance.id,
                player_identity=identity,
                buying_club_id=row.loan_club_id,
                selling_club_id=row.parent_club_id,
                amount=_amount(row.buy_option_fee),
                currency=None,
                game_date=row.start_date,
                observed_at=row.observed_at or utcnow(),
                source=row.source or "import",
                eligible=False,
                evidence={"loan_id": row.id, "buy_option_fee": row.buy_option_fee},
            )
        )
    if row.has_obligation is True:
        events.append(
            _event(
                save_id=save_id,
                event_key=_fingerprint(save_id, "LOAN_OBLIGATION_RECORDED", identity, row.source_record_id),
                event_type="LOAN_OBLIGATION_RECORDED",
                transaction_type="loan",
                verification="CONFIRMED",
                player_instance_id=instance.id,
                player_identity=identity,
                buying_club_id=row.loan_club_id,
                selling_club_id=row.parent_club_id,
                amount=_amount(row.buy_obligation_fee),
                currency=None,
                game_date=row.start_date,
                observed_at=row.observed_at or utcnow(),
                source=row.source or "import",
                eligible=False,
                evidence={"loan_id": row.id, "buy_obligation_fee": row.buy_obligation_fee},
            )
        )
    return events


_NEGOTIATION_EVENT_MAP = {
    "offer_submitted": "OFFER_SUBMITTED",
    "offer_revised": "OFFER_SUBMITTED",
    "counter_received": "COUNTER_OFFER_RECEIVED",
    "accepted": "OFFER_ACCEPTED",
    "completed": "OFFER_ACCEPTED",
    "rejected": "OFFER_REJECTED",
    "cancelled": "NEGOTIATION_CANCELLED",
    "withdrawn": "NEGOTIATION_CANCELLED",
}

_FEEDBACK_EVENT_MAP = {
    "completed": "OFFER_ACCEPTED",
    "rejected": "OFFER_REJECTED",
    "cancelled": "NEGOTIATION_CANCELLED",
    "negotiating": "OFFER_SUBMITTED",
}


def _negotiation_event(
    db: Session,
    save_id: int,
    row: NegotiationEvent,
    negotiation: TransferNegotiation,
    user_club_id: int | None,
) -> TransferLearningEvent | None:
    event_type = _NEGOTIATION_EVENT_MAP.get(row.event_type)
    if event_type is None:
        return None
    instance = db.get(PlayerInstance, negotiation.player_instance_id)
    if instance is None or instance.fm_save_id != save_id:
        return None
    identity = _identity(instance)
    currency = _currency(negotiation.currency)
    if negotiation.direction == "purchase":
        buying_club_id, selling_club_id = user_club_id, instance.club_id
    else:
        # 出售时真实买家未知；不能凭空写入一个买方俱乐部。
        buying_club_id, selling_club_id = None, user_club_id
    return _event(
        save_id=save_id,
        event_key=_fingerprint(save_id, event_type, identity, row.id, row.occurred_at, row.amount),
        event_type=event_type,
        transaction_type="loan" if negotiation.direction == "loan" else "permanent",
        verification="CONFIRMED",
        player_instance_id=instance.id,
        player_identity=identity,
        buying_club_id=buying_club_id,
        selling_club_id=selling_club_id,
        amount=_amount(row.amount),
        currency=currency,
        game_date=(row.occurred_at.date() if row.occurred_at else None),
        observed_at=row.occurred_at or utcnow(),
        source=row.source or "user_confirmed",
        eligible=False,
        evidence={"negotiation_id": negotiation.id, "negotiation_event_id": row.id, "direction": negotiation.direction},
    )


def _feedback_event(
    db: Session, save_id: int, row: TransferFeedback, user_club_id: int | None
) -> TransferLearningEvent | None:
    event_type = _FEEDBACK_EVENT_MAP.get(row.outcome)
    if event_type is None:
        return None
    instance = db.get(PlayerInstance, row.player_instance_id)
    if instance is None or instance.fm_save_id != save_id:
        return None
    identity = _identity(instance)
    if row.direction == "purchase":
        buying_club_id, selling_club_id = user_club_id, instance.club_id
    else:
        buying_club_id, selling_club_id = None, user_club_id
    return _event(
        save_id=save_id,
        event_key=_fingerprint(save_id, event_type, identity, "feedback", row.dedupe_key),
        event_type=event_type,
        transaction_type="loan" if row.direction == "loan" else "permanent",
        verification="CONFIRMED",
        player_instance_id=instance.id,
        player_identity=identity,
        buying_club_id=buying_club_id,
        selling_club_id=selling_club_id,
        amount=_amount(row.amount),
        currency=None,
        game_date=row.created_at.date() if row.created_at else None,
        observed_at=row.created_at or utcnow(),
        source=row.source or "user_confirmed",
        eligible=False,
        evidence={"feedback_id": row.id, "outcome": row.outcome, "direction": row.direction},
    )


# ---------------------------------------------------------------------------
# 俱乐部画像
# ---------------------------------------------------------------------------


def _bucket() -> dict[str, Any]:
    return {
        "completed": 0,
        "loans": 0,
        "free": 0,
        "fee_total": 0.0,
        "fee_count": 0,
        "fees": [],
        "ages": {},
        "positions": {},
    }


def _empty_stats() -> dict[str, Any]:
    return {
        "buying": _bucket(),
        "selling": _bucket(),
        "loans": {"count": 0, "fee_total": 0.0, "fee_count": 0, "option": 0, "obligation": 0},
        "negotiation": {"submitted": 0, "accepted": 0, "rejected": 0, "countered": 0},
        "currencies": [],
        "amount_missing": 0,
        "players": [],
        "value_ratios": {"buying": [], "selling": [], "loans": []},
        "first_event_at": None,
        "last_event_at": None,
    }


def _merge_stats(raw: dict[str, Any] | None) -> dict[str, Any]:
    base = _empty_stats()
    if not raw:
        return base
    for key in ("buying", "selling", "loans", "negotiation", "value_ratios"):
        if isinstance(raw.get(key), dict):
            base[key].update(raw[key])
    for key in ("currencies", "players"):
        if isinstance(raw.get(key), list):
            base[key] = list(raw[key])
    for key in ("amount_missing",):
        base[key] = int(raw.get(key) or 0)
    for key in ("first_event_at", "last_event_at"):
        base[key] = raw.get(key)
    return base


def _bump(bucket: dict[str, Any], age: int | None, position: str | None, amount: float | None,
          value: float | None, kind: str) -> None:
    if kind == "free":
        bucket["free"] += 1
        bucket["completed"] += 1
    elif kind == "loan":
        bucket["loans"] += 1
    else:
        bucket["completed"] += 1
    if amount is not None:
        bucket["fee_total"] = round(float(bucket["fee_total"]) + amount, 2)
        bucket["fee_count"] = int(bucket["fee_count"]) + 1
        fees = bucket["fees"]
        fees.append(amount)
        if len(fees) > MAX_LIST:
            del fees[0: len(fees) - MAX_LIST]
    if age is not None:
        key = str(int(age))
        bucket["ages"][key] = int(bucket["ages"].get(key, 0)) + 1
    if position:
        key = str(position)[:16]
        bucket["positions"][key] = int(bucket["positions"].get(key, 0)) + 1
    return None


def _confidence(stats: dict[str, Any], sample: int, evidence: dict[str, Any]) -> dict[str, Any]:
    tier = transfer_strategy.confidence_tier(sample)
    total = max(1, int(evidence.get("events") or 0))
    confirmed_ratio = float(evidence.get("confirmed") or 0) / total
    identity_ratio = float(evidence.get("identity") or 0) / total
    amount_ratio = float(evidence.get("amount") or 0) / total
    players = len(stats.get("players") or [])
    diversity = min(1.0, players / 5.0)
    span_days = float(evidence.get("span_days") or 0)
    span = min(1.0, span_days / 180.0)
    quality = round(
        confirmed_ratio * 0.30 + identity_ratio * 0.20 + amount_ratio * 0.25 + diversity * 0.15 + span * 0.10,
        3,
    )
    level = tier["level"]
    if quality < 0.5 and level in {"stable", "limited"}:
        level = "preliminary"
    basis = [
        f"确认事件占比 {round(confirmed_ratio * 100)}%",
        f"身份可解析占比 {round(identity_ratio * 100)}%",
        f"金额可用占比 {round(amount_ratio * 100)}%",
        f"涉及球员 {players} 人",
        f"时间跨度 {int(span_days)} 天",
    ]
    return {
        "level": level,
        "label": tier["label"],
        "sample_size": sample,
        "quality_score": quality,
        "basis": basis,
    }


def _profile_sample(stats: dict[str, Any]) -> int:
    buying = stats["buying"]
    selling = stats["selling"]
    loans = stats["loans"]
    return int(buying["completed"]) + int(selling["completed"]) + int(buying["loans"]) + int(selling["loans"]) + int(loans["count"])


def _apply_event_to_stats(stats: dict[str, Any], event: TransferLearningEvent, side: str) -> None:
    evidence = _loads(event.evidence_json)
    age = evidence.get("age")
    position = evidence.get("position")
    value = evidence.get("market_value")
    bucket = stats[side]
    if event.event_type == "TRANSFER_COMPLETED":
        kind = "free" if event.transaction_type == "free" else "permanent"
        _bump(bucket, age, position, event.amount, value, kind)
        if event.amount is not None and value:
            ratio = round(float(event.amount) / float(value), 4)
            stats["value_ratios"][side].append(ratio)
            if len(stats["value_ratios"][side]) > MAX_LIST:
                del stats["value_ratios"][side][0: len(stats["value_ratios"][side]) - MAX_LIST]
    elif event.event_type == "LOAN_COMPLETED":
        _bump(bucket, age, position, event.amount, value, "loan")
        stats["loans"]["count"] += 1
        if event.amount is not None:
            stats["loans"]["fee_total"] = round(float(stats["loans"]["fee_total"]) + event.amount, 2)
            stats["loans"]["fee_count"] += 1
        if event.amount is not None and value:
            ratio = round(float(event.amount) / float(value), 4)
            stats["value_ratios"]["loans"].append(ratio)
            if len(stats["value_ratios"]["loans"]) > MAX_LIST:
                del stats["value_ratios"]["loans"][0: len(stats["value_ratios"]["loans"]) - MAX_LIST]
    elif event.event_type == "LOAN_OPTION_RECORDED":
        stats["loans"]["option"] += 1
    elif event.event_type == "LOAN_OBLIGATION_RECORDED":
        stats["loans"]["obligation"] += 1
    elif event.event_type == "OFFER_SUBMITTED":
        stats["negotiation"]["submitted"] += 1
    elif event.event_type == "OFFER_ACCEPTED":
        stats["negotiation"]["accepted"] += 1
    elif event.event_type == "OFFER_REJECTED":
        stats["negotiation"]["rejected"] += 1
    elif event.event_type == "COUNTER_OFFER_RECEIVED":
        stats["negotiation"]["countered"] += 1

    if event.amount is None and event.event_type in ELIGIBLE_EVENTS:
        stats["amount_missing"] += 1
    currency = event.currency
    if currency and currency not in stats["currencies"]:
        stats["currencies"].append(currency)
        if len(stats["currencies"]) > 8:
            del stats["currencies"][0: len(stats["currencies"]) - 8]
    identity = event.player_identity
    if identity and identity not in stats["players"]:
        stats["players"].append(identity)
        if len(stats["players"]) > MAX_PLAYERS:
            del stats["players"][0: len(stats["players"]) - MAX_PLAYERS]
    stamp = iso(event.observed_at)
    if stamp:
        if not stats["first_event_at"] or stamp < stats["first_event_at"]:
            stats["first_event_at"] = stamp
        if not stats["last_event_at"] or stamp > stats["last_event_at"]:
            stats["last_event_at"] = stamp


def _update_profiles(
    db: Session, save_id: int, events: list[TransferLearningEvent], user_club_id: int | None
) -> tuple[int, int]:
    """增量应用事件到俱乐部画像；返回 (updated, focus_promoted)。"""
    relevant = [
        row
        for row in events
        if row.event_type in ELIGIBLE_EVENTS
        or row.event_type
        in {
            "LOAN_OPTION_RECORDED",
            "LOAN_OBLIGATION_RECORDED",
            "OFFER_SUBMITTED",
            "OFFER_ACCEPTED",
            "OFFER_REJECTED",
            "COUNTER_OFFER_RECEIVED",
        }
    ]
    if not relevant:
        return 0, 0
    club_ids = sorted(
        {
            club_id
            for row in relevant
            for club_id in (row.buying_club_id, row.selling_club_id)
            if club_id is not None
        }
    )
    if not club_ids:
        return 0, 0
    profiles: dict[int, ClubTransferProfile] = {}
    for chunk in _chunks(club_ids):
        for profile in db.scalars(
            select(ClubTransferProfile).where(
                ClubTransferProfile.fm_save_id == save_id,
                ClubTransferProfile.club_id.in_(chunk),
            )
        ):
            profiles[int(profile.club_id)] = profile
    known_clubs = set(
        db.scalars(select(Club.id).where(Club.fm_save_id == save_id, Club.id.in_(club_ids)))
    )
    for club_id in club_ids:
        if club_id not in known_clubs:
            continue
        if club_id not in profiles:
            profile = ClubTransferProfile(
                fm_save_id=save_id,
                club_id=club_id,
                priority="global",
                last_event_id=0,
                sample_size=0,
                stats_json=_dumps(_empty_stats()),
                confidence_json=_dumps(transfer_strategy.confidence_tier(0)),
            )
            db.add(profile)
            profiles[club_id] = profile
    db.flush()

    updated = 0
    promoted = 0
    activities: list[TransferLearningActivity] = []
    quality: dict[int, dict[str, int]] = {club_id: {"events": 0, "confirmed": 0, "identity": 0, "amount": 0} for club_id in profiles}
    stamps: dict[int, list[datetime]] = {club_id: [] for club_id in profiles}
    cache: dict[int, dict[str, Any]] = {
        club_id: _merge_stats(_loads(profile.stats_json)) for club_id, profile in profiles.items()
    }

    for event in sorted(relevant, key=lambda row: row.id):
        for club_id, side in (
            (event.buying_club_id, "buying"),
            (event.selling_club_id, "selling"),
        ):
            profile = profiles.get(club_id) if club_id is not None else None
            if profile is None:
                continue
            if event.id <= int(profile.last_event_id or 0):
                continue
            _apply_event_to_stats(cache[club_id], event, side)
            profile.last_event_id = int(event.id)
            updated += 1
            quality[club_id]["events"] += 1
            if event.verification_status == "CONFIRMED":
                quality[club_id]["confirmed"] += 1
            if event.player_instance_id is not None:
                quality[club_id]["identity"] += 1
            if event.amount is not None:
                quality[club_id]["amount"] += 1
            if event.observed_at:
                stamps[club_id].append(event.observed_at)
            if user_club_id is not None and club_id != user_club_id and profile.priority != "focus":
                profile.priority = "focus"
                promoted += 1
                club = db.get(Club, club_id)
                activities.append(
                    TransferLearningActivity(
                        fm_save_id=save_id,
                        activity_type="focus_promoted",
                        title=f"{club.name if club else '俱乐部'} 已升级为重点学习对象"[:256],
                        detail_json=_dumps({"club_id": club_id, "event_id": event.id}),
                        event_id=event.id,
                        club_id=club_id,
                    )
                )
    for club_id, profile in profiles.items():
        stats = cache[club_id]
        info = quality.get(club_id) or {"events": 0, "confirmed": 0, "identity": 0, "amount": 0}
        span_days = 0
        if stamps[club_id]:
            span_days = (max(stamps[club_id]) - min(stamps[club_id])).days
        info["span_days"] = span_days
        profile.stats_json = _dumps(stats)
        profile.sample_size = _profile_sample(stats)
        profile.confidence_json = _dumps(_confidence(stats, int(profile.sample_size or 0), info))
    db.add_all(activities)
    db.commit()
    return updated, promoted


def _record_activity(
    db: Session, save_id: int, event: TransferLearningEvent
) -> None:
    label = {
        "TRANSFER_COMPLETED": "已确认一笔永久转会",
        "LOAN_COMPLETED": "已确认一笔租借交易",
        "PLAYER_LISTED": "观察到球员进入挂牌名单",
        "PLAYER_UNLISTED": "观察到球员被移出挂牌名单",
        "PLAYER_LOAN_LISTED": "观察到球员被标记为可租借",
        "PLAYER_RELEASED": "观察到球员进入解约挂牌",
        "OFFER_ACCEPTED": "记录到一次被接受的报价",
        "OFFER_REJECTED": "记录到一次被拒绝的报价",
        "COUNTER_OFFER_RECEIVED": "记录到一次对方还价",
    }.get(event.event_type)
    if label is None:
        return
    db.add(
        TransferLearningActivity(
            fm_save_id=save_id,
            activity_type="event_detected",
            title=label,
            detail_json=_dumps(
                {
                    "event_id": event.id,
                    "event_type": event.event_type,
                    "amount": event.amount,
                    "currency": event.currency,
                }
            ),
            event_id=event.id,
            club_id=event.buying_club_id or event.selling_club_id,
        )
    )


# ---------------------------------------------------------------------------
# 增量处理
# ---------------------------------------------------------------------------


def process_incremental(
    db: Session,
    save_id: int,
    *,
    checkpoint: dict[str, Any] | None = None,
    token: str | None = None,
    mode: str = "auto",
    batch_size: int = DEFAULT_BATCH,
    cancel_cb: Callable[[], bool] | None = None,
    progress_cb: Callable[[int, int, int, int, int], None] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """按游标增量处理新数据。

    第一次调用只建立基线（不把历史数据计为新学习）；之后每次只处理游标之后的行。
    无新数据时不写事件、不重建画像。
    """
    save = db.get(FmSave, save_id)
    if save is None:
        raise ValueError("save not found")
    session, _ = _ensure_session(db, save_id)
    if not session.enabled and not force:
        return {
            "save_id": save_id,
            "mode": "paused",
            "events_created": 0,
            "events_skipped": 0,
            "profiles_updated": 0,
            "focus_promoted": 0,
            "processed": 0,
            "partial": False,
            "cancelled": False,
            "checkpoint": _cursor(session),
            "engine_version": ENGINE_VERSION,
        }

    cursor = _cursor(session)
    if checkpoint and isinstance(checkpoint.get("cursor"), dict):
        for key, value in checkpoint["cursor"].items():
            if key in cursor:
                cursor[key] = int(value or 0)
    monitor_at = _last_monitor_at(db, save_id)
    session.status = "PROCESSING"
    session.last_monitor_at = monitor_at or session.last_monitor_at
    db.commit()

    total = _count_pending(db, save_id, cursor)
    if total == 0:
        session.status = "MONITORING"
        session.last_monitor_at = monitor_at or session.last_monitor_at
        db.commit()
        return {
            "save_id": save_id,
            "mode": "incremental",
            "events_created": 0,
            "events_skipped": 0,
            "profiles_updated": 0,
            "focus_promoted": 0,
            "processed": 0,
            "total": 0,
            "partial": False,
            "cancelled": False,
            "checkpoint": cursor,
            "engine_version": ENGINE_VERSION,
        }

    created = skipped = processed = 0
    profiles_updated = promoted = 0
    cancelled = False
    activities_recorded = 0
    batch = max(50, int(batch_size))
    user_club_id = save.user_club_id

    def persist(events: list[TransferLearningEvent]) -> None:
        nonlocal created, skipped, profiles_updated, promoted, activities_recorded
        inserted, duplicates = _persist_events(db, events)
        created += len(inserted)
        skipped += duplicates
        if inserted:
            for event in inserted:
                # 学习动态只保留有限条，避免一次导入产生海量 UI 噪音。
                if activities_recorded < 200:
                    _record_activity(db, save_id, event)
                    activities_recorded += 1
            db.commit()
            updated, focus = _update_profiles(db, save_id, inserted, user_club_id)
            profiles_updated += updated
            promoted += focus

    while True:
        if cancel_cb is not None and cancel_cb():
            cancelled = True
            break
        events: list[TransferLearningEvent] = []

        transfers = list(
            db.scalars(
                select(Transfer)
                .where(Transfer.fm_save_id == save_id, Transfer.id > cursor["last_transfer_id"])
                .order_by(Transfer.id.asc())
                .limit(batch)
            )
        )
        transfer_instances = _batch_instances(
            db, save_id, {int(row.player_instance_id) for row in transfers if row.player_instance_id}
        )
        transfer_snapshots = _batch_snapshot_evidence(db, transfer_instances)
        for row in transfers:
            event = _transfer_event(
                db,
                save_id,
                row,
                instances=transfer_instances,
                snapshots=transfer_snapshots,
            )
            if event is None:
                skipped += 1
            else:
                events.append(event)
            cursor["last_transfer_id"] = int(row.id)
        processed += len(transfers)

        loans = list(
            db.scalars(
                select(LoanRecord)
                .where(LoanRecord.fm_save_id == save_id, LoanRecord.id > cursor["last_loan_id"])
                .order_by(LoanRecord.id.asc())
                .limit(batch)
            )
        )
        for row in loans:
            events.extend(_loan_events(db, save_id, row))
            cursor["last_loan_id"] = int(row.id)
        processed += len(loans)

        availability_rows = list(
            db.execute(
                select(PlayerAvailability)
                .join(PlayerInstance, PlayerInstance.id == PlayerAvailability.player_instance_id)
                .where(
                    PlayerInstance.fm_save_id == save_id,
                    PlayerAvailability.id > cursor["last_availability_id"],
                )
                .order_by(PlayerAvailability.id.asc())
                .limit(batch)
            ).scalars()
        )
        availability_instances = _batch_instances(
            db, save_id, {int(row.player_instance_id) for row in availability_rows}
        )
        availability_previous = _batch_previous_availability(db, availability_rows)
        for row in availability_rows:
            events.extend(
                _availability_events(
                    save_id,
                    row,
                    availability_previous.get(int(row.id)),
                    availability_instances.get(int(row.player_instance_id)),
                )
            )
            cursor["last_availability_id"] = int(row.id)
        processed += len(availability_rows)

        candidates = list(
            db.scalars(
                select(TransferEventCandidate)
                .where(
                    TransferEventCandidate.fm_save_id == save_id,
                    TransferEventCandidate.id > cursor["last_candidate_id"],
                )
                .order_by(TransferEventCandidate.id.asc())
                .limit(batch)
            )
        )
        for row in candidates:
            event = _candidate_event(db, save_id, row)
            if event is not None:
                events.append(event)
            cursor["last_candidate_id"] = int(row.id)
        processed += len(candidates)

        negotiations = db.execute(
            select(NegotiationEvent, TransferNegotiation)
            .join(TransferNegotiation, TransferNegotiation.id == NegotiationEvent.negotiation_id)
            .where(
                NegotiationEvent.fm_save_id == save_id,
                NegotiationEvent.id > cursor["last_negotiation_event_id"],
            )
            .order_by(NegotiationEvent.id.asc())
            .limit(batch)
        ).all()
        for event_row, negotiation in negotiations:
            event = _negotiation_event(db, save_id, event_row, negotiation, user_club_id)
            if event is not None:
                events.append(event)
            cursor["last_negotiation_event_id"] = int(event_row.id)
        processed += len(negotiations)

        feedback = list(
            db.scalars(
                select(TransferFeedback)
                .where(
                    TransferFeedback.fm_save_id == save_id,
                    TransferFeedback.id > cursor["last_feedback_id"],
                )
                .order_by(TransferFeedback.id.asc())
                .limit(batch)
            )
        )
        for row in feedback:
            event = _feedback_event(db, save_id, row, user_club_id)
            if event is not None:
                events.append(event)
            cursor["last_feedback_id"] = int(row.id)
        processed += len(feedback)

        persist(events)

        session.cursor_json = _dumps(cursor)
        session.last_monitor_at = monitor_at or session.last_monitor_at
        db.commit()

        if progress_cb is not None:
            progress_cb(processed, max(total, processed), created, skipped, cursor["last_transfer_id"])
        if not transfers and not loans and not availability_rows and not candidates and not negotiations and not feedback:
            break

    session.cursor_json = _dumps(cursor)
    session.events_processed = int(session.events_processed or 0) + processed
    session.events_new = int(session.events_new or 0) + created
    session.events_skipped = int(session.events_skipped or 0) + skipped
    session.learning_cycles = int(session.learning_cycles or 0) + 1
    session.last_learning_at = utcnow()
    if created:
        session.last_event_at = db.scalar(
            select(func.max(TransferLearningEvent.observed_at)).where(
                TransferLearningEvent.fm_save_id == save_id
            )
        ) or session.last_event_at
    if cancelled:
        session.status = "PARTIAL"
    elif processed:
        session.status = "MONITORING"
    else:
        session.status = "MONITORING"
    session.last_error = None
    db.commit()
    return {
        "save_id": save_id,
        "mode": "incremental",
        "events_created": created,
        "events_skipped": skipped,
        "profiles_updated": profiles_updated,
        "focus_promoted": promoted,
        "processed": processed,
        "total": total,
        "partial": False,
        "cancelled": cancelled,
        "checkpoint": cursor,
        "engine_version": ENGINE_VERSION,
    }


def _count_pending(db: Session, save_id: int, cursor: dict[str, int]) -> int:
    total = 0
    total += int(
        db.scalar(
            select(func.count()).select_from(Transfer).where(
                Transfer.fm_save_id == save_id, Transfer.id > cursor["last_transfer_id"]
            )
        )
        or 0
    )
    total += int(
        db.scalar(
            select(func.count()).select_from(LoanRecord).where(
                LoanRecord.fm_save_id == save_id, LoanRecord.id > cursor["last_loan_id"]
            )
        )
        or 0
    )
    total += int(
        db.scalar(
            select(func.count())
            .select_from(PlayerAvailability)
            .join(PlayerInstance, PlayerInstance.id == PlayerAvailability.player_instance_id)
            .where(
                PlayerInstance.fm_save_id == save_id,
                PlayerAvailability.id > cursor["last_availability_id"],
            )
        )
        or 0
    )
    total += int(
        db.scalar(
            select(func.count()).select_from(TransferEventCandidate).where(
                TransferEventCandidate.fm_save_id == save_id,
                TransferEventCandidate.id > cursor["last_candidate_id"],
            )
        )
        or 0
    )
    total += int(
        db.scalar(
            select(func.count()).select_from(NegotiationEvent).where(
                NegotiationEvent.fm_save_id == save_id,
                NegotiationEvent.id > cursor["last_negotiation_event_id"],
            )
        )
        or 0
    )
    total += int(
        db.scalar(
            select(func.count()).select_from(TransferFeedback).where(
                TransferFeedback.fm_save_id == save_id,
                TransferFeedback.id > cursor["last_feedback_id"],
            )
        )
        or 0
    )
    return total


def count_pending(db: Session, save_id: int) -> int:
    """当前存档游标之后还有多少待处理行（不写库）。"""
    session = get_session(db, save_id)
    if session is None:
        return 0
    return _count_pending(db, save_id, _cursor(session))


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------


def _event_payload(row: TransferLearningEvent, club_names: dict[int, str],
                   player_names: dict[int, str]) -> dict[str, Any]:
    return {
        "event_id": row.id,
        "event_type": row.event_type,
        "transaction_type": row.transaction_type,
        "verification_status": row.verification_status,
        "player_instance_id": row.player_instance_id,
        "player_name": player_names.get(int(row.player_instance_id)) if row.player_instance_id else None,
        "buying_club_id": row.buying_club_id,
        "buying_club_name": club_names.get(int(row.buying_club_id)) if row.buying_club_id else None,
        "selling_club_id": row.selling_club_id,
        "selling_club_name": club_names.get(int(row.selling_club_id)) if row.selling_club_id else None,
        "amount": row.amount,
        "currency": row.currency,
        "currency_known": row.currency is not None,
        "game_date": iso(row.game_date),
        "observed_at": iso(row.observed_at),
        "source": row.source,
        "learning_eligible": bool(row.learning_eligible),
    }


def list_events(
    db: Session,
    save_id: int,
    *,
    club_id: int | None = None,
    player_instance_id: int | None = None,
    event_type: str | None = None,
    verification_status: str | None = None,
    since: date | None = None,
    until: date | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    if event_type is not None and event_type not in EVENT_TYPES:
        raise ValueError(f"unsupported event_type: {event_type}")
    if verification_status is not None and verification_status not in VERIFICATION_STATUSES:
        raise ValueError(f"unsupported verification_status: {verification_status}")
    conditions = [TransferLearningEvent.fm_save_id == save_id]
    if club_id is not None:
        conditions.append(
            or_(
                TransferLearningEvent.buying_club_id == club_id,
                TransferLearningEvent.selling_club_id == club_id,
            )
        )
    if player_instance_id is not None:
        conditions.append(TransferLearningEvent.player_instance_id == player_instance_id)
    if event_type:
        conditions.append(TransferLearningEvent.event_type == event_type)
    if verification_status:
        conditions.append(TransferLearningEvent.verification_status == verification_status)
    if since is not None:
        conditions.append(TransferLearningEvent.game_date >= since)
    if until is not None:
        conditions.append(TransferLearningEvent.game_date <= until)
    total = int(
        db.scalar(select(func.count()).select_from(TransferLearningEvent).where(*conditions)) or 0
    )
    rows = list(
        db.scalars(
            select(TransferLearningEvent)
            .where(*conditions)
            .order_by(TransferLearningEvent.observed_at.desc(), TransferLearningEvent.id.desc())
            .limit(min(max(1, limit), 200))
            .offset(max(0, offset))
        )
    )
    club_ids = {row.buying_club_id for row in rows if row.buying_club_id} | {
        row.selling_club_id for row in rows if row.selling_club_id
    }
    instance_ids = {row.player_instance_id for row in rows if row.player_instance_id}
    club_names: dict[int, str] = {}
    if club_ids:
        club_names = {
            int(club.id): club.name
            for club in db.scalars(select(Club).where(Club.fm_save_id == save_id, Club.id.in_(club_ids)))
        }
    player_names: dict[int, str] = {}
    if instance_ids:
        for instance_id, name in db.execute(
            select(PlayerInstance.id, Player.full_name)
            .join(Player, Player.id == PlayerInstance.player_id)
            .where(PlayerInstance.fm_save_id == save_id, PlayerInstance.id.in_(instance_ids))
        ).all():
            player_names[int(instance_id)] = name
    return {
        "items": [_event_payload(row, club_names, player_names) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def _profile_payload(profile: ClubTransferProfile, club: Club | None) -> dict[str, Any]:
    stats = _merge_stats(_loads(profile.stats_json))
    return {
        "club_id": profile.club_id,
        "club_name": club.name if club else None,
        "league": club.league if club else None,
        "priority": profile.priority,
        "sample_size": int(profile.sample_size or 0),
        "confidence": _loads(profile.confidence_json),
        "buying": stats["buying"],
        "selling": stats["selling"],
        "loans": stats["loans"],
        "negotiation": stats["negotiation"],
        "currencies": stats["currencies"],
        "mixed_currency": len(stats["currencies"]) > 1,
        "amount_missing": stats["amount_missing"],
        "updated_at": iso(profile.updated_at),
    }


def list_clubs(
    db: Session,
    save_id: int,
    *,
    search: str | None = None,
    league: str | None = None,
    transaction_type: str | None = None,
    min_sample: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    if transaction_type is not None and transaction_type not in {"buying", "selling", "loans", "negotiation"}:
        raise ValueError("unsupported transaction_type")
    conditions = [ClubTransferProfile.fm_save_id == save_id]
    if min_sample is not None:
        conditions.append(ClubTransferProfile.sample_size >= int(min_sample))
    query = (
        select(ClubTransferProfile, Club)
        .join(Club, Club.id == ClubTransferProfile.club_id)
        .where(*conditions)
    )
    if search:
        query = query.where(Club.name.ilike(f"%{search.strip()}%"))
    if league:
        query = query.where(Club.league == league)
    rows = db.execute(
        query.order_by(ClubTransferProfile.sample_size.desc(), Club.name.asc())
    ).all()
    if transaction_type:
        def matches(profile: ClubTransferProfile) -> bool:
            stats = _merge_stats(_loads(profile.stats_json))
            if transaction_type == "loans":
                return int(stats["loans"]["count"]) > 0
            if transaction_type == "negotiation":
                return any(int(value) > 0 for value in stats["negotiation"].values())
            bucket = stats[transaction_type]
            return int(bucket["completed"]) + int(bucket["loans"]) > 0
        rows = [(profile, club) for profile, club in rows if matches(profile)]
    total = len(rows)
    page = rows[max(0, offset): max(0, offset) + min(max(1, limit), 200)]
    return {
        "items": [_profile_payload(profile, club) for profile, club in page],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def club_profile(db: Session, save_id: int, club_id: int) -> dict[str, Any]:
    club = db.get(Club, club_id)
    if club is None or club.fm_save_id != save_id:
        raise ValueError("club not found")
    profile = db.scalar(
        select(ClubTransferProfile).where(
            ClubTransferProfile.fm_save_id == save_id, ClubTransferProfile.club_id == club_id
        )
    )
    if profile is None:
        return {
            "club_id": club_id,
            "club_name": club.name,
            "league": club.league,
            "priority": "global",
            "sample_size": 0,
            "confidence": transfer_strategy.confidence_tier(0),
            "buying": _empty_stats()["buying"],
            "selling": _empty_stats()["selling"],
            "loans": _empty_stats()["loans"],
            "negotiation": _empty_stats()["negotiation"],
            "currencies": [],
            "mixed_currency": False,
            "amount_missing": 0,
            "patterns": [],
            "recent_events": [],
            "message": "暂无该俱乐部交易样本",
        }
    payload = _profile_payload(profile, club)
    stats = _merge_stats(_loads(profile.stats_json))
    patterns: list[dict[str, Any]] = []
    sample = int(profile.sample_size or 0)
    if sample:
        patterns.append(
            {
                "key": "buying_volume",
                "label": "买入成交",
                "sample_size": int(stats["buying"]["completed"]),
                "confidence": transfer_strategy.confidence_tier(int(stats["buying"]["completed"])),
                "summary": f"已确认买入 {int(stats['buying']['completed'])} 笔",
            }
        )
        patterns.append(
            {
                "key": "selling_volume",
                "label": "出售成交",
                "sample_size": int(stats["selling"]["completed"]),
                "confidence": transfer_strategy.confidence_tier(int(stats["selling"]["completed"])),
                "summary": f"已确认出售 {int(stats['selling']['completed'])} 笔",
            }
        )
        patterns.append(
            {
                "key": "loan_preference",
                "label": "租借倾向",
                "sample_size": int(stats["loans"]["count"]),
                "confidence": transfer_strategy.confidence_tier(int(stats["loans"]["count"])),
                "summary": "存在租借交易" if int(stats["loans"]["count"]) else "暂无租借交易",
            }
        )
    payload["patterns"] = patterns
    payload["recent_events"] = list_events(db, save_id, club_id=club_id, limit=10)["items"]
    payload["message"] = None if sample else "暂无该俱乐部交易样本"
    return payload


def focus_clubs(db: Session, save_id: int, *, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    rows = db.execute(
        select(ClubTransferProfile, Club)
        .join(Club, Club.id == ClubTransferProfile.club_id)
        .where(
            ClubTransferProfile.fm_save_id == save_id,
            ClubTransferProfile.priority == "focus",
        )
        .order_by(ClubTransferProfile.updated_at.desc())
    ).all()
    total = len(rows)
    page = rows[max(0, offset): max(0, offset) + min(max(1, limit), 200)]
    items = []
    for profile, club in page:
        payload = _profile_payload(profile, club)
        stats = _merge_stats(_loads(profile.stats_json))
        payload["trade_counts"] = {
            "buying": int(stats["buying"]["completed"]),
            "selling": int(stats["selling"]["completed"]),
            "loans": int(stats["loans"]["count"]),
        }
        payload["promotion_reason"] = "与用户俱乐部发生过交易或可确认的报价往来"
        payload["last_transaction_at"] = stats.get("last_event_at")
        items.append(payload)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def strategies(db: Session, save_id: int) -> dict[str, Any]:
    profiles = list(
        db.scalars(
            select(ClubTransferProfile).where(ClubTransferProfile.fm_save_id == save_id)
        )
    )
    total_samples = sum(int(profile.sample_size or 0) for profile in profiles)
    focus = [profile for profile in profiles if profile.priority == "focus"]
    patterns: list[dict[str, Any]] = []
    toggles = {"loan_preference": 0, "installments": 0, "young_sales": 0, "free_transfers": 0}
    for profile in profiles:
        stats = _merge_stats(_loads(profile.stats_json))
        toggles["loan_preference"] += int(stats["loans"]["count"])
        toggles["free_transfers"] += int(stats["buying"]["free"]) + int(stats["selling"]["free"])
        toggles["young_sales"] += sum(
            1 for age, count in stats["selling"]["ages"].items() if int(age) <= 23
        )
    definitions = (
        ("loan_preference", "租借倾向"),
        ("free_transfers", "自由转会"),
        ("young_sales", "出售年轻球员"),
    )
    for key, label in definitions:
        sample = int(toggles[key])
        patterns.append(
            {
                "key": key,
                "label": label,
                "sample_size": sample,
                "confidence": transfer_strategy.confidence_tier(sample),
                "summary": f"全球画像中观察到 {sample} 个相关样本" if sample else "暂无可归纳样本",
            }
        )
    focus_payload = []
    if focus:
        clubs = {
            int(club.id): club
            for club in db.scalars(select(Club).where(Club.fm_save_id == save_id))
        }
        for profile in focus[:20]:
            focus_payload.append(_profile_payload(profile, clubs.get(int(profile.club_id))))
    return {
        "save_id": save_id,
        "available": total_samples > 0,
        "global": {
            "clubs": len(profiles),
            "samples": total_samples,
            "confidence": transfer_strategy.confidence_tier(total_samples),
        },
        "patterns": patterns,
        "focus": focus_payload,
        "message": None if total_samples else "当前存档没有真实成交样本；策略结论保持为空",
        "engine_version": ENGINE_VERSION,
    }


def activity(db: Session, save_id: int, limit: int = 20) -> dict[str, Any]:
    rows = list(
        db.scalars(
            select(TransferLearningActivity)
            .where(TransferLearningActivity.fm_save_id == save_id)
            .order_by(TransferLearningActivity.created_at.desc(), TransferLearningActivity.id.desc())
            .limit(min(max(1, limit), 100))
        )
    )
    total = int(
        db.scalar(
            select(func.count()).select_from(TransferLearningActivity).where(
                TransferLearningActivity.fm_save_id == save_id
            )
        )
        or 0
    )
    return {
        "items": [
            {
                "activity_id": row.id,
                "activity_type": row.activity_type,
                "title": row.title,
                "created_at": iso(row.created_at),
                "club_id": row.club_id,
                "event_id": row.event_id,
                "detail": _loads(row.detail_json),
            }
            for row in rows
        ],
        "total": total,
    }


def status(db: Session, save_id: int) -> dict[str, Any]:
    save = db.get(FmSave, save_id)
    if save is None:
        raise ValueError("save not found")
    session, _ = _ensure_session(db, save_id)
    events_observed = int(
        db.scalar(
            select(func.count()).select_from(TransferLearningEvent).where(
                TransferLearningEvent.fm_save_id == save_id
            )
        )
        or 0
    )
    events_confirmed = int(
        db.scalar(
            select(func.count()).select_from(TransferLearningEvent).where(
                TransferLearningEvent.fm_save_id == save_id,
                TransferLearningEvent.verification_status == "CONFIRMED",
            )
        )
        or 0
    )
    confirmed_transfers = int(
        db.scalar(
            select(func.count()).select_from(TransferLearningEvent).where(
                TransferLearningEvent.fm_save_id == save_id,
                TransferLearningEvent.event_type.in_(ELIGIBLE_EVENTS),
                TransferLearningEvent.verification_status == "CONFIRMED",
            )
        )
        or 0
    )
    global_clubs = int(
        db.scalar(
            select(func.count()).select_from(ClubTransferProfile).where(
                ClubTransferProfile.fm_save_id == save_id
            )
        )
        or 0
    )
    focus_count = int(
        db.scalar(
            select(func.count()).select_from(ClubTransferProfile).where(
                ClubTransferProfile.fm_save_id == save_id,
                ClubTransferProfile.priority == "focus",
            )
        )
        or 0
    )
    real_transfer = db.scalar(
        select(Transfer.id).where(
            Transfer.fm_save_id == save_id,
            or_(Transfer.source.is_(None), Transfer.source.not_like("synthetic%")),
        ).limit(1)
    )
    offers_available = db.scalar(
        select(NegotiationEvent.id).where(NegotiationEvent.fm_save_id == save_id).limit(1)
    )
    state = session.status
    if not session.enabled:
        state = "PAUSED"
    elif state in {"STOPPED", "FAILED", "PARTIAL"}:
        pass
    elif events_observed or global_clubs:
        state = "MONITORING"
    else:
        state = "MONITORING"
    return {
        "save_id": save_id,
        "status": state,
        "status_label": STATUS_LABELS.get(state, state),
        "enabled": bool(session.enabled),
        "paused": not bool(session.enabled),
        "save_name": save.name,
        "last_monitor_at": iso(session.last_monitor_at or _last_monitor_at(db, save_id)),
        "last_event_at": iso(session.last_event_at),
        "last_learning_at": iso(session.last_learning_at),
        "counts": {
            "events_observed": events_observed,
            "events_confirmed": events_confirmed,
            "confirmed_transfers": confirmed_transfers,
            "global_clubs": global_clubs,
            "focus_clubs": focus_count,
        },
        "latest_error": session.last_error,
        "coverage": {
            "transfer_history_available": bool(real_transfer),
            "native_reader_transfers": False,
            "offers_available": bool(offers_available),
            "note": "原生读取器不提供转会历史；只有导入的成交记录会计入学习",
        },
        "engine_version": ENGINE_VERSION,
    }


# ---------------------------------------------------------------------------
# 报价学习调整层
# ---------------------------------------------------------------------------


def _stats_ratio(stats: dict[str, Any], side: str) -> tuple[float | None, int]:
    ratios = stats.get("value_ratios", {}).get(side) or []
    values = sorted(float(item) for item in ratios if item is not None and float(item) > 0)
    if not values:
        return None, 0
    middle = len(values) // 2
    median = values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2
    return median, len(values)


def learning_adjustment(
    db: Session,
    save_id: int,
    instance: PlayerInstance,
    base_amount: float | None,
    direction: str,
) -> dict[str, Any]:
    """用俱乐部画像对基础报价做有限调整；样本不足/币种未知时明确回退。"""
    tier = transfer_strategy.confidence_tier(0)
    empty = {
        "applied": False,
        "multiplier": 1.0,
        "before": base_amount,
        "after": base_amount,
        "sample_size": 0,
        "confidence": tier,
        "club_id": None,
        "club_priority": None,
        "basis": "没有可用的俱乐部学习样本，沿用原有确定性规则",
    }
    if base_amount is None or float(base_amount) <= 0:
        return empty
    if direction == "sale":
        club_id = instance.club_id
        side = "selling"
    elif direction == "loan":
        club_id = instance.club_id
        # 租借费用与身价的比值单独统计，不与永久转会混算。
        side = "loans"
    else:
        club_id = instance.club_id
        # 买入时对方是卖出方：用其出售成交/身价比值作为价格基准。
        side = "selling"
    if club_id is None:
        return {**empty, "basis": "球员当前俱乐部未知，无法使用俱乐部画像"}
    profile = db.scalar(
        select(ClubTransferProfile).where(
            ClubTransferProfile.fm_save_id == save_id, ClubTransferProfile.club_id == club_id
        )
    )
    if profile is None:
        return {**empty, "club_id": club_id, "basis": "该俱乐部暂无学习画像"}
    stats = _merge_stats(_loads(profile.stats_json))
    currencies = stats.get("currencies") or []
    if len(currencies) > 1:
        return {
            **empty,
            "club_id": club_id,
            "club_priority": profile.priority,
            "basis": "该俱乐部样本包含多种币种，不能混算，沿用原有规则",
        }
    ratio, sample = _stats_ratio(stats, side)
    if ratio is None or sample < ADJUSTMENT_MIN_SAMPLES:
        return {
            **empty,
            "club_id": club_id,
            "club_priority": profile.priority,
            "sample_size": sample,
            "confidence": transfer_strategy.confidence_tier(sample),
            "basis": f"可用样本只有 {sample} 个，低于最低样本 {ADJUSTMENT_MIN_SAMPLES}，未调整报价",
        }
    multiplier = round(_clamp(float(ratio), *ADJUSTMENT_BOUNDS), 4)
    applied = abs(multiplier - 1.0) >= 0.0001
    return {
        "applied": applied,
        "multiplier": multiplier if applied else 1.0,
        "before": round(float(base_amount), 2),
        "after": round(float(base_amount) * (multiplier if applied else 1.0), 2),
        "sample_size": sample,
        "confidence": _loads(profile.confidence_json) or transfer_strategy.confidence_tier(sample),
        "club_id": club_id,
        "club_priority": profile.priority,
        "basis": "该俱乐部相似交易成交金额与球员身价的比值中位数（倍数限制在 0.85–1.15）"
        if applied
        else "该俱乐部相似交易的成交金额与身价基本一致，无需调整",
    }
