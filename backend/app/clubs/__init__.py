"""Club resolution package: stable club identity, provenance and the operator's managed club."""

from __future__ import annotations

from .resolver import (
    SOURCE_CONFIDENCE,
    SOURCE_CSV,
    SOURCE_LABELS,
    SOURCE_MANUAL,
    SOURCE_PAYLOAD_CLUBS,
    SOURCE_PLAYER_FIELD,
    ClubResolver,
    ResolvedClub,
    name_uid,
    normalize_name,
)

__all__ = [
    "SOURCE_CONFIDENCE",
    "SOURCE_CSV",
    "SOURCE_LABELS",
    "SOURCE_MANUAL",
    "SOURCE_PAYLOAD_CLUBS",
    "SOURCE_PLAYER_FIELD",
    "ClubResolver",
    "ResolvedClub",
    "name_uid",
    "normalize_name",
]
