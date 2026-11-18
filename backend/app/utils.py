"""Small time, money and text helpers shared by the backend modules."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date, datetime, timezone


def utcnow() -> datetime:
    """Current UTC time as a naive datetime, which is what the database columns store."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(value: datetime | date | None) -> str | None:
    """Serialize a stored value as UTC ISO-8601 with a ``Z`` suffix (dates stay date-only)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value.replace(microsecond=0).isoformat() + "Z"
    return value.isoformat()


def parse_datetime(value: str) -> datetime | None:
    """Parse an ISO-8601 instant, accepting ``Z``; returns ``None`` for unusable input."""
    text = value.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def parse_date(value: str | None) -> date | None:
    """Parse a game date written as ``YYYY-MM-DD``; returns ``None`` for empty or invalid values."""
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def normalize_name(value: str) -> str:
    """Fold a player name for identity matching: case, accents and punctuation are ignored."""
    decomposed = unicodedata.normalize("NFKD", value)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9 ]", "", stripped.lower()).strip()


def payload_checksum(payload: bytes) -> str:
    """SHA-256 of the raw scan payload, used to detect accidental re-uploads."""
    return hashlib.sha256(payload).hexdigest()


def fee_round(value: float | None) -> float | None:
    """Round a money value to whole currency units without inventing precision."""
    if value is None:
        return None
    return round(float(value), 2)
