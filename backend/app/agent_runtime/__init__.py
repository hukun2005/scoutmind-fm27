"""V3.3.3-01 LangGraph Agent Runtime。

Runtime 只负责编排：工具仍由 :mod:`app.agents.tools` 执行，数字与结论仍来自确定性工具；
模型只产出「调用哪些工具、参数是什么」，永远不接触 ``save_id / user_id / thread_id``。
"""

from __future__ import annotations

from .exceptions import (
    AgentRuntimeError,
    ApprovalConsumed,
    ApprovalExpired,
    ApprovalInvalid,
    CheckpointUnsupported,
    LimitExceeded,
    PlanInvalid,
    RuntimeUnavailable,
    ScopeViolation,
    TaskConflict,
    TaskNotFound,
    ToolFailed,
)
from .runtime import RUNTIME_VERSION, AgentRuntime, get_runtime

__all__ = [
    "AgentRuntime",
    "AgentRuntimeError",
    "ApprovalConsumed",
    "ApprovalExpired",
    "ApprovalInvalid",
    "CheckpointUnsupported",
    "LimitExceeded",
    "PlanInvalid",
    "RUNTIME_VERSION",
    "RuntimeUnavailable",
    "ScopeViolation",
    "TaskConflict",
    "TaskNotFound",
    "ToolFailed",
    "get_runtime",
]
