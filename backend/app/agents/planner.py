"""Rule-based intent parsing for the decision assistant.

The MVP ships without an LLM dependency: a deterministic parser maps Chinese questions to tool plans, so answers are
reproducible and the regression tests can assert that no number appears without a tool result behind it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

POSITION_WORDS: tuple[tuple[str, str], ...] = (
    ("门将", "GK"),
    ("中卫", "DF"),
    ("后卫", "DF"),
    ("边翼卫", "DF"),
    ("后腰", "MF"),
    ("中场", "MF"),
    ("中前卫", "MF"),
    ("前腰", "MF"),
    ("边锋", "FW"),
    ("前锋", "FW"),
    ("中锋", "FW"),
)


@dataclass
class Intent:
    """A parsed question and the tool plan it implies."""

    kind: str
    question: str
    position_group: str | None = None
    min_age: int | None = None
    max_age: int | None = None
    min_ca: int | None = None
    min_pa: int | None = None
    min_value: int | None = None
    max_value: int | None = None
    budget: float | None = None
    installments: int = 3
    instance_id: int | None = None
    transfer_id: int | None = None
    club_id: int | None = None
    mentions_own_club: bool = False
    role_key: str | None = None


def parse(question: str, instance_id: int | None = None, club_id: int | None = None) -> Intent:
    """Parse one natural-language question into an :class:`Intent`."""
    text = question.strip()
    lowered = text.lower()
    intent = Intent(kind=_kind(lowered), question=text, instance_id=instance_id, club_id=club_id)
    intent.position_group = _position_group(text)
    intent.min_age, intent.max_age = _ages(text)
    intent.min_ca = _number(lowered, r"ca\s*[:：]?\s*(\d{2,3})")
    intent.min_pa = _number(lowered, r"pa\s*[:：]?\s*(\d{2,3})")
    intent.budget = _money(lowered)
    intent.mentions_own_club = any(word in text for word in ("我队", "我的球员", "自家", "本队"))
    intent.installments = _number(lowered, r"分\s*(\d)\s*期") or 3
    if intent.kind == "deal":
        intent.transfer_id = _number(lowered, r"交易\s*#?(\d+)")
    return intent


def _kind(lowered: str) -> str:
    if any(word in lowered for word in ("俱乐部画像", "哪些俱乐部", "买卖风格", "低价买入", "高价卖出", "转会画像")):
        return "club_profile"
    if any(word in lowered for word in ("复盘", "这笔交易", "成交复盘", "我这笔")):
        return "deal"
    if any(
        word in lowered
        for word in ("报价", "估值", "值多少", "应该出", "出多少", "值不值", "多少能买", "出售", "卖掉", "卖窗口", "续约")
    ):
        return "valuation"
    if any(word in lowered for word in ("成交价", "中位数", "行情", "价格分布", "卖多少", "卖多少钱", "分位")):
        return "price_stats"
    if any(word in lowered for word in ("相似", "类似", "可比")):
        return "similar"
    return "scout"


def _position_group(text: str) -> str | None:
    for word, group in POSITION_WORDS:
        if word in text:
            return group
    return None


def _ages(text: str) -> tuple[int | None, int | None]:
    under = re.search(r"u\s*(\d{2})", text, re.IGNORECASE)
    if under:
        return None, int(under.group(1))
    exact = re.search(r"(\d{2})\s*岁", text)
    if exact:
        age = int(exact.group(1))
        return age - 1, age + 1
    between = re.search(r"(\d{2})\s*[-–到至]\s*(\d{2})\s*岁", text)
    if between:
        return int(between.group(1)), int(between.group(2))
    return None, None


def _number(lowered: str, pattern: str) -> int | None:
    match = re.search(pattern, lowered)
    return int(match.group(1)) if match else None


def _money(lowered: str) -> float | None:
    match = re.search(r"预算[是为]?\s*([\d.]+)\s*(亿|万)?", lowered)
    if not match:
        return None
    amount = float(match.group(1))
    unit = match.group(2)
    if unit == "亿":
        return amount * 100_000_000
    if unit == "万":
        return amount * 10_000
    return amount
