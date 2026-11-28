"""ToolAdapter：把既有 27 个确定性工具接入 Runtime，不重写任何业务逻辑。

职责：
* 暴露工具文档给 Provider（模型只看文档，不碰数据库）。
* 复用 ``llm_planner`` 的严格参数校验与作用域校验；越权参数/跨存档实体直接拒绝。
* 写操作（当前为 ``record_negotiation``）必须经过人工确认，且在同一任务内幂等。
"""

from __future__ import annotations

import json
import time
from typing import Any

from sqlalchemy.orm import Session

from ..agents import llm_planner
from ..agents.tools import ToolCall
from .exceptions import PlanInvalid, ScopeViolation, ToolFailed

#: 会产生持久化副作用的工具：必须先确认，且同一任务内只执行一次。
WRITE_TOOLS = frozenset({"record_negotiation"})


class ToolAdapter:
    """Runtime 与业务工具之间的唯一通道。"""

    def __init__(self, *, max_tool_calls: int | None = None) -> None:
        from ..config import settings

        self.max_tool_calls = int(max_tool_calls or settings.agent_max_tool_calls)

    # -- 文档与校验 ---------------------------------------------------------------------------
    def tool_docs(self) -> list[dict[str, Any]]:
        """给 Provider 的工具清单；不包含任何可执行对象。"""
        return [
            {"name": name, "description": spec["description"], "parameters": spec["parameters"]}
            for name, spec in llm_planner.TOOL_SPECS.items()
        ]

    def known(self, name: str) -> bool:
        return name in llm_planner.TOOL_SPECS

    def requires_approval(self, name: str) -> bool:
        return name in WRITE_TOOLS

    def describe(self, name: str) -> dict[str, Any]:
        """工具声明：只读性、副作用、确认、存档依赖、超时与幂等策略。"""
        from ..config import settings

        if not self.known(name):
            raise PlanInvalid(f"未知工具：{name}")
        write = name in WRITE_TOOLS
        return {
            "name": name,
            "description": llm_planner.TOOL_SPECS[name]["description"],
            "parameters": llm_planner.TOOL_SPECS[name]["parameters"],
            "read_only": not write,
            "side_effect": write,
            "requires_approval": write,
            "depends_on_save": True,
            "timeout_seconds": int(settings.agent_tool_timeout_seconds),
            "idempotency": "task-payload-hash" if write else "none",
            "permission": "active_save_member",
        }

    def validate(self, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
        """严格校验工具名与参数；错误统一为 :class:`PlanInvalid`。"""
        if not self.known(name):
            raise PlanInvalid(f"未知工具：{name}")
        raw = arguments or {}
        if not isinstance(raw, dict):
            raise PlanInvalid(f"{name} 的参数必须是对象")
        try:
            return llm_planner.validate_tool_arguments(llm_planner.TOOL_SPECS[name], raw)
        except llm_planner.PlannerError as exc:
            raise PlanInvalid(str(exc), details={"tool": name}) from exc

    def assert_plan_size(self, plan: list[dict[str, Any]]) -> None:
        if len(plan) > self.max_tool_calls:
            raise PlanInvalid(f"工具调用超过上限 {self.max_tool_calls}")

    def fingerprint(self, name: str, arguments: dict[str, Any]) -> str:
        """同一（工具, 参数）的稳定指纹：用于写操作幂等。"""
        canonical = json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        return f"{name}:{canonical}"

    # -- 执行 ---------------------------------------------------------------------------------
    def execute(
        self,
        session: Session,
        save_id: int,
        name: str,
        arguments: dict[str, Any],
        *,
        cache: dict[str, ToolCall] | None = None,
    ) -> tuple[ToolCall, bool]:
        """执行一个工具，返回 ``(call, reused)``。

        写工具在 ``cache`` 中已有同一指纹时直接复用，避免 resume 或重复确认造成双写；
        只读工具不缓存，避免掩盖真实的数据变化。
        """
        cleaned = self.validate(name, arguments)
        key = self.fingerprint(name, cleaned)
        if cache is not None and name in WRITE_TOOLS and key in cache:
            return cache[key], True
        try:
            llm_planner.assert_tool_scope(session, save_id, cleaned)
        except llm_planner.PlannerError as exc:
            raise ScopeViolation(str(exc), details={"tool": name}) from exc

        started = time.monotonic()
        try:
            call = llm_planner.TOOL_SPECS[name]["execute"](session, save_id, cleaned)
        except Exception as exc:  # noqa: BLE001 - 工具失败要记录而不是伪造结果
            raise ToolFailed(
                f"{name} 执行失败：{exc}",
                details={"tool": name, "elapsed_ms": int((time.monotonic() - started) * 1000)},
            ) from exc
        if cache is not None and name in WRITE_TOOLS:
            cache[key] = call
        return call, False
