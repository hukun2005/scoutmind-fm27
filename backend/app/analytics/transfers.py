"""Transfer Intelligence: historical transaction queries, price statistics, similarity and club profiles.

Everything here is deterministic. The AI layer may only quote numbers produced by these functions, and every
response carries its sample size, field coverage and algorithm version.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..models import Club, PlayerInstance, PlayerSnapshot, Transfer
from ..utils import fee_round
from .fees import paid_components_total, potential_components_total
from .quantiles import histogram, summarize

TRANSFER_STATS_VERSION = "transfer-stats-1"
SIMILAR_ALGORITHM_VERSION = "similar-transfers-1"

SIMILARITY_WEIGHTS: dict[str, float] = {
    "position": 0.15,
    "age": 0.25,
    "ca": 0.30,
    "pa": 0.20,
    "contract": 0.10,
}

AGE_SCALE = 6.0
CA_SCALE = 30.0
PA_SCALE = 40.0
CONTRACT_SCALE = 24.0


@dataclass(frozen=True)
class TransferFilter:
    """Filters accepted by the transfer list and statistics endpoints."""

    status: str = "completed"
    transfer_type: str | None = None
    from_date: date | None = None
    to_date: date | None = None
    club_id: int | None = None
    position_group: str | None = None
    league: str | None = None
    min_fee: float | None = None
    max_fee: float | None = None
    min_age: int | None = None
    max_age: int | None = None
    min_ca: int | None = None
    max_ca: int | None = None


@dataclass
class SimilarOutcome:
    """Result of a similarity search, including the weight policy that produced it."""

    target: dict[str, object]
    items: list[dict[str, object]] = field(default_factory=list)
    effective_weights: dict[str, float] = field(default_factory=dict)
    missing_fields: list[str] = field(default_factory=list)
    data_gaps: list[str] = field(default_factory=list)
    sample_size: int = 0


def _filter_conditions(filters: TransferFilter) -> list:
    """SQL conditions shared by ORM paging and the column-only statistics query."""
    conditions = []
    if filters.status != "all":
        conditions.append(Transfer.status == filters.status)
    if filters.transfer_type:
        conditions.append(Transfer.transfer_type == filters.transfer_type)
    if filters.from_date:
        conditions.append(Transfer.transfer_date >= filters.from_date)
    if filters.to_date:
        conditions.append(Transfer.transfer_date <= filters.to_date)
    if filters.club_id:
        conditions.append(
            (Transfer.from_club_id == filters.club_id) | (Transfer.to_club_id == filters.club_id)
        )
    if filters.min_fee is not None:
        conditions.append(Transfer.effective_fee >= filters.min_fee)
    if filters.max_fee is not None:
        conditions.append(Transfer.effective_fee <= filters.max_fee)
    if filters.min_age is not None:
        conditions.append(Transfer.player_age_at_transfer >= filters.min_age)
    if filters.max_age is not None:
        conditions.append(Transfer.player_age_at_transfer <= filters.max_age)
    if filters.min_ca is not None:
        conditions.append(Transfer.player_ca_at_transfer >= filters.min_ca)
    if filters.max_ca is not None:
        conditions.append(Transfer.player_ca_at_transfer <= filters.max_ca)
    return conditions


def build_query(save_id: int, filters: TransferFilter):  # noqa: ANN201 - SQLAlchemy Select is not worth importing for typing
    """Build the base select for a filter set; callers add ordering and paging."""
    query = (
        select(Transfer)
        .options(selectinload(Transfer.components))
        .where(Transfer.fm_save_id == save_id)
    )
    for condition in _filter_conditions(filters):
        query = query.where(condition)
    return query


def fetch_transfers(
    session: Session, save_id: int, filters: TransferFilter, limit: int | None = None, offset: int = 0
) -> list[Transfer]:
    """Load one page of transfers.

    位置与联赛筛选依赖关联数据，先在 SQL 里筛掉能筛的条件，再把剩余的行按位置/联赛过滤；
    没有这类筛选时 LIMIT/OFFSET 完全下推到数据库，不会把整张转会表读进内存。
    """
    query = build_query(save_id, filters).order_by(Transfer.transfer_date.desc(), Transfer.id.desc())
    needs_python_filter = bool(filters.position_group or filters.league)
    if not needs_python_filter:
        if offset:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        return list(session.scalars(query))

    # 有 Python 侧筛选时只能逐行判断；仍然在 SQL 里做联赛/位置可下推的部分（league 在 Club 表上）。
    if filters.league:
        from sqlalchemy import or_

        league_clubs = select(Club.id).where(Club.fm_save_id == save_id, Club.league == filters.league)
        query = query.where(or_(Transfer.from_club_id.in_(league_clubs), Transfer.to_club_id.in_(league_clubs)))

    rows = list(session.scalars(query))
    if filters.position_group:
        positions = _instance_positions(session, [row.player_instance_id for row in rows])
        rows = [row for row in rows if _position_group_of(row, positions) == filters.position_group]
    return rows[offset : offset + limit] if limit is not None else rows[offset:]


def count_transfers(session: Session, save_id: int, filters: TransferFilter) -> int:
    """Count matching transfers with a COUNT query, never by loading the page."""
    from sqlalchemy import func as sql_func

    query = build_query(save_id, filters)
    if not (filters.position_group or filters.league):
        return int(session.scalar(select(sql_func.count()).select_from(query.subquery())) or 0)
    # 位置筛选无法纯 SQL 表达（位置来自球员实例），退回计数时只做 SQL 可下推的部分。
    return len(fetch_transfers(session, save_id, filters))


def serialize_transfer(transfer: Transfer, clubs: dict[int, Club] | None = None) -> dict[str, object]:
    """Serialize one transfer row exactly as documented in ``docs/API.md``."""
    mapping = clubs or {}
    from_club = mapping.get(transfer.from_club_id) if transfer.from_club_id else None
    to_club = mapping.get(transfer.to_club_id) if transfer.to_club_id else None
    components = list(transfer.components)
    return {
        "id": transfer.id,
        "player_instance_id": transfer.player_instance_id,
        "player_name": transfer.player_name,
        "from_club": transfer.from_club_name or (from_club.name if from_club else None),
        "to_club": transfer.to_club_name or (to_club.name if to_club else None),
        "from_club_id": transfer.from_club_id,
        "to_club_id": transfer.to_club_id,
        "transfer_type": transfer.transfer_type,
        "status": transfer.status,
        "transfer_date": transfer.transfer_date.isoformat(),
        "season": transfer.season,
        "base_fee": fee_round(transfer.base_fee),
        "fee_paid": fee_round(transfer.fee_paid),
        "addons_potential": fee_round(transfer.addons_potential),
        "effective_fee": fee_round(transfer.effective_fee),
        "currency": transfer.currency,
        "player_age_at_transfer": transfer.player_age_at_transfer,
        "player_ca_at_transfer": transfer.player_ca_at_transfer,
        "player_pa_at_transfer": transfer.player_pa_at_transfer,
        "contract_remaining_months": transfer.contract_remaining_months,
        "source": transfer.source,
        "confidence": transfer.confidence,
        "fee_components": [
            {
                "type": component.component_type,
                "amount": fee_round(component.amount),
                "status": component.status,
                "due_date": component.due_date.isoformat() if component.due_date else None,
                "condition": component.condition,
            }
            for component in components
        ],
        "paid_total": fee_round(paid_components_total(components)),
        "potential_total": fee_round(potential_components_total(components)),
    }


def transfer_price_stats(session: Session, save_id: int, filters: TransferFilter) -> dict[str, object]:
    """Compute median/quartile statistics for completed *permanent* transfers with a known fee.

    口径（与 deals.TRANSACTION_CATEGORIES 一致）：
    * 只有 ``status='completed'`` 且类别计入统计（正式转会 / 买断 / 解约金）的记录进入价格样本；
    * 租借、自由转会、交换、青训提拔、未完成、已达成未生效、取消、失败都不进价格统计；
    * 成交金额未知（None）的记录只计入 excluded，不当作 0。

    性能：这里不再把整张表加载成 ORM 对象——只 SELECT ``effective_fee`` 一列，计数走 SQL 聚合；
    分类计数用 GROUP BY，50 万行时也不会产生几十万个对象。
    """
    from sqlalchemy import func as sql_func

    from .deals import NON_STAT_TYPES, category_of

    all_filters = replace(filters, status="all")
    # 只 SELECT 两列，且不携带 ORM loader（selectinload）；50 万行也不会构造实体/触发第二条查询。
    stat_fee_query = (
        select(Transfer.effective_fee, Transfer.currency)
        .where(Transfer.fm_save_id == save_id, *_filter_conditions(all_filters))
        .where(
            Transfer.status == "completed",
            Transfer.transfer_type.not_in(NON_STAT_TYPES),
        )
    )
    currency_values: dict[str, list[float]] = {}
    for fee, currency in session.execute(stat_fee_query):
        if fee is not None:
            currency_values.setdefault(currency or "UNKNOWN", []).append(float(fee))
    values = [value for group in currency_values.values() for value in group]
    mixed_currency = len(currency_values) > 1
    summary = summarize(values if not mixed_currency else [])

    # 分类计数：一条 GROUP BY，避免逐行 category_of。
    group_query = (
        build_query(save_id, all_filters)
        .with_only_columns(Transfer.status, Transfer.transfer_type, sql_func.count())
        .group_by(Transfer.status, Transfer.transfer_type)
    )
    counts_by_category: dict[str, int] = {}
    for status, transfer_type, count in session.execute(group_query):
        proxy = Transfer(status=status, transfer_type=transfer_type)
        key = category_of(proxy)
        counts_by_category[key] = counts_by_category.get(key, 0) + int(count)

    completed_for_stats = sum(
        count for key, count in counts_by_category.items() if _counts_in_price_stats(key)
    )
    completed_any = sum(count for key, count in counts_by_category.items() if key not in {"pending", "agreed", "cancelled", "failed", "bid_rejected"})
    transfer_history_available = completed_any > 0
    total_completed = completed_for_stats
    priced = len(values)
    fee_coverage = priced / total_completed if total_completed else 0.0

    ca_coverage = _column_coverage(session, build_query(save_id, all_filters), Transfer.player_ca_at_transfer, completed_for_stats)
    contract_coverage = _column_coverage(
        session, build_query(save_id, all_filters), Transfer.contract_remaining_months, completed_for_stats
    )

    excluded_categories = {
        key: count
        for key, count in counts_by_category.items()
        if not _counts_in_price_stats(key) and count
    }
    warnings: list[str] = []
    if mixed_currency:
        warnings.append(
            "样本包含多种币种，未配置汇率时不混合统计；请按币种分别查看（见 currencies）"
        )
    if not values:
        warnings.append("当前筛选条件下没有带成交金额的已完成交易，无法给出价格统计")
    if values and fee_coverage < 0.9:
        warnings.append(f"仅 {fee_coverage:.0%} 的已完成交易带有成交金额，统计可能遗漏部分交易")
    if values and ca_coverage < 0.6:
        warnings.append(f"仅 {ca_coverage:.0%} 的样本带有成交时 CA，分位数未按 CA 校正")
    if values and contract_coverage < 0.5:
        warnings.append("合同剩余时间覆盖率不足 50%，未做合同年限校正")
    return {
        "sample_size": len(values),
        "currency": next(iter(currency_values)) if len(currency_values) == 1 else None,
        "currencies": {key: {"sample": len(group), "median": summarize(group)["median"]} for key, group in currency_values.items()},
        "mixed_currency": mixed_currency,
        "median": summary["median"],
        "p25": summary["p25"],
        "p75": summary["p75"],
        "mean": summary["mean"],
        "min": summary["min"],
        "max": summary["max"],
        "distribution": histogram(values),
        "filters": _filters_payload(filters),
        "coverage": {
            "fee": round(fee_coverage, 4),
            "ca_at_transfer": round(ca_coverage, 4),
            "contract_remaining_months": round(contract_coverage, 4),
        },
        "algorithm_version": TRANSFER_STATS_VERSION,
        "excluded": {
            "incomplete": max(total_completed - priced, 0),
            "non_completed": sum(counts_by_category.values()) - total_completed,
            "by_category": excluded_categories,
        },
        "availability": {
            "transfer_history": transfer_history_available,
            "completed_for_stats": total_completed,
            "agreed": counts_by_category.get("agreed", 0),
            "pending": counts_by_category.get("pending", 0),
            "cancelled": counts_by_category.get("cancelled", 0),
            "note": None if transfer_history_available else "该存档没有已完成的历史转会记录，价格统计不可用",
        },
        "warnings": warnings,
    }


def _counts_in_price_stats(category: str) -> bool:
    """类别是否计入成交价格统计（与 deals.TRANSACTION_CATEGORIES.counts_in_stats 对齐）。"""
    return category in {"completed_permanent", "loan_buyout", "clause_release"}


def _column_coverage(session: Session, base, column, denominator: int) -> float:
    """某一列在"计入统计的已完成交易"中的非空比例。"""
    if denominator <= 0:
        return 0.0
    from sqlalchemy import func as sql_func

    present = session.scalar(
        base.with_only_columns(sql_func.count(column)).where(
            Transfer.status == "completed",
            Transfer.transfer_type.not_in(_non_stat_types()),
            column.is_not(None),
        )
    )
    return float(present or 0) / denominator


def _non_stat_types() -> tuple[str, ...]:
    from .deals import NON_STAT_TYPES

    return NON_STAT_TYPES


def similar_transfers(
    session: Session,
    instance_id: int,
    limit: int = 20,
    save_id: int | None = None,
    min_similarity: float = 0.0,
) -> SimilarOutcome:
    """Score completed transfers by weighted distance to a target player profile.

    Fields the target does not have are excluded and the weights are renormalised; the caller reports that via
    ``missing_fields`` so the user sees the evidence base shrinking.
    """
    instance = session.get(PlayerInstance, instance_id)
    if instance is None:
        raise ValueError("player instance not found")
    target = _target_profile(session, instance)
    effective_save = save_id or instance.fm_save_id
    rows = fetch_transfers(session, effective_save, TransferFilter(status="completed"))
    candidates = [row for row in rows if row.effective_fee is not None and row.player_instance_id != instance_id]
    weights = dict(SIMILARITY_WEIGHTS)
    missing: list[str] = []
    for key, _weight in SIMILARITY_WEIGHTS.items():
        target_value = target.get(key)
        if target_value is None:
            weights[key] = 0.0
            missing.append("contract_remaining_months" if key == "contract" else key)
    candidates = candidates or []
    if not candidates:
        return SimilarOutcome(
            target=target,
            items=[],
            effective_weights={key: round(value, 4) for key, value in weights.items()},
            missing_fields=missing,
            data_gaps=["没有可比成交样本（目标球员自身的成交已排除）"],
            sample_size=0,
        )
    for key in list(weights):
        if weights[key] == 0:
            continue
        present = sum(1 for row in candidates if _candidate_value(row, key) is not None)
        ratio = present / len(candidates) if candidates else 0.0
        weights[key] *= ratio
    total_weight = sum(weights.values())
    if total_weight <= 0:
        return SimilarOutcome(
            target=target,
            items=[],
            effective_weights={key: 0.0 for key in weights},
            missing_fields=missing,
            data_gaps=["可比成交缺少全部用于匹配的字段，无法计算相似度"],
            sample_size=0,
        )
    effective_weights = {key: round(value / total_weight, 4) for key, value in weights.items()}
    items: list[dict[str, object]] = []
    clubs = {club.id: club for club in session.scalars(select(Club).where(Club.fm_save_id == effective_save))}
    positions = _instance_positions(session, [row.player_instance_id for row in candidates])
    for row in candidates:
        distance, factors = _distance(target, row, effective_weights, positions)
        similarity = round(1.0 - distance, 4)
        if similarity < min_similarity:
            continue
        items.append(
            {
                "transfer_id": row.id,
                "transfer": serialize_transfer(row, clubs),
                "similarity": similarity,
                "factors": factors,
            }
        )
    items.sort(key=lambda item: float(item["similarity"]), reverse=True)
    gaps: list[str] = []
    if missing:
        gaps.append(f"目标球员缺少 {', '.join(missing)}，相关权重已重新分配")
    if len(items) < 5:
        gaps.append(f"相似交易仅 {len(items)} 笔，统计结论不稳定")
    return SimilarOutcome(
        target=target,
        items=items[:limit],
        effective_weights=effective_weights,
        missing_fields=missing,
        data_gaps=gaps,
        sample_size=len(items),
    )


def club_transfer_profile(session: Session, club_id: int) -> dict[str, object]:
    """Buy/sell behaviour of one club inside its save."""
    club = session.get(Club, club_id)
    if club is None:
        raise ValueError("club not found")
    rows = fetch_transfers(session, club.fm_save_id, TransferFilter(status="completed"))
    bought = [row for row in rows if row.to_club_id == club_id and row.effective_fee is not None]
    sold = [row for row in rows if row.from_club_id == club_id and row.effective_fee is not None]
    bought_values = [float(row.effective_fee) for row in bought if row.effective_fee is not None]
    sold_values = [float(row.effective_fee) for row in sold if row.effective_fee is not None]
    bought_stats = summarize(bought_values)
    sold_stats = summarize(sold_values)
    young = [row for row in bought if (row.player_age_at_transfer or 99) <= 22]
    realised: list[float] = []
    bought_by_player = {
        row.player_instance_id: row
        for row in bought
        if row.player_instance_id is not None and row.effective_fee is not None
    }
    for row in sold:
        if row.player_instance_id is None or row.effective_fee is None:
            continue
        entry = bought_by_player.get(row.player_instance_id)
        if entry is None or entry.effective_fee is None:
            continue
        realised.append(float(row.effective_fee) - float(entry.effective_fee))
    clubs = {item.id: item for item in session.scalars(select(Club).where(Club.fm_save_id == club.fm_save_id))}
    top = sorted(
        [row for row in rows if row.effective_fee is not None and (row.from_club_id == club_id or row.to_club_id == club_id)],
        key=lambda row: float(row.effective_fee or 0),
        reverse=True,
    )[:5]
    warnings: list[str] = []
    total_relevant = len(bought) + len(sold)
    if total_relevant and (len(bought_values) + len(sold_values)) / max(total_relevant, 1) < 0.9:
        warnings.append("部分交易的金额缺失，均值与净投入仅基于有金额的记录")
    if not realised:
        warnings.append("没有同一球员的买入与卖出配对，无法计算已实现利润")
    return {
        "club_id": club.id,
        "name": club.name,
        "nation": club.nation,
        "league": club.league,
        "reputation": club.reputation,
        "is_user_club": club.is_user_club,
        "currency": bought[0].currency if bought else (sold[0].currency if sold else "EUR"),
        "bought": {
            "count": len(bought_values),
            "total": fee_round(sum(bought_values)) if bought_values else 0.0,
            "median": bought_stats["median"],
        },
        "sold": {
            "count": len(sold_values),
            "total": fee_round(sum(sold_values)) if sold_values else 0.0,
            "median": sold_stats["median"],
        },
        "net_spend": fee_round(sum(bought_values) - sum(sold_values)),
        "avg_profit_per_sale": fee_round(sum(realised) / len(realised)) if realised else None,
        "young_signing_ratio": round(len(young) / len(bought), 4) if bought else None,
        "loan_in_count": sum(1 for row in rows if row.to_club_id == club_id and row.transfer_type == "loan"),
        "loan_out_count": sum(1 for row in rows if row.from_club_id == club_id and row.transfer_type == "loan"),
        "top_transfers": [serialize_transfer(row, clubs) for row in top],
        "sample_size": total_relevant,
        "coverage": {
            "fee": round((len(bought_values) + len(sold_values)) / total_relevant, 4) if total_relevant else 0.0
        },
        "warnings": warnings,
        "algorithm_version": TRANSFER_STATS_VERSION,
    }


def _filters_payload(filters: TransferFilter) -> dict[str, object]:
    payload = {
        "position_group": filters.position_group,
        "league": filters.league,
        "min_age": filters.min_age,
        "max_age": filters.max_age,
        "min_ca": filters.min_ca,
        "max_ca": filters.max_ca,
        "from_date": filters.from_date.isoformat() if filters.from_date else None,
        "to_date": filters.to_date.isoformat() if filters.to_date else None,
        "club_id": filters.club_id,
        "transfer_type": filters.transfer_type,
        "status": filters.status,
    }
    return {key: value for key, value in payload.items() if value is not None}


def _instance_positions(session: Session, instance_ids: list[int | None]) -> dict[int, str | None]:
    ids = [value for value in instance_ids if value is not None]
    if not ids:
        return {}
    rows = session.scalars(select(PlayerInstance).where(PlayerInstance.id.in_(ids)))
    return {row.id: row.position for row in rows}


def _position_group_of(transfer: Transfer, positions: dict[int, str | None]) -> str | None:
    from ..ingestion.attributes import position_group

    if transfer.player_instance_id is None:
        return None
    return position_group(positions.get(transfer.player_instance_id))


def _target_profile(session: Session, instance: PlayerInstance) -> dict[str, object]:
    snapshot = session.scalar(
        select(PlayerSnapshot)
        .where(PlayerSnapshot.player_instance_id == instance.id)
        .order_by(PlayerSnapshot.observed_at.desc())
        .limit(1)
    )
    from ..ingestion.attributes import position_group

    position = instance.position or (snapshot.position if snapshot else None)
    contract_months = None
    if snapshot is not None and snapshot.contract_end is not None:
        reference = snapshot.game_date or snapshot.observed_at.date()
        contract_months = max(
            (snapshot.contract_end.year - reference.year) * 12 + (snapshot.contract_end.month - reference.month),
            0,
        )
    age = snapshot.age if snapshot else None
    if age is None and instance.player.birth_date is not None:
        if snapshot is not None:
            reference_date = snapshot.game_date or snapshot.observed_at.date()
        else:
            reference_date = date.today()
        age = reference_date.year - instance.player.birth_date.year
    return {
        "instance_id": instance.id,
        "name": instance.player.full_name,
        "age": age,
        "position": position,
        "position_group": position_group(position),
        "ca": snapshot.ca if snapshot else None,
        "pa": snapshot.pa if snapshot else None,
        "market_value": snapshot.market_value if snapshot else None,
        "contract_remaining_months": contract_months,
        "currency": "EUR",
    }


def _candidate_value(transfer: Transfer, key: str) -> object:
    if key == "position":
        if transfer.player_instance_id is None:
            return None
        return "present"
    if key == "age":
        return transfer.player_age_at_transfer
    if key == "ca":
        return transfer.player_ca_at_transfer
    if key == "pa":
        return transfer.player_pa_at_transfer
    return transfer.contract_remaining_months


def _distance(
    target: dict[str, object],
    transfer: Transfer,
    weights: dict[str, float],
    positions: dict[int, str | None],
) -> tuple[float, list[dict[str, object]]]:
    from ..ingestion.attributes import position_group

    factors: list[dict[str, object]] = []
    total = 0.0
    scheduled = 0.0
    candidate_position = (
        position_group(positions.get(transfer.player_instance_id)) if transfer.player_instance_id else None
    )
    numeric_scales = {"age": AGE_SCALE, "ca": CA_SCALE, "pa": PA_SCALE, "contract": CONTRACT_SCALE}
    for key, weight in weights.items():
        if weight <= 0:
            continue
        target_value = target.get(key if key != "contract" else "contract_remaining_months")
        if key == "position":
            if target_value is None or candidate_position is None:
                continue
            distance = 0.0 if target_value == candidate_position else 1.0
            factors.append(
                {
                    "key": "position",
                    "value": candidate_position,
                    "target": target_value,
                    "distance": distance,
                    "weight": round(weight, 4),
                }
            )
        else:
            candidate_value = _candidate_value(transfer, key)
            if target_value is None or candidate_value is None:
                continue
            distance = min(abs(float(target_value) - float(candidate_value)) / numeric_scales[key], 1.0)
            factors.append(
                {
                    "key": key,
                    "value": candidate_value,
                    "target": target_value,
                    "distance": round(distance, 4),
                    "weight": round(weight, 4),
                }
            )
        total += distance * weight
        scheduled += weight
    if scheduled <= 0:
        return 1.0, factors
    return total / scheduled, factors

