"""模型 Provider 抽象：OpenAI 兼容 / 规则回退 / 测试 Mock。

约束：
* Provider 只产出计划（工具名 + 参数），不执行工具、不读数据库。
* 无 Key、被关闭或失败时，调用方降级到 :class:`RuleProvider`，并在报告里标注 ``mode=deterministic`` 与原因。
* API Key 只从 settings/环境读取，不出现在 State、事件或日志里。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, runtime_checkable

from ..agents import llm_planner, planner
from ..config import settings
from .exceptions import AgentRuntimeError


class ProviderUnavailable(AgentRuntimeError):
    """Provider 未配置、超时或返回不合法结构：调用方必须降级而不是伪造结果。"""

    code = "AGENT_PROVIDER_UNAVAILABLE"
    http_status = 503
    retryable = True


@dataclass
class ToolCallSpec:
    """计划中的一步：调用哪个工具、参数是什么、为什么。"""

    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"tool": self.tool, "arguments": self.arguments, "reason": self.reason}


@dataclass
class ModelReply:
    """Provider 的规划结果。"""

    tool_calls: list[ToolCallSpec]
    provider_id: str
    model_id: str | None = None
    mode: str = "deterministic"
    usage: dict[str, int] | None = None
    degraded_reason: str | None = None


@runtime_checkable
class ModelProvider(Protocol):
    """规划器协议；实现方不得执行工具。"""

    provider_id: str
    supports_tool_calling: bool
    supports_streaming: bool

    def plan(
        self,
        *,
        question: str,
        tools: list[dict[str, Any]],
        timeout: float,
        context: dict[str, Any] | None = None,
    ) -> ModelReply: ...


class RuleProvider:
    """无 Key 时的确定性规划：把 :func:`app.agents.planner.parse` 的意图映射成工具计划。

    这不是「AI」：``mode`` 明确为 ``deterministic``，报告里也会说明降级原因。
    """

    provider_id = "rule"
    supports_tool_calling = False
    supports_streaming = False
    model_id = None

    def plan(
        self,
        *,
        question: str,
        tools: list[dict[str, Any]],
        timeout: float,
        context: dict[str, Any] | None = None,
    ) -> ModelReply:
        data = context or {}
        intent = planner.parse(
            question,
            instance_id=_as_int(data.get("instance_id")),
            club_id=_as_int(data.get("club_id")),
        )
        specs = _plan_for_intent(intent, data)
        return ModelReply(
            tool_calls=specs,
            provider_id=self.provider_id,
            model_id=None,
            mode="deterministic",
            degraded_reason=data.get("fallback_reason"),
        )


class OpenAICompatibleProvider:
    """OpenAI 兼容 chat/completions 的规划器；模型只输出 JSON 计划。"""

    supports_tool_calling = True
    supports_streaming = False

    def __init__(
        self,
        *,
        chat: Callable[[list[dict[str, str]], float], dict[str, Any]] | None = None,
        provider_id: str | None = None,
        model_id: str | None = None,
    ) -> None:
        self.provider_id = provider_id or settings.agent_llm_provider_id
        self.model_id = model_id or settings.agent_llm_model
        self._chat = chat

    def plan(
        self,
        *,
        question: str,
        tools: list[dict[str, Any]],
        timeout: float,
        context: dict[str, Any] | None = None,
    ) -> ModelReply:
        if not llm_planner.llm_enabled():
            raise ProviderUnavailable("未配置 agent_llm_enabled / agent_llm_api_key")
        chat = self._chat or (lambda messages, seconds: llm_planner.chat_completion(messages, timeout=seconds))
        system = (
            "你是 ScoutMind 的任务规划器。只输出 JSON：{\"tool_calls\":[{\"tool\":名称,\"arguments\":{},\"reason\":\"一句中文\"}]}。"
            f"最多 {settings.agent_max_tool_calls} 个调用；只能使用给定工具；不要编造数据；"
            "绝不要输出 save_id、user_id、thread_id 等作用域参数。"
            f"可用工具：{json.dumps(tools, ensure_ascii=False)}"
        )
        try:
            response = chat(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": question},
                ],
                timeout,
            )
            content = response["choices"][0]["message"]["content"]
            payload = json.loads(content)
        except ProviderUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 - 统一转成可降级的 Provider 错误
            raise ProviderUnavailable(f"模型调用失败：{exc}") from exc

        calls = payload.get("tool_calls") if isinstance(payload, dict) else None
        if not isinstance(calls, list) or not calls:
            raise ProviderUnavailable("模型没有返回任何工具计划")
        specs: list[ToolCallSpec] = []
        for item in calls:
            if not isinstance(item, dict):
                raise ProviderUnavailable("模型计划项不是对象")
            name = str(item.get("tool") or item.get("name") or "").strip()
            args = item.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError as exc:
                    raise ProviderUnavailable(f"{name} 的参数不是合法 JSON") from exc
            if not name or not isinstance(args, dict):
                raise ProviderUnavailable("模型计划缺少工具名或参数对象")
            specs.append(ToolCallSpec(tool=name, arguments=args, reason=str(item.get("reason") or "")))
        usage = response.get("usage") if isinstance(response, dict) else None
        return ModelReply(
            tool_calls=specs,
            provider_id=self.provider_id,
            model_id=self.model_id,
            mode="llm-planned",
            usage={k: int(v) for k, v in usage.items() if isinstance(v, (int, float))} if isinstance(usage, dict) else None,
        )


class MockProvider:
    """仅测试使用：按脚本返回计划；生产入口不会构造它。"""

    provider_id = "mock"
    supports_tool_calling = True
    supports_streaming = False
    model_id = "mock"

    def __init__(self, replies: list[list[dict[str, Any]]]) -> None:
        self._replies = list(replies)
        self.calls: list[str] = []

    def plan(
        self,
        *,
        question: str,
        tools: list[dict[str, Any]],
        timeout: float,
        context: dict[str, Any] | None = None,
    ) -> ModelReply:
        self.calls.append(question)
        if not self._replies:
            raise ProviderUnavailable("MockProvider 脚本已耗尽")
        raw = self._replies.pop(0)
        return ModelReply(
            tool_calls=[ToolCallSpec(tool=str(item["tool"]), arguments=dict(item.get("arguments") or {}), reason=str(item.get("reason") or "")) for item in raw],
            provider_id=self.provider_id,
            model_id=self.model_id,
            mode="mock",
        )


def build_provider() -> ModelProvider:
    """生产入口：有 Key 用 OpenAI 兼容，否则规则回退；绝不返回 Mock。"""
    if llm_planner.llm_enabled():
        return OpenAICompatibleProvider()
    return RuleProvider()


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _plan_for_intent(intent: planner.Intent, context: dict[str, Any]) -> list[ToolCallSpec]:
    """意图 → 工具计划。每个数字仍由工具返回；这里只决定查什么。"""
    kind = intent.kind
    instance_id = intent.instance_id
    if instance_id is None and kind in {"valuation", "similar", "deal", "growth", "compare"}:
        instance_id = _as_int(context.get("instance_id"))

    if kind == "price_stats":
        args: dict[str, Any] = {"position_group": intent.position_group} if intent.position_group else {}
        return [ToolCallSpec("transfer_price_stats", args, "统计同位置历史成交价分位")]
    if kind == "valuation":
        if instance_id:
            calls = [ToolCallSpec("transfer_valuation", {"instance_id": instance_id}, "按可比成交给出估值区间")]
            if intent.budget is not None:
                calls.append(ToolCallSpec("purchase_offers", {"instance_id": instance_id, "budget": intent.budget}, "按预算生成报价方案"))
            return calls
        return [ToolCallSpec("search_players", _search_args(intent), "没有具体球员时先定位候选")]
    if kind == "similar":
        if instance_id:
            return [ToolCallSpec("transfer_valuation", {"instance_id": instance_id}, "用可比成交近似相似交易")]
        return [ToolCallSpec("search_players", _search_args(intent), "先定位可比较的球员")]
    if kind == "club_profile":
        if intent.club_id:
            return [ToolCallSpec("club_transfer_intelligence", {"club_id": intent.club_id}, "汇总俱乐部长期转会策略")]
        return [ToolCallSpec("transfer_strategy_cases", {"limit": 10}, "没有俱乐部时给出策略案例归纳")]
    if kind == "deal":
        if intent.transfer_id:
            return [ToolCallSpec("transfer_roi", {"transfer_id": intent.transfer_id}, "计算这笔交易的收益口径")]
        return [ToolCallSpec("transfer_opportunities", {"limit": 10}, "没有具体交易时列出当前机会")]
    if kind == "squad":
        return [ToolCallSpec("squad_overview", {}, "读取阵容结构概览")]
    if kind == "depth":
        return [ToolCallSpec("position_depth", {}, "读取各位置人数与缺口")]
    if kind == "recruitment":
        args = {"prefer": "balanced"}
        if intent.slot:
            args["slot"] = intent.slot
        if intent.budget is not None:
            args["budget"] = intent.budget
        calls = [ToolCallSpec("recruitment_recommend", args, "按位置与预算推荐引援目标")]
        target_args: dict[str, Any] = {"limit": 10}
        if intent.slot:
            target_args["slot"] = intent.slot
        if intent.budget is not None:
            target_args["max_value"] = intent.budget
        calls.append(ToolCallSpec("transfer_targets", target_args, "补充可操作的引援目标"))
        return calls
    if kind == "growth":
        if instance_id:
            return [
                ToolCallSpec("player_growth", {"instance_id": instance_id}, "读取成长历史"),
                ToolCallSpec("player_forecast", {"instance_id": instance_id}, "给出成长区间与置信度"),
            ]
        return [ToolCallSpec("search_players", {**_search_args(intent), "max_age": 23}, "定位年轻球员的成长样本")]
    if kind == "compare":
        if instance_id:
            return [ToolCallSpec("player_profile", {"instance_id": instance_id}, "读取球员当前画像")]
        return [ToolCallSpec("search_players", _search_args(intent), "定位可比较的球员")]
    if kind == "transfer_history":
        if instance_id:
            return [ToolCallSpec("player_transfer_history", {"instance_id": instance_id, "limit": 20}, "读取球员历史转会")]
        if intent.club_id:
            return [ToolCallSpec("club_transfer_history", {"club_id": intent.club_id}, "读取俱乐部买卖汇总")]
        return [ToolCallSpec("transfer_opportunities", {"type": "contract_expiring", "limit": 10}, "列出合同到期机会")]
    return [ToolCallSpec("search_players", _search_args(intent), "按条件搜索球员")]


def _search_args(intent: planner.Intent) -> dict[str, Any]:
    args: dict[str, Any] = {"limit": 10}
    if intent.position_group:
        args["position_group"] = intent.position_group
    if intent.min_age is not None:
        args["min_age"] = intent.min_age
    if intent.max_age is not None:
        args["max_age"] = intent.max_age
    if intent.min_ca is not None:
        args["min_ca"] = intent.min_ca
    return args
