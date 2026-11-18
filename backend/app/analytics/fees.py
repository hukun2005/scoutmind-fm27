"""Transfer fee arithmetic shared by ingestion and analytics.

The product spec forbids treating potential money as paid money, so every surface uses the same definition:
the effective fee of a completed transfer is the sum of components already paid or triggered; when a source only
provides a lump sum, that observed amount is used instead.
"""

from __future__ import annotations

from typing import Protocol

PAID_STATUSES = frozenset({"paid", "triggered"})
POTENTIAL_STATUSES = frozenset({"untriggered", "conditional_unknown", "scheduled"})


class FeeLike(Protocol):
    """Minimal shape of a fee component, satisfied by both ORM rows and protocol records."""

    type: str
    amount: float | None
    status: str


def paid_components_total(components: list[FeeLike]) -> float | None:
    """Sum amounts that are already paid or triggered; ``None`` when no such component carries an amount."""
    total = 0.0
    seen = False
    for component in components:
        if component.status not in PAID_STATUSES or component.amount is None:
            continue
        total += float(component.amount)
        seen = True
    return total if seen else None


def potential_components_total(components: list[FeeLike]) -> float | None:
    """Sum amounts that are conditional or scheduled but not yet paid."""
    total = 0.0
    seen = False
    for component in components:
        if component.status not in POTENTIAL_STATUSES or component.amount is None:
            continue
        total += float(component.amount)
        seen = True
    return total if seen else None


def compute_effective_fee(
    base_fee: float | None,
    fee_paid: float | None,
    addons_potential: float | None,
    components: list[FeeLike],
) -> float | None:
    """Return the amount a completed transfer actually cost, or ``None`` when the source has no amount at all.

    ``addons_potential`` is deliberately ignored: it is potential money, not paid money.
    """
    paid = paid_components_total(components)
    if paid is not None:
        return round(paid, 2)
    if fee_paid is not None:
        return round(float(fee_paid), 2)
    if base_fee is not None:
        return round(float(base_fee), 2)
    return None
