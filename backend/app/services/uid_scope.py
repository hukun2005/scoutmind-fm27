"""V3.2.9 Phase 1：UID 作用域。

UID 是「一个存档内的关联键」，不是全球永久身份。本模块负责：

* 统一分类（复用 :mod:`app.ingestion.uid_status`，不重新实现哨兵规则）；
* 生成带作用域的幂等观测键（存档 + 存档身份指纹 + 会话 + 来源 + 实例 + 时间）；
* 只追加地记录观测，重放同一扫描不会产生第二行；
* 统计同存档内的唯一 / 重复 / 缺失 / 冲突数量。

这里不建立任何「跨存档 UID 唯一」约束，也不同步把 UID 当成身份。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..ingestion.uid_status import UID_INVALID, UID_SENTINEL, classify_uid
from ..models import PlayerInstance, PlayerUidObservation, SaveIdentity
from ..utils import utcnow

#: ``player_uid_observations.status``
STATUS_VALID = "Valid"
STATUS_MISSING = "Missing"
STATUS_DUPLICATE = "Duplicate"
STATUS_CONFLICTED = "Conflicted"
STATUS_STALE = "Stale"
STATUS_UNSUPPORTED = "Unsupported"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def digest_json(payload: Any) -> str:
    """稳定 JSON 摘要：键排序、无空格，便于跨进程比对。"""
    return sha256_text(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str))


@dataclass(frozen=True)
class UidScope:
    """一次 UID 观测的作用域。任何一项变化都意味着新的观测，而不是覆盖旧观测。"""

    save_id: int
    source_type: str = "live_reader"
    save_identity_fingerprint: str | None = None
    session_key: str | None = None
    game_build: str | None = None
    layout_version: str | None = None

    def describe(self) -> dict[str, Any]:
        return {
            "save_id": self.save_id,
            "source_type": self.source_type,
            "save_identity_fingerprint": self.save_identity_fingerprint,
            "session_key": self.session_key,
            "game_build": self.game_build,
            "layout_version": self.layout_version,
        }


def current_identity_fingerprint(db: Session, save_id: int) -> str | None:
    """该存档当前最可信的存档身份指纹；没有就返回 None（绝不编造）。"""
    identity = db.scalar(
        select(SaveIdentity)
        .where(SaveIdentity.fm_save_id == save_id)
        .order_by(SaveIdentity.last_seen_at.desc(), SaveIdentity.id.desc())
        .limit(1)
    )
    return identity.identity_fingerprint if identity is not None else None


def attribute_record_digest(*, name: str | None, birth_date: Any, uid: str | None) -> str:
    """属性记录摘要：只含身份字段，不含任何内存地址。"""
    return digest_json({"name": name or "", "birth_date": str(birth_date or ""), "uid": uid or ""})


def observation_key(
    scope: UidScope,
    *,
    uid_raw: str | None,
    player_instance_id: int | None,
    observed_at: datetime,
) -> str:
    return digest_json(
        {
            **scope.describe(),
            "uid": uid_raw,
            "player_instance_id": player_instance_id,
            "observed_at": observed_at.replace(microsecond=0).isoformat(),
        }
    )


def status_for_assessment(status: str) -> tuple[str, str | None]:
    """把底层分类结果映射成观测状态。哨兵 / 缺失 / 非法一律是 Missing，不是 0。"""
    if status == "valid":
        return STATUS_VALID, None
    if status == UID_SENTINEL:
        return STATUS_MISSING, "sentinel_uid"
    if status == UID_INVALID:
        return STATUS_MISSING, "invalid_uid"
    return STATUS_MISSING, "missing_uid"


def record_observation(
    db: Session,
    scope: UidScope,
    *,
    uid_raw: str | None,
    player_instance_id: int | None,
    player_id: int | None,
    name: str | None = None,
    birth_date: Any = None,
    observed_at: datetime | None = None,
    confidence: float | None = None,
    status: str | None = None,
    uid_reason: str | None = None,
    conflicting_player_id: int | None = None,
    flush: bool = True,
) -> PlayerUidObservation:
    """幂等记录一条 UID 观测；已存在则返回原行（不更新、不覆盖）。

    ``flush=False`` 供批量扫描使用：由调用方在批末统一 flush，避免逐行 fsync。
    """
    moment = (observed_at or utcnow()).replace(microsecond=0)
    assessment = classify_uid(uid_raw)
    derived_status, derived_reason = status_for_assessment(assessment.status)
    final_status = status or derived_status
    key = observation_key(scope, uid_raw=assessment.raw_uid, player_instance_id=player_instance_id, observed_at=moment)
    existing = db.scalar(
        select(PlayerUidObservation).where(
            PlayerUidObservation.fm_save_id == scope.save_id,
            PlayerUidObservation.observation_key == key,
        )
    )
    if existing is not None:
        return existing

    digest = attribute_record_digest(name=name, birth_date=birth_date, uid=assessment.raw_uid)
    evidence = digest_json(
        {
            "observation_key": key,
            "scope": scope.describe(),
            "uid_status": assessment.status,
            "attribute_record_digest": digest,
            "player_instance_id": player_instance_id,
            "player_id": player_id,
            "status": final_status,
        }
    )
    observation = PlayerUidObservation(
        fm_save_id=scope.save_id,
        observation_key=key,
        save_identity_fingerprint=scope.save_identity_fingerprint,
        session_key=scope.session_key,
        player_instance_id=player_instance_id,
        player_id=player_id,
        uid=assessment.raw_uid,
        uid_status=assessment.status,
        uid_reason=uid_reason or derived_reason,
        status=final_status,
        source_type=scope.source_type,
        game_build=scope.game_build,
        layout_version=scope.layout_version,
        observed_at=moment,
        confidence=confidence if confidence is not None else (1.0 if assessment.is_valid else None),
        attribute_record_digest=digest,
        evidence_hash=evidence,
        conflicting_player_id=conflicting_player_id,
    )
    db.add(observation)
    if flush:
        db.flush()
    return observation


def duplicate_uid_groups(db: Session, save_id: int) -> list[dict[str, Any]]:
    """同存档内一个 UID 对应多个球员实体：重复，不自动合并。"""
    rows = db.execute(
        select(
            PlayerInstance.save_local_uid,
            func.count(func.distinct(PlayerInstance.player_id)),
            func.min(PlayerInstance.player_id),
            func.max(PlayerInstance.player_id),
        )
        .where(PlayerInstance.fm_save_id == save_id)
        .group_by(PlayerInstance.save_local_uid)
        .having(func.count(func.distinct(PlayerInstance.player_id)) > 1)
        .order_by(PlayerInstance.save_local_uid)
    ).all()
    return [
        {
            "uid": row[0],
            "player_count": int(row[1]),
            "first_player_id": int(row[2]),
            "last_player_id": int(row[3]),
        }
        for row in rows
    ]


def players_for_uid(db: Session, save_id: int, uid: str) -> list[int]:
    return list(
        db.scalars(
            select(PlayerInstance.player_id)
            .where(
                PlayerInstance.fm_save_id == save_id,
                PlayerInstance.save_local_uid == uid,
            )
            .distinct()
            .order_by(PlayerInstance.player_id)
        )
    )


def summary(db: Session, save_id: int) -> dict[str, Any]:
    """当前存档的 UID 作用域统计（真实数据库计数，不复制历史数字）。"""
    total_instances = int(
        db.scalar(select(func.count()).select_from(PlayerInstance).where(PlayerInstance.fm_save_id == save_id)) or 0
    )
    observations = db.execute(
        select(PlayerUidObservation.status, func.count())
        .where(PlayerUidObservation.fm_save_id == save_id)
        .group_by(PlayerUidObservation.status)
    ).all()
    by_status = {row[0]: int(row[1]) for row in observations}
    distinct_uids = int(
        db.scalar(
            select(func.count(func.distinct(PlayerInstance.save_local_uid))).where(
                PlayerInstance.fm_save_id == save_id
            )
        )
        or 0
    )
    duplicates = duplicate_uid_groups(db, save_id)
    return {
        "save_id": save_id,
        "player_instances": total_instances,
        "distinct_save_local_uids": distinct_uids,
        "observations": sum(by_status.values()),
        "by_status": by_status,
        "duplicate_uid_count": len(duplicates),
        "duplicate_uids": duplicates[:50],
        "note": "UID 只作存档内关联键；跨存档相同 UID 不视为同一球员",
    }
