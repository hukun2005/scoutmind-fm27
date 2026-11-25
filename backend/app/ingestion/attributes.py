"""Attribute dictionary and position grouping shared by ingestion and analytics.

The keys match the scanner protocol (``docs/DATA_PROTOCOL.md``). Unknown keys from a scan are ignored with a
warning instead of being stored as invented attributes.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import PlayerAttribute

# (key, 中文名, category, sort order)
ATTRIBUTES: tuple[tuple[str, str, str, int], ...] = (
    ("finishing", "射门", "technical", 10),
    ("dribbling", "盘带", "technical", 20),
    ("passing", "传球", "technical", 30),
    ("tackling", "抢断", "technical", 40),
    ("technique", "技术", "technical", 50),
    ("first_touch", "停球", "technical", 60),
    ("crossing", "传中", "technical", 70),
    ("heading", "头球", "technical", 80),
    ("long_shots", "远射", "technical", 90),
    ("marking", "盯人", "technical", 100),
    ("free_kick", "任意球", "technical", 110),
    ("penalty_taking", "点球", "technical", 120),
    ("anticipation", "预判", "mental", 10),
    ("composure", "冷静", "mental", 20),
    ("concentration", "专注", "mental", 30),
    ("decisions", "决断", "mental", 40),
    ("determination", "意志", "mental", 50),
    ("flair", "灵感", "mental", 60),
    ("leadership", "领导力", "mental", 70),
    ("off_the_ball", "无球跑动", "mental", 80),
    ("positioning", "位置感", "mental", 90),
    ("teamwork", "团队合作", "mental", 100),
    ("vision", "视野", "mental", 110),
    ("work_rate", "工作效率", "mental", 120),
    ("aggression", "侵略性", "mental", 130),
    ("bravery", "勇敢", "mental", 140),
    ("acceleration", "加速", "physical", 10),
    ("agility", "灵活", "physical", 20),
    ("balance", "平衡", "physical", 30),
    ("jumping", "弹跳", "physical", 40),
    ("natural_fitness", "体能", "physical", 50),
    ("pace", "速度", "physical", 60),
    ("stamina", "耐力", "physical", 70),
    ("strength", "力量", "physical", 80),
    ("aerial_reach", "制空范围", "goalkeeping", 10),
    ("command_of_area", "指挥禁区", "goalkeeping", 20),
    ("communication", "沟通", "goalkeeping", 30),
    ("eccentricity", "冒险度", "goalkeeping", 40),
    ("handling", "手控球", "goalkeeping", 50),
    ("kicking", "开球", "goalkeeping", 60),
    ("one_on_ones", "一对一", "goalkeeping", 70),
    ("reflexes", "反应", "goalkeeping", 80),
    ("rushing_out", "出击", "goalkeeping", 90),
    ("punching", "击球", "goalkeeping", 100),
)

ATTRIBUTE_KEYS: frozenset[str] = frozenset(item[0] for item in ATTRIBUTES)

POSITION_GROUPS: dict[str, str] = {
    "GK": "GK",
    "DC": "DF",
    "DL": "DF",
    "DR": "DF",
    "WBL": "DF",
    "WBR": "DF",
    "DM": "MF",
    "MC": "MF",
    "ML": "MF",
    "MR": "MF",
    "AMC": "MF",
    "AML": "FW",
    "AMR": "FW",
    "ST": "FW",
    "STC": "FW",
}

POSITION_NAMES_ZH: dict[str, str] = {
    "GK": "门将",
    "DC": "中后卫",
    "DL": "左后卫",
    "DR": "右后卫",
    "WBL": "左翼卫",
    "WBR": "右翼卫",
    "DM": "后腰",
    "MC": "中前卫",
    "ML": "左前卫",
    "MR": "右前卫",
    "AMC": "前腰",
    "AML": "左边锋",
    "AMR": "右边锋",
    "ST": "前锋",
    "STC": "中锋",
}


def position_group(position: str | None) -> str | None:
    """Map a scanner position code to GK/DF/MF/FW, returning ``None`` for unknown codes."""
    if not position:
        return None
    return POSITION_GROUPS.get(position.strip().upper())


# Squad slots are the ten places a squad is planned around. They are wider than scanner position codes so that, for
# example, a left wing-back and a left back both count towards coverage of ``LB``.
SQUAD_SLOTS: tuple[str, ...] = ("GK", "CB", "LB", "RB", "DM", "CM", "AM", "LW", "RW", "ST")

SLOT_NAMES_ZH: dict[str, str] = {
    "GK": "门将",
    "CB": "中后卫",
    "LB": "左后卫",
    "RB": "右后卫",
    "DM": "后腰",
    "CM": "中前卫",
    "AM": "前腰",
    "LW": "左边锋",
    "RW": "右边锋",
    "ST": "中锋",
}

POSITION_TO_SLOT: dict[str, str] = {
    "GK": "GK",
    "DC": "CB",
    "DL": "LB",
    "WBL": "LB",
    "DR": "RB",
    "WBR": "RB",
    "DM": "DM",
    "MC": "CM",
    "ML": "LW",
    "MR": "RW",
    "AMC": "AM",
    "AML": "LW",
    "AMR": "RW",
    "ST": "ST",
    "STC": "ST",
}

# Minimum number of players a competitive squad needs in each slot; used by the coverage and depth components.
SLOT_REQUIREMENT: dict[str, int] = {
    "GK": 2,
    "CB": 4,
    "LB": 2,
    "RB": 2,
    "DM": 2,
    "CM": 3,
    "AM": 1,
    "LW": 2,
    "RW": 2,
    "ST": 2,
}

# How much a hole in the slot hurts the overall squad score.
SLOT_IMPORTANCE: dict[str, float] = {
    "GK": 1.0,
    "CB": 1.0,
    "LB": 0.8,
    "RB": 0.8,
    "DM": 0.8,
    "CM": 1.0,
    "AM": 0.7,
    "LW": 0.7,
    "RW": 0.7,
    "ST": 1.0,
}


def slot_of(position: str | None) -> str | None:
    """Map a scanner position code to a squad slot, returning ``None`` for unknown codes."""
    if not position:
        return None
    return POSITION_TO_SLOT.get(position.strip().upper())


def ensure_attributes(session: Session) -> dict[str, int]:
    """Idempotently seed the attribute dictionary and return key -> id."""
    existing = {row.key: row.id for row in session.scalars(select(PlayerAttribute))}
    created = 0
    for key, name_zh, category, sort_order in ATTRIBUTES:
        if key in existing:
            continue
        row = PlayerAttribute(
            key=key,
            name=key.replace("_", " ").title(),
            name_zh=name_zh,
            category=category,
            sort_order=sort_order,
        )
        try:
            # 并发导入可能同时补种同一属性；唯一约束先到先得，后到者复读已有行。
            with session.begin_nested():
                session.add(row)
                session.flush()
        except IntegrityError:
            stored = session.scalar(select(PlayerAttribute).where(PlayerAttribute.key == key))
            if stored is None:
                raise
            existing[key] = stored.id
            continue
        existing[key] = row.id
        created += 1
    if created:
        session.flush()
    return existing
