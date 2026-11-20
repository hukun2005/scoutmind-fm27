"""转会金额解析与币种标准化（SM-022）。

支持格式（大小写不敏感）：

* 纯数字：``2500000``、``2500000.0``
* 千分位：``2,500,000``
* 符号 + 单位：``£2.5m``、``€12.5M``、``$500K``、``¥1.2亿``
* 英文单位：``500K``、``1.2 million``、``2 m``
* 中文单位：``150万``、``1200万``、``1.2亿``

规则：

1. 金额与币种必须能确定；缺币种或格式不认识 → 返回 error，由导入器拒绝并给行号；
2. 绝不把 ``2.5M`` 解析成 ``2.5``；
3. 不支持的格式不做"猜测"；
4. 原始字符串由调用方保留在 ``*_raw`` 列与 ``raw_payload_json``；
5. 不做跨币种换算（没有可靠汇率来源）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

CURRENCY_SYMBOLS = {
    "£": "GBP",
    "€": "EUR",
    "$": "USD",
    "¥": "CNY",
    "￥": "CNY",
    "₩": "KRW",
}

CURRENCY_CODES = {"GBP", "EUR", "USD", "CNY", "JPY", "KRW", "BRL", "ARS", "TRY"}

UNIT_FACTORS = {
    "k": 1_000,
    "thousand": 1_000,
    "m": 1_000_000,
    "million": 1_000_000,
    "b": 1_000_000_000,
    "billion": 1_000_000_000,
    "万": 10_000,
    "亿": 100_000_000,
}

_SUFFIX = re.compile(r"^\s*([-+]?[\d,]+(?:\.\d+)?)\s*([a-zA-Z]+|万|亿)?\s*$")
_PREFIX = re.compile(r"^\s*([£€$¥￥₩])\s*([-+]?[\d,]+(?:\.\d+)?)\s*([a-zA-Z]+|万|亿)?\s*$")
_CODE = re.compile(r"^\s*(GBP|EUR|USD|CNY|JPY|KRW|BRL|ARS|TRY)\s*([-+]?[\d,]+(?:\.\d+)?)\s*([a-zA-Z]+|万|亿)?\s*$", re.I)
_NUMBER = re.compile(r"^\d{1,3}(?:,\d{3})*(?:\.\d+)?$|^\d+(?:\.\d+)?$")


@dataclass(frozen=True)
class AmountParse:
    """一次金额解析的结果。"""

    amount: float | None
    currency: str | None
    raw: str | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.amount is not None


def _number(text: str) -> float:
    """严格校验千分位：只接受 2,500,000 / 2500000 / 2500000.5，拒绝 2,5 与 1,2,3。"""
    if not _NUMBER.match(text):
        raise ValueError(f"非法数字格式 {text!r}（千分位必须每三位一组）")
    return float(text.replace(",", ""))


def parse_amount(value: object, currency_hint: str | None = None) -> AmountParse:
    """解析一个金额单元格；失败时给出可读原因，不做猜测。"""
    if value is None:
        return AmountParse(None, None, None)
    raw = str(value).strip()
    if not raw:
        return AmountParse(None, None, raw)
    if raw.lower() in {"-", "n/a", "na", "unknown", "?"}:
        return AmountParse(None, None, raw, "金额标记为未知")

    hint = (currency_hint or "").strip().upper()
    currency = hint if hint in CURRENCY_CODES else None

    match = _PREFIX.match(raw)
    if match:
        symbol, number, suffix = match.groups()
        currency = CURRENCY_SYMBOLS[symbol]
        return _finish(number, suffix, raw, currency)

    match = _CODE.match(raw)
    if match:
        code, number, suffix = match.groups()
        return _finish(number, suffix, raw, code.upper())

    match = _SUFFIX.match(raw)
    if match:
        number, suffix = match.groups()
        return _finish(number, suffix, raw, currency)

    return AmountParse(None, None, raw, f"无法解析金额 {raw!r}（支持 2500000 / 2,500,000 / £2.5m / 500K / 150万 等格式）")


def _finish(number_text: str, suffix: str | None, raw: str, currency: str | None) -> AmountParse:
    try:
        value = _number(number_text)
    except ValueError as exc:
        return AmountParse(None, currency, raw, f"金额数字部分非法：{exc}")
    if suffix:
        unit = UNIT_FACTORS.get(suffix.lower())
        if unit is None:
            return AmountParse(None, currency, raw, f"未知金额单位 {suffix!r}")
        value *= unit
    if value < 0:
        return AmountParse(None, currency, raw, "金额不能为负")
    if currency is None:
        return AmountParse(None, None, raw, f"金额 {raw!r} 缺少币种（请提供 currency 列或货币符号）")
    if value >= 10_000_000_000:
        return AmountParse(None, currency, raw, "金额数量级异常（>= 100 亿），拒绝导入")
    return AmountParse(value, currency, raw)


def parse_ratio(value: object, *, maximum: float = 100.0) -> tuple[float | None, str | None]:
    """解析百分比/比例（0..maximum）：接受 ``10``、``10%``、``12.5 %``；不做字符过滤。"""
    if value is None:
        return None, None
    raw = str(value).strip()
    if not raw:
        return None, None
    text = raw[:-1].strip() if raw.endswith("%") else raw
    try:
        number = _number(text)
    except ValueError as exc:
        return None, f"比例/百分比格式非法：{exc}"
    if number < 0 or number > maximum:
        return None, f"比例 {number} 超出 0..{maximum:g}"
    return number, None


def parse_plain_number(value: object) -> tuple[float | None, str | None]:
    """解析工资分摊等纯数字字段：不接受货币符号、单位或任意字符。"""
    if value is None:
        return None, None
    raw = str(value).strip()
    if not raw:
        return None, None
    try:
        return _number(raw), None
    except ValueError as exc:
        return None, f"数字格式非法：{exc}"
