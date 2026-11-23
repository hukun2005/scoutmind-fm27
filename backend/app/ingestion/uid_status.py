"""Save-local UID classification shared by the protocol, the adapters and the importer.

An FM save-local UID is a signed 32-bit handle. Upstream dumps report ``4294967295``
(``0xFFFFFFFF``, also seen as ``-1``) for people that have no identity yet — free agents and
created players that never entered the world. That value is a sentinel, not an identity:
writing it to ``save_local_uid`` would give every unresolved player one shared identity.

The module is deliberately dependency free so the protocol validator, the FMSuperScout adapter
and the importer all answer "what is this UID?" with the same rule.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

#: A UID that can identify one player instance inside one save.
UID_VALID = "valid"
#: ``0xFFFFFFFF`` and the equivalent ``-1``: "no identity assigned".
UID_SENTINEL = "sentinel"
#: The upstream row carried no ID at all.
UID_MISSING = "missing"
#: A value that is present but cannot be an identity (``0``, non-numeric, out of range).
UID_INVALID = "invalid"

UID_STATUSES = (UID_VALID, UID_SENTINEL, UID_MISSING, UID_INVALID)

UidStatus = Literal["valid", "sentinel", "missing", "invalid"]

#: Largest UID a 32-bit signed handle can address once ``0xFFFFFFFF`` is reserved as sentinel.
MAX_VALID_UID = 0xFFFF_FFFE

#: Upstream sentinels. ``4294967295`` is the unsigned spelling of ``-1``.
SENTINEL_UIDS = (0xFFFF_FFFF, -1)

#: Hex spellings of the same sentinel; compared case-insensitively because dumps differ.
SENTINEL_TEXTS = frozenset({"4294967295", "-1", "0xffffffff", "0xffffffffffffffff"})

#: Anything wider than an unsigned 64-bit value cannot be a game handle.
MAX_U64 = 0xFFFF_FFFF_FFFF_FFFF

_DIGITS = re.compile(r"^[+-]?\d+$")


@dataclass(frozen=True)
class UidAssessment:
    """One classification result, keeping the raw text so evidence survives rewriting."""

    status: UidStatus
    raw_uid: str | None
    reason: str | None = None

    @property
    def is_valid(self) -> bool:
        """True when the value may be used as ``save_local_uid``."""
        return self.status == UID_VALID

    @property
    def is_unresolved(self) -> bool:
        """True when the row must be stored as an unresolved observation instead of an identity."""
        return self.status != UID_VALID


def _text(value: object) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return None


def classify_uid(value: object) -> UidAssessment:
    """Classify one upstream or protocol UID.

    ``value`` may be ``None``, an integer or a string; any other type is reported as invalid rather
    than coerced. Numeric handles are checked against the known sentinels; an opaque textual handle
    (other data sources use them) stays valid because its owner, not this module, defines the format.
    A sentinel is never repaired into an identity.
    """
    raw = _text(value)
    if raw is None:
        if value is None or (isinstance(value, str) and not value.strip()):
            return UidAssessment(UID_MISSING, None, "missing_uid")
        return UidAssessment(UID_INVALID, None, "invalid_uid_type")
    if raw.lower() in SENTINEL_TEXTS:
        return UidAssessment(UID_SENTINEL, raw, "sentinel_uid")
    if not _DIGITS.fullmatch(raw):
        return UidAssessment(UID_VALID, raw)
    number = int(raw)
    if number == 0:
        return UidAssessment(UID_INVALID, raw, "zero_uid")
    if number < 0:
        return UidAssessment(UID_SENTINEL, raw, "sentinel_uid")
    if number > MAX_U64:
        return UidAssessment(UID_INVALID, raw, "out_of_range_uid")
    if number > MAX_VALID_UID:
        return UidAssessment(UID_SENTINEL, raw, "sentinel_uid")
    return UidAssessment(UID_VALID, raw)


def identity_payload(
    assessment: UidAssessment,
    *,
    source_record_id: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the wire ``identity`` block for a row classified by :func:`classify_uid`.

    Valid rows keep the schema-1.0 ``save_local_uid`` field as well, so a reader that only knows
    the old contract still imports them. Unresolved rows carry no ``save_local_uid`` at all.
    """
    if assessment.is_valid:
        return {"kind": "save_local_uid", "value": assessment.raw_uid}
    block: dict[str, Any] = {
        "kind": "unresolved",
        "raw_uid": assessment.raw_uid,
        "reason": assessment.reason,
    }
    if assessment.status in (UID_SENTINEL, UID_INVALID):
        block["uid_status"] = assessment.status
    if source_record_id:
        block["source_record_id"] = source_record_id
    if evidence:
        block["evidence"] = dict(evidence)
    return block
