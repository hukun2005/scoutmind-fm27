"""LangGraph StateGraph 装配。

拓扑：
``START → validate_scope → classify → plan → validate_plan → execute_step → review_results``
``review_results`` 按状态分流到「继续执行 / 请求确认 / 生成报告 / 失败 / 取消」。
"""

from __future__ import annotations

from typing import Any

from .exceptions import RuntimeUnavailable
from .nodes import AgentNodes
from .state import AgentTaskState


def build_graph(nodes: AgentNodes, checkpointer: Any = None):
    """编译 Graph；LangGraph 缺失时抛出 ``RuntimeUnavailable``（旧 Agent 不受影响）。"""
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:  # pragma: no cover - 打包缺失时的兜底
        raise RuntimeUnavailable("LangGraph 未安装，Agent Runtime 不可用") from exc

    builder = StateGraph(AgentTaskState)
    builder.add_node("validate_scope", nodes.validate_scope)
    builder.add_node("classify", nodes.classify)
    builder.add_node("plan", nodes.plan)
    builder.add_node("validate_plan", nodes.validate_plan)
    builder.add_node("execute_step", nodes.execute_step)
    builder.add_node("review_results", nodes.review_results)
    builder.add_node("request_approval", nodes.request_approval)
    builder.add_node("apply_approved", nodes.apply_approved)
    builder.add_node("finalize_report", nodes.finalize_report)
    builder.add_node("fail", nodes.fail)

    builder.add_edge(START, "validate_scope")
    builder.add_conditional_edges(
        "validate_scope", nodes.route_after_scope, {"classify": "classify", "fail": "fail"}
    )
    builder.add_edge("classify", "plan")
    builder.add_conditional_edges("plan", nodes.route_after_plan, {"validate_plan": "validate_plan", "fail": "fail"})
    builder.add_conditional_edges(
        "validate_plan", nodes.route_after_validate_plan, {"review_results": "review_results", "fail": "fail"}
    )
    builder.add_edge("execute_step", "review_results")
    builder.add_conditional_edges(
        "review_results",
        nodes.route_after_review,
        {
            "continue": "execute_step",
            "approval_required": "request_approval",
            "report_ready": "finalize_report",
            "fail": "fail",
            "cancelled": END,
        },
    )
    builder.add_conditional_edges(
        "request_approval",
        nodes.route_after_approval,
        {"apply_approved": "apply_approved", "continue": "review_results", "fail": "fail"},
    )
    builder.add_edge("apply_approved", "review_results")
    builder.add_edge("finalize_report", END)
    builder.add_edge("fail", END)
    return builder.compile(checkpointer=checkpointer)
