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

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..ingestion.attributes import position_group
from ..models import (
    Club,
    LoanRecord,
    PlayerInstance,
    PlayerSnapshot,
    Transfer,
    TransferFeedback,
    TransferFeeComponent,
    TransferNegotiation,
)
from ..utils import fee_round, iso

STRATEGY_VERSION = "transfer-strategy-1"
MIN_PATTERN_SAMPLE = 3
INSUFFICIENT_MESSAGE = "当前相似成交案例不足，报价主要依据当前球员和预算数据生成。"

#: 相似度权重（V3.3.2-07 可配置）：总权重固定为 100，缺字段时自动归一化。
SIMILARITY_WEIGHTS: dict[str, float] = {
    "position": 30.0,
    "age": 20.0,
    "value": 20.0,
    "contract": 15.0,
    "availability": 15.0,
}

#: 低于该匹配度不视为"相似案例"，避免仅凭位置相同就认定相似。
SIMILARITY_THRESHOLD = 50.0

#: 相似匹配候选上限：只扫描最近的 N 个成交案例，避免报价耗时随案例总量线性增长。
SIMILARITY_CANDIDATE_LIMIT = 5000

#: 置信度分级：样本数 → (level, label)。达到门槛不等于统计可靠。
CONFIDENCE_TIERS: tuple[tuple[int, str, str], ...] = (
    (10, "stable", "可进行更稳定的统计分析"),
    (5, "limited", "有限参考"),
    (3, "preliminary", "初步策略"),
    (1, "insufficient", "样本不足，仅展示案例"),
    (0, "none", "无可用案例"),
)


def confidence_tier(sample_size: int) -> dict[str, Any]:
    """按有效案例数量返回置信度分级；不把数量等同于统计可靠性。"""
    size = max(0, int(sample_size or 0))
    for threshold, level, label in CONFIDENCE_TIERS:
        if size >= threshold:
            note = (
                "样本已达到最低门槛，仍需检查案例相似度与数据质量"
                if threshold >= MIN_PATTERN_SAMPLE
                else label
            )
            return {"level": level, "label": label, "sample_size": size, "note": note}
    return {"level": "none", "label": "无可用案例", "sample_size": size, "note": "无可用案例"}



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


def _chunks(items: list[int], size: int = 800) -> list[list[int]]:
    """分块查询，避免 SQLite 单条语句参数过多（60k 案例时必需）。"""
    return [items[index: index + size] for index in range(0, len(items), size)]


def _snapshots_for(db: Session, instance_ids: list[int]) -> dict[int, PlayerSnapshot]:
    """批量取最新快照，避免逐条 db.get 造成 N+1（10k 案例下会放大到数秒）。"""
    snapshots: dict[int, PlayerSnapshot] = {}
    unique = sorted({int(item) for item in instance_ids if item is not None})
    for chunk in _chunks(unique):
        rows = db.execute(
            select(PlayerInstance.id, PlayerSnapshot)
            .join(PlayerSnapshot, PlayerSnapshot.id == PlayerInstance.latest_snapshot_id)
            .where(PlayerInstance.id.in_(chunk))
        ).all()
        for instance_id, snapshot in rows:
            snapshots[int(instance_id)] = snapshot
    return snapshots


def _build_cases(
    db: Session, save_id: int, limit_transfers: int | None = None
) -> list[dict[str, Any]]:
    query = (
        select(Transfer)
        .where(Transfer.fm_save_id == save_id, Transfer.status == "completed")
        .order_by(Transfer.transfer_date.desc())
    )
    if limit_transfers is not None:
        query = query.limit(int(limit_transfers))
    transfers = list(db.scalars(query))
    if not transfers:
        return []
    transfer_ids = [row.id for row in transfers]
    components: dict[int, list[TransferFeeComponent]] = {}
    for chunk in _chunks(transfer_ids):
        for component in db.scalars(
            select(TransferFeeComponent).where(TransferFeeComponent.transfer_id.in_(chunk))
        ):
            components.setdefault(component.transfer_id, []).append(component)
    loans: dict[int, LoanRecord] = {}
    instance_ids = [row.player_instance_id for row in transfers if row.player_instance_id]
    snapshots = _snapshots_for(db, instance_ids)
    if instance_ids:
        for chunk in _chunks(instance_ids):
            for loan in db.scalars(
                select(LoanRecord).where(LoanRecord.player_instance_id.in_(chunk))
            ):
                if loan.player_instance_id is not None:
                    loans.setdefault(int(loan.player_instance_id), loan)

    cases: list[dict[str, Any]] = []
    for transfer in transfers:
        parts = components.get(transfer.id, [])
        installments = [item for item in parts if item.component_type == "installment"]
        addons = [item for item in parts if item.component_type == "addon"]
        snapshot = snapshots.get(int(transfer.player_instance_id)) if transfer.player_instance_id else None
        loan = loans.get(int(transfer.player_instance_id)) if transfer.player_instance_id else None
        actual_fee = transfer.fee_paid if transfer.fee_paid is not None else transfer.base_fee
        origin = _origin(transfer.source)
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
                "actual_fee": actual_fee,
                "currency": transfer.currency,
                "usable_for_stats": origin != "demo" and actual_fee is not None and float(actual_fee) > 0,
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
                "case_origin": origin,
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
    snapshots = _snapshots_for(db, [row.player_instance_id for row in rows if row.player_instance_id])
    for row in rows:
        snapshot = snapshots.get(int(row.player_instance_id)) if row.player_instance_id else None
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
                "currency": row.currency,
                "usable_for_stats": row.final_fee is not None and float(row.final_fee) > 0,
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


def _all_cases(
    db: Session, save_id: int, limit_transfers: int | None = None
) -> list[dict[str, Any]]:
    return _build_cases(db, save_id, limit_transfers) + _negotiation_cases(db, save_id)


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
    """按可配置权重计算相似度；缺失维度不参与归一化，避免凭空加分。"""
    weights = SIMILARITY_WEIGHTS
    matched: list[str] = []
    differences: list[str] = []
    total = 0.0
    earned = 0.0

    case_position = case.get("player_position")
    target_position = target.get("position")
    if case_position and target_position:
        weight = float(weights.get("position", 0.0))
        total += weight
        if position_group(str(case_position)) == position_group(str(target_position)):
            earned += weight
            matched.append("位置组相同")
        else:
            differences.append("位置不同")

    case_age = case.get("player_age")
    target_age = target.get("age")
    if case_age is not None and target_age is not None:
        weight = float(weights.get("age", 0.0))
        total += weight
        diff = abs(int(case_age) - int(target_age))
        if diff <= 2:
            earned += weight
            matched.append("年龄接近")
        elif diff <= 4:
            earned += weight / 2
            matched.append("年龄相近")
        else:
            differences.append(f"年龄相差 {diff} 岁")

    case_value = case.get("player_value")
    target_value = target.get("market_value")
    if case_value and target_value:
        weight = float(weights.get("value", 0.0))
        total += weight
        ratio = float(case_value) / float(target_value) if target_value else 0
        if 0.5 <= ratio <= 2:
            earned += weight
            matched.append("身价量级相近")

    case_contract = case.get("contract_remaining")
    target_contract = target.get("contract_remaining_months")
    if case_contract is not None and target_contract is not None:
        weight = float(weights.get("contract", 0.0))
        total += weight
        diff = abs(int(case_contract) - int(target_contract))
        if diff <= 12:
            earned += weight
            matched.append("合同剩余接近")
        else:
            differences.append(f"合同剩余相差 {diff} 个月")

    if target.get("loan_listed") is True or target.get("listed") is True:
        weight = float(weights.get("availability", 0.0))
        total += weight
        if case.get("transfer_type") == "loan" or case.get("transfer_type") == "free":
            earned += weight
            matched.append("成交方式与当前挂牌状态相符")

    pct = round(earned / total * 100, 1) if total else 0.0
    return {
        "match_pct": pct,
        "similar": pct >= SIMILARITY_THRESHOLD,
        "matched_features": matched,
        "differences": differences,
    }


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
    for case in _all_cases(db, save_id, limit_transfers=SIMILARITY_CANDIDATE_LIMIT):
        if case.get("player_instance_id") == instance_id:
            continue
        if case.get("case_origin") == "demo":
            # 演示数据只用于功能展示，不能进入真实相似案例。
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
        "candidate_limit": SIMILARITY_CANDIDATE_LIMIT,
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


def _band_counts(
    cases: list[dict[str, Any]], field: str, edges: list[tuple[str, float, float]]
) -> dict[str, int]:
    counts = {label: 0 for label, _, _ in edges}
    for case in cases:
        value = case.get(field)
        if value is None:
            continue
        numeric = float(value)
        for label, low, high in edges:
            if low <= numeric < high:
                counts[label] += 1
                break
    return counts


def _quantiles(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"p25": None, "p50": None, "p75": None}
    ordered = sorted(values)

    def pick(percent: float) -> float:
        index = min(len(ordered) - 1, max(0, int(round(percent * (len(ordered) - 1)))))
        return fee_round(ordered[index])

    return {"p25": pick(0.25), "p50": pick(0.5), "p75": pick(0.75)}


def _patterns_from_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """从已加载的案例派生模式，避免重复查询整份案例集。"""
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
    fee_edges = [
        ("低于 500 万", 0.0, 5_000_000.0),
        ("500–1500 万", 5_000_000.0, 15_000_000.0),
        ("1500–4000 万", 15_000_000.0, 40_000_000.0),
        ("4000 万以上", 40_000_000.0, float("inf")),
    ]
    age_edges = [
        ("18–21 岁", 0.0, 22.0),
        ("22–25 岁", 22.0, 26.0),
        ("26–29 岁", 26.0, 30.0),
        ("30 岁及以上", 30.0, float("inf")),
    ]
    fee_band = _band_counts(cases, "actual_fee", fee_edges)
    age_band = _band_counts(cases, "player_age", age_edges)
    top_fee = max(fee_band, key=lambda key: fee_band[key]) if any(fee_band.values()) else "未知"
    top_age = max(age_band, key=lambda key: age_band[key]) if any(age_band.values()) else "未知"

    def avg(rows: list[dict[str, Any]], field: str) -> float | None:
        values = [float(row[field]) for row in rows if row.get(field) is not None]
        return round(sum(values) / len(values), 2) if values else None

    return [
        _pattern("installments", "分期付款", instalment_cases,
                 "分期付款在成交中多次出现", {"avg_actual_fee": avg(instalment_cases, "actual_fee")}),
        _pattern("addons", "浮动附加条款", addon_cases, "附加条款用于降低固定费用风险"),
        _pattern("loan", "租借成交", loan_cases, "租借是独立成交方式"),
        _pattern("loan_buyout", "租借附带买断", loan_buyout_cases, "租借合同存在买断选择权或强制买断"),
        _pattern("sell_on", "二次转会分成", sell_on_cases, "出售时加入二次转会分成条款"),
        _pattern("expiring", "合同即将到期交易", expiring_cases,
                 "合同剩余 12 个月以内的交易", {"avg_actual_fee": avg(expiring_cases, "actual_fee")}),
        _pattern("free", "免签/自由转会", free_cases, "自由转会案例"),
        _pattern(
            "fee_band",
            "成交金额区间",
            cases,
            f"成交金额主要集中在 {top_fee}",
            {
                "bands": fee_band,
                "quantiles": _quantiles(
                    [float(row["actual_fee"]) for row in cases if row.get("actual_fee") is not None]
                ),
            },
        ),
        _pattern(
            "age_band",
            "成交年龄区间",
            cases,
            f"成交球员年龄主要集中在 {top_age}",
            {"bands": age_band},
        ),
    ]


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

    demo_count = sum(1 for row in cases if row.get("case_origin") == "demo")
    stat_cases = [row for row in cases if row.get("case_origin") != "demo"]
    patterns = _patterns_from_cases(stat_cases or cases)
    if not stat_cases:
        message = "当前存档只有演示数据，不能作为真实 FM27 成交策略证据。"
    elif demo_count:
        message = "演示存档数据仅用于功能验证，不能作为真实 FM27 成交策略证据"
    else:
        message = None
    return {
        "save_id": save_id,
        "available": bool(stat_cases),
        "patterns": patterns,
        "totals": {
            "cases": len(cases),
            "demo_cases": demo_count,
            "imported_cases": len(stat_cases),
        },
        "message": message,
        "strategy_version": STRATEGY_VERSION,
        "min_sample": MIN_PATTERN_SAMPLE,
    }


# ---------------------------------------------------------------------------
# V3.3.2-07 学习状态、数据版本与俱乐部交易画像
# ---------------------------------------------------------------------------


def data_version(
    db: Session, save_id: int, cases: list[dict[str, Any]] | None = None
) -> str:
    """学习数据版本：案例数、反馈数与最近观测时间；反馈写入后版本必然变化。"""
    if cases is None:
        cases = _all_cases(db, save_id)
    feedback_count = int(
        db.scalar(
            select(func.count())
            .select_from(TransferFeedback)
            .where(TransferFeedback.fm_save_id == save_id)
        )
        or 0
    )
    latest = max((str(case.get("observed_at") or "") for case in cases), default="")
    return f"cases:{len(cases)}:feedback:{feedback_count}:{latest}"


def learning_status(db: Session, save_id: int) -> dict[str, Any]:
    """当前存档的学习状态：样本量、类型分布、置信度与可见模式。"""
    cases = _all_cases(db, save_id)
    usable = [case for case in cases if case.get("usable_for_stats")]
    by_type: dict[str, int] = {}
    for case in usable:
        key = str(case.get("transfer_type") or "unknown")
        by_type[key] = by_type.get(key, 0) + 1
    demo_cases = sum(1 for case in cases if case.get("case_origin") == "demo")
    negotiation_cases = sum(1 for case in cases if case.get("case_origin") == "negotiation")
    completed_transfers = sum(1 for case in cases if case.get("case_origin") == "imported" and case.get("usable_for_stats"))

    patterns: list[dict[str, Any]] = []
    stat_cases = [case for case in cases if case.get("case_origin") != "demo"]
    if stat_cases:
        for item in _patterns_from_cases(stat_cases):
            patterns.append(
                {
                    "key": item["key"],
                    "sample_size": int(item["sample_size"]),
                    "confidence": confidence_tier(int(item["sample_size"])),
                    "summary": item["summary"],
                }
            )

    if not cases:
        message = "当前存档没有真实成交案例（数据源不提供历史转会）"
    elif not stat_cases:
        message = "当前存档只有演示数据，不能作为真实 FM27 成交策略证据。"
    else:
        message = None
    return {
        "save_id": save_id,
        "available": bool(stat_cases),
        "data_version": data_version(db, save_id, cases),
        "totals": {
            "cases": len(cases),
            "completed_transfers": completed_transfers,
            "negotiation_cases": negotiation_cases,
            "demo_cases": demo_cases,
        },
        "by_type": by_type,
        "confidence": confidence_tier(len(usable)),
        "patterns": patterns,
        "message": message,
        "strategy_version": STRATEGY_VERSION,
    }


def club_habits(db: Session, save_id: int, club_id: int) -> dict[str, Any]:
    """单个俱乐部在**本存档**内的交易画像；不同俱乐部、不同交易类型分开统计。"""
    club = db.get(Club, club_id)
    if club is None or club.fm_save_id != save_id:
        raise ValueError("club not found")

    rows = list(
        db.scalars(
            select(Transfer).where(
                Transfer.fm_save_id == save_id,
                Transfer.status == "completed",
                or_(Transfer.from_club_id == club_id, Transfer.to_club_id == club_id),
            )
        )
    )
    selling = [row for row in rows if row.from_club_id == club_id]
    buying = [row for row in rows if row.to_club_id == club_id]

    components: dict[int, set[str]] = {}
    if rows:
        ids = [row.id for row in rows]
        for chunk in _chunks(ids):
            for transfer_id, component_type in db.execute(
                select(TransferFeeComponent.transfer_id, TransferFeeComponent.component_type).where(
                    TransferFeeComponent.transfer_id.in_(chunk)
                )
            ).all():
                components.setdefault(int(transfer_id), set()).add(str(component_type))

    def bucket(items: list[Transfer]) -> dict[str, int]:
        return {
            "completed": len(items),
            "loans": sum(1 for item in items if item.transfer_type == "loan"),
            "free": sum(1 for item in items if item.transfer_type == "free"),
            "installments": sum(
                1 for item in items if "installment" in components.get(item.id, set())
            ),
            "addons": sum(1 for item in items if "addon" in components.get(item.id, set())),
            "buyout": sum(
                1
                for item in items
                if item.transfer_type == "loan" and item.loan_fee is not None
            ),
        }

    selling_stats = bucket(selling)
    buying_stats = bucket(buying)
    observations = bucket(rows)
    available = len(rows) >= MIN_PATTERN_SAMPLE
    direction = "selling" if len(selling) >= len(buying) else "buying"

    patterns: list[dict[str, Any]] = []
    if available:
        def add(
            key: str,
            label: str,
            sample_size: int,
            summary: str,
        ) -> None:
            patterns.append(
                {
                    "key": key,
                    "label": label,
                    "sample_size": int(sample_size),
                    "confidence": confidence_tier(int(sample_size)),
                    "summary": summary,
                }
            )

        add(
            "loan_preference",
            "租借倾向",
            observations["loans"],
            "该俱乐部有一定租借交易倾向" if observations["loans"] >= 2 else "租借交易较少",
        )
        add(
            "installment_usage",
            "分期付款",
            observations["installments"],
            "常见分期付款" if observations["installments"] >= 2 else "很少使用分期付款",
        )
        add(
            "addon_usage",
            "附加条款",
            observations["addons"],
            "常用附加条款降低固定费用" if observations["addons"] >= 2 else "附加条款使用较少",
        )
        add(
            "free_transfers",
            "自由转会",
            observations["free"],
            "存在自由转会案例" if observations["free"] else "没有自由转会案例",
        )
        young_sales = sum(1 for item in selling if (item.player_age_at_transfer or 99) <= 23)
        add(
            "young_player_sales",
            "出售年轻球员",
            young_sales,
            "倾向出售年轻球员" if young_sales >= 2 else "很少出售年轻球员",
        )
        expiring_sales = sum(
            1
            for item in selling
            if item.contract_remaining_months is not None and int(item.contract_remaining_months) <= 12
        )
        add(
            "expiring_sales",
            "合同到期前出售",
            expiring_sales,
            "常在合同到期前出售" if expiring_sales >= 2 else "较少在合同到期前出售",
        )

    return {
        "club_id": club.id,
        "club_name": club.name,
        "available": available,
        "direction": direction,
        "observations": observations,
        "selling": selling_stats,
        "buying": buying_stats,
        "patterns": patterns,
        "confidence": confidence_tier(len(rows)),
        "message": None if available else "暂无足够数据",
        "strategy_version": STRATEGY_VERSION,
    }
