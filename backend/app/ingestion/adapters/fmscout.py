"""FMSuperScout dump adapter.

FMSuperScout (https://github.com/mavarobli/FMSuperScout, MIT) is an external, open-source reader that pulls the
Football Manager database out of the running game and writes a dump to its own data folder. ScoutMind consumes that
dump strictly read-only and converts it into the ScoutMind scan protocol; nothing here writes to the game, the save
or FMSuperScout's files.

Only this module knows the dump layout. Everything it cannot map is reported, never guessed:

* attributes are renamed through :data:`ATTRIBUTE_MAP`; an attribute ScoutMind has no key for is dropped with a
  warning instead of being stored under an invented name;
* sentinel values (``0`` CA, ``0xFFFF`` reputation, no club) become ``NULL``;
* fields the dump does not contain (minutes, appearances, transfers, per-match statistics) stay absent and are
  listed in the report so the affected screens keep saying "unavailable".

The dump format is the upstream project's, so it may change between FMSuperScout releases. :func:`detect` only
accepts shapes it recognises, and the report names the dump's own ``meta.generated`` timestamp so an import can be
traced back to the exact dump it came from.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

ADAPTER_NAME = "fmscout"
ADAPTER_VERSION = "1"

#: Upstream writes ``0xFFFF`` into reputation fields that were never set.
SENTINEL_U16 = 0xFFFF

#: Values at or above this are "not set" sentinels in the dump's integer money fields.
SENTINEL_INT = 0xFFFF_FF00

#: Dump attribute names (upstream PascalCase) to the ScoutMind attribute dictionary keys.
ATTRIBUTE_MAP: dict[str, str] = {
    "Crossing": "crossing",
    "Dribbling": "dribbling",
    "Finishing": "finishing",
    "FirstTouch": "first_touch",
    "Heading": "heading",
    "LongShots": "long_shots",
    "Marking": "marking",
    "Passing": "passing",
    "Tackling": "tackling",
    "Technique": "technique",
    "Aggression": "aggression",
    "Anticipation": "anticipation",
    "Bravery": "bravery",
    "Composure": "composure",
    "Concentration": "concentration",
    "Decisions": "decisions",
    "Determination": "determination",
    "Flair": "flair",
    "Leadership": "leadership",
    "OffTheBall": "off_the_ball",
    "Positioning": "positioning",
    "Teamwork": "teamwork",
    "Vision": "vision",
    "WorkRate": "work_rate",
    "Acceleration": "acceleration",
    "Agility": "agility",
    "Balance": "balance",
    "JumpingReach": "jumping",
    "NaturalFitness": "natural_fitness",
    "Pace": "pace",
    "Stamina": "stamina",
    "Strength": "strength",
    "FreeKicks": "free_kick",
    "PenaltyTaking": "penalty_taking",
    "AerialReach": "aerial_reach",
    "CommandOfArea": "command_of_area",
    "Communication": "communication",
    "Eccentricity": "eccentricity",
    "Handling": "handling",
    "Kicking": "kicking",
    "OneOnOnes": "one_on_ones",
    "Punching": "punching",
    "Reflexes": "reflexes",
    "RushingOut": "rushing_out",
}

#: Dump attributes with no ScoutMind key; they are reported, never stored.
UNMAPPED_ATTRIBUTES = frozenset({"Corners", "LongThrows", "Throwing"})

#: Fields the adapter maps when the dump carries them.
MAPPED_FIELDS = (
    "id",
    "name",
    "age / birthYear+birthDoy",
    "ca",
    "pa",
    "value",
    "wage",
    "expires",
    "club",
    "div",
    "nat",
    "posArr / posNat",
    "attrs",
    "height",
    "foot",
    "worldRep",
    "listed / loanListed / notForSale / setForRelease",
    "attrs.InjuryProneness",
    "ownerClub / ownerTeamType / teamType",
    "transferTo / transferDate",
)

#: Scan-protocol fields the dump has no source for, so every dependent feature reports them unavailable.
ABSENT_FIELDS = (
    "minutes_played",
    "appearances",
    "goals",
    "assists",
    "statistics",
    "transfers",
    "current_injury",
    "injury_history",
    "loan_option",
)

#: Dump keys the adapter deliberately ignores, with the reason shown in the report.
IGNORED_FIELDS: dict[str, str] = {
    "staff": "教练与职员数据：ScoutMind 当前没有职员模型",
    "staffAttrs": "职员属性，不属于球员模型",
    "manager": "存档主教练身份，仅用于确定「我的俱乐部」",
    "adaptability": "隐藏性格属性，ScoutMind 未建模",
    "ambition": "隐藏性格属性，ScoutMind 未建模",
    "controversy": "隐藏性格属性，ScoutMind 未建模",
    "loyalty": "隐藏性格属性，ScoutMind 未建模",
    "pressure": "隐藏性格属性，ScoutMind 未建模",
    "professionalism": "隐藏性格属性，ScoutMind 未建模",
    "sportsmanship": "隐藏性格属性，ScoutMind 未建模",
    "temperament": "隐藏性格属性，ScoutMind 未建模",
    "job": "职员岗位，不属于球员模型",
    "askingPrice": "要价，ScoutMind 的估值走自己的可比成交模型",
    "wageDemand": "合同要价，尚未建模",
    "dob": "出生日期字符串，协议使用 birthYear/birthDoy + birth_date",
    "natId": "国籍 ID，协议只存国籍名称",
    "source": "读取器自报来源，导入时使用报文级 source",
    "jobId": "职员岗位 ID，不属于球员模型",
    "jobPrefs": "职员偏好，不属于球员模型",
    "prefJob": "职员偏好，不属于球员模型",
}

#: Every player key the adapter knows about, used to report genuinely new upstream fields instead of hiding them.
KNOWN_PLAYER_FIELDS = frozenset(
    {
        "id",
        "uid",
        "name",
        "birthYear",
        "birthDoy",
        "age",
        "ca",
        "pa",
        "value",
        "wage",
        "expires",
        "club",
        "clubRep",
        "div",
        "nat",
        "natId",
        "pos",
        "posArr",
        "posNat",
        "worldRep",
        "attrs",
        "staffAttrs",
        "height",
        "foot",
        "gender",
        "teamType",
        "ownerTeamType",
        "ownerClub",
        "listed",
        "loanListed",
        "notForSale",
        "setForRelease",
        "transferDate",
        "transferTo",
        "job",
        "jobId",
        "jobPrefs",
        "prefJob",
        "adaptability",
        "ambition",
        "controversy",
        "loyalty",
        "pressure",
        "professionalism",
        "sportsmanship",
        "temperament",
        "state",
        "v",
        "askingPrice",
        "wageDemand",
        "dob",
        "natId",
        "source",
    }
)

#: Game families this adapter was written against. A different ``meta.game`` is a compatibility risk, not an error.
SUPPORTED_GAME_MAJORS = ("26", "27")
#: The four listing flags the report groups under one row.
AVAILABILITY_KEYS = ("listed", "loan_listed", "not_for_sale", "set_for_release")

_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")


@dataclass
class AdapterReport:
    """What the adapter did: counts, field coverage and everything it refused to guess."""

    detected: bool = False
    adapter: str = ADAPTER_NAME
    adapter_version: str = ADAPTER_VERSION
    dump_generated: str | None = None
    dump_game: str | None = None
    scan_id: str | None = None
    players_total: int = 0
    players_skipped: int = 0
    players_converted: int = 0
    clubs_converted: int = 0
    user_club: str | None = None
    attributes_mapped: int = 0
    attributes_ignored: list[str] = field(default_factory=list)
    mapped_fields: list[str] = field(default_factory=list)
    absent_fields: list[str] = field(default_factory=list)
    ignored_fields: list[dict[str, str]] = field(default_factory=list)
    unknown_fields: list[str] = field(default_factory=list)
    compatibility: dict[str, object] = field(default_factory=dict)
    coverage: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def payload(self) -> dict[str, object]:
        """Serialise the report for the API and for the import audit trail."""
        return {
            "detected": self.detected,
            "adapter": self.adapter,
            "adapter_version": self.adapter_version,
            "dump_generated": self.dump_generated,
            "dump_game": self.dump_game,
            "scan_id": self.scan_id,
            "players_total": self.players_total,
            "players_skipped": self.players_skipped,
            "players_converted": self.players_converted,
            "clubs_converted": self.clubs_converted,
            "user_club": self.user_club,
            "attributes_mapped": self.attributes_mapped,
            "attributes_ignored": self.attributes_ignored,
            "mapped_fields": self.mapped_fields,
            "absent_fields": self.absent_fields,
            "ignored_fields": self.ignored_fields,
            "unknown_fields": self.unknown_fields,
            "compatibility": self.compatibility,
            "coverage": self.coverage,
            "warnings": self.warnings,
        }


def detect(document: object) -> bool:
    """True when ``document`` looks like an FMSuperScout dump rather than a ScoutMind scan payload.

    The check is structural: a scan payload always carries ``schema_version``, while a dump carries ``meta`` and a
    ``players`` array whose rows use upstream's field names.
    """
    if not isinstance(document, dict):
        return False
    if "schema_version" in document:
        return False
    players = document.get("players")
    meta = document.get("meta")
    if not isinstance(players, list) or not isinstance(meta, dict):
        return False
    if not players:
        # An empty dump is still a dump: meta is the discriminator, players may legitimately be empty.
        return True
    sample = players[0]
    if not isinstance(sample, dict):
        return False
    markers = ("id", "name", "ca", "pa", "club", "attrs")
    return sum(1 for marker in markers if marker in sample) >= 3


def convert_dump(raw: bytes, *, save_source_note: str | None = None) -> tuple[dict[str, Any], AdapterReport]:
    """Convert one FMSuperScout dump into a ScoutMind scan payload plus a report.

    Args:
        raw: The dump file bytes exactly as FMSuperScout wrote them.
        save_source_note: Optional note appended to the payload warnings.

    Returns:
        The scan payload (``docs/DATA_PROTOCOL.md`` §2) and the adapter report.

    Raises:
        ValueError: The bytes are not a recognised FMSuperScout dump.
    """
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"不是有效的 JSON 文件：{exc}") from exc
    return convert_document(document, raw=raw, save_source_note=save_source_note)


def convert_document(
    document: object,
    *,
    raw: bytes | None = None,
    save_source_note: str | None = None,
) -> tuple[dict[str, Any], AdapterReport]:
    """Convert an already parsed dump. ``raw`` is used for the content hash that makes the import idempotent."""
    if not detect(document):
        raise ValueError("不是 FMSuperScout 数据导出文件（缺少 meta 与 players）")
    assert isinstance(document, dict)
    meta = document.get("meta") or {}
    players = document.get("players") or []
    report = AdapterReport(detected=True)

    generated = _parse_datetime(meta.get("generated"))
    report.dump_generated = generated.isoformat() if generated else None
    report.dump_game = _text(meta.get("game")) or _text(meta.get("gameVersion"))
    observed_at = generated or datetime.now(timezone.utc)
    game_date = _parse_date(meta.get("gameDate"))

    fingerprint = raw if raw is not None else json.dumps(document, sort_keys=True, ensure_ascii=False).encode("utf-8")
    scan_id = f"{ADAPTER_NAME}-{hashlib.sha256(fingerprint).hexdigest()[:16]}"
    report.scan_id = scan_id

    user_club_name = _text(meta.get("myClub")) or _text(meta.get("myClubName"))
    report.user_club = user_club_name

    clubs: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    attribute_seen: dict[str, int] = {}
    ignored_attributes: set[str] = set()
    numeric_presence = {
        "ca": 0,
        "pa": 0,
        "market_value": 0,
        "wage": 0,
        "contract_end": 0,
        "birth_date": 0,
        "age": 0,
        "height_cm": 0,
        "foot": 0,
        "world_reputation": 0,
        "listed": 0,
        "injury_proneness": 0,
        "injured": 0,
        "parent_club": 0,
        "loan_club": 0,
        "agreed_transfer": 0,
        "club": 0,
    }

    for entry in players:
        if not isinstance(entry, dict):
            report.warnings.append("players 中存在非对象行，已跳过")
            continue
        report.players_total += 1
        if _is_ghost(entry):
            report.players_skipped += 1
            continue
        club_name = _text(entry.get("club"))
        club_uid = _club_uid(club_name) if club_name else None
        if club_name and club_uid is not None:
            _ensure_club(
                clubs,
                club_name,
                league=_text(entry.get("div")),
                reputation=_int(entry.get("clubRep"), sentinel_u16=True),
                user_club_name=user_club_name,
            )
        ownership = _ownership(entry, club_name)
        # A parent, loan or buying club may have no players in this dump; keep its name so the relationship is not lost.
        for related_name in (_text(entry.get("ownerClub")), _text(entry.get("transferTo"))):
            if related_name:
                _ensure_club(clubs, related_name, league=None, reputation=None, user_club_name=user_club_name)
        agreed = _agreed_transfer(entry)
        row, present, ignored = _player_row(entry, club_uid, ownership=ownership, agreed=agreed)
        attribute_seen.update({key: attribute_seen.get(key, 0) + 1 for key in row.get("attributes", {})})
        ignored_attributes.update(ignored)
        for key, value in present.items():
            if value:
                numeric_presence[key] = numeric_presence.get(key, 0) + 1
        rows.append(row)
        report.players_converted += 1

    report.clubs_converted = len(clubs)
    report.attributes_mapped = len(attribute_seen)
    report.attributes_ignored = sorted(ignored_attributes)
    report.mapped_fields = [name for name in MAPPED_FIELDS if _field_used(name, rows, clubs)]
    report.absent_fields = [name for name in ABSENT_FIELDS if not _absent_override(name, players)]
    report.ignored_fields = [
        {"field": key, "reason": reason}
        for key, reason in IGNORED_FIELDS.items()
        if key in document or any(key in entry for entry in players if isinstance(entry, dict))
    ]

    report.unknown_fields = sorted(
        {
            str(key)
            for entry in players
            if isinstance(entry, dict)
            for key in entry
            if str(key) not in KNOWN_PLAYER_FIELDS
        }
    )
    report.compatibility = _compatibility(report.dump_game, meta)
    if report.unknown_fields:
        report.warnings.append(
            "上游新增了适配层不认识的字段：" + "、".join(report.unknown_fields) + "（已保留在报告中，未写入数据库）"
        )
    if not report.compatibility.get("supported", True):
        report.warnings.append(str(report.compatibility.get("message")))

    total = max(report.players_converted, 1)
    report.coverage = {
        key: round(value / total, 4) for key, value in numeric_presence.items()
    }
    if user_club_name and not any(club["is_user_club"] for club in clubs.values()):
        report.warnings.append(f"meta.myClub「{user_club_name}」没有出现在球员列表里，阵容分析将没有球队")
    if report.players_skipped:
        report.warnings.append(
            f"{report.players_skipped} 条无俱乐部的幽灵记录已跳过（上游同样会过滤这些尚未进入游戏的 newgen）"
        )
    if ignored_attributes:
        report.warnings.append(
            "以下属性 ScoutMind 没有对应字段，已忽略：" + "、".join(sorted(ignored_attributes))
        )
    if not users_has_transfers(players):
        report.warnings.append("FMSuperScout 的导出不含转会与逐场统计，转会/表现模块只能显示已有数据")

    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "source": "fmsuperscout",
        "reader_version": f"{ADAPTER_NAME}-adapter-{ADAPTER_VERSION}",
        "game": {
            "version": report.dump_game,
            "build": _text(meta.get("gameDateSource")),
            "app_id": None,
        },
        "scan": {
            "scan_id": scan_id,
            "observed_at": _naive_utc(observed_at).isoformat(),
            "game_date": game_date.isoformat() if game_date else None,
            "user_club_uid": _club_uid(user_club_name) if user_club_name else None,
        },
        "coverage": {
            "players": True,
            "attributes": bool(attribute_seen),
            # The dump carries neither transfers nor per-match rows; say so instead of implying zero.
            "transfers": False,
            "statistics": False,
            "finances": False,
        },
        "warnings": [
            "数据来源：FMSuperScout 导出（第三方开源读取器，MIT 许可），由 ScoutMind 适配层转换",
            *([save_source_note] if save_source_note else []),
            *report.warnings,
        ],
        "clubs": list(clubs.values()),
        "players": rows,
        "transfers": [],
    }
    return payload, report


def users_has_transfers(players: list[object]) -> bool:
    """True when the dump carries any transfer information; upstream dumps currently do not."""
    return any(isinstance(entry, dict) and "transferDate" in entry for entry in players)


def _player_row(
    entry: dict[str, object],
    club_uid: str | None,
    *,
    ownership: dict[str, Any],
    agreed: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, bool], set[str]]:
    """Map one dump player row onto the scan protocol player record."""
    uid = _text(entry.get("id")) or _text(entry.get("uid"))
    name = _text(entry.get("name"))
    birth = _birth_date(entry)
    age = _int(entry.get("age"))
    attributes, ignored, proneness = _attributes(entry.get("attrs"))
    position = _position(entry)
    availability = _availability(entry, proneness)
    row: dict[str, Any] = {
        "record_id": uid,
        "save_local_uid": uid,
        "game_unique_id": uid,
        "name": name or "未命名球员",
        "birth_date": birth.isoformat() if birth else None,
        "age": age,
        "nationality": _primary_nationality(entry.get("nat")),
        "position": position,
        "club_uid": club_uid,
        "ca": _positive(entry.get("ca")),
        "pa": _positive(entry.get("pa")),
        "market_value": _money(entry.get("value")),
        "wage": _money(entry.get("wage")),
        "contract_end": _contract_end(entry.get("expires")),
        "height_cm": _int(entry.get("height")),
        "foot": _foot(entry.get("foot")),
        "world_reputation": _int(entry.get("worldRep"), sentinel_u16=True),
        "attributes": attributes,
        "statistics": [],
        "availability": availability,
        "ownership": ownership or None,
        "agreed_transfer": agreed,
    }
    present = {
        "ca": row["ca"] is not None,
        "pa": row["pa"] is not None,
        "market_value": row["market_value"] is not None,
        "wage": row["wage"] is not None,
        "contract_end": row["contract_end"] is not None,
        "birth_date": row["birth_date"] is not None,
        "age": row["age"] is not None,
        "height_cm": row["height_cm"] is not None,
        "foot": row["foot"] is not None,
        "world_reputation": row["world_reputation"] is not None,
        "listed": (availability or {}).get("listed") is not None,
        "injury_proneness": (availability or {}).get("injury_proneness") is not None,
        "injured": (availability or {}).get("injured") is not None,
        "parent_club": bool(ownership.get("parent_club_uid")),
        "loan_club": bool(ownership.get("loan_club_uid")),
        "agreed_transfer": bool(agreed and agreed.get("to_club_uid")),
        "club": bool(club_uid),
    }
    return row, present, ignored


def _availability(entry: dict[str, object], injury_proneness: int | None) -> dict[str, Any]:
    """Listing flags and injury fields. Upstream reports the flag trio and the proneness; injury status is absent."""
    availability: dict[str, Any] = {
        "listed": _flag(entry.get("listed")),
        "loan_listed": _flag(entry.get("loanListed")),
        "not_for_sale": _flag(entry.get("notForSale")),
        "set_for_release": _flag(entry.get("setForRelease")),
        "injury_proneness": injury_proneness,
        # Upstream does not expose the current injury, its dates or a history: stay unknown, never "fit".
        "injured": None,
        "injury_start_date": None,
        "expected_return_date": None,
        "injury_note": None,
    }
    if all(value is None for value in availability.values()):
        return {}
    return availability


def _ownership(entry: dict[str, object], club_name: str | None) -> dict[str, Any]:
    """Owner and loan clubs, when the dump names them. Absent keys stay absent instead of being guessed."""
    owner = _text(entry.get("ownerClub"))
    team_type = _normalise_team_type(_text(entry.get("ownerTeamType")) or _text(entry.get("teamType")))
    if not owner:
        return {}
    ownership: dict[str, Any] = {
        "parent_club_uid": _club_uid(owner),
        "team_type": team_type,
        # Loan clauses are not in the dump; leave them None so callers show "unknown".
        "loan_start_date": None,
        "loan_end_date": None,
        "has_option": None,
        "has_obligation": None,
    }
    if club_name and club_name != owner:
        ownership["loan_club_uid"] = _club_uid(club_name)
    return ownership


def _agreed_transfer(entry: dict[str, object]) -> dict[str, Any] | None:
    """A future move the dump already knows about, stored as an agreed transfer rather than spending."""
    target = _text(entry.get("transferTo"))
    if not target:
        return None
    return {"to_club_uid": _club_uid(target), "transfer_date": _contract_end(entry.get("transferDate"))}


def _ensure_club(
    clubs: dict[str, dict[str, Any]],
    name: str,
    *,
    league: str | None,
    reputation: int | None,
    user_club_name: str | None,
) -> None:
    """Register a club mentioned by a player row, a loan or an agreed transfer."""
    uid = _club_uid(name)
    club = clubs.setdefault(
        uid,
        {
            "uid": uid,
            "name": name,
            "nation": None,
            "league": league,
            "reputation": reputation,
            "is_user_club": bool(user_club_name and name == user_club_name),
        },
    )
    if club["league"] is None:
        club["league"] = league
    if club["reputation"] is None:
        club["reputation"] = reputation

def _attributes(raw: object) -> tuple[dict[str, float], set[str], int | None]:
    """Rename a dump attribute dict; unknown upstream keys are collected for the report.

    ``InjuryProneness`` is pulled out of the attribute set: it is a proneness rating for availability, not a scored
    football attribute, so it must not leak into role scores.
    """
    if not isinstance(raw, dict):
        return {}, set(), None
    attributes: dict[str, float] = {}
    ignored: set[str] = set()
    proneness: int | None = None
    for key, value in raw.items():
        name = str(key)
        if name == "InjuryProneness":
            proneness = _int(value)
            continue
        mapped = ATTRIBUTE_MAP.get(name)
        number = _number(value)
        if mapped is None:
            ignored.add(name)
            continue
        if number is None:
            continue
        attributes[mapped] = number
    return attributes, ignored, proneness


def _flag(value: object) -> bool | None:
    """Three-valued listing flag: only a real boolean is an observation."""
    if isinstance(value, bool):
        return value
    return None


#: Foot labels seen in real dumps across UI languages. Anything unknown falls back to a prefix match, then to None.
FOOT_LABELS = {
    "rechts": "right",
    "links": "left",
    "beide": "both",
    "right": "right",
    "left": "left",
    "both": "both",
    "either": "both",
    "droit": "right",
    "gauche": "left",
    "les deux": "both",
    "derecho": "right",
    "izquierdo": "left",
    "ambos": "both",
    "destro": "right",
    "sinistro": "left",
    "entrambi": "both",
    "prawo": "right",
    "lewo": "left",
    "obojętnie": "both",
}


def _foot(value: object) -> str | None:
    """Normalise the dump's foot label onto the protocol enum; unknown labels stay None."""
    text = (_text(value) or "").strip().lower()
    if not text:
        return None
    if text in FOOT_LABELS:
        return FOOT_LABELS[text]
    if text.startswith(("r", "p")):  # right / rechts / prawo
        return "right"
    if text.startswith(("l", "g")):  # left / links / gauche / lewo
        return "left"
    if text.startswith(("b", "e")):  # both / beide / either
        return "both"
    return None


def _primary_nationality(raw: object) -> str | None:
    """Take the primary nationality; the dump can carry a list (dual nationality)."""
    if isinstance(raw, list):
        for item in raw:
            text = _text(item)
            if text:
                return text
        return None
    return _text(raw)


def _money(value: object) -> int | None:
    """Money fields: 0 and sentinels mean "not stated" in the dump, not a real zero."""
    integer = _int(value, sentinel_int=True)
    if integer is None or integer <= 0:
        return None
    return integer

def _normalise_team_type(value: str | None) -> str | None:
    """Map upstream's squad-type label onto senior/reserve/youth; unknown values are dropped."""
    if not value:
        return None
    text = value.strip().lower()
    if text in {"senior", "first", "firstteam", "first team"}:
        return "senior"
    if text in {"reserve", "reserves", "b", "second"}:
        return "reserve"
    if text in {"youth", "u18", "u19", "u21", "academy"}:
        return "youth"
    return None


def _position(entry: dict[str, object]) -> str | None:
    """Preferred position: the dump's natural list first, then any listed position."""
    for key in ("posNat", "posArr"):
        values = entry.get(key)
        if isinstance(values, list):
            for value in values:
                code = _text(value)
                if code:
                    return code.upper()
    text = _text(entry.get("pos"))
    if not text:
        return None
    match = re.match(r"[A-Za-z]{2,4}", text)
    return match.group(0).upper() if match else None


def _birth_date(entry: dict[str, object]) -> date | None:
    """Birth date from upsteam's year + day-of-year fields; ``None`` when only one of them exists."""
    year = _int(entry.get("birthYear"))
    doy = _int(entry.get("birthDoy"))
    if year is None or year < 1900 or year > 2100:
        return None
    if doy is None or doy < 1 or doy > 366:
        return None
    try:
        return date(year, 1, 1) + timedelta(days=doy - 1)
    except ValueError:
        return None


def _contract_end(raw: object) -> str | None:
    text = _text(raw)
    if not text:
        return None
    parsed = _parse_date(text)
    return parsed.isoformat() if parsed else None


def _is_ghost(entry: dict[str, object]) -> bool:
    """Upstream's own filter: no club and an unset reputation means the newgen does not exist in the world yet."""
    if _text(entry.get("club")):
        return False
    reputation = entry.get("worldRep")
    return isinstance(reputation, int) and reputation == SENTINEL_U16


def _compatibility(game: str | None, meta: dict[str, object] | None = None) -> dict[str, object]:
    """Detect a game family the adapter was not written against.

    Upstream reports its own ``versionOk`` / ``supportedVersion``: when the scanner says the extraction is based on
    an older build than the running game, field reliability is *lower*, and the report says so instead of silently
    trusting the numbers.
    """
    meta = meta or {}
    supported = ", ".join(f"FM{major}" for major in SUPPORTED_GAME_MAJORS)
    upstream_ok = meta.get("versionOk")
    upstream_build = _text(meta.get("supportedVersion"))
    game_version = _text(meta.get("gameVersion"))
    if not game:
        return {
            "game": None,
            "supported": False,
            "known_majors": list(SUPPORTED_GAME_MAJORS),
            "upstream_version_ok": upstream_ok,
            "message": f"导出里没有 meta.game，无法判断版本；适配层按 {supported} 编写，请人工核对",
        }
    major = "".join(ch for ch in str(game) if ch.isdigit())[:2]
    supported_dump = major in SUPPORTED_GAME_MAJORS
    messages: list[str] = []
    if not supported_dump:
        messages.append(f"导出标注的版本 {game} 不在已验证的 {supported} 内；字段可能已变化")
    if upstream_ok is False:
        detail = f"（扫描器按 {upstream_build} 解析游戏 {game_version}）" if upstream_build else ""
        messages.append(f"读取器自检 versionOk=false：上游认为该版本解析可能不可靠{detail}")
    return {
        "game": game,
        "major": major or None,
        "supported": supported_dump and upstream_ok is not False,
        "known_majors": list(SUPPORTED_GAME_MAJORS),
        "upstream_version_ok": upstream_ok,
        "upstream_supported_version": upstream_build,
        "game_version": game_version,
        "message": "；".join(messages) if messages else None,
    }


def _club_uid(name: str) -> str:
    """Stable club identifier derived from the club name the dump reports."""
    slug = _SLUG_PATTERN.sub("-", name.strip().lower()).strip("-")
    return f"fs-{slug}" if slug else "fs-unknown"


def _field_used(name: str, rows: list[dict[str, Any]], clubs: dict[str, dict[str, Any]]) -> bool:
    """Whether a mapped field actually carried data in this dump (drives the report, not the conversion)."""
    if name == "club":
        return bool(clubs)
    if name == "div":
        return any(club.get("league") for club in clubs.values())
    if name.startswith("age") or name == "id":
        return bool(rows)
    if name == "attrs":
        return any(row.get("attributes") for row in rows)
    if name == "attrs.InjuryProneness":
        return any((row.get("availability") or {}).get("injury_proneness") is not None for row in rows)
    if name.startswith("listed"):
        return any(
            any((row.get("availability") or {}).get(key) is not None for key in AVAILABILITY_KEYS)
            for row in rows
        )
    if name.startswith("ownerClub"):
        return any((row.get("ownership") or {}).get("parent_club_uid") for row in rows)
    if name.startswith("transferTo"):
        return any(row.get("agreed_transfer") for row in rows)
    if name == "height":
        return any(row.get("height_cm") is not None for row in rows)
    if name == "foot":
        return any(row.get("foot") is not None for row in rows)
    if name == "worldRep":
        return any(row.get("world_reputation") is not None for row in rows)
    if name == "expires":
        return any(row.get("contract_end") for row in rows)
    return any(row.get(name) is not None for row in rows)


def _absent_override(name: str, players: list[object]) -> bool:
    """Fields that the report lists as absent even when a stray row carries them."""
    if name == "transfers":
        return users_has_transfers(players)
    return False


def _positive(value: object) -> int | None:
    """An ability rating below 1 is not an observation in FM; treat it as unknown rather than as 0."""
    number = _int(value)
    if number is None or number <= 0:
        return None
    return number


def _int(value: object, *, sentinel_u16: bool = False, sentinel_int: bool = False) -> int | None:
    number = _number(value)
    if number is None:
        return None
    integer = int(number)
    if integer < 0:
        return None
    if sentinel_u16 and integer >= SENTINEL_U16:
        return None
    if sentinel_int and integer >= SENTINEL_INT:
        return None
    return integer


def _number(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _text(value: object) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return None


def _parse_datetime(value: object) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    candidate = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    return parsed


def _parse_date(value: object) -> date | None:
    text = _text(value)
    if not text:
        return None
    for slice_end in (10, 7, 4):
        chunk = text[:slice_end]
        try:
            if slice_end == 10:
                return date.fromisoformat(chunk)
            if slice_end == 7:
                return date.fromisoformat(f"{chunk}-01")
            return date.fromisoformat(f"{chunk}-01-01")
        except ValueError:
            continue
    return None


def _naive_utc(moment: datetime) -> datetime:
    """Store observations as naive UTC, matching the protocol's normalisation."""
    if moment.tzinfo is not None:
        return moment.astimezone(timezone.utc).replace(tzinfo=None)
    return moment
