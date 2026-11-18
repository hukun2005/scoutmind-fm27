"""Valuation from comparable completed transfers.

The estimator refuses to produce a precise number when the comparable sample is too small, and it never treats the
player's current market value as a historical transfer fee. Every output names the algorithm version and evidence.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..config import settings
from ..utils import iso, utcnow
from .quantiles import quantile
from .transfers import SimilarOutcome, similar_transfers

VALUATION_VERSION = "valuation-1"


def _contract_factor(months: int | None) -> tuple[float, str | None]:
    if months is None:
        return 1.0, "缺少合同剩余时间，未做合同调整"
    if months < 6:
        return 0.70, "合同剩余不足 6 个月，压价 30%"
    if months < 12:
        return 0.85, "合同剩余不足 12 个月，压价 15%"
    if months >= 36:
        return 1.05, "合同剩余 36 个月以上，溢价 5%"
    return 1.0, None


def estimate_value(
    session: Session,
    instance_id: int,
    min_sample: int | None = None,
    comparable_limit: int = 25,
) -> dict[str, object]:
    """Estimate a transfer fee range for one player from completed comparable transfers."""
    threshold = min_sample if min_sample is not None else settings.min_similar_sample
    outcome = _safe_similar(session, instance_id, comparable_limit)
    comparable_fees = [
        float(item["transfer"]["effective_fee"])
        for item in outcome.items
        if isinstance(item.get("transfer"), dict) and item["transfer"].get("effective_fee") is not None
    ]
    target = outcome.target
    contract_months = target.get("contract_remaining_months")
    factor, factor_note = _contract_factor(contract_months if isinstance(contract_months, int) else None)
    basis: dict[str, object] = {
        "comparable_count": len(comparable_fees),
        "median": None,
        "p25": None,
        "p75": None,
        "adjustment": {
            "contract_factor": factor,
            "contract_note": factor_note,
            "market_value": target.get("market_value"),
        },
    }
    if len(comparable_fees) < threshold:
        return {
            "instance_id": instance_id,
            "currency": "EUR",
            "low": None,
            "mid": None,
            "high": None,
            "sample_size": len(comparable_fees),
            "method": "similar_transfers_quantile",
            "algorithm_version": VALUATION_VERSION,
            "confidence": "insufficient",
            "insufficient_sample": True,
            "basis": basis,
            "coverage": {"fee": 0.0},
            "warnings": [
                f"可比成交只有 {len(comparable_fees)} 笔，低于最小样本 {threshold}，不给出估值区间",
                "可以放宽位置、年龄或能力范围后重试，或改用成交价分位数参考",
            ],
        }
    median = float(quantile(comparable_fees, 0.5) or 0)
    p25 = float(quantile(comparable_fees, 0.25) or 0)
    p75 = float(quantile(comparable_fees, 0.75) or 0)
    market_value = target.get("market_value")
    blended = median
    if isinstance(market_value, int) and market_value > 0:
        blended = median * 0.6 + market_value * 0.4
    mid = blended * factor
    low = min(p25 * factor, mid)
    high = max(p75 * factor, mid)
    basis.update({"median": round(median, 2), "p25": round(p25, 2), "p75": round(p75, 2), "blended": round(blended, 2)})
    confidence = "high" if len(comparable_fees) >= 20 else "medium" if len(comparable_fees) >= 10 else "low"
    warnings: list[str] = list(outcome.data_gaps)
    if factor_note:
        warnings.append(factor_note)
    if isinstance(market_value, int) and market_value > 0 and median > 0 and (market_value / median) > 1.8:
        warnings.append("当前身价显著高于可比成交中位数，估值可能偏乐观")
    return {
        "instance_id": instance_id,
        "currency": "EUR",
        "low": round(low, 2),
        "mid": round(mid, 2),
        "high": round(high, 2),
        "sample_size": len(comparable_fees),
        "method": "similar_transfers_quantile",
        "algorithm_version": VALUATION_VERSION,
        "confidence": confidence,
        "insufficient_sample": False,
        "basis": basis,
        "coverage": {"fee": 1.0},
        "warnings": warnings,
    }


def valuation_payload(result: dict[str, object], generated_at: str | None = None) -> dict[str, object]:
    """Attach provenance fields used by the API and by stored valuations."""
    payload = dict(result)
    payload["generated_at"] = generated_at or iso(utcnow())
    payload["evidence"] = {
        "method": result.get("method"),
        "algorithm_version": result.get("algorithm_version"),
        "sample_size": result.get("sample_size"),
        "basis": result.get("basis"),
    }
    return payload


def _safe_similar(session: Session, instance_id: int, limit: int) -> SimilarOutcome:
    try:
        return similar_transfers(session, instance_id, limit=limit)
    except ValueError:
        return SimilarOutcome(target={"instance_id": instance_id}, data_gaps=["没有可用的可比成交数据"])

