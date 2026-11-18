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
)

#: Scan-protocol fields the dump has no source for, so every dependent feature reports them unavailable.
ABSENT_FIELDS = (
    "minutes_played",
    "appearances",
    "goals",
    "assists",
    "statistics",
    "transfers",
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
    "InjuryProneness": "伤倾字段，ScoutMind 的伤病风险仍标记为不可评估",
    "height": "身体尺寸，当前模型未使用",
    "foot": "惯用脚，当前模型未使用",
    "listed": "挂牌状态，尚无对应的持久化字段",
    "loanListed": "租借挂牌状态，尚无对应的持久化字段",
    "notForSale": "非卖品标记，尚无对应的持久化字段",
    "setForRelease": "解约标记，尚无对应的持久化字段",
    "worldRep": "世界声望，ScoutMind 只使用俱乐部声誉",
    "ownerClub": "所有权归属，当前模型未使用",
    "ownerTeamType": "球队类型，当前模型未使用",
    "teamType": "球队类型，当前模型未使用",
    "job": "职员岗位，不属于球员模型",
}

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
    numeric_presence = {"ca": 0, "pa": 0, "market_value": 0, "wage": 0, "contract_end": 0, "birth_date": 0, "age": 0}

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
            club = clubs.setdefault(
                club_uid,
                {
                    "uid": club_uid,
                    "name": club_name,
                    "nation": None,
                    "league": _text(entry.get("div")),
                    "reputation": _int(entry.get("clubRep"), sentinel_u16=True),
                    "is_user_club": bool(user_club_name and club_name == user_club_name),
                },
            )
            if club["league"] is None:
                club["league"] = _text(entry.get("div"))
        row, present, ignored = _player_row(entry, club_uid)
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
    entry: dict[str, object], club_uid: str | None
) -> tuple[dict[str, Any], dict[str, bool], set[str]]:
    """Map one dump player row onto the scan protocol player record."""
    uid = _text(entry.get("id")) or _text(entry.get("uid"))
    name = _text(entry.get("name"))
    birth = _birth_date(entry)
    age = _int(entry.get("age"))
    attributes, ignored = _attributes(entry.get("attrs"))
    position = _position(entry)
    row: dict[str, Any] = {
        "record_id": uid,
        "save_local_uid": uid,
        "game_unique_id": uid,
        "name": name or "未命名球员",
        "birth_date": birth.isoformat() if birth else None,
        "age": age,
        "nationality": _text(entry.get("nat")),
        "position": position,
        "club_uid": club_uid,
        "ca": _int(entry.get("ca"), sentinel_u16=False),
        "pa": _int(entry.get("pa"), sentinel_u16=False),
        "market_value": _int(entry.get("value"), sentinel_int=True),
        "wage": _int(entry.get("wage"), sentinel_int=True),
        "contract_end": _contract_end(entry.get("expires")),
        "attributes": attributes,
        "statistics": [],
    }
    present = {
        "ca": row["ca"] is not None,
        "pa": row["pa"] is not None,
        "market_value": row["market_value"] is not None,
        "wage": row["wage"] is not None,
        "contract_end": row["contract_end"] is not None,
        "birth_date": row["birth_date"] is not None,
        "age": row["age"] is not None,
    }
    return row, present, ignored


def _attributes(raw: object) -> tuple[dict[str, float], set[str]]:
    """Rename a dump attribute dict; unknown upstream keys are collected for the report."""
    if not isinstance(raw, dict):
        return {}, set()
    attributes: dict[str, float] = {}
    ignored: set[str] = set()
    for key, value in raw.items():
        name = str(key)
        mapped = ATTRIBUTE_MAP.get(name)
        number = _number(value)
        if mapped is None:
            ignored.add(name)
            continue
        if number is None:
            continue
        attributes[mapped] = number
    return attributes, ignored


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


def _club_uid(name: str) -> str:
    """Stable club identifier derived from the club name the dump reports."""
    slug = _SLUG_PATTERN.sub("-", name.strip().lower()).strip("-")
    return f"fs-{slug}" if slug else "fs-unknown"


def _field_used(name: str, rows: list[dict[str, Any]], clubs: dict[str, dict[str, Any]]) -> bool:
    if name == "club":
        return bool(clubs)
    if name == "div":
        return any(club.get("league") for club in clubs.values())
    if name.startswith("age") or name == "id":
        return bool(rows)
    if name == "attrs":
        return any(row.get("attributes") for row in rows)
    if name == "expires":
        return any(row.get("contract_end") for row in rows)
    return any(row.get(name) is not None for row in rows)


def _absent_override(name: str, players: list[object]) -> bool:
    """Fields that the report lists as absent even when a stray row carries them."""
    if name == "transfers":
        return users_has_transfers(players)
    return False


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
