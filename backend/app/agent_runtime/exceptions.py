"""Agent Runtime 的结构化错误。

错误码是稳定契约：前端按 ``code`` 决定提示与可恢复性，日志与审计只记录错误码和用户可读摘要，
不记录 API Key、原始存档或 Traceback。
"""

from __future__ import annotations

from typing import Any


class AgentRuntimeError(Exception):
    """Runtime 基类错误：携带稳定错误码与可安全展示的明细。"""

    code = "AGENT_RUNTIME_ERROR"
    http_status = 500
    retryable = False

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(message)
        if code:
            self.code = code
        self.details = details or {}
        if retryable is not None:
            self.retryable = retryable

    def as_error(self) -> dict[str, Any]:
        """API 与事件流共用的错误结构。"""
        return {
            "code": self.code,
            "message": str(self),
            "details": self.details,
            "retryable": self.retryable,
        }


class ScopeViolation(AgentRuntimeError):
    """任务、存档、用户或代次不匹配。"""

    code = "AGENT_SCOPE_VIOLATION"
    http_status = 403


class PlanInvalid(AgentRuntimeError):
    """模型/规则给出的计划不合法：未知工具、越权参数、超过上限。"""

    code = "AGENT_PLAN_INVALID"
    http_status = 400


class LimitExceeded(AgentRuntimeError):
    """步数、工具调用数或并发数超过硬限制。"""

    code = "AGENT_LIMIT_EXCEEDED"
    http_status = 409


class ToolFailed(AgentRuntimeError):
    """确定性工具执行失败；失败被记录，不伪造结果。"""

    code = "AGENT_TOOL_FAILED"
    http_status = 500


class ApprovalInvalid(AgentRuntimeError):
    """确认单不可用：已决策、已消费、载荷或代次不匹配。"""

    code = "AGENT_APPROVAL_INVALID"
    http_status = 409


class ApprovalExpired(ApprovalInvalid):
    """确认单超过 TTL。"""

    code = "AGENT_APPROVAL_EXPIRED"


class ApprovalConsumed(ApprovalInvalid):
    """确认单已被消费（一次性）。"""

    code = "AGENT_APPROVAL_CONSUMED"


class CheckpointUnsupported(AgentRuntimeError):
    """当前部署方式没有可用的 Checkpoint 后端。"""

    code = "AGENT_CHECKPOINT_UNSUPPORTED"
    http_status = 501


class RuntimeUnavailable(AgentRuntimeError):
    """LangGraph 不可导入或 Runtime 未初始化。"""

    code = "AGENT_RUNTIME_UNAVAILABLE"
    http_status = 503
    retryable = True


class TaskNotFound(AgentRuntimeError):
    """任务不存在或不属于当前用户/存档（不泄露存在性）。"""

    code = "AGENT_TASK_NOT_FOUND"
    http_status = 404


class TaskConflict(AgentRuntimeError):
    """任务状态不允许当前操作（例如已完成任务再次取消）。"""

    code = "AGENT_TASK_CONFLICT"
    http_status = 409
