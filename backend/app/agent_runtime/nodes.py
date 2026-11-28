"""Graph 节点实现：只做编排，所有数字来自确定性工具。

每个节点自行打开/关闭数据库 Session，避免把连接放进可持久化的 State；
写操作在节点内提交，LangGraph 只负责状态与 Checkpoint。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from sqlalchemy.orm import Session

from ..agents import planner, service as agent_service
from ..agents.tools import ToolCall
from ..models import AgentTask, AiReport, AgentMessage
from ..utils import iso, utcnow
from .approval import ApprovalService, current_generation
from .events import TaskEventBus
from .exceptions import ApprovalConsumed, ApprovalInvalid, PlanInvalid, ScopeViolation, ToolFailed
from .model_provider import ModelProvider, ProviderUnavailable, RuleProvider
from .state import (
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_RUNNING,
    STATUS_WAITING_APPROVAL,
    AgentTaskState,
    Limits,
)
from .tool_adapter import ToolAdapter

log = logging.getLogger("scoutmind.agent.runtime")


@dataclass
class NodeContext:
    """节点依赖：全部可注入，便于测试使用内存库与 Mock Provider。"""

    session_factory: Callable[[], Session]
    adapter: ToolAdapter
    provider: ModelProvider
    rule_provider: RuleProvider
    events: TaskEventBus
    approvals: ApprovalService
    limits: Limits
    clock: Callable[[], datetime] = utcnow


class AgentNodes:
    """把 State 转换成一串确定性的节点函数。"""

    def __init__(self, context: NodeContext) -> None:
        self.ctx = context
        self._write_cache: dict[str, dict[str, ToolCall]] = {}
        self._lock = threading.Lock()

    # -- 节点：校验 -----------------------------------------------------------------------------
    def validate_scope(self, state: AgentTaskState) -> dict[str, Any]:
        session = self.ctx.session_factory()
        try:
            task = session.get(AgentTask, state.get("task_id") or "")
            if task is None or task.user_id != state.get("user_id") or task.fm_save_id != state.get("save_id"):
                return {"execution_status": STATUS_FAILED, "error": {"code": "AGENT_TASK_NOT_FOUND", "message": "任务不存在"}}
            generation = current_generation(session, task.fm_save_id)
            if task.save_generation is not None and generation is not None and int(task.save_generation) != generation:
                self._emit(
                    session,
                    task.id,
                    "task_failed",
                    {"code": "AGENT_SCOPE_VIOLATION", "message": "存档已切换，任务失效"},
                )
                return {
                    "execution_status": STATUS_FAILED,
                    "error": {"code": "AGENT_SCOPE_VIOLATION", "message": "存档已切换，任务失效"},
                }
            task.status = STATUS_RUNNING
            if task.started_at is None:
                task.started_at = utcnow()
            task.current_step = "校验任务范围"
            session.commit()
            self._emit(session, task.id, "task_started", {"task_type": state.get("task_type"), "goal": state.get("user_goal")})
            deadline = time.time() + float(self.ctx.limits.task_timeout_seconds)
            return {
                "execution_status": STATUS_RUNNING,
                "current_step": "校验任务范围",
                "deadline_epoch": deadline,
                "updated_at": iso(utcnow()),
            }
        finally:
            session.close()

    # -- 节点：分类 -----------------------------------------------------------------------------
    def classify(self, state: AgentTaskState) -> dict[str, Any]:
        goal = str(state.get("user_goal") or "").strip()
        if not goal:
            return {"execution_status": STATUS_FAILED, "error": {"code": "AGENT_PLAN_INVALID", "message": "任务目标为空"}}
        intent = planner.parse(goal)
        task_type = str(state.get("task_type") or "general")
        if task_type in {"", "general", "auto"}:
            task_type = intent.kind
        from .state import TASK_TYPES

        if task_type not in TASK_TYPES:
            return {
                "execution_status": STATUS_FAILED,
                "error": {"code": "AGENT_PLAN_INVALID", "message": f"未知任务类型：{task_type}"},
            }
        return {
            "task_type": task_type,
            "intent": {
                "kind": intent.kind,
                "position_group": intent.position_group,
                "slot": intent.slot,
                "min_age": intent.min_age,
                "max_age": intent.max_age,
                "instance_id": intent.instance_id,
                "club_id": intent.club_id,
                "transfer_id": intent.transfer_id,
                "budget": intent.budget,
            },
            "current_step": "识别任务类型",
        }

    # -- 节点：规划 -----------------------------------------------------------------------------
    def plan(self, state: AgentTaskState) -> dict[str, Any]:
        goal = str(state.get("user_goal") or "")
        context: dict[str, Any] = {}
        intent = state.get("intent") or {}
        if not intent.get("instance_id") and intent.get("kind") in {"valuation", "similar", "deal", "growth", "compare", "transfer_history"}:
            session = self.ctx.session_factory()
            try:
                resolved = agent_service.resolve_player_instance(session, int(state["save_id"]), goal)
            finally:
                session.close()
            if resolved:
                context["instance_id"] = resolved
                intent["instance_id"] = resolved
        if intent.get("club_id"):
            context["club_id"] = intent["club_id"]
        if intent.get("transfer_id"):
            context["transfer_id"] = intent["transfer_id"]

        reply = None
        degraded: str | None = None
        provider = self.ctx.provider
        if provider.supports_tool_calling:
            try:
                reply = provider.plan(
                    question=goal,
                    tools=self.ctx.adapter.tool_docs(),
                    timeout=self.ctx.limits.model_timeout_seconds,
                    context=context,
                )
            except ProviderUnavailable as exc:
                degraded = str(exc)
                log.warning("provider 不可用，降级为规则规划：%s", exc)
        if reply is None:
            reply = self.ctx.rule_provider.plan(
                question=goal,
                tools=self.ctx.adapter.tool_docs(),
                timeout=self.ctx.limits.model_timeout_seconds,
                context={**context, "fallback_reason": degraded},
            )

        plan: list[dict[str, Any]] = []
        for index, spec in enumerate(reply.tool_calls):
            tool = spec.tool
            plan.append(
                {
                    "step_id": f"{index}:{tool}",
                    "tool": tool,
                    "arguments": dict(spec.arguments or {}),
                    "reason": spec.reason or "",
                    "status": "pending",
                    "requires_approval": self.ctx.adapter.requires_approval(tool),
                }
            )
        pending = [step["step_id"] for step in plan]
        session = self.ctx.session_factory()
        try:
            self._emit(
                session,
                str(state["task_id"]),
                "plan_created",
                {
                    "provider_id": reply.provider_id,
                    "mode": reply.mode,
                    "degraded_reason": reply.degraded_reason,
                    "steps": [{"tool": step["tool"], "reason": step["reason"]} for step in plan],
                },
            )
        finally:
            session.close()
        return {
            "execution_plan": plan,
            "pending_steps": pending,
            "completed_steps": list(state.get("completed_steps") or []),
            "tool_results": list(state.get("tool_results") or []),
            "current_step": "生成执行计划",
            "analysis_results": {
                **dict(state.get("analysis_results") or {}),
                "provider_id": reply.provider_id,
                "model_id": reply.model_id,
                "mode": reply.mode,
                "degraded_reason": reply.degraded_reason or degraded,
                "usage": reply.usage,
            },
            "execution_status": STATUS_RUNNING,
        }

    # -- 节点：校验计划 -------------------------------------------------------------------------
    def validate_plan(self, state: AgentTaskState) -> dict[str, Any]:
        plan = list(state.get("execution_plan") or [])
        if not plan:
            return {"execution_status": STATUS_FAILED, "error": {"code": "AGENT_PLAN_INVALID", "message": "没有可执行的计划"}}
        try:
            self.ctx.adapter.assert_plan_size(plan)
            for step in plan:
                self.ctx.adapter.validate(step.get("tool") or "", step.get("arguments") or {})
        except (PlanInvalid, ScopeViolation) as exc:
            return {"execution_status": STATUS_FAILED, "error": exc.as_error()}
        if len(plan) > self.ctx.limits.max_steps:
            return {
                "execution_status": STATUS_FAILED,
                "error": {"code": "AGENT_LIMIT_EXCEEDED", "message": f"计划步数超过上限 {self.ctx.limits.max_steps}"},
            }
        return {"current_step": "校验执行计划"}

    # -- 节点：执行一步 -------------------------------------------------------------------------
    def execute_step(self, state: AgentTaskState) -> dict[str, Any]:
        if self._timed_out(state):
            return self._fail(state, "AGENT_TASK_TIMEOUT", "任务超过时间上限，已停止")
        pending = list(state.get("pending_steps") or [])
        if not pending:
            return {"execution_status": STATUS_RUNNING}
        plan = list(state.get("execution_plan") or [])
        step_id = pending[0]
        step = next((item for item in plan if item.get("step_id") == step_id), None)
        if step is None:
            return self._fail(state, "AGENT_PLAN_INVALID", "计划与待执行步骤不一致")

        session = self.ctx.session_factory()
        try:
            task = session.get(AgentTask, str(state["task_id"]))
            if task is None:
                return self._fail(state, "AGENT_TASK_NOT_FOUND", "任务不存在")
            if task.cancel_requested:
                self._emit(session, task.id, "task_cancelled", {"reason": "用户取消"})
                return {"execution_status": STATUS_CANCELLED, "error": {"code": "AGENT_TASK_CANCELLED", "message": "任务已取消"}}
            self._emit(session, task.id, "step_started", {"step_id": step_id, "tool": step["tool"], "reason": step.get("reason")})
            self._emit(session, task.id, "tool_started", {"tool": step["tool"]})
            try:
                call, reused = self.ctx.adapter.execute(
                    session,
                    int(state["save_id"]),
                    step["tool"],
                    dict(step.get("arguments") or {}),
                    cache=self._cache_for(str(state["task_id"])),
                )
            except (ToolFailed, PlanInvalid, ScopeViolation) as exc:
                step["status"] = "error"
                step["error"] = exc.as_error()
                self._emit(
                    session,
                    task.id,
                    "tool_completed",
                    {"tool": step["tool"], "status": "error", "code": exc.code, "message": str(exc)},
                )
                return self._advance(
                    state,
                    plan,
                    step,
                    result={"tool": step["tool"], "arguments": step.get("arguments") or {}, "status": "error", "error": exc.as_error()},
                    call=None,
                )
            payload = call.payload()
            step["status"] = "done"
            self._emit(
                session,
                task.id,
                "tool_completed",
                {"tool": step["tool"], "status": "ok", "summary": payload.get("result_summary"), "reused": reused},
            )
            return self._advance(
                state,
                plan,
                step,
                result={
                    "tool": call.name,
                    "arguments": payload.get("arguments") or {},
                    "summary": payload.get("result_summary"),
                    "warnings": payload.get("warnings") or [],
                    "result": payload.get("result"),
                    "status": "ok",
                },
                call=call,
            )
        finally:
            session.close()

    # -- 节点：复核 -----------------------------------------------------------------------------
    def review_results(self, state: AgentTaskState) -> dict[str, Any]:
        if state.get("error"):
            return {"execution_status": STATUS_FAILED}
        if self._timed_out(state):
            return self._fail(state, "AGENT_TASK_TIMEOUT", "任务超过时间上限，已停止")
        session = self.ctx.session_factory()
        try:
            task = session.get(AgentTask, str(state["task_id"]))
            if task is not None and task.cancel_requested:
                self._emit(session, task.id, "task_cancelled", {"reason": "用户取消"})
                return {"execution_status": STATUS_CANCELLED, "error": {"code": "AGENT_TASK_CANCELLED", "message": "任务已取消"}}
        finally:
            session.close()

        plan = list(state.get("execution_plan") or [])
        pending = list(state.get("pending_steps") or [])
        results = list(state.get("tool_results") or [])
        successes = [item for item in results if item.get("status") == "ok"]
        if not pending:
            if not successes:
                if results and all(item.get("status") == "skipped" for item in results):
                    return {
                        "execution_status": STATUS_CANCELLED,
                        "error": {"code": "AGENT_APPROVAL_REJECTED", "message": "写操作被拒绝，任务已安全结束"},
                    }
                return self._fail(state, "AGENT_TOOL_FAILED", "所有工具都执行失败，不能生成回答")
            return {"execution_status": STATUS_RUNNING}
        next_step = next((item for item in plan if item.get("step_id") == pending[0]), None)
        if next_step is None:
            return self._fail(state, "AGENT_PLAN_INVALID", "计划与待执行步骤不一致")
        if next_step.get("requires_approval") and not next_step.get("approved"):
            return {"execution_status": STATUS_WAITING_APPROVAL}
        if int(state.get("step_count") or 0) >= self.ctx.limits.max_steps:
            return self._fail(state, "AGENT_LIMIT_EXCEEDED", f"超过步数上限 {self.ctx.limits.max_steps}")
        if int(state.get("tool_call_count") or 0) >= self.ctx.limits.max_tool_calls:
            if successes:
                return {"execution_status": STATUS_RUNNING, "analysis_results": {**dict(state.get("analysis_results") or {}), "truncated": True}}
            return self._fail(state, "AGENT_LIMIT_EXCEEDED", f"超过工具调用上限 {self.ctx.limits.max_tool_calls}")
        return {"execution_status": STATUS_RUNNING}

    # -- 节点：请求确认 -------------------------------------------------------------------------
    def request_approval(self, state: AgentTaskState) -> dict[str, Any]:
        pending = list(state.get("pending_steps") or [])
        plan = list(state.get("execution_plan") or [])
        step_id = pending[0]
        step = next((item for item in plan if item.get("step_id") == step_id), None)
        if step is None:
            return self._fail(state, "AGENT_PLAN_INVALID", "计划与待执行步骤不一致")

        session = self.ctx.session_factory()
        try:
            task = session.get(AgentTask, str(state["task_id"]))
            if task is None:
                return self._fail(state, "AGENT_TASK_NOT_FOUND", "任务不存在")
            approval = self.ctx.approvals.ensure_pending(
                session,
                task,
                operation_type=str(step["tool"]),
                payload={"step_id": step_id, "tool": step["tool"], "arguments": step.get("arguments") or {}},
                reason=str(step.get("reason") or "该操作会写入持久化记录，需要你确认"),
            )
            task.status = STATUS_WAITING_APPROVAL
            task.current_step = f"等待确认：{step['tool']}"
            session.commit()
            self._emit(
                session,
                task.id,
                "approval_required",
                {
                    "approval_id": approval.id,
                    "operation_type": approval.operation_type,
                    "reason": approval.reason,
                    "expires_at": iso(approval.expires_at),
                },
            )
            self._emit(session, task.id, "task_paused", {"approval_id": approval.id})
            payload_for_ui = {
                "approval_id": approval.id,
                "operation_type": approval.operation_type,
                "reason": approval.reason,
                "expires_at": iso(approval.expires_at),
            }
        finally:
            session.close()

        # LangGraph 在此挂起；恢复时返回用户决策（{"decision": "approve"|"reject"}）。
        from langgraph.types import interrupt

        decision = interrupt(payload_for_ui)
        choice = str((decision or {}).get("decision") if isinstance(decision, dict) else decision or "").strip()
        approvals = list(state.get("approval_requests") or [])

        session = self.ctx.session_factory()
        try:
            task = session.get(AgentTask, str(state["task_id"]))
            if task is not None:
                task.status = STATUS_RUNNING
                session.commit()
                self._emit(session, task.id, "task_resumed", {"approval_id": payload_for_ui["approval_id"], "decision": choice or "reject"})
        finally:
            session.close()

        if choice == "approve":
            step["approved"] = True
            approvals.append({"approval_id": payload_for_ui["approval_id"], "step_id": step_id})
            approved_actions = list(state.get("approved_actions") or [])
            approved_actions.append({"approval_id": payload_for_ui["approval_id"], "step_id": step_id})
            return {
                "execution_status": STATUS_RUNNING,
                "execution_plan": plan,
                "approval_requests": approvals,
                "approved_actions": approved_actions,
                "current_step": f"已确认：{step['tool']}",
            }

        step["status"] = "skipped"
        return self._advance(
            state,
            plan,
            step,
            result={"tool": step["tool"], "arguments": step.get("arguments") or {}, "status": "skipped", "reason": "用户拒绝"},
            call=None,
            status=STATUS_RUNNING,
        )

    # -- 节点：执行已确认的副作用 ---------------------------------------------------------------
    def apply_approved(self, state: AgentTaskState) -> dict[str, Any]:
        pending = list(state.get("pending_steps") or [])
        if not pending:
            return {"execution_status": STATUS_RUNNING}
        plan = list(state.get("execution_plan") or [])
        step_id = pending[0]
        step = next((item for item in plan if item.get("step_id") == step_id), None)
        if step is None:
            return self._fail(state, "AGENT_PLAN_INVALID", "计划与待执行步骤不一致")
        approved = list(state.get("approved_actions") or [])
        approval_id = approved[-1]["approval_id"] if approved else ""
        if step.get("executed_approval") == approval_id:
            return {"execution_status": STATUS_RUNNING}

        session = self.ctx.session_factory()
        try:
            task = session.get(AgentTask, str(state["task_id"]))
            if task is None:
                return self._fail(state, "AGENT_TASK_NOT_FOUND", "任务不存在")
            try:
                record = self.ctx.approvals.get(session, task, approval_id)
                if record.status == "consumed":
                    # 崩溃恢复：确认单已消费说明副作用可能已执行，绝不再写一次。
                    step["status"] = "done"
                    step["executed_approval"] = approval_id
                    self._emit(session, task.id, "tool_completed", {"tool": step["tool"], "status": "ok", "reused": True})
                    return self._advance(
                        state,
                        plan,
                        step,
                        result={
                            "tool": step["tool"],
                            "arguments": step.get("arguments") or {},
                            "summary": "恢复：确认单已消费，跳过重复写入",
                            "status": "ok",
                        },
                        call=None,
                    )
                self.ctx.approvals.consume(session, record)
            except (ApprovalInvalid, ApprovalConsumed) as exc:
                return self._fail(state, exc.code, str(exc))
            try:
                call, reused = self.ctx.adapter.execute(
                    session,
                    int(state["save_id"]),
                    step["tool"],
                    dict(step.get("arguments") or {}),
                    cache=self._cache_for(str(state["task_id"])),
                )
            except (ToolFailed, PlanInvalid, ScopeViolation) as exc:
                step["status"] = "error"
                self._emit(session, task.id, "tool_completed", {"tool": step["tool"], "status": "error", "code": exc.code})
                return self._advance(
                    state,
                    plan,
                    step,
                    result={"tool": step["tool"], "arguments": step.get("arguments") or {}, "status": "error", "error": exc.as_error()},
                    call=None,
                )
            payload = call.payload()
            step["status"] = "done"
            step["executed_approval"] = approval_id
            self._emit(session, task.id, "tool_completed", {"tool": step["tool"], "status": "ok", "summary": payload.get("result_summary"), "reused": reused})
            return self._advance(
                state,
                plan,
                step,
                result={
                    "tool": call.name,
                    "arguments": payload.get("arguments") or {},
                    "summary": payload.get("result_summary"),
                    "warnings": payload.get("warnings") or [],
                    "result": payload.get("result"),
                    "status": "ok",
                },
                call=call,
            )
        finally:
            session.close()

    # -- 节点：生成报告 -------------------------------------------------------------------------
    def finalize_report(self, state: AgentTaskState) -> dict[str, Any]:
        results = [item for item in (state.get("tool_results") or []) if item.get("status") == "ok"]
        calls = [
            ToolCall(
                name=str(item.get("tool")),
                arguments=dict(item.get("arguments") or {}),
                result=dict(item.get("result") or {}),
                summary=str(item.get("summary") or ""),
                warnings=list(item.get("warnings") or []),
            )
            for item in results
        ]
        if not calls:
            return self._fail(state, "AGENT_TOOL_FAILED", "没有可用的工具结果，无法生成报告")
        analysis = dict(state.get("analysis_results") or {})
        mode = "llm-planned" if analysis.get("mode") == "llm-planned" else "deterministic"

        session = self.ctx.session_factory()
        try:
            report = agent_service.compose_tool_answer(
                session,
                int(state["save_id"]),
                str(state.get("user_goal") or ""),
                calls,
                mode=mode,
                fallback_reason=analysis.get("degraded_reason"),
            )
            report["task"] = {
                "task_type": state.get("task_type"),
                "provider_id": analysis.get("provider_id"),
                "model_id": analysis.get("model_id"),
                "step_count": state.get("step_count"),
                "tool_call_count": state.get("tool_call_count"),
                "truncated": bool(analysis.get("truncated")),
            }
            task = session.get(AgentTask, str(state["task_id"]))
            if task is not None:
                task.status = STATUS_COMPLETED
                task.current_step = "生成报告"
                session.add(
                    AiReport(
                        fm_save_id=task.fm_save_id,
                        conversation_id=task.conversation_id,
                        question=task.user_goal,
                        answer=str(report.get("conclusion") or ""),
                        reliability_json=json.dumps(report.get("reliability") or {}, ensure_ascii=False, default=str),
                        citations_json=json.dumps(report.get("citations") or [], ensure_ascii=False, default=str),
                        tool_calls_json=json.dumps([call.payload() for call in calls], ensure_ascii=False, default=str),
                    )
                )
                if task.conversation_id:
                    session.add(
                        AgentMessage(
                            conversation_id=task.conversation_id,
                            role="assistant",
                            content=str(report.get("conclusion") or ""),
                            answer_json=json.dumps(report, ensure_ascii=False, default=str),
                            tool_calls_json=json.dumps([call.payload() for call in calls], ensure_ascii=False, default=str),
                        )
                    )
                session.commit()
                self._emit(
                    session,
                    task.id,
                    "task_completed",
                    {
                        "mode": mode,
                        "steps": len(results),
                        "conclusion": str(report.get("conclusion") or "")[:300],
                    },
                )
            return {
                "execution_status": STATUS_COMPLETED,
                "final_report": report,
                "current_step": "生成报告",
                "updated_at": iso(utcnow()),
            }
        finally:
            session.close()

    # -- 节点：失败 -----------------------------------------------------------------------------
    def fail(self, state: AgentTaskState) -> dict[str, Any]:
        error = state.get("error") or {"code": "AGENT_RUNTIME_ERROR", "message": "任务失败"}
        session = self.ctx.session_factory()
        try:
            task = session.get(AgentTask, str(state.get("task_id") or ""))
            if task is not None:
                task.status = STATUS_FAILED
                task.error_code = str(error.get("code"))[:64]
                task.error_summary = str(error.get("message"))[:1000]
                session.commit()
                self._emit(session, task.id, "task_failed", error)
        finally:
            session.close()
        return {"execution_status": STATUS_FAILED, "error": error}

    # -- 条件边 ---------------------------------------------------------------------------------
    def route_after_scope(self, state: AgentTaskState) -> str:
        return "fail" if state.get("execution_status") == STATUS_FAILED else "classify"

    def route_after_plan(self, state: AgentTaskState) -> str:
        return "fail" if state.get("execution_status") == STATUS_FAILED else "validate_plan"

    def route_after_validate_plan(self, state: AgentTaskState) -> str:
        return "fail" if state.get("execution_status") == STATUS_FAILED else "review_results"

    def route_after_review(self, state: AgentTaskState) -> str:
        status = state.get("execution_status")
        if status == STATUS_FAILED:
            return "fail"
        if status == STATUS_CANCELLED:
            return "cancelled"
        pending = list(state.get("pending_steps") or [])
        if not pending:
            return "report_ready"
        plan = list(state.get("execution_plan") or [])
        next_step = next((item for item in plan if item.get("step_id") == pending[0]), None)
        if next_step is not None and next_step.get("requires_approval") and not next_step.get("approved"):
            return "approval_required"
        return "continue"

    def route_after_approval(self, state: AgentTaskState) -> str:
        if state.get("execution_status") == STATUS_FAILED:
            return "fail"
        pending = list(state.get("pending_steps") or [])
        plan = list(state.get("execution_plan") or [])
        next_step = next((item for item in plan if item.get("step_id") == (pending[0] if pending else "")), None)
        if next_step is not None and next_step.get("approved") and next_step.get("status") == "pending":
            return "apply_approved"
        return "continue"

    # -- 内部工具 -------------------------------------------------------------------------------
    def _advance(
        self,
        state: AgentTaskState,
        plan: list[dict[str, Any]],
        step: dict[str, Any],
        *,
        result: dict[str, Any],
        call: ToolCall | None,
        status: str = STATUS_RUNNING,
    ) -> dict[str, Any]:
        pending = [item for item in (state.get("pending_steps") or []) if item != step["step_id"]]
        completed = list(state.get("completed_steps") or [])
        completed.append(step["step_id"])
        results = list(state.get("tool_results") or [])
        results.append(result)
        step_count = int(state.get("step_count") or 0) + 1
        tool_call_count = int(state.get("tool_call_count") or 0) + (1 if call is not None else 0)
        analysis = dict(state.get("analysis_results") or {})
        if call is not None:
            analysis["last_tool"] = call.name
        return {
            "execution_plan": plan,
            "pending_steps": pending,
            "completed_steps": completed,
            "tool_results": results,
            "approved_actions": list(state.get("approved_actions") or []),
            "step_count": step_count,
            "tool_call_count": tool_call_count,
            "analysis_results": analysis,
            "execution_status": status,
            "current_step": f"执行 {step['tool']}",
            "updated_at": iso(utcnow()),
        }

    def _fail(self, state: AgentTaskState, code: str, message: str) -> dict[str, Any]:
        return {
            "execution_status": STATUS_FAILED,
            "error": {"code": code, "message": message},
            "updated_at": iso(utcnow()),
        }

    def _timed_out(self, state: AgentTaskState) -> bool:
        deadline = state.get("deadline_epoch")
        try:
            return bool(deadline) and time.time() > float(deadline)
        except (TypeError, ValueError):
            return False

    def _emit(self, session: Session, task_id: str, event_type: str, payload: dict[str, Any] | None = None) -> None:
        self.ctx.events.append(session, task_id, event_type, payload)

    def _cache_for(self, task_id: str) -> dict[str, ToolCall]:
        with self._lock:
            return self._write_cache.setdefault(task_id, {})
