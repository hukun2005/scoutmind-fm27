"""LLM 工具规划器（SM-009）。

职责边界刻意划得很窄：

1. **LLM 只做规划与解释**：把自然语言问题转成"调用哪些确定性工具、参数是什么"，
   以及把工具返回的事实组织成一段说明。
2. **数字只能来自工具**：计划里的每个工具都由 :mod:`app.agents.tools` 执行，
   模型看不到、也不能直接读数据库；回答里的金额/评分都引用工具结果。
3. **参数由服务端校验并注入 save_id**：模型不允许指定存档，越权参数直接丢弃/拒绝。
4. **失败就降级**：LLM 不可用、超时、返回非法 JSON、工具名不存在时，退回规则规划器，
   并在回答里说明降级原因——绝不假装是 LLM 结果。

工具调用上限 5 次，每次参数都按 JSON Schema 做类型/范围校验。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy.orm import Session

from ..config import settings
from . import tools
from .tools import ToolCall

log = logging.getLogger("scoutmind.agent.llm")

MAX_TOOL_CALLS = 5

#: 允许模型规划的工具白名单。save_id 永远由服务端注入，不出现在参数里。
TOOL_SPECS: dict[str, dict[str, Any]] = {
    "search_players": {
        "description": "按位置、年龄、CA 等条件搜索球员（只读）",
        "parameters": {
            "type": "object",
            "properties": {
                "position_group": {"type": "string", "enum": ["GK", "DF", "MF", "FW"]},
                "min_age": {"type": "integer", "minimum": 14, "maximum": 50},
                "max_age": {"type": "integer", "minimum": 14, "maximum": 50},
                "min_ca": {"type": "integer", "minimum": 1, "maximum": 200},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            "additionalProperties": False,
        },
        "execute": lambda session, save_id, args: tools.search_players(session, save_id, filters=args, limit=args.get("limit", 20)),
    },
    "squad_overview": {
        "description": "球队阵容概览（人数、年龄、CA 分布）",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        "execute": lambda session, save_id, args: tools.get_squad_overview(session, save_id),
    },
    "position_depth": {
        "description": "各位置人数与缺口分析",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        "execute": lambda session, save_id, args: tools.analyze_position_depth(session, save_id),
    },
    "transfer_price_stats": {
        "description": "历史转会价格统计（已完成交易）",
        "parameters": {
            "type": "object",
            "properties": {"position_group": {"type": "string", "enum": ["GK", "DF", "MF", "FW"]}},
            "additionalProperties": False,
        },
        "execute": lambda session, save_id, args: tools.get_transfer_price_stats(session, save_id, criteria=args),
    },
    "transfer_targets": {
        "description": "按位置/预算筛选引援目标",
        "parameters": {
            "type": "object",
            "properties": {
                "slot": {"type": "string", "minLength": 1, "maxLength": 8},
                "max_value": {"type": "number", "minimum": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            "additionalProperties": False,
        },
        "execute": lambda session, save_id, args: tools.find_transfer_targets(
            session, save_id, slot=args.get("slot"), max_value=args.get("max_value"), limit=args.get("limit", 20)
        ),
    },
    "player_profile": {
        "description": "单个球员档案（需要 instance_id）",
        "parameters": {
            "type": "object",
            "properties": {"instance_id": {"type": "integer", "minimum": 1}},
            "required": ["instance_id"],
            "additionalProperties": False,
        },
        "execute": lambda session, save_id, args: tools.get_player_profile(session, int(args["instance_id"])),
    },
    "player_growth": {
        "description": "球员发展历史（需要 instance_id）",
        "parameters": {
            "type": "object",
            "properties": {"instance_id": {"type": "integer", "minimum": 1}},
            "required": ["instance_id"],
            "additionalProperties": False,
        },
        "execute": lambda session, save_id, args: tools.get_player_growth_history(session, int(args["instance_id"])),
    },
    "player_evaluation": {
        "description": "按存档与球员实例计算评分（需要 instance_id）",
        "parameters": {
            "type": "object",
            "properties": {"instance_id": {"type": "integer", "minimum": 1}},
            "required": ["instance_id"],
            "additionalProperties": False,
        },
        "execute": lambda session, save_id, args: tools.evaluate_player(session, save_id, int(args["instance_id"])),
    },
}

#: 禁止出现在参数里的键：存档/用户上下文只由服务端决定。
FORBIDDEN_ARGUMENTS = {"save_id", "fm_save_id", "user_id", "session_id"}


@dataclass
class PlanResult:
    """规划与执行结果。"""

    calls: list[ToolCall]
    trace: list[dict[str, object]] = field(default_factory=list)
    mode: str = "llm"
    warning: str | None = None


class LlmUnavailable(RuntimeError):
    """LLM 未配置或不可用：由调用方降级到规则规划器。"""


class PlannerError(ValueError):
    """模型给出的计划不合法（未知工具、参数越界、超过调用上限）。"""


def llm_enabled() -> bool:
    return bool(settings.agent_llm_enabled and settings.agent_llm_api_key)


def _validate_arguments(spec: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """按 schema 做最小但严格的校验：类型、枚举、范围、未知键、禁止键。"""
    params = spec["parameters"]
    properties = params.get("properties", {})
    allowed = set(properties)
    unknown = set(arguments) - allowed
    forbidden = unknown & FORBIDDEN_ARGUMENTS
    if forbidden:
        raise PlannerError(f"模型试图指定受限参数：{sorted(forbidden)}")
    if unknown:
        raise PlannerError(f"未知参数：{sorted(unknown)}")

    cleaned: dict[str, Any] = {}
    for key, value in arguments.items():
        rule = properties[key]
        kind = rule.get("type")
        if kind == "integer":
            if not isinstance(value, int) or isinstance(value, bool):
                raise PlannerError(f"{key} 必须是整数")
            if "minimum" in rule and value < rule["minimum"]:
                raise PlannerError(f"{key} 小于下限")
            if "maximum" in rule and value > rule["maximum"]:
                raise PlannerError(f"{key} 超过上限")
        elif kind == "number":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise PlannerError(f"{key} 必须是数字")
            if "minimum" in rule and value < rule["minimum"]:
                raise PlannerError(f"{key} 小于下限")
        elif kind == "string":
            if not isinstance(value, str):
                raise PlannerError(f"{key} 必须是字符串")
            if "enum" in rule and value not in rule["enum"]:
                raise PlannerError(f"{key} 不在允许取值内")
        cleaned[key] = value

    for key in params.get("required", []):
        if key not in cleaned:
            raise PlannerError(f"缺少必需参数 {key}")
    return cleaned


def parse_plan(payload: dict[str, Any], *, allow: set[str] | None = None) -> list[tuple[str, dict[str, Any]]]:
    """把模型返回的 JSON 解析成 ``[(tool, args)]``，并做全部校验。"""
    calls = payload.get("tool_calls")
    if not isinstance(calls, list) or not calls:
        raise PlannerError("模型没有给出任何工具调用")
    if len(calls) > MAX_TOOL_CALLS:
        raise PlannerError(f"工具调用超过上限 {MAX_TOOL_CALLS}")

    plan: list[tuple[str, dict[str, Any]]] = []
    for item in calls:
        name = str(item.get("tool") or item.get("name") or "").strip()
        if name not in TOOL_SPECS:
            raise PlannerError(f"未知工具：{name}")
        if allow is not None and name not in allow:
            raise PlannerError(f"工具 {name} 不在本次允许范围内")
        raw_args = item.get("arguments") or {}
        if isinstance(raw_args, str):
            try:
                raw_args = json.loads(raw_args)
            except json.JSONDecodeError as exc:
                raise PlannerError(f"{name} 的参数不是合法 JSON") from exc
        if not isinstance(raw_args, dict):
            raise PlannerError(f"{name} 的参数必须是对象")
        plan.append((name, _validate_arguments(TOOL_SPECS[name], raw_args)))
    return plan


def execute_plan(
    session: Session,
    save_id: int,
    plan: list[tuple[str, dict[str, Any]]],
    *,
    mode: str = "llm",
) -> PlanResult:
    """按计划执行确定性工具，记录每一步轨迹。"""
    calls: list[ToolCall] = []
    trace: list[dict[str, object]] = []
    for name, arguments in plan:
        spec = TOOL_SPECS[name]
        try:
            call = spec["execute"](session, save_id, arguments)
        except Exception as exc:  # noqa: BLE001 - 工具失败要记录而不是伪造结果
            log.warning("tool %s failed: %s", name, exc)
            trace.append({"tool": name, "arguments": arguments, "status": "error", "error": str(exc)})
            continue
        calls.append(call)
        trace.append(
            {
                "tool": name,
                "arguments": arguments,
                "status": "ok",
                "summary": call.payload().get("result_summary"),
            }
        )
    if not calls:
        raise PlannerError("所有工具都执行失败，不能生成回答")
    return PlanResult(calls=calls, trace=trace, mode=mode)


def chat_completion(messages: list[dict[str, str]], *, timeout: float = 20.0) -> dict[str, Any]:
    """调用 OpenAI 兼容的 chat/completions。未配置 Key 时抛 :class:`LlmUnavailable`。"""
    if not llm_enabled():
        raise LlmUnavailable("未配置 agent_llm_api_key 或 agent_llm_enabled=false")

    import httpx

    url = settings.agent_llm_base_url.rstrip("/") + "/v1/chat/completions"
    payload = {
        "model": settings.agent_llm_model,
        "messages": messages,
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    try:
        response = httpx.post(
            url,
            json=payload,
            timeout=timeout,
            headers={"Authorization": f"Bearer {settings.agent_llm_api_key}"},
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:  # noqa: BLE001 - 网络/配额问题都要降级
        raise LlmUnavailable(f"LLM 调用失败：{exc}") from exc


def plan_with_llm(session: Session, save_id: int, question: str, *, client: Callable[[list[dict[str, str]]], dict[str, Any]] | None = None) -> PlanResult:
    """用 LLM 规划并执行；失败时抛 :class:`LlmUnavailable` 让调用方降级。"""
    tools_doc = [
        {"name": name, "description": spec["description"], "parameters": spec["parameters"]}
        for name, spec in TOOL_SPECS.items()
    ]
    system = (
        "你是 ScoutMind 的规划器。只输出 JSON：{\"tool_calls\":[{\"tool\":名称,\"arguments\":{}}]}。"
        f"最多 {MAX_TOOL_CALLS} 个调用；只能使用给定工具；不要编造球员数据；不要指定 save_id。"
        f"可用工具：{json.dumps(tools_doc, ensure_ascii=False)}"
    )
    call = client or (lambda messages: chat_completion(messages))
    response = call(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": question},
        ]
    )
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LlmUnavailable("LLM 返回结构不符合预期") from exc
    try:
        payload = json.loads(content)
    except (TypeError, json.JSONDecodeError) as exc:
        raise PlannerError("LLM 没有返回合法 JSON 计划") from exc
    plan = parse_plan(payload)
    return execute_plan(session, save_id, plan, mode="llm")


def explain_with_llm(question: str, calls: list[ToolCall], *, client: Callable[[list[dict[str, str]]], dict[str, Any]] | None = None) -> str | None:
    """让 LLM 基于工具结果写一段解释；结果里不能出现工具未提供的数字。

    这里做一次"数字校验"：解释文本里出现的金额/评分必须能在工具结果里找到同名数值，
    否则丢弃解释，返回 None（调用方保留确定性结论）。
    """
    if not calls:
        return None
    call = client or (lambda messages: chat_completion(messages))
    facts = [call.payload() for call in calls]
    try:
        response = call(
            [
                {
                    "role": "system",
                    "content": "只根据给定工具结果写 3 句以内中文说明，不要新增任何数字，不要编造球员。",
                },
                {"role": "user", "content": json.dumps({"question": question, "facts": facts}, ensure_ascii=False, default=str)},
            ]
        )
        text = response["choices"][0]["message"]["content"]
    except Exception:  # noqa: BLE001 - 解释失败不影响确定性结论
        return None
    if not isinstance(text, str) or not text.strip():
        return None
    allowed = json.dumps(facts, ensure_ascii=False, default=str)
    import re

    for number in re.findall(r"\d[\d,\.]*", text):
        normalized = number.replace(",", "")
        if normalized not in allowed and normalized.rstrip("0").rstrip(".") not in allowed:
            return None
    return text.strip()
