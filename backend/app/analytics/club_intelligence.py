"""俱乐部转会情报（SM-015）。

口径（与 `analytics.deals.TRANSACTION_CATEGORIES` 一致）：

* 只有 `status='completed'` 的交易计入买卖支出/收入/净支出；
* `agreed`、`pending`、`cancelled`、`failed` 单独计数，绝不并入金额；
* 租借费用（`loan_fee`）与永久转会费（`effective_fee`）分开；
* 附加条款区分"已支付/已触发"和"潜在"；
* 自由转会的转会费为 0，但工资/签字费不在本表内，因此显示为"转会费 0，不等于总成本 0"；
* 缺失金额显示为 unknown（None），不填 0。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Club, PlayerSnapshot, Transfer, TransferFeeComponent
from ..utils import fee_round

NON_SPEND_TYPES = ("loan", "loan_with_option", "free_transfer", "release", "swap", "youth_transfer")


def club_transfer_intelligence(
    session: Session,
    save_id: int,
    club_id: int,
    *,
    season: str | None = None,
) -> dict[str, Any]:
    """一个俱乐部的长期交易策略：买卖金额、年龄、类型、赛季分布与覆盖率。"""
    rows = list(
        session.scalars(
            select(Transfer).where(
                Transfer.fm_save_id == save_id,
                (Transfer.from_club_id == club_id) | (Transfer.to_club_id == club_id),
            )
        )
    )
    if not rows:
        raise ValueError("club has no transfers")
    club = session.get(Club, club_id)
    if season:
        rows = [row for row in rows if row.season == season]
    components = list(
        session.scalars(
            select(TransferFeeComponent).where(TransferFeeComponent.transfer_id.in_([row.id for row in rows] or [-1]))
        )
    )
    components_by_transfer: dict[int, list[TransferFeeComponent]] = {}
    for component in components:
        components_by_transfer.setdefault(component.transfer_id, []).append(component)

    completed = [row for row in rows if row.status == "completed"]
    buys = [row for row in completed if row.to_club_id == club_id]
    sells = [row for row in completed if row.from_club_id == club_id]

    def side_stats(items: list[Transfer], *, buying: bool) -> dict[str, Any]:
        by_currency: dict[str, float] = {}
        known = 0
        unknown = 0
        ages: list[int] = []
        for row in items:
            if row.transfer_type.startswith("loan"):
                continue
            if row.effective_fee is None:
                unknown += 1
            else:
                known += 1
                by_currency[row.currency] = by_currency.get(row.currency, 0.0) + float(row.effective_fee)
            if row.player_age_at_transfer is not None:
                ages.append(row.player_age_at_transfer)
        currencies = sorted(by_currency)
        mixed = len(currencies) > 1
        return {
            "count": len(items),
            "known_fee_count": known,
            "unknown_fee_count": unknown,
            "cash": None if mixed else fee_round(next(iter(by_currency.values()), 0.0)),
            "cash_by_currency": {key: fee_round(value) for key, value in by_currency.items()},
            "currencies": currencies,
            "mixed_currency": mixed,
            "mixed_currency_note": "多种币种，未配置汇率时不汇总；见 cash_by_currency" if mixed else None,
            "average_age": round(sum(ages) / len(ages), 2) if ages else None,
            "average_age_note": None if ages else "没有带年龄的成交记录",
            "direction": "buy" if buying else "sell",
        }

    buy_stats = side_stats(buys, buying=True)
    sell_stats = side_stats(sells, buying=False)
    net = None
    net_note = None
    if buy_stats["mixed_currency"] or sell_stats["mixed_currency"]:
        net_note = "买卖涉及多种币种，未配置汇率时不计算净支出"
    elif buy_stats["currencies"] != sell_stats["currencies"] and buy_stats["currencies"] and sell_stats["currencies"]:
        net_note = "买卖币种不同，未配置汇率时不计算净支出"
    elif buy_stats["cash"] is not None and sell_stats["cash"] is not None:
        net = fee_round(float(buy_stats["cash"]) - float(sell_stats["cash"]))

    def group(key) -> dict[str, Any]:
        buckets: dict[str, dict[str, Any]] = {}
        for row in completed:
            name = key(row) or "unknown"
            bucket = buckets.setdefault(name, {"count": 0, "cash": 0.0, "unknown": 0})
            bucket["count"] += 1
            if row.effective_fee is None:
                bucket["unknown"] += 1
            else:
                bucket["cash"] = fee_round(float(bucket["cash"]) + float(row.effective_fee))
        return buckets

    fee_bands = {
        "0": "自由/零转会费",
        "unknown": "金额未知",
        "0-5M": "0–5M",
        "5-15M": "5–15M",
        "15-40M": "15–40M",
        "40M+": "40M+",
    }

    def band(row: Transfer) -> str:
        if row.effective_fee is None:
            return "unknown"
        value = float(row.effective_fee)
        if value == 0:
            return "0"
        if value < 5_000_000:
            return "0-5M"
        if value < 15_000_000:
            return "5-15M"
        if value < 40_000_000:
            return "15-40M"
        return "40M+"

    coverage = {
        "fee_known": len([row for row in completed if row.effective_fee is not None]),
        "fee_unknown": len([row for row in completed if row.effective_fee is None]),
        "ca_known": len([row for row in completed if row.player_ca_at_transfer is not None]),
        "age_known": len([row for row in completed if row.player_age_at_transfer is not None]),
    }
    total_completed = len(completed)
    coverage["fee_ratio"] = round(coverage["fee_known"] / total_completed, 4) if total_completed else 0.0

    # 买入球员的后续表现：用该实例最新快照 CA 与买入时 CA 的差（只是观测差，不是因果）。
    instance_ids = [row.player_instance_id for row in buys if row.player_instance_id]
    latest: dict[int, PlayerSnapshot] = {}
    if instance_ids:
        for snapshot in session.scalars(
            select(PlayerSnapshot)
            .where(PlayerSnapshot.player_instance_id.in_(instance_ids))
            .order_by(PlayerSnapshot.player_instance_id, PlayerSnapshot.observed_at)
        ):
            latest[snapshot.player_instance_id] = snapshot
    bought_progress = []
    for row in buys:
        if not row.player_instance_id or row.player_ca_at_transfer is None:
            continue
        snapshot = latest.get(row.player_instance_id)
        if snapshot is None or snapshot.ca is None:
            continue
        bought_progress.append(
            {
                "transfer_id": row.id,
                "player_name": row.player_name,
                "ca_at_transfer": row.player_ca_at_transfer,
                "ca_latest": snapshot.ca,
                "delta": snapshot.ca - row.player_ca_at_transfer,
                "observed_at": snapshot.observed_at.isoformat(),
            }
        )

    from ..ingestion.attributes import position_group

    by_position: dict[str, dict[str, Any]] = {}
    for row in completed:
        snapshot = latest.get(row.player_instance_id) if row.player_instance_id else None
        group_name = position_group(snapshot.position) if snapshot and snapshot.position else "unknown"
        bucket = by_position.setdefault(group_name, {"count": 0, "cash": 0.0, "unknown": 0})
        bucket["count"] += 1
        if row.effective_fee is None:
            bucket["unknown"] += 1
        else:
            bucket["cash"] = fee_round(float(bucket["cash"]) + float(row.effective_fee))

    return {
        "club_id": club_id,
        "club_name": club.name if club else None,
        "save_id": save_id,
        "season": season,
        "completed": {
            "buy": buy_stats,
            "sell": sell_stats,
            "net_cash": net,
            "net_cash_note": net_note,
            "note": "只统计 completed；租借费单列；附加条款不计入现金",
        },
        "agreed": {
            "count": len([row for row in rows if row.status == "agreed"]),
            "note": "已达成未生效，不计入实际支出",
        },
        "pending": {"count": len([row for row in rows if row.status == "pending"])},
        "cancelled": {"count": len([row for row in rows if row.status == "cancelled"])},
        "failed": {"count": len([row for row in rows if row.status == "failed"])},
        "loan": {
            "count": len([row for row in completed if row.transfer_type.startswith("loan")]),
            "loan_fee_known": len([row for row in completed if row.transfer_type.startswith("loan") and row.loan_fee is not None]),
            "note": "租借费与永久转会费分开统计",
        },
        "by_type": group(lambda row: row.transfer_type),
        "by_season": group(lambda row: row.season),
        "by_fee_band": group(band),
        "by_position": by_position,
        "fee_bands_legend": fee_bands,
        "coverage": coverage,
        "bought_player_progress": bought_progress[:20],
        "algorithm_version": "club-transfer-intelligence-1",
        "data_notes": [
            "缺失金额记为 unknown，不按 0 处理" if coverage["fee_unknown"] else "所有 completed 交易都有金额",
            "自由转会只表示转会费为 0，工资/签字费不在本表统计",
        ],
    }
