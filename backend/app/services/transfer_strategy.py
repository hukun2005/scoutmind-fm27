"""V3.3.2-05-02 历史成交策略学习。

案例不另建表，全部由既有真实/导入数据确定性推导：

* ``transfer_history``（``status='completed'``）+ ``transfer_fee_components``（分期/附加）；
* ``loan_records``（租借与买断条款）；
* ``transfer_negotiations``（``status='COMPLETED'`` 的用户真实成交）。

每条案例都带 ``case_origin``：``demo`` 表示演示存档的合成数据，``imported`` 表示导入/游戏内数据，
``negotiation`` 表示用户确认的谈判结果。真实存档没有成交记录时返回空案例并明确提示，
不允许编造案例或“学习效果”。
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ingestion.attributes import position_group
from ..models import (
    LoanRecord,
    PlayerInstance,
    PlayerSnapshot,
    Transfer,
    TransferFeeComponent,
    TransferNegotiation,
)
from ..utils import iso

STRATEGY_VERSION = "transfer-strategy-1"
MIN_PATTERN_SAMPLE = 3
INSUFFICIENT_MESSAGE = "当前相似成交案例不足，报价主要依据当前球员和预算数据生成。"


def _months_between(start: date, end: date) -> int:
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return months


def _latest_snapshot(db: Session, instance_id: int) -> PlayerSnapshot | None:
    instance = db.get(PlayerInstance, instance_id)
    if instance is None or instance.latest_snapshot_id is None:
        return None
    return db.get(PlayerSnapshot, instance.latest_snapshot_id)


def _origin(source: str | None) -> str:
    return "demo" if (source or "").startswith("synthetic") else "imported"


def _build_cases(db: Session, save_id: int) -> list[dict[str, Any]]:
    transfers = list(
        db.scalars(
            select(Transfer)
            .where(Transfer.fm_save_id == save_id, Transfer.status == "completed")
            .order_by(Transfer.transfer_date.desc())
        )
    )
    if not transfers:
        return []
    transfer_ids = [row.id for row in transfers]
    components: dict[int, list[TransferFeeComponent]] = {}
    for component in db.scalars(
        select(TransferFeeComponent).where(TransferFeeComponent.transfer_id.in_(transfer_ids))
    ):
        components.setdefault(component.transfer_id, []).append(component)
    loans: dict[int, LoanRecord] = {}
    instance_ids = [row.player_instance_id for row in transfers if row.player_instance_id]
    if instance_ids:
        for loan in db.scalars(select(LoanRecord).where(LoanRecord.player_instance_id.in_(instance_ids))):
            if loan.player_instance_id is not None:
                loans.setdefault(int(loan.player_instance_id), loan)

    cases: list[dict[str, Any]] = []
    for transfer in transfers:
        parts = components.get(transfer.id, [])
        installments = [item for item in parts if item.component_type == "installment"]
        addons = [item for item in parts if item.component_type == "addon"]
        snapshot = _latest_snapshot(db, transfer.player_instance_id) if transfer.player_instance_id else None
        loan = loans.get(int(transfer.player_instance_id)) if transfer.player_instance_id else None
        cases.append(
            {
                "case_id": f"transfer:{transfer.id}",
                "save_id": save_id,
                "player_instance_id": transfer.player_instance_id,
                "player_name": transfer.player_name,
                "player_position": snapshot.position if snapshot is not None else None,
                "player_age": transfer.player_age_at_transfer,
                "player_value": None,
                "contract_remaining": transfer.contract_remaining_months,
                "selling_club": transfer.from_club_name,
                "buying_club": transfer.to_club_name,
                "transfer_type": transfer.transfer_type,
                "transfer_status": transfer.status,
                "actual_fee": transfer.fee_paid if transfer.fee_paid is not None else transfer.base_fee,
                "base_fee": transfer.base_fee,
                "effective_fee": transfer.effective_fee,
                "addons_potential": transfer.addons_potential,
                "installments": {
                    "count": len(installments),
                    "amount": round(sum(float(item.amount) for item in installments if item.amount is not None), 2)
                    if installments
                    else None,
                },
                "addons": {
                    "count": len(addons),
                    "amount": round(sum(float(item.amount) for item in addons if item.amount is not None), 2)
                    if addons
                    else None,
                },
                "loan_terms": {
                    "loan_fee": loan.loan_fee if loan is not None else None,
                    "wage_contribution_pct": loan.wage_contribution_pct if loan is not None else None,
                    "has_option": loan.has_option if loan is not None else None,
                    "has_obligation": loan.has_obligation if loan is not None else None,
                }
                if loan is not None
                else None,
                "sell_on_clause": transfer.sell_on_clause_pct,
                "deal_result": transfer.status,
                "data_source": transfer.source,
                "case_origin": _origin(transfer.source),
                "confidence": transfer.confidence,
                "observed_at": iso(transfer.updated_at or transfer.created_at),
            }
        )
    return cases


def _negotiation_cases(db: Session, save_id: int) -> list[dict[str, Any]]:
    rows = list(
        db.scalars(
            select(TransferNegotiation)
            .where(TransferNegotiation.fm_save_id == save_id, TransferNegotiation.status == "COMPLETED")
            .order_by(TransferNegotiation.completed_at.desc())
        )
    )
    cases = []
    for row in rows:
        snapshot = _latest_snapshot(db, row.player_instance_id)
        cases.append(
            {
                "case_id": f"negotiation:{row.id}",
                "save_id": save_id,
                "player_instance_id": row.player_instance_id,
                "player_name": None,
                "player_position": snapshot.position if snapshot is not None else None,
                "player_age": snapshot.age if snapshot is not None else None,
                "player_value": snapshot.market_value if snapshot is not None else None,
                "contract_remaining": None,
                "selling_club": None,
                "buying_club": None,
                "transfer_type": "permanent" if row.direction != "loan" else "loan",
                "transfer_status": row.status,
                "actual_fee": row.final_fee,
                "base_fee": row.final_fee,
                "effective_fee": row.final_fee,
                "addons_potential": None,
                "installments": None,
                "addons": None,
                "loan_terms": None,
                "sell_on_clause": None,
                "deal_result": row.status,
                "data_source": row.source,
                "case_origin": "negotiation",
                "confidence": 1.0,
                "observed_at": iso(row.completed_at or row.updated_at),
            }
        )
    return cases


def _all_cases(db: Session, save_id: int) -> list[dict[str, Any]]:
    return _build_cases(db, save_id) + _negotiation_cases(db, save_id)


def list_cases(
    db: Session,
    save_id: int,
    *,
    transfer_type: str | None = None,
    case_origin: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    cases = _all_cases(db, save_id)
    if transfer_type:
        cases = [row for row in cases if row.get("transfer_type") == transfer_type]
    if case_origin:
        cases = [row for row in cases if row.get("case_origin") == case_origin]
    total = len(cases)
    items = cases[offset: offset + limit]
    return {
        "items": items,
        "total": total,
        "available": total > 0,
        "limit": limit,
        "offset": offset,
        "message": None if total else "当前存档没有真实成交案例（数据源不提供历史转会）",
        "strategy_version": STRATEGY_VERSION,
    }


def _match_score(case: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    matched: list[str] = []
    differences: list[str] = []
    total = 0.0
    earned = 0.0

    case_position = case.get("player_position")
    target_position = target.get("position")
    if case_position and target_position:
        total += 30
        if position_group(str(case_position)) == position_group(str(target_position)):
            earned += 30
            matched.append("位置组相同")
        else:
            differences.append("位置不同")

    case_age = case.get("player_age")
    target_age = target.get("age")
    if case_age is not None and target_age is not None:
        total += 20
        diff = abs(int(case_age) - int(target_age))
        if diff <= 2:
            earned += 20
            matched.append("年龄接近")
        elif diff <= 4:
            earned += 10
            matched.append("年龄相近")
        else:
            differences.append(f"年龄相差 {diff} 岁")

    case_value = case.get("player_value")
    target_value = target.get("market_value")
    if case_value and target_value:
        total += 20
        ratio = float(case_value) / float(target_value) if target_value else 0
        if 0.5 <= ratio <= 2:
            earned += 20
            matched.append("身价量级相近")

    case_contract = case.get("contract_remaining")
    target_contract = target.get("contract_remaining_months")
    if case_contract is not None and target_contract is not None:
        total += 15
        diff = abs(int(case_contract) - int(target_contract))
        if diff <= 12:
            earned += 15
            matched.append("合同剩余接近")
        else:
            differences.append(f"合同剩余相差 {diff} 个月")

    if target.get("loan_listed") is True or target.get("listed") is True:
        total += 15
        if case.get("transfer_type") == "loan" or case.get("transfer_type") == "free":
            earned += 15
            matched.append("成交方式与当前挂牌状态相符")

    pct = round(earned / total * 100, 1) if total else 0.0
    return {"match_pct": pct, "matched_features": matched, "differences": differences}


def similar_cases(db: Session, save_id: int, instance_id: int, limit: int = 10) -> dict[str, Any]:
    snapshot = _latest_snapshot(db, instance_id)
    if snapshot is None:
        raise ValueError("player snapshot not found")
    from .transfer_director import latest_availability

    availability = latest_availability(db, instance_id)
    target = {
        "position": snapshot.position,
        "age": snapshot.age,
        "market_value": snapshot.market_value,
        "contract_remaining_months": None,
        "listed": availability.listed if availability else None,
        "loan_listed": availability.loan_listed if availability else None,
    }
    if snapshot.contract_end is not None:
        base = snapshot.game_date or date.today()
        target["contract_remaining_months"] = _months_between(base, snapshot.contract_end)

    candidates = []
    for case in _all_cases(db, save_id):
        if case.get("player_instance_id") == instance_id:
            continue
        match = _match_score(case, target)
        if match["match_pct"] <= 0:
            continue
        candidates.append({**case, **match})
    candidates.sort(key=lambda row: -float(row["match_pct"]))
    items = candidates[:limit]
    return {
        "instance_id": instance_id,
        "available": bool(items),
        "items": items,
        "total": len(candidates),
        "message": None if items else INSUFFICIENT_MESSAGE,
        "strategy_version": STRATEGY_VERSION,
    }


def _pattern(
    key: str,
    label: str,
    cases: list[dict[str, Any]],
    description: str,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    case_ids = [str(row["case_id"]) for row in cases]
    sufficient = len(cases) >= MIN_PATTERN_SAMPLE
    if sufficient:
        summary = f"{description}；共 {len(cases)} 个案例，引用 {', '.join(case_ids[:5])}"
    else:
        summary = f"样本不足（{len(cases)} < {MIN_PATTERN_SAMPLE}），暂不归纳策略"
    return {
        "key": key,
        "label": label,
        "sample_size": len(cases),
        "sufficient_sample": sufficient,
        "case_ids": case_ids[:20],
        "summary": summary,
        **(detail or {}),
    }


def insights(db: Session, save_id: int) -> dict[str, Any]:
    cases = _all_cases(db, save_id)
    if not cases:
        return {
            "save_id": save_id,
            "available": False,
            "patterns": [],
            "message": "当前存档没有可学习的成交案例；策略结论保持为空，不虚构学习效果。",
            "strategy_version": STRATEGY_VERSION,
            "min_sample": MIN_PATTERN_SAMPLE,
        }

    instalment_cases = [
        row for row in cases if (row.get("installments") or {}).get("count")
    ]
    addon_cases = [row for row in cases if row.get("addons_potential") is not None or (row.get("addons") or {}).get("count")]
    loan_cases = [row for row in cases if row.get("transfer_type") == "loan"]
    loan_buyout_cases = [
        row for row in loan_cases if (row.get("loan_terms") or {}).get("has_option") or (row.get("loan_terms") or {}).get("has_obligation")
    ]
    sell_on_cases = [row for row in cases if row.get("sell_on_clause") is not None]
    expiring_cases = [
        row for row in cases if row.get("contract_remaining") is not None and int(row["contract_remaining"]) <= 12
    ]
    free_cases = [row for row in cases if row.get("transfer_type") == "free"]
    demo_count = sum(1 for row in cases if row.get("case_origin") == "demo")

    def avg(rows: list[dict[str, Any]], field: str) -> float | None:
        values = [float(row[field]) for row in rows if row.get(field) is not None]
        return round(sum(values) / len(values), 2) if values else None

    patterns = [
        _pattern("installments", "分期付款", instalment_cases,
                 "分期付款在成交中多次出现", {"avg_actual_fee": avg(instalment_cases, "actual_fee")}),
        _pattern("addons", "浮动附加条款", addon_cases, "附加条款用于降低固定费用风险"),
        _pattern("loan", "租借成交", loan_cases, "租借是独立成交方式"),
        _pattern("loan_buyout", "租借附带买断", loan_buyout_cases, "租借合同存在买断选择权或强制买断"),
        _pattern("sell_on", "二次转会分成", sell_on_cases, "出售时加入二次转会分成条款"),
        _pattern("expiring", "合同即将到期交易", expiring_cases,
                 "合同剩余 12 个月以内的交易", {"avg_actual_fee": avg(expiring_cases, "actual_fee")}),
        _pattern("free", "免签/自由转会", free_cases, "自由转会案例"),
    ]
    return {
        "save_id": save_id,
        "available": True,
        "patterns": patterns,
        "totals": {
            "cases": len(cases),
            "demo_cases": demo_count,
            "imported_cases": len(cases) - demo_count,
        },
        "message": "演示存档数据仅用于功能验证，不能作为真实 FM27 成交策略证据"
        if demo_count
        else None,
        "strategy_version": STRATEGY_VERSION,
        "min_sample": MIN_PATTERN_SAMPLE,
    }
