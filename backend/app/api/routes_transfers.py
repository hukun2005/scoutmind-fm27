"""Transfer Intelligence and club endpoints."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..analytics.transfers import (
    count_transfers,
    TransferFilter,
    club_transfer_profile,
    fetch_transfers,
    serialize_transfer,
    similar_transfers,
    transfer_price_stats,
)
from ..analytics.deals import (
    deal_cost,
    decision_report,
    investment_score,
    transaction_summary,
    transfer_review,
)
from ..analytics.valuation import estimate_value
from ..clubs import ClubResolver
from ..db import get_db
from ..models import Club, FmSave, PlayerInstance, PlayerValuation, Transfer, TransferCandidate
from ..schemas import DealRequest
from ..utils import iso, utcnow
from .deps import (
    candidate_in_save_or_404,
    get_active_save,
    get_current_user,
    owned_save_or_404,
    transfer_in_save_or_404,
)

router = APIRouter()


def _filters(
    status: str,
    transfer_type: str | None,
    from_date: date | None,
    to_date: date | None,
    club_id: int | None,
    position_group: str | None,
    league: str | None,
    min_fee: float | None,
    max_fee: float | None,
    min_age: int | None,
    max_age: int | None,
    min_ca: int | None,
    max_ca: int | None,
) -> TransferFilter:
    return TransferFilter(
        status=status,
        transfer_type=transfer_type,
        from_date=from_date,
        to_date=to_date,
        club_id=club_id,
        position_group=position_group.upper() if position_group else None,
        league=league,
        min_fee=min_fee,
        max_fee=max_fee,
        min_age=min_age,
        max_age=max_age,
        min_ca=min_ca,
        max_ca=max_ca,
    )


@router.get("/transfers")
def list_transfers(
    save_id: int | None = Query(default=None),
    status: str = Query(default="completed"),
    transfer_type: str | None = Query(default=None),
    from_date: date | None = Query(default=None, alias="from_date"),
    to_date: date | None = Query(default=None, alias="to_date"),
    club_id: int | None = Query(default=None),
    position_group: str | None = Query(default=None),
    league: str | None = Query(default=None),
    min_fee: float | None = Query(default=None, ge=0),
    max_fee: float | None = Query(default=None, ge=0),
    min_age: int | None = Query(default=None),
    max_age: int | None = Query(default=None),
    min_ca: int | None = Query(default=None),
    max_ca: int | None = Query(default=None),
    sort: str = Query(default="-transfer_date"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Completed (or all) transfers with their fee components."""
    filters = _filters(
        status, transfer_type, from_date, to_date, club_id, position_group, league, min_fee, max_fee, min_age, max_age,
        min_ca, max_ca,
    )
    target_save = save_id or save.id
    # 分页在 SQL 层完成（没有位置筛选时是真正的 LIMIT/OFFSET），总数用 COUNT 查询。
    total = count_transfers(db, target_save, filters)
    rows = fetch_transfers(db, target_save, filters, limit=limit, offset=offset)
    clubs = {club.id: club for club in db.scalars(select(Club).where(Club.fm_save_id == target_save))}
    items = [serialize_transfer(row, clubs) for row in rows]
    priced = [row for row in all_rows if row.effective_fee is not None]
    total_rows = max(total, 1)
    return {
        "items": items,
        "total": total,
        "coverage": {
            "effective_fee": round(len(priced) / total_rows, 4),
            "transfer_date": 1.0,
            "ca_at_transfer": round(
                sum(1 for row in all_rows if row.player_ca_at_transfer is not None) / total_rows, 4
            ),
            "contract_remaining_months": round(
                sum(1 for row in all_rows if row.contract_remaining_months is not None) / total_rows, 4
            ),
        },
    }


@router.get("/transfers/stats")
def transfer_stats(
    save_id: int | None = Query(default=None),
    position_group: str | None = Query(default=None),
    min_age: int | None = Query(default=None),
    max_age: int | None = Query(default=None),
    min_ca: int | None = Query(default=None),
    max_ca: int | None = Query(default=None),
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    club_id: int | None = Query(default=None),
    league: str | None = Query(default=None),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Median/quartile statistics for completed transfers."""
    filters = _filters(
        "completed", None, from_date, to_date, club_id, position_group, league, None, None, min_age, max_age, min_ca,
        max_ca,
    )
    return transfer_price_stats(db, save_id or save.id, filters)


@router.get("/transfers/similar")
def transfers_similar(
    instance_id: int = Query(...),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
) -> dict[str, Any]:
    """Weighted comparable transfers for one player."""
    from .deps import instance_owned_or_404

    instance_owned_or_404(db, instance_id, user)
    try:
        outcome = similar_transfers(db, instance_id, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "similar_unavailable", "message": str(exc)}) from exc
    return {
        "target": outcome.target,
        "items": outcome.items,
        "effective_weights": outcome.effective_weights,
        "missing_fields": outcome.missing_fields,
        "data_gaps": outcome.data_gaps,
        "sample_size": outcome.sample_size,
    }


@router.get("/transfers/valuation")
def transfers_valuation(
    instance_id: int = Query(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
) -> dict[str, Any]:
    """Comparable-transfer valuation range, stored for audit."""
    from .deps import instance_owned_or_404

    instance_owned_or_404(db, instance_id, user)
    result = estimate_value(db, instance_id)
    db.add(
        PlayerValuation(
            player_instance_id=instance_id,
            as_of=utcnow(),
            method=str(result["method"]),
            algorithm_version=str(result["algorithm_version"]),
            low=result["low"] if isinstance(result["low"], (int, float)) else None,
            mid=result["mid"] if isinstance(result["mid"], (int, float)) else None,
            high=result["high"] if isinstance(result["high"], (int, float)) else None,
            sample_size=int(result["sample_size"]),
            confidence=str(result["confidence"]),
            insufficient_sample=bool(result["insufficient_sample"]),
            evidence_json=__import__("json").dumps(result["basis"], ensure_ascii=False),
        )
    )
    db.commit()
    return result


@router.get("/transfers/review")
def transfers_review(
    save_id: int | None = Query(default=None),
    club_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Review the managed club's completed deals: price percentile, later value and CA change."""
    return transfer_review(db, save_id or save.id, club_id)


@router.get("/transfers/categories")
def transfers_categories(
    save_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Transaction taxonomy with counts and the rules that keep a category out of price statistics."""
    return transaction_summary(db, save_id or save.id)


@router.get("/transfers/{transfer_id}/cost")
def transfer_cost(
    transfer_id: int,
    wage_period: str = Query(default="week", pattern="^(week|month|year)$"),
    contract_years: float | None = Query(default=None, gt=0, le=20),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
) -> dict[str, Any]:
    """Total cost model for one recorded transfer."""
    transfer = db.get(Transfer, transfer_id)
    if transfer is None:
        raise HTTPException(status_code=404, detail={"code": "transfer_not_found", "message": "交易不存在"})
    owned_save_or_404(db, transfer.fm_save_id, user)
    return deal_cost(db, transfer, wage_period=wage_period, contract_years=contract_years)


@router.post("/transfers/deal-report")
def deal_report(
    body: DealRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Decision report for a prospective signing: fit, cost, wage, age, resale and recommendation."""
    target = owned_save_or_404(db, body.save_id, user) if body.save_id is not None else save
    instance = db.get(PlayerInstance, body.instance_id)
    if instance is None or instance.fm_save_id != target.id:
        raise HTTPException(status_code=404, detail={"code": "player_not_found", "message": "球员不存在"})
    try:
        return decision_report(
            db,
            target.id,
            body.instance_id,
            fee=body.fee,
            budget=body.budget,
            wage_period=body.wage_period,
            contract_years=body.contract_years,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "player_not_found", "message": str(exc)}) from exc


@router.get("/transfers/investment")
def transfer_investment(
    instance_id: int = Query(...),
    total_cost: float | None = Query(default=None, ge=0),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
) -> dict[str, Any]:
    """Investment score for a player at a given total cost."""
    instance = db.get(PlayerInstance, instance_id)
    if instance is None:
        raise HTTPException(status_code=404, detail={"code": "player_not_found", "message": "球员不存在"})
    owned_save_or_404(db, instance.fm_save_id, user)
    return investment_score(db, instance_id, total_cost)


@router.get("/transfers/candidates", summary="待确认的俱乐部变化（候选事件）")
def list_candidates(
    save_id: int | None = Query(default=None),
    status: str = Query(default="candidate"),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """快照对比发现的俱乐部变化：在确认前只是候选事件，不进入任何统计。"""
    target = owned_save_or_404(db, save_id, user) if save_id is not None else save
    query = select(TransferCandidate).where(TransferCandidate.fm_save_id == target.id)
    if status != "all":
        query = query.where(TransferCandidate.status == status)
    rows = list(db.scalars(query.order_by(TransferCandidate.detected_at.desc()).limit(limit)))
    return {
        "items": [_candidate_payload(db, row) for row in rows],
        "total": len(rows),
        "note": "候选事件来自快照对比，只有确认后才会生成交易记录",
    }


@router.post("/transfers/candidates/{candidate_id}/confirm", status_code=201, summary="确认候选事件")
def confirm_candidate(
    candidate_id: int,
    payload: dict[str, Any] | None = None,
    save_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """确认一个候选变化；可关联已有交易，否则按确认信息生成一笔无金额的已完成交易。"""
    target = owned_save_or_404(db, save_id, user) if save_id is not None else save
    candidate = candidate_in_save_or_404(db, candidate_id, target)
    if candidate.status != "candidate":
        raise HTTPException(status_code=409, detail={"code": "candidate_not_open", "message": "该候选事件已处理"})
    body = payload or {}
    transfer_id = body.get("transfer_id")
    if transfer_id is not None:
        try:
            numeric_transfer_id = int(transfer_id)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=404, detail={"code": "transfer_not_found", "message": "交易不存在"}
            ) from None
        transfer = transfer_in_save_or_404(db, numeric_transfer_id, target)
        candidate.confirmed_transfer_id = transfer.id
    else:
        instance = db.get(PlayerInstance, candidate.player_instance_id)
        transfer = Transfer(
            fm_save_id=candidate.fm_save_id,
            source_record_id=f"candidate-{candidate.id}",
            player_instance_id=candidate.player_instance_id,
            player_name=instance.player.full_name if instance and instance.player else "未知球员",
            from_club_id=candidate.from_club_id,
            to_club_id=candidate.to_club_id,
            from_club_name=_club_name(db, candidate.from_club_id),
            to_club_name=_club_name(db, candidate.to_club_id),
            transfer_type="loan" if candidate.kind == "loan" else "permanent",
            status="completed",
            transfer_date=_date_or_today(body.get("transfer_date"), candidate.detected_at.date()),
            currency="EUR",
            fee_paid=body.get("fee"),
            source="manual",
            confidence=0.6,
        )
        db.add(transfer)
        db.flush()
        candidate.confirmed_transfer_id = transfer.id
    candidate.status = "confirmed"
    db.commit()
    return {"candidate": _candidate_payload(db, candidate), "transfer_id": candidate.confirmed_transfer_id}


@router.post("/transfers/candidates/{candidate_id}/dismiss", summary="标记候选事件为误报")
def dismiss_candidate(
    candidate_id: int,
    payload: dict[str, Any] | None = None,
    save_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """把候选变化标记为误报（例如租借结束回归、退役或数据错乱）。"""
    target = owned_save_or_404(db, save_id, user) if save_id is not None else save
    candidate = candidate_in_save_or_404(db, candidate_id, target)
    candidate.status = "dismissed"
    reason = (payload or {}).get("reason")
    if reason:
        evidence = json.loads(candidate.evidence_json or "{}")
        evidence["dismiss_reason"] = str(reason)
        candidate.evidence_json = json.dumps(evidence, ensure_ascii=False)
    db.commit()
    return {"candidate": _candidate_payload(db, candidate)}


def _candidate_payload(db: Session, candidate: TransferCandidate) -> dict[str, Any]:
    instance = db.get(PlayerInstance, candidate.player_instance_id)
    return {
        "id": candidate.id,
        "player": {
            "instance_id": candidate.player_instance_id,
            "name": instance.player.full_name if instance and instance.player else None,
        },
        "from_club": _club_name(db, candidate.from_club_id),
        "to_club": _club_name(db, candidate.to_club_id),
        "kind": candidate.kind,
        "status": candidate.status,
        "detected_at": iso(candidate.detected_at),
        "previous_observed_at": iso(candidate.previous_observed_at) if candidate.previous_observed_at else None,
        "confirmed_transfer_id": candidate.confirmed_transfer_id,
        "evidence": json.loads(candidate.evidence_json or "{}"),
    }


def _club_name(db: Session, club_id: int | None) -> str | None:
    if club_id is None:
        return None
    club = db.get(Club, club_id)
    return club.name if club else None


def _date_or_today(raw: object, fallback: date) -> date:
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return fallback
    return fallback


@router.get("/clubs")
def list_clubs(
    save_id: int | None = Query(default=None),
    query: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Clubs of the save with provenance: where each record came from and how much to trust it."""
    target = save_id or save.id
    items = ClubResolver(db, target).search(query=query, limit=limit)
    # `club_id` 是既有前端使用的字段名，保留以兼容；`id` 供新代码使用。
    shaped = [{**item, "club_id": item["id"]} for item in items]
    return {"items": shaped, "total": len(shaped)}

@router.get("/clubs/{club_id}/transfer-profile")
def club_profile(
    club_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
) -> dict[str, Any]:
    """Buy/sell behaviour of one club."""
    club = db.get(Club, club_id)
    if club is None:
        raise HTTPException(status_code=404, detail={"code": "club_not_found", "message": "俱乐部不存在"})
    owned_save_or_404(db, club.fm_save_id, user)
    try:
        return club_transfer_profile(db, club_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "club_not_found", "message": str(exc)}) from exc


def _save_of_instance(db: Session, instance_id: int) -> int:
    """Save that owns a player instance, so a deal report can default its scope."""
    instance = db.get(PlayerInstance, instance_id)
    if instance is None:
        raise HTTPException(status_code=404, detail={"code": "player_not_found", "message": "球员不存在"})
    return instance.fm_save_id


