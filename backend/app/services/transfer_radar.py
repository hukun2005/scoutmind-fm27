"""V3.3.2-05-01 全局转会机会雷达。

只使用真实可读字段：

* ``player_availability.listed / loan_listed / set_for_release``：已确认状态；
* ``player_snapshots.contract_end`` + ``game_date``：合同到期（已确认日期）；
* 阵容需求来自 :mod:`app.analytics.squad`（复用，不重复实现）。

离队意愿在真实来源中不存在，因此不生成任何"想离队"机会；规则推测只写入
``verified_status='inferred'`` 的 ``ai_inferred`` 行，并带明确证据。

扫描结果物化到 ``transfer_opportunities``，页面读取只查表；只有显式刷新
（或该存档尚无快照）才重新扫描。所有查询以 ``fm_save_id`` 隔离。
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Callable

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from ..analytics.squad import squad_overview, user_club
from ..config import settings
from ..ingestion.attributes import position_group, slot_of
from ..models import (
    Alert,
    Club,
    FmSave,
    Player,
    PlayerAvailability,
    PlayerInstance,
    PlayerSnapshot,
    TransferOpportunity,
    TransferOpportunityEvent,
    Watchlist,
    WatchlistItem,
)
from ..utils import iso, utcnow

SCAN_VERSION = "transfer-radar-2"
OPPORTUNITY_TYPES = ("listed", "loan_listed", "release_listed", "contract_expiring", "ai_inferred")
CONFIRMED_TYPES = {"listed", "loan_listed", "release_listed", "contract_expiring"}

TYPE_LABELS = {
    "listed": "已挂牌",
    "loan_listed": "可租借",
    "release_listed": "解约挂牌",
    "contract_expiring": "合同到期",
    "ai_inferred": "AI 推测机会",
}
ALERT_LABELS = {
    "listed": "新增挂牌球员",
    "loan_listed": "新增可租借球员",
    "release_listed": "新增解约挂牌球员",
    "contract_expiring": "合同即将到期",
    "ai_inferred": "AI 推测机会",
}
TYPE_PRIORITY = {
    "listed": 1,
    "loan_listed": 2,
    "release_listed": 3,
    "contract_expiring": 4,
    "ai_inferred": 5,
}
GROUP_LABELS = {
    "strong": "强烈推荐关注",
    "watch": "值得考察",
    "loan": "可租借机会",
    "long_term": "长期潜力目标",
    "not_recommended": "暂不推荐",
}
CONTRACT_BUCKETS = ((6, "6m"), (12, "12m"), (24, "24m"))
WEIGHTS = {"ability": 0.35, "fit": 0.25, "opportunity": 0.25, "financial": 0.15}
UNSUPPORTED_FIELDS = ("transfer_intent", "transfer_budget", "appearance_statistics")
CONTRACT_ALERT_ABILITY = 75  # ability_score 0-100，约等于 CA 145 以上


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _months_between(start: date, end: date) -> int:
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return months


def _reference_date(db: Session, save_id: int) -> date:
    newest = db.scalar(
        select(func.max(PlayerSnapshot.game_date))
        .join(PlayerInstance, PlayerInstance.id == PlayerSnapshot.player_instance_id)
        .where(PlayerInstance.fm_save_id == save_id, PlayerSnapshot.game_date.is_not(None))
    )
    return newest or date.today()


def _player_slot(position: str | None) -> str | None:
    """把扫描器的多位置字符串映射到阵容槽位；无法识别返回 None。"""
    if not position:
        return None
    parts = [part.strip().upper() for part in str(position).replace("/", ",").split(",") if part.strip()]
    for part in parts:
        slot = slot_of(part)
        if slot is not None:
            return slot
    for part in parts:
        group = position_group(part)
        if group is not None:
            return {"GK": "GK", "DF": "CB", "MF": "CM", "FW": "ST"}.get(group)
    return None


def _squad_need(db: Session, save_id: int) -> dict[str, dict[str, float]]:
    """复用阵容分析：槽位 -> 需求强度（0-1）与重要度。没有阵容时返回空字典。"""
    club = user_club(db, save_id)
    if club is None:
        return {}
    overview = squad_overview(db, save_id, club_id=club.id)
    needs: dict[str, dict[str, float]] = {}
    for row in overview.get("depth") or []:
        slot = str(row.get("slot") or "")
        if not slot:
            continue
        coverage = float(row.get("coverage") or 0.0)
        quality = float(row.get("depth_quality") or 0.0)
        importance = float(row.get("importance") or 1.0)
        needs[slot] = {
            "need": _clamp(0.6 * (1 - coverage) + 0.4 * (1 - quality), 0.0, 1.0),
            "importance": importance,
        }
    return needs


def _score_entry(
    *,
    entry_type: str,
    verified: str,
    snapshot: PlayerSnapshot,
    remaining: int | None,
    detail: dict[str, Any],
    needs: dict[str, dict[str, float]],
    slot: str | None,
) -> dict[str, Any]:
    ca = snapshot.ca
    ability = None if ca is None else _clamp((float(ca) - 40) / 140 * 100, 0.0, 100.0)

    fit = None
    if slot is not None and slot in needs:
        fit = round(needs[slot]["need"] * 100, 2)

    opportunity = {
        "listed": 85.0,
        "release_listed": 80.0,
        "loan_listed": 75.0,
        "contract_expiring": {"6m": 80.0, "12m": 65.0, "24m": 50.0}.get(detail.get("bucket"), 50.0),
        "ai_inferred": 40.0,
    }.get(entry_type, 40.0)
    if remaining is not None and remaining <= 12:
        opportunity = min(100.0, opportunity + 5.0)
    if verified == "inferred":
        opportunity = min(opportunity, 45.0)

    dimensions = {
        "ability": ability,
        "fit": fit,
        "opportunity": opportunity,
        "financial": None,  # 没有预算来源，不计算财务可行性
    }
    available = {key: value for key, value in dimensions.items() if value is not None}
    weight_sum = sum(WEIGHTS[key] for key in available)
    overall = (
        round(sum(available[key] * WEIGHTS[key] for key in available) / weight_sum, 2) if weight_sum else None
    )

    data_conf = 0.7
    if snapshot.market_value is not None:
        data_conf += 0.15
    if snapshot.wage is not None:
        data_conf += 0.15
    score_confidence = round(min(1.0, weight_sum) * min(1.0, data_conf), 3) if overall is not None else None

    age = snapshot.age
    potential_gap = None
    if snapshot.ca is not None and snapshot.pa is not None:
        potential_gap = int(snapshot.pa) - int(snapshot.ca)

    group = "not_recommended"
    if overall is not None:
        if overall >= 75 and opportunity >= 70:
            group = "strong"
        elif entry_type == "loan_listed" and overall >= 55:
            group = "loan"
        elif age is not None and age <= 21 and (potential_gap or 0) >= 15 and overall >= 55:
            group = "long_term"
        elif overall >= 60:
            group = "watch"

    return {
        "ability_score": None if ability is None else round(ability, 2),
        "squad_fit_score": fit,
        "opportunity_score": round(opportunity, 2),
        "financial_score": None,
        "overall_score": overall,
        "recommendation_group": group,
        "score_confidence": score_confidence,
    }


def _club_average(db: Session, save_id: int) -> dict[int, tuple[float, int]]:
    """俱乐部平均 ca（仅统计 >=5 人的俱乐部），由 SQL 聚合，避免全量加载。

    与旧实现语义一致：只看当前归属 ``instances.club_id`` 与最新快照的 ca。
    """
    rows = db.execute(
        select(PlayerInstance.club_id, func.avg(PlayerSnapshot.ca), func.count())
        .join(PlayerSnapshot, PlayerSnapshot.id == PlayerInstance.latest_snapshot_id)
        .where(
            PlayerInstance.fm_save_id == save_id,
            PlayerInstance.club_id.is_not(None),
            PlayerSnapshot.ca.is_not(None),
        )
        .group_by(PlayerInstance.club_id)
    ).all()
    return {
        int(club_id): (float(average), int(count))
        for club_id, average, count in rows
        if club_id is not None and count and int(count) >= 5
    }


def _build_entries(
    db: Session,
    save_id: int,
    rows: list[tuple[PlayerInstance, PlayerSnapshot, str | None]],
    availability: dict[int, PlayerAvailability],
    reference_date: date,
    needs: dict[str, dict[str, float]],
    user_club_id: int | None,
    club_average: dict[int, tuple[float, int]] | None = None,
) -> dict[tuple[int, str], dict[str, Any]]:
    if club_average is None:
        club_stats: dict[int, list[int]] = {}
        for instance, snapshot, _name in rows:
            if instance.club_id is None or snapshot.ca is None:
                continue
            club_stats.setdefault(instance.club_id, []).append(int(snapshot.ca))
        club_average = {
            club_id: (sum(values) / len(values), len(values)) for club_id, values in club_stats.items() if len(values) >= 5
        }

    entries: dict[tuple[int, str], dict[str, Any]] = {}

    def add(instance: PlayerInstance, snapshot: PlayerSnapshot, entry_type: str, verified: str,
            confidence: float, source: str, detail: dict[str, Any], remaining: int | None,
            contract: dict[str, Any] | None = None) -> None:
        slot = _player_slot(snapshot.position)
        scores = _score_entry(
            entry_type=entry_type,
            verified=verified,
            snapshot=snapshot,
            remaining=remaining,
            detail=detail,
            needs=needs,
            slot=slot,
        )
        detail = {**detail, "slot": slot, "position": snapshot.position, "age": snapshot.age}
        if contract:
            detail.update(
                {
                    "contract_end": contract.get("contract_end"),
                    "game_date": contract.get("game_date"),
                    "remaining_months": contract.get("remaining_months"),
                    "bucket": contract.get("bucket"),
                }
            )
        entries[(instance.id, entry_type)] = {
            "instance_id": instance.id,
            "type": entry_type,
            "verified_status": verified,
            "confidence": confidence,
            "source": source,
            "detail": detail,
            "remaining": remaining,
            "scores": scores,
        }

    for instance, snapshot, _name in rows:
        row = availability.get(instance.id)
        flags = {
            "listed": row.listed if row else None,
            "loan_listed": row.loan_listed if row else None,
            "set_for_release": row.set_for_release if row else None,
            "observed_at": iso(row.observed_at) if row else None,
        }
        remaining = None
        bucket = None
        if snapshot.contract_end is not None:
            base = snapshot.game_date or reference_date
            remaining = _months_between(base, snapshot.contract_end)
            for limit, label in CONTRACT_BUCKETS:
                if remaining <= limit:
                    bucket = label
                    break
            if remaining < 0:
                remaining = 0
                bucket = "6m"
        contract_detail = {
            "flags": flags,
            "contract_end": iso(snapshot.contract_end),
            "game_date": iso(snapshot.game_date or reference_date),
            "remaining_months": remaining,
            "bucket": bucket,
        }

        if row is not None and row.listed is True:
            add(instance, snapshot, "listed", "confirmed", 1.0, "player_availability",
                {"flags": flags}, remaining, contract_detail)
        if row is not None and row.loan_listed is True:
            add(instance, snapshot, "loan_listed", "confirmed", 1.0, "player_availability",
                {"flags": flags}, remaining, contract_detail)
        if row is not None and row.set_for_release is True:
            add(instance, snapshot, "release_listed", "confirmed", 1.0, "player_availability",
                {"flags": flags}, remaining, contract_detail)
        if bucket is not None:
            add(instance, snapshot, "contract_expiring", "confirmed", 1.0, "player_snapshots",
                contract_detail, remaining, contract_detail)

        if instance.club_id is None or instance.club_id == user_club_id:
            continue
        stats = club_average.get(instance.club_id)
        if stats is None:
            continue
        average_ca, roster_size = stats
        signals: list[str] = []
        if snapshot.age is not None and snapshot.age >= 31 and remaining is not None and remaining <= 24:
            signals.append("年龄 31 岁以上且合同剩余不超过 24 个月，可能与球队长期规划不匹配")
        if snapshot.age is not None and snapshot.age <= 24 and snapshot.ca is not None and snapshot.ca >= average_ca + 5:
            signals.append(f"能力 {snapshot.ca} 高于同队平均 {average_ca:.1f}，可能被更大俱乐部关注")
        if signals:
            add(instance, snapshot, "ai_inferred", "inferred", 0.5, "rule:ageing" if "年龄" in signals[0] else "rule:ability",
                {
                    "flags": flags,
                    "signals": signals,
                    "club_roster_size": roster_size,
                    "club_average_ca": round(average_ca, 1),
                    "contract_end": iso(snapshot.contract_end),
                    "game_date": iso(snapshot.game_date or reference_date),
                    "remaining_months": remaining,
                    "bucket": bucket,
                    "note": "AI 推测机会，不是游戏内挂牌或离队意愿",
                },
                remaining)

    primaries: dict[int, tuple[int, float]] = {}
    for (instance_id, entry_type), entry in entries.items():
        priority = TYPE_PRIORITY[entry_type]
        score = entry["scores"]["overall_score"]
        candidate = (priority, -(score if score is not None else -1))
        current = primaries.get(instance_id)
        if current is None or candidate < current:
            primaries[instance_id] = candidate
    for key, entry in entries.items():
        entry["is_primary"] = primaries.get(entry["instance_id"]) == (
            TYPE_PRIORITY[entry["type"]],
            -(entry["scores"]["overall_score"] if entry["scores"]["overall_score"] is not None else -1),
        )
    return entries


def _watchlist_ids(db: Session, save_id: int) -> set[int]:
    rows = db.scalars(
        select(WatchlistItem.player_instance_id)
        .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
        .where(Watchlist.fm_save_id == save_id)
    )
    return set(rows)


class ScanCancelled(Exception):
    """用户取消扫描。已完成的批次已提交，checkpoint 记录最后处理到的球员。"""

    def __init__(self, checkpoint: dict[str, Any]) -> None:
        super().__init__("scan cancelled")
        self.checkpoint = checkpoint


def _scan_batch(
    db: Session, save_id: int, after_id: int, batch_size: int, changed: Any | None = None
) -> list[tuple[PlayerInstance, PlayerSnapshot, str | None]]:
    """按 ``PlayerInstance.id`` 升序取一批，避免一次性物化整个存档。"""
    query = (
        select(PlayerInstance, PlayerSnapshot, Player.full_name)
        .join(PlayerSnapshot, PlayerSnapshot.id == PlayerInstance.latest_snapshot_id)
        .join(Player, Player.id == PlayerInstance.player_id)
        .where(PlayerInstance.fm_save_id == save_id, PlayerInstance.id > after_id)
        .order_by(PlayerInstance.id.asc())
        .limit(batch_size)
    )
    if changed is not None:
        query = query.where(changed)
    return [(row[0], row[1], row[2]) for row in db.execute(query).all()]


def _count_candidates(db: Session, save_id: int, changed: Any | None = None) -> int:
    query = (
        select(func.count())
        .select_from(PlayerInstance)
        .join(PlayerSnapshot, PlayerSnapshot.id == PlayerInstance.latest_snapshot_id)
        .where(PlayerInstance.fm_save_id == save_id)
    )
    if changed is not None:
        query = query.where(changed)
    return int(db.scalar(query) or 0)


def _availability_for_ids(db: Session, ids: list[int]) -> dict[int, PlayerAvailability]:
    """只取这一批球员的最新可用状态，避免每次扫描加载整张表。"""
    if not ids:
        return {}
    ranked = (
        select(
            PlayerAvailability.id.label("availability_id"),
            func.row_number()
            .over(
                partition_by=PlayerAvailability.player_instance_id,
                order_by=(PlayerAvailability.observed_at.desc(), PlayerAvailability.id.desc()),
            )
            .label("rn"),
        )
        .where(PlayerAvailability.player_instance_id.in_(ids))
        .subquery()
    )
    rows = db.scalars(
        select(PlayerAvailability)
        .join(ranked, ranked.c.availability_id == PlayerAvailability.id)
        .where(ranked.c.rn == 1)
    )
    return {row.player_instance_id: row for row in rows}


def _existing_for_ids(
    db: Session, save_id: int, ids: list[int]
) -> dict[tuple[int, str], TransferOpportunity]:
    if not ids:
        return {}
    rows = db.scalars(
        select(TransferOpportunity).where(
            TransferOpportunity.fm_save_id == save_id,
            TransferOpportunity.player_instance_id.in_(ids),
        )
    )
    return {(row.player_instance_id, row.opportunity_type): row for row in rows}


def _apply_entries(
    db: Session,
    save_id: int,
    entries: dict[tuple[int, str], dict[str, Any]],
    existing: dict[tuple[int, str], TransferOpportunity],
    now: datetime,
    token: str,
    names: dict[int, str],
    discovered: list[dict[str, Any]],
    change_items: list[dict[str, Any]],
) -> dict[str, int]:
    """把一批计算出的机会写回：新增、更新、变化事件与提醒素材。"""
    created = 0
    updated = 0
    events = 0
    for key, entry in entries.items():
        row = existing.get(key)
        scores = entry["scores"]
        detail_json = json.dumps(entry["detail"], ensure_ascii=False, sort_keys=True)
        if row is None:
            row = TransferOpportunity(
                fm_save_id=save_id,
                player_instance_id=entry["instance_id"],
                opportunity_type=entry["type"],
                verified_status=entry["verified_status"],
                confidence=entry["confidence"],
                source=entry["source"],
                first_seen_at=now,
                last_seen_at=now,
                active=True,
                is_primary=entry["is_primary"],
                scan_token=token,
                detail_json=detail_json,
                ability_score=scores["ability_score"],
                squad_fit_score=scores["squad_fit_score"],
                opportunity_score=scores["opportunity_score"],
                financial_score=scores["financial_score"],
                overall_score=scores["overall_score"],
                recommendation_group=scores["recommendation_group"],
                score_confidence=scores["score_confidence"],
            )
            db.add(row)
            created += 1
            discovered.append(
                {
                    "instance_id": entry["instance_id"],
                    "opportunity_type": entry["type"],
                    "verified_status": entry["verified_status"],
                    "ability_score": scores["ability_score"],
                    "overall_score": scores["overall_score"],
                    "detail": entry["detail"],
                }
            )
            events += _record_event(db, save_id, entry["instance_id"], entry["type"], "discovered",
                                    None, _detail_value(entry), now)
            continue

        previous_detail = _loads(row.detail_json)
        changed_event = None
        previous_value = None
        new_value = None
        if not row.active:
            changed_event = "reappeared"
            previous_value = "inactive"
            new_value = "active"
        elif entry["type"] == "contract_expiring" and previous_detail.get("bucket") != entry["detail"].get("bucket"):
            changed_event = "bucket_changed"
            previous_value = str(previous_detail.get("bucket"))
            new_value = str(entry["detail"].get("bucket"))
        elif entry["type"] == "ai_inferred" and previous_detail.get("signals") != entry["detail"].get("signals"):
            changed_event = "inferred_changed"
            previous_value = ";".join(previous_detail.get("signals") or [])
            new_value = ";".join(entry["detail"].get("signals") or [])

        row.last_seen_at = now
        row.active = True
        row.is_primary = entry["is_primary"]
        row.confidence = entry["confidence"]
        row.verified_status = entry["verified_status"]
        row.source = entry["source"]
        row.detail_json = detail_json
        row.scan_token = token
        row.ability_score = scores["ability_score"]
        row.squad_fit_score = scores["squad_fit_score"]
        row.opportunity_score = scores["opportunity_score"]
        row.financial_score = scores["financial_score"]
        row.overall_score = scores["overall_score"]
        row.recommendation_group = scores["recommendation_group"]
        row.score_confidence = scores["score_confidence"]
        updated += 1
        if changed_event:
            events += _record_event(db, save_id, entry["instance_id"], entry["type"], changed_event,
                                    previous_value, new_value, now)
            if changed_event == "bucket_changed" and new_value == "6m":
                change_items.append(
                    {
                        "instance_id": entry["instance_id"],
                        "alert_type": "contract_6m",
                        "title": f"合同进入 6 个月：{names.get(entry['instance_id'], '')}（{now.date()}）",
                        "severity": "warning",
                        "message": "合同剩余不足 6 个月，进入低价谈判窗口",
                        "score": entry["scores"]["overall_score"] or 0.0,
                    }
                )
    return {"created": created, "updated": updated, "events": events}


def _deactivate_rows(
    db: Session,
    rows: list[tuple[TransferOpportunity, str | None]],
    names: dict[int, str],
    change_items: list[dict[str, Any]],
    now: datetime,
) -> int:
    count = 0
    for row, name in rows:
        row.active = False
        row.is_primary = False
        if name:
            names.setdefault(row.player_instance_id, name)
        count += 1
        _record_event(db, row.fm_save_id, row.player_instance_id, row.opportunity_type, "withdrawn",
                      _detail_value({"detail": _loads(row.detail_json)}), None, now)
        if row.opportunity_type in {"listed", "loan_listed", "release_listed"}:
            labels = {"listed": "撤销挂牌", "loan_listed": "取消可租借", "release_listed": "取消解约挂牌"}
            change_items.append(
                {
                    "instance_id": row.player_instance_id,
                    "alert_type": f"{row.opportunity_type}_withdrawn",
                    "title": f"{labels[row.opportunity_type]}：{name or names.get(row.player_instance_id, '')}"
                             f"（{now.date()}）"[:128],
                    "severity": "info",
                    "message": "该球员的可用状态已变化，请重新确认",
                    "score": row.overall_score or 0.0,
                }
            )
    return count


def _deactivate_stale(
    db: Session,
    save_id: int,
    token: str,
    now: datetime,
    names: dict[int, str],
    change_items: list[dict[str, Any]],
    batch_size: int,
) -> int:
    """全量扫描完整结束后，才下线本次未再出现的旧机会（分批，可中断）。"""
    total = 0
    while True:
        rows = db.execute(
            select(TransferOpportunity, Player.full_name)
            .join(PlayerInstance, PlayerInstance.id == TransferOpportunity.player_instance_id)
            .outerjoin(Player, Player.id == PlayerInstance.player_id)
            .where(
                TransferOpportunity.fm_save_id == save_id,
                TransferOpportunity.active.is_(True),
                or_(TransferOpportunity.scan_token.is_(None), TransferOpportunity.scan_token != token),
            )
            .limit(batch_size)
        ).all()
        if not rows:
            break
        total += _deactivate_rows(db, [(row, name) for row, name in rows], names, change_items, now)
        db.commit()
    return total


def _deactivate_for_ids(
    db: Session,
    save_id: int,
    ids: list[int],
    token: str,
    now: datetime,
    names: dict[int, str],
    change_items: list[dict[str, Any]],
) -> int:
    """增量扫描只对本次处理过的球员下线旧机会，避免误伤未变化的数据。"""
    if not ids:
        return 0
    rows = db.execute(
        select(TransferOpportunity, Player.full_name)
        .join(PlayerInstance, PlayerInstance.id == TransferOpportunity.player_instance_id)
        .outerjoin(Player, Player.id == PlayerInstance.player_id)
        .where(
            TransferOpportunity.fm_save_id == save_id,
            TransferOpportunity.player_instance_id.in_(ids),
            TransferOpportunity.active.is_(True),
            or_(TransferOpportunity.scan_token.is_(None), TransferOpportunity.scan_token != token),
        )
    ).all()
    return _deactivate_rows(db, [(row, name) for row, name in rows], names, change_items, now)


def scan_batched(
    db: Session,
    save_id: int,
    *,
    batch_size: int | None = None,
    mode: str = "full",
    since_time: datetime | None = None,
    token: str | None = None,
    checkpoint: dict[str, Any] | None = None,
    cancel_cb: Callable[[], bool] | None = None,
    progress_cb: Callable[[int, int, int, int, int], None] | None = None,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    """分批扫描并把机会物化到 ``transfer_opportunities``。

    * 按 ``PlayerInstance.id`` 键集分页，每批提交一次，进度可观测、可取消；
    * ``mode='incremental'`` 只处理导入时间/关联时间/实例创建时间晚于 ``since_time`` 的球员；
      没有可靠变化标识时退回全量，并在结果里标记 ``incremental_available=False``；
    * 全量扫描完成后才用 ``scan_token`` 下线旧机会；取消或失败时不会误下线。
    """
    save = db.get(FmSave, save_id)
    if save is None:
        raise ValueError("save not found")
    if mode not in {"full", "incremental"}:
        raise ValueError(f"unsupported scan mode: {mode}")
    now = observed_at or utcnow()
    token = token or uuid.uuid4().hex
    batch_size = max(50, int(batch_size or settings.scan_batch_size))
    checkpoint = checkpoint or {}
    incremental_available = mode == "incremental" and since_time is not None
    effective_mode = "incremental" if incremental_available else "full"
    changed = None
    if effective_mode == "incremental":
        changed = or_(
            PlayerSnapshot.imported_at > since_time,
            PlayerInstance.club_linked_at > since_time,
            PlayerInstance.created_at > since_time,
        )

    reference_date = _reference_date(db, save_id)
    needs = _squad_need(db, save_id)
    club_average = _club_average(db, save_id)
    watched = _watchlist_ids(db, save_id)
    total = _count_candidates(db, save_id, changed)

    names: dict[int, str] = {}
    discovered: list[dict[str, Any]] = []
    change_items: list[dict[str, Any]] = []
    created = updated = events = deactivated = 0
    processed = 0
    active_entries = 0
    last_id = int(checkpoint.get("last_instance_id") or 0)

    while True:
        if cancel_cb is not None and cancel_cb():
            raise ScanCancelled(
                {
                    "last_instance_id": last_id,
                    "token": token,
                    "mode": effective_mode,
                    "processed": processed,
                    "matched": created + updated,
                    "failed": 0,
                    "total": total,
                }
            )
        rows = _scan_batch(db, save_id, last_id, batch_size, changed)
        if not rows:
            break
        ids = [row[0].id for row in rows]
        availability = _availability_for_ids(db, ids)
        entries = _build_entries(
            db, save_id, rows, availability, reference_date, needs, save.user_club_id, club_average=club_average
        )
        existing = _existing_for_ids(db, save_id, ids)
        for instance, _snapshot, full_name in rows:
            if full_name:
                names[instance.id] = full_name
        stats = _apply_entries(db, save_id, entries, existing, now, token, names, discovered, change_items)
        created += stats["created"]
        updated += stats["updated"]
        events += stats["events"]
        if effective_mode == "incremental":
            deactivated += _deactivate_for_ids(db, save_id, ids, token, now, names, change_items)
        db.commit()
        processed += len(rows)
        active_entries += len(entries)
        last_id = ids[-1]
        if progress_cb is not None:
            progress_cb(processed, total, created + updated, 0, last_id)

    if effective_mode == "full":
        deactivated = _deactivate_stale(db, save_id, token, now, names, change_items, batch_size)
        events += deactivated

    alerts = _create_alerts(db, save_id, discovered, change_items, names, now, watched)
    db.commit()
    return {
        "save_id": save_id,
        "scan_version": SCAN_VERSION,
        "mode": effective_mode,
        "incremental_available": incremental_available,
        "batch_size": batch_size,
        "scanned_players": processed,
        "created": created,
        "updated": updated,
        "deactivated": deactivated,
        "events": events,
        "alerts_created": alerts,
        "active_opportunities": active_entries,
        "reference_date": iso(reference_date),
        "observed_at": iso(now),
        "checkpoint": {"last_instance_id": last_id, "token": token, "mode": effective_mode},
        "unsupported_fields": list(UNSUPPORTED_FIELDS),
    }


def scan(db: Session, save_id: int, observed_at: datetime | None = None) -> dict[str, Any]:
    """重新扫描并写回机会、变化事件与提醒。无变化时幂等。"""
    return scan_batched(db, save_id, mode="full", observed_at=observed_at)


def _detail_value(entry: dict[str, Any]) -> str:
    detail = entry.get("detail") or {}
    if detail.get("bucket"):
        return f"bucket={detail['bucket']}"
    return entry.get("type") or "active"


def _record_event(db: Session, save_id: int, instance_id: int, opportunity_type: str, event_type: str,
                  previous_value: str | None, new_value: str | None, observed_at: datetime) -> int:
    db.add(
        TransferOpportunityEvent(
            fm_save_id=save_id,
            player_instance_id=instance_id,
            opportunity_type=opportunity_type,
            event_type=event_type,
            previous_value=(previous_value or "")[:64] or None,
            new_value=(new_value or "")[:64] or None,
            observed_at=observed_at,
            evidence_json="{}",
        )
    )
    return 1


def _create_alerts(db: Session, save_id: int, discovered: list[dict[str, Any]],
                   change_items: list[dict[str, Any]], names: dict[int, str], now: datetime,
                   watched: set[int] | None = None) -> int:
    if not discovered and not change_items:
        return 0
    if watched is None:
        watched = _watchlist_ids(db, save_id)
    existing = {
        (row.alert_type, row.player_instance_id, row.title)
        for row in db.scalars(select(Alert).where(Alert.fm_save_id == save_id))
    }
    candidates: list[dict[str, Any]] = []
    for item in discovered:
        instance_id = int(item["instance_id"])
        name = names.get(instance_id)
        if not name:
            continue
        opportunity_type = str(item["opportunity_type"])
        important = instance_id in watched
        if opportunity_type in {"listed", "loan_listed", "release_listed"}:
            important = True
        elif opportunity_type == "contract_expiring":
            detail = item.get("detail") or {}
            important = detail.get("bucket") == "6m" or (item.get("ability_score") or 0) >= CONTRACT_ALERT_ABILITY
        if not important:
            continue
        title = f"{ALERT_LABELS.get(opportunity_type, '转会机会')}：{name}"[:128]
        candidates.append(
            {
                "instance_id": instance_id,
                "alert_type": opportunity_type,
                "title": title,
                "severity": "info" if item.get("verified_status") == "confirmed" else "low",
                "message": f"{TYPE_LABELS.get(opportunity_type, '转会机会')}，更新时间 {iso(now)}",
                "score": item.get("overall_score") or 0.0,
                "watched": instance_id in watched,
            }
        )
    candidates.extend(
        {**item, "watched": item["instance_id"] in watched} for item in change_items[:100]
    )
    candidates.sort(key=lambda item: (not item["watched"], -(item.get("score") or 0.0)))
    created = 0
    for item in candidates[:200]:
        key = (item["alert_type"], item["instance_id"], item["title"])
        if key in existing:
            continue
        db.add(
            Alert(
                fm_save_id=save_id,
                player_instance_id=item["instance_id"],
                alert_type=item["alert_type"],
                severity=item.get("severity", "info"),
                title=item["title"],
                message=item["message"],
            )
        )
        existing.add(key)
        created += 1
    return created


def _loads(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _last_scan_at(db: Session, save_id: int) -> datetime | None:
    return db.scalar(select(func.max(TransferOpportunity.last_seen_at)).where(TransferOpportunity.fm_save_id == save_id))


def ensure_scanned(db: Session, save_id: int) -> dict[str, Any] | None:
    """该存档尚无任何机会行时自动扫描一次，避免首次打开空白。"""
    exists = db.scalar(
        select(func.count()).select_from(TransferOpportunity).where(TransferOpportunity.fm_save_id == save_id)
    )
    if exists:
        return None
    return scan(db, save_id)


def _type_counts(db: Session, save_id: int) -> dict[str, int]:
    rows = db.execute(
        select(TransferOpportunity.opportunity_type, func.count(func.distinct(TransferOpportunity.player_instance_id)))
        .where(TransferOpportunity.fm_save_id == save_id, TransferOpportunity.active.is_(True))
        .group_by(TransferOpportunity.opportunity_type)
    ).all()
    return {str(row[0]): int(row[1]) for row in rows}


def _group_counts(db: Session, save_id: int) -> dict[str, int]:
    rows = db.execute(
        select(TransferOpportunity.recommendation_group, func.count())
        .where(
            TransferOpportunity.fm_save_id == save_id,
            TransferOpportunity.active.is_(True),
            TransferOpportunity.is_primary.is_(True),
        )
        .group_by(TransferOpportunity.recommendation_group)
    ).all()
    return {str(row[0]): int(row[1]) for row in rows if row[0]}


def summary(db: Session, save_id: int, auto_scan: bool = True) -> dict[str, Any]:
    scan_result = ensure_scanned(db, save_id) if auto_scan else None
    counts = _type_counts(db, save_id)
    groups = _group_counts(db, save_id)
    last_scan = _last_scan_at(db, save_id)
    since = utcnow() - timedelta(hours=24)
    new_count = db.scalar(
        select(func.count())
        .select_from(TransferOpportunity)
        .where(
            TransferOpportunity.fm_save_id == save_id,
            TransferOpportunity.active.is_(True),
            TransferOpportunity.first_seen_at >= since,
        )
    )
    total_players = db.scalar(
        select(func.count()).select_from(PlayerInstance).where(PlayerInstance.fm_save_id == save_id)
    )
    known_club = db.scalar(
        select(func.count())
        .select_from(PlayerInstance)
        .where(PlayerInstance.fm_save_id == save_id, PlayerInstance.club_id.is_not(None))
    )
    missing_contract = db.scalar(
        select(func.count())
        .select_from(PlayerInstance)
        .join(PlayerSnapshot, PlayerSnapshot.id == PlayerInstance.latest_snapshot_id)
        .where(PlayerInstance.fm_save_id == save_id, PlayerSnapshot.contract_end.is_(None))
    )
    unread = db.scalar(
        select(func.count()).select_from(Alert).where(Alert.fm_save_id == save_id, Alert.read_at.is_(None))
    )
    top = _top_recommendations(db, save_id)
    return {
        "save_id": save_id,
        "scan_version": SCAN_VERSION,
        "last_scan_at": iso(last_scan),
        "counts": {
            "listed": counts.get("listed", 0),
            "loan_listed": counts.get("loan_listed", 0),
            "release_listed": counts.get("release_listed", 0),
            "contract_expiring": counts.get("contract_expiring", 0),
            "ai_inferred": counts.get("ai_inferred", 0),
            "new_24h": int(new_count or 0),
        },
        "groups": groups,
        "group_labels": GROUP_LABELS,
        "top_recommendations": top,
        "alerts_unread": int(unread or 0),
        "capabilities": {
            "total_players": int(total_players or 0),
            "known_club_players": int(known_club or 0),
            "missing_contract": int(missing_contract or 0),
            "transfer_intent": "unsupported",
            "transfer_intent_note": "当前数据源不提供离队意愿字段，雷达不生成“想离队”机会",
            "transfer_budget": "unsupported",
            "appearance_statistics": "unsupported",
            "known_club_note": "真实存档中绝大多数球员没有俱乐部归属，俱乐部筛选只覆盖已知俱乐部",
        },
        "unsupported_fields": list(UNSUPPORTED_FIELDS),
        "auto_scan": scan_result,
    }


def _top_recommendations(db: Session, save_id: int, limit: int = 8) -> list[dict[str, Any]]:
    query = (
        select(TransferOpportunity, Player.full_name, PlayerSnapshot, Club.name)
        .join(PlayerInstance, PlayerInstance.id == TransferOpportunity.player_instance_id)
        .join(Player, Player.id == PlayerInstance.player_id)
        .join(PlayerSnapshot, PlayerSnapshot.id == PlayerInstance.latest_snapshot_id)
        .outerjoin(Club, Club.id == PlayerInstance.club_id)
        .where(
            TransferOpportunity.fm_save_id == save_id,
            TransferOpportunity.active.is_(True),
            TransferOpportunity.is_primary.is_(True),
            TransferOpportunity.overall_score.is_not(None),
        )
        .order_by(TransferOpportunity.overall_score.desc())
        .limit(limit)
    )
    return [
        {
            "instance_id": row[0].player_instance_id,
            "name": row[1],
            "club_name": row[3],
            "position": row[2].position,
            "age": row[2].age,
            "opportunity_type": row[0].opportunity_type,
            "overall_score": row[0].overall_score,
            "group": row[0].recommendation_group,
        }
        for row in db.execute(query).all()
    ]


def _serialize_row(row: TransferOpportunity, name: str | None, snapshot: PlayerSnapshot | None,
                   club_name: str | None, club_id: int | None = None,
                   types: list[str] | None = None) -> dict[str, Any]:
    detail = _loads(row.detail_json)
    flags = detail.get("flags") or {}
    return {
        "opportunity_id": row.id,
        "instance_id": row.player_instance_id,
        "player_name": name,
        "club_id": club_id,
        "club_name": club_name,
        "position": snapshot.position if snapshot is not None else detail.get("position"),
        "age": snapshot.age if snapshot is not None else detail.get("age"),
        "market_value": snapshot.market_value if snapshot is not None else None,
        "wage": snapshot.wage if snapshot is not None else None,
        "contract_end": iso(snapshot.contract_end) if snapshot is not None else detail.get("contract_end"),
        "contract_remaining_months": detail.get("remaining_months"),
        "contract_bucket": detail.get("bucket"),
        "listed": flags.get("listed"),
        "loan_listed": flags.get("loan_listed"),
        "set_for_release": flags.get("set_for_release"),
        "opportunity_type": row.opportunity_type,
        "verified_status": row.verified_status,
        "confidence": row.confidence,
        "source": row.source,
        "is_primary": row.is_primary,
        "scores": {
            "ability": row.ability_score,
            "squad_fit": row.squad_fit_score,
            "opportunity": row.opportunity_score,
            "financial": row.financial_score,
            "overall": row.overall_score,
            "confidence": row.score_confidence,
        },
        "recommendation_group": row.recommendation_group,
        "detail": detail,
        "types": types or [row.opportunity_type],
        "first_seen_at": iso(row.first_seen_at),
        "last_seen_at": iso(row.last_seen_at),
    }


def list_opportunities(
    db: Session,
    save_id: int,
    *,
    opportunity_type: str | None = None,
    club_id: int | None = None,
    position: str | None = None,
    age_min: int | None = None,
    age_max: int | None = None,
    group: str | None = None,
    search: str | None = None,
    sort: str = "score",
    limit: int = 30,
    offset: int = 0,
    auto_scan: bool = True,
) -> dict[str, Any]:
    if auto_scan:
        ensure_scanned(db, save_id)
    conditions = [TransferOpportunity.fm_save_id == save_id, TransferOpportunity.active.is_(True)]
    if opportunity_type:
        if opportunity_type not in OPPORTUNITY_TYPES:
            raise ValueError(f"unsupported opportunity_type: {opportunity_type}")
        conditions.append(TransferOpportunity.opportunity_type == opportunity_type)
    else:
        conditions.append(TransferOpportunity.is_primary.is_(True))
    if group:
        conditions.append(TransferOpportunity.recommendation_group == group)
    if club_id is not None:
        conditions.append(PlayerInstance.club_id == club_id)
    if position:
        conditions.append(PlayerSnapshot.position.ilike(f"%{position.upper()}%"))
    if age_min is not None:
        conditions.append(PlayerSnapshot.age >= age_min)
    if age_max is not None:
        conditions.append(PlayerSnapshot.age <= age_max)
    if search:
        pattern = f"%{search.strip()}%"
        conditions.append(or_(Player.full_name.ilike(pattern), Club.name.ilike(pattern)))

    base = (
        select(TransferOpportunity, Player.full_name, PlayerSnapshot, Club.name, PlayerInstance.club_id)
        .join(PlayerInstance, PlayerInstance.id == TransferOpportunity.player_instance_id)
        .join(Player, Player.id == PlayerInstance.player_id)
        .join(PlayerSnapshot, PlayerSnapshot.id == PlayerInstance.latest_snapshot_id)
        .outerjoin(Club, Club.id == PlayerInstance.club_id)
        .where(and_(*conditions))
    )
    if sort == "contract":
        base = base.order_by(PlayerSnapshot.contract_end.asc().nulls_last())
    elif sort == "age":
        base = base.order_by(PlayerSnapshot.age.asc().nulls_last())
    elif sort == "value":
        base = base.order_by(PlayerSnapshot.market_value.desc().nulls_last())
    elif sort == "newest":
        base = base.order_by(TransferOpportunity.first_seen_at.desc())
    else:
        base = base.order_by(
            TransferOpportunity.overall_score.desc().nulls_last(),
            TransferOpportunity.player_instance_id.asc(),
        )
    total = db.scalar(
        select(func.count())
        .select_from(TransferOpportunity)
        .join(PlayerInstance, PlayerInstance.id == TransferOpportunity.player_instance_id)
        .join(Player, Player.id == PlayerInstance.player_id)
        .join(PlayerSnapshot, PlayerSnapshot.id == PlayerInstance.latest_snapshot_id)
        .outerjoin(Club, Club.id == PlayerInstance.club_id)
        .where(and_(*conditions))
    )
    rows = db.execute(base.limit(limit).offset(offset)).all()
    instance_ids = [row[0].player_instance_id for row in rows]
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
    items = [
        _serialize_row(row[0], row[1], row[2], row[3], row[4], type_map.get(row[0].player_instance_id))
        for row in rows
    ]
    return {"items": items, "total": int(total or 0), "limit": limit, "offset": offset, "sort": sort}


def player_opportunities(db: Session, save_id: int, instance_id: int) -> dict[str, Any]:
    rows = db.execute(
        select(TransferOpportunity, Player.full_name, PlayerSnapshot, Club.name, PlayerInstance.club_id)
        .join(PlayerInstance, PlayerInstance.id == TransferOpportunity.player_instance_id)
        .join(Player, Player.id == PlayerInstance.player_id)
        .join(PlayerSnapshot, PlayerSnapshot.id == PlayerInstance.latest_snapshot_id)
        .outerjoin(Club, Club.id == PlayerInstance.club_id)
        .where(
            TransferOpportunity.fm_save_id == save_id,
            TransferOpportunity.player_instance_id == instance_id,
        )
        .order_by(TransferOpportunity.opportunity_type)
    ).all()
    if not rows:
        return {"instance_id": instance_id, "items": [], "types": []}
    types = [str(row[0].opportunity_type) for row in rows if row[0].active]
    primary = next((row for row in rows if row[0].is_primary), rows[0])
    payload = _serialize_row(primary[0], primary[1], primary[2], primary[3], primary[4], types)
    payload["items"] = [_serialize_row(row[0], row[1], row[2], row[3], row[4]) for row in rows]
    return payload


def list_events(db: Session, save_id: int, instance_id: int | None = None, limit: int = 50,
                offset: int = 0) -> dict[str, Any]:
    conditions = [TransferOpportunityEvent.fm_save_id == save_id]
    if instance_id is not None:
        conditions.append(TransferOpportunityEvent.player_instance_id == instance_id)
    total = db.scalar(select(func.count()).select_from(TransferOpportunityEvent).where(and_(*conditions)))
    rows = db.execute(
        select(TransferOpportunityEvent, Player.full_name)
        .join(PlayerInstance, PlayerInstance.id == TransferOpportunityEvent.player_instance_id)
        .join(Player, Player.id == PlayerInstance.player_id)
        .where(and_(*conditions))
        .order_by(TransferOpportunityEvent.observed_at.desc(), TransferOpportunityEvent.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return {
        "items": [
            {
                "event_id": row[0].id,
                "instance_id": row[0].player_instance_id,
                "player_name": row[1],
                "opportunity_type": row[0].opportunity_type,
                "event_type": row[0].event_type,
                "previous_value": row[0].previous_value,
                "new_value": row[0].new_value,
                "observed_at": iso(row[0].observed_at),
            }
            for row in rows
        ],
        "total": int(total or 0),
        "limit": limit,
        "offset": offset,
    }


def list_alerts(db: Session, save_id: int, unread_only: bool = False, limit: int = 50) -> dict[str, Any]:
    conditions = [Alert.fm_save_id == save_id]
    if unread_only:
        conditions.append(Alert.read_at.is_(None))
    rows = db.execute(
        select(Alert, Player.full_name)
        .outerjoin(PlayerInstance, PlayerInstance.id == Alert.player_instance_id)
        .outerjoin(Player, Player.id == PlayerInstance.player_id)
        .where(and_(*conditions))
        .order_by(Alert.created_at.desc())
        .limit(limit)
    ).all()
    unread = db.scalar(
        select(func.count()).select_from(Alert).where(Alert.fm_save_id == save_id, Alert.read_at.is_(None))
    )
    return {
        "items": [
            {
                "alert_id": row[0].id,
                "instance_id": row[0].player_instance_id,
                "player_name": row[1],
                "type": row[0].alert_type,
                "severity": row[0].severity,
                "title": row[0].title,
                "message": row[0].message,
                "read_at": iso(row[0].read_at),
                "created_at": iso(row[0].created_at),
            }
            for row in rows
        ],
        "unread": int(unread or 0),
    }


def mark_alert_read(db: Session, save_id: int, alert_id: int) -> dict[str, Any]:
    alert = db.get(Alert, alert_id)
    if alert is None or alert.fm_save_id != save_id:
        raise ValueError("alert not found")
    if alert.read_at is None:
        alert.read_at = utcnow()
        db.commit()
    return {"alert_id": alert.id, "read_at": iso(alert.read_at)}
