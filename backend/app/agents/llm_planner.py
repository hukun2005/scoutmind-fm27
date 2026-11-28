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
import time
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
    "simulate_transfer": {
        "description": "模拟一笔引援（成本、报价区间、阵容提升、三情景、风险、替代方案）",
        "parameters": {
            "type": "object",
            "properties": {
                "instance_id": {"type": "integer", "minimum": 1},
                "fee": {"type": "number", "minimum": 0},
                "wage": {"type": "number", "minimum": 0},
                "budget": {"type": "number", "minimum": 0},
                "contract_years": {"type": "number", "minimum": 0.5, "maximum": 8},
                "transfer_type": {"type": "string", "enum": ["permanent", "loan", "loan_with_option", "free_transfer"]},
            },
            "required": ["instance_id"],
            "additionalProperties": False,
        },
        "execute": lambda session, save_id, args: _simulate_call(session, save_id, args),
    },
    "player_forecast": {
        "description": "球员成长预测（1 年/3 年区间、置信度、回测口径）",
        "parameters": {
            "type": "object",
            "properties": {"instance_id": {"type": "integer", "minimum": 1}},
            "required": ["instance_id"],
            "additionalProperties": False,
        },
        "execute": lambda session, save_id, args: _forecast_call(session, args),
    },
    "club_transfer_intelligence": {
        "description": "俱乐部长期转会策略（买卖现金、净支出、类型/赛季分布）",
        "parameters": {
            "type": "object",
            "properties": {
                "club_id": {"type": "integer", "minimum": 1},
                "season": {"type": "string", "minLength": 7, "maxLength": 7},
            },
            "required": ["club_id"],
            "additionalProperties": False,
        },
        "execute": lambda session, save_id, args: _club_intel_call(session, save_id, args),
    },
    "transfer_roi": {
        "description": "单笔买入的现金/会计/估值/已实现收益（口径分开）",
        "parameters": {
            "type": "object",
            "properties": {"transfer_id": {"type": "integer", "minimum": 1}},
            "required": ["transfer_id"],
            "additionalProperties": False,
        },
        "execute": lambda session, save_id, args: _roi_call(session, args),
    },
    "recruitment_recommend": {
        "description": "按位置/预算/偏好推荐引援目标（可解释加权）",
        "parameters": {
            "type": "object",
            "properties": {
                "slot": {"type": "string", "minLength": 1, "maxLength": 8},
                "budget": {"type": "number", "minimum": 0},
                "prefer": {"type": "string", "enum": ["balanced", "ready", "potential"]},
                "page_size": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "additionalProperties": False,
        },
        "execute": lambda session, save_id, args: _recommend_call(session, save_id, args),
    },
    "career_timeline": {
        "description": "球员职业轨迹（跨存档、按全局身份）",
        "parameters": {
            "type": "object",
            "properties": {"instance_id": {"type": "integer", "minimum": 1}},
            "required": ["instance_id"],
            "additionalProperties": False,
        },
        "execute": lambda session, save_id, args: _career_call(session, save_id, args),
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
    "transfer_contract": {
        "description": "球员真实合同：周薪、到期日、剩余月份、挂牌状态（需要 instance_id）",
        "parameters": {
            "type": "object",
            "properties": {"instance_id": {"type": "integer", "minimum": 1}},
            "required": ["instance_id"],
            "additionalProperties": False,
        },
        "execute": lambda session, save_id, args: tools.get_player_contract(
            session, save_id, int(args["instance_id"])
        ),
    },
    "player_transfer_history": {
        "description": "球员在当前存档的历史转会（需要 instance_id）",
        "parameters": {
            "type": "object",
            "properties": {
                "instance_id": {"type": "integer", "minimum": 1},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            "required": ["instance_id"],
            "additionalProperties": False,
        },
        "execute": lambda session, save_id, args: tools.get_player_transfer_history(
            session, save_id, int(args["instance_id"]), limit=int(args.get("limit", 20))
        ),
    },
    "club_transfer_history": {
        "description": "俱乐部买入/卖出/租借/未来/取消汇总（需要 club_id）",
        "parameters": {
            "type": "object",
            "properties": {"club_id": {"type": "integer", "minimum": 1}},
            "required": ["club_id"],
            "additionalProperties": False,
        },
        "execute": lambda session, save_id, args: tools.get_club_transfer_history(
            session, save_id, int(args["club_id"])
        ),
    },
    "transfer_clauses": {
        "description": "球员已确认/已导入的分期、浮动、二转分成与买断条款（需要 instance_id）",
        "parameters": {
            "type": "object",
            "properties": {"instance_id": {"type": "integer", "minimum": 1}},
            "required": ["instance_id"],
            "additionalProperties": False,
        },
        "execute": lambda session, save_id, args: tools.get_transfer_clauses(
            session, save_id, int(args["instance_id"])
        ),
    },
    "club_financial_context": {
        "description": "俱乐部预算与工资空间；没有可靠来源时明确返回不可用",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        "execute": lambda session, save_id, args: tools.get_club_financial_context(session, save_id),
    },
    "transfer_valuation": {
        "description": "确定性转会估值（可比成交分位；样本不足拒绝给区间，需要 instance_id）",
        "parameters": {
            "type": "object",
            "properties": {"instance_id": {"type": "integer", "minimum": 1}},
            "required": ["instance_id"],
            "additionalProperties": False,
        },
        "execute": lambda session, save_id, args: tools.calculate_transfer_valuation(
            session, save_id, int(args["instance_id"])
        ),
    },
    "purchase_offers": {
        "description": "生成三套买入报价方案（保守/竞争/快速，可选预算）",
        "parameters": {
            "type": "object",
            "properties": {
                "instance_id": {"type": "integer", "minimum": 1},
                "budget": {"type": "number", "minimum": 0},
            },
            "required": ["instance_id"],
            "additionalProperties": False,
        },
        "execute": lambda session, save_id, args: tools.generate_purchase_offers(
            session, save_id, int(args["instance_id"]), budget=args.get("budget")
        ),
    },
    "sale_offers": {
        "description": "生成三套出售报价方案（快速/合理/价值最大化）",
        "parameters": {
            "type": "object",
            "properties": {"instance_id": {"type": "integer", "minimum": 1}},
            "required": ["instance_id"],
            "additionalProperties": False,
        },
        "execute": lambda session, save_id, args: tools.generate_sale_offers(
            session, save_id, int(args["instance_id"])
        ),
    },
    "loan_offers": {
        "description": "生成三套租借报价方案（低成本/发展型/租借后买断）",
        "parameters": {
            "type": "object",
            "properties": {"instance_id": {"type": "integer", "minimum": 1}},
            "required": ["instance_id"],
            "additionalProperties": False,
        },
        "execute": lambda session, save_id, args: tools.generate_loan_offers(
            session, save_id, int(args["instance_id"])
        ),
    },
    "transfer_opportunities": {
        "description": "全局转会机会雷达：挂牌/可租借/合同到期/AI 推测机会（可筛选类型与推荐分组）",
        "parameters": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["listed", "loan_listed", "release_listed", "contract_expiring", "ai_inferred"],
                },
                "group": {
                    "type": "string",
                    "enum": ["strong", "watch", "loan", "long_term", "not_recommended"],
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            "additionalProperties": False,
        },
        "execute": lambda session, save_id, args: tools.get_transfer_opportunities(
            session,
            save_id,
            opportunity_type=args.get("type"),
            group=args.get("group"),
            limit=int(args.get("limit", 20)),
        ),
    },
    "transfer_strategy_cases": {
        "description": "历史成交策略案例：案例库、相似案例匹配与规则归纳（可选 instance_id）",
        "parameters": {
            "type": "object",
            "properties": {
                "instance_id": {"type": "integer", "minimum": 1},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            "additionalProperties": False,
        },
        "execute": lambda session, save_id, args: tools.get_transfer_strategy_cases(
            session, save_id, int(args["instance_id"]) if args.get("instance_id") else None,
            limit=int(args.get("limit", 10)),
        ),
    },
    "record_negotiation": {
        "description": "记录用户真实谈判事件（不提交游戏内报价，需要 negotiation_id）",
        "parameters": {
            "type": "object",
            "properties": {
                "negotiation_id": {"type": "integer", "minimum": 1},
                "event_type": {
                    "type": "string",
                    "enum": [
                        "draft_created",
                        "offer_generated",
                        "offer_submitted",
                        "counter_received",
                        "offer_revised",
                        "accepted",
                        "rejected",
                        "withdrawn",
                        "completed",
                        "cancelled",
                        "note",
                    ],
                },
                "amount": {"type": "number", "minimum": 0},
                "note": {"type": "string", "minLength": 1, "maxLength": 256},
            },
            "required": ["negotiation_id", "event_type"],
            "additionalProperties": False,
        },
        "execute": lambda session, save_id, args: tools.record_negotiation_event(
            session,
            save_id,
            int(args["negotiation_id"]),
            str(args["event_type"]),
            amount=args.get("amount"),
            data={"note": args["note"]} if args.get("note") else None,
        ),
    },
    "negotiation_review": {
        "description": "复盘一笔已完成谈判（需要 negotiation_id）",
        "parameters": {
            "type": "object",
            "properties": {"negotiation_id": {"type": "integer", "minimum": 1}},
            "required": ["negotiation_id"],
            "additionalProperties": False,
        },
        "execute": lambda session, save_id, args: tools.review_negotiation(
            session, save_id, int(args["negotiation_id"])
        ),
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
    usage: dict[str, int] | None = None
    cost_estimate: float | None = None


class LlmUnavailable(RuntimeError):
    """LLM 未配置或不可用：由调用方降级到规则规划器。"""


class PlannerError(ValueError):
    """模型给出的计划不合法（未知工具、参数越界、超过调用上限）。"""


def llm_enabled() -> bool:
    return bool(settings.agent_llm_enabled and settings.agent_llm_api_key)


def _validate_arguments(spec: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """严格校验工具参数：类型、有限性、枚举、范围、长度、未知/禁止键。

    不依赖第三方库：规则集是 JSON Schema 的子集，行为由测试固定。bool 不能冒充 integer/number，
    NaN/Infinity 一律拒绝；未知键和 save_id/user_id 等作用域参数直接拒绝。
    """
    import math

    params = spec["parameters"]
    properties = params.get("properties", {})
    allowed = set(properties)
    unknown = set(arguments) - allowed
    forbidden = unknown & FORBIDDEN_ARGUMENTS
    if forbidden:
        raise PlannerError(f"模型试图指定受限参数：{sorted(forbidden)}")
    if unknown:
        raise PlannerError(f"未知参数：{sorted(unknown)}")
    if params.get("additionalProperties") is False and unknown:
        raise PlannerError(f"未知参数：{sorted(unknown)}")

    cleaned: dict[str, Any] = {}
    for key, value in arguments.items():
        rule = properties[key]
        kind = rule.get("type")
        if kind == "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                raise PlannerError(f"{key} 必须是整数")
        elif kind == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise PlannerError(f"{key} 必须是数字")
            if not math.isfinite(float(value)):
                raise PlannerError(f"{key} 必须是有限数字")
        elif kind == "string":
            if not isinstance(value, str):
                raise PlannerError(f"{key} 必须是字符串")
        elif kind == "boolean":
            if not isinstance(value, bool):
                raise PlannerError(f"{key} 必须是布尔值")
        elif kind is not None:
            raise PlannerError(f"{key} 的 schema 类型不受支持")

        if "enum" in rule and value not in rule["enum"]:
            raise PlannerError(f"{key} 不在允许取值内")
        if kind in {"integer", "number"}:
            if "minimum" in rule and value < rule["minimum"]:
                raise PlannerError(f"{key} 小于下限")
            if "maximum" in rule and value > rule["maximum"]:
                raise PlannerError(f"{key} 超过上限")
        if kind == "string":
            if "minLength" in rule and len(value) < rule["minLength"]:
                raise PlannerError(f"{key} 长度小于下限")
            if "maxLength" in rule and len(value) > rule["maxLength"]:
                raise PlannerError(f"{key} 长度超过上限")
        cleaned[key] = value

    for key in params.get("required", []):
        if key not in cleaned:
            raise PlannerError(f"缺少必需参数 {key}")
    return cleaned


def _assert_tool_scope(session: Session, save_id: int, arguments: dict[str, Any]) -> None:
    """在调用工具前验证所有实体 ID 都属于当前存档；错误不泄露记录是否存在。"""
    from ..models import Club, PlayerInstance, RecruitmentShortlist, Transfer, TransferCandidate

    checks = {
        "instance_id": (PlayerInstance, "fm_save_id"),
        "transfer_id": (Transfer, "fm_save_id"),
        "club_id": (Club, "fm_save_id"),
        "shortlist_id": (RecruitmentShortlist, "fm_save_id"),
        "candidate_id": (TransferCandidate, "fm_save_id"),
    }
    for key, (model, save_attribute) in checks.items():
        value = arguments.get(key)
        if value is None:
            continue
        entity = session.get(model, int(value))
        if entity is None or getattr(entity, save_attribute) != save_id:
            raise PlannerError("工具参数引用了当前存档之外的记录")



# -- 第三阶段工具：模拟、预测、俱乐部情报、ROI、推荐、职业轨迹 --------------------------------


def validate_tool_arguments(spec: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """公开入口：严格校验单个工具的参数（V3.3.3 Runtime 复用同一套规则）。"""
    return _validate_arguments(spec, arguments)


def assert_tool_scope(session: Session, save_id: int, arguments: dict[str, Any]) -> None:
    """公开入口：调用工具前校验实体归属（V3.3.3 Runtime 复用同一套规则）。"""
    _assert_tool_scope(session, save_id, arguments)



def _tool_call(name: str, result: dict[str, Any], summary: str) -> ToolCall:
    return ToolCall(name=name, arguments={}, result=result, summary=summary)


def _simulate_call(session, save_id: int, args: dict[str, Any]) -> ToolCall:
    from ..analytics.simulator import simulate_transfer

    result = simulate_transfer(
        session,
        save_id,
        int(args["instance_id"]),
        fee=args.get("fee"),
        wage=args.get("wage"),
        budget=args.get("budget"),
        contract_years=float(args.get("contract_years", 4.0)),
        transfer_type=str(args.get("transfer_type", "permanent")),
    )
    return _tool_call("simulate_transfer", result, result["recommendation"]["reason"])


def _forecast_call(session, args: dict[str, Any]) -> ToolCall:
    from ..analytics.forecast import forecast_player

    result = forecast_player(session, int(args["instance_id"]))
    one_year = result["forecast"]["one_year"]
    summary = (
        f"1 年预测 CA {one_year['low']}–{one_year['high']}（中值 {one_year['mid']}），"
        f"依据：{result['basis']['method']}"
        if one_year
        else "快照不足，无法给出 1 年预测"
    )
    return _tool_call("player_forecast", result, summary)


def _club_intel_call(session, save_id: int, args: dict[str, Any]) -> ToolCall:
    from ..analytics.club_intelligence import club_transfer_intelligence

    result = club_transfer_intelligence(session, save_id, int(args["club_id"]), season=args.get("season"))
    buy = result["completed"]["buy"]
    return _tool_call(
        "club_transfer_intelligence",
        result,
        f"{result['club_name']}：买入 {buy['count']} 笔、现金 {buy['cash']}，净支出 {result['completed']['net_cash']}",
    )


def _roi_call(session, args: dict[str, Any]) -> ToolCall:
    from ..analytics.roi import transfer_roi

    result = transfer_roi(session, int(args["transfer_id"]))
    realized = result["cash"]["realized_profit"]
    return _tool_call("transfer_roi", result, f"已实现收益 {realized}（None 表示尚未卖出或成本未知）")


def _recommend_call(session, save_id: int, args: dict[str, Any]) -> ToolCall:
    from ..analytics.recruitment_recommend import recommend

    result = recommend(
        session,
        save_id,
        slot=args.get("slot"),
        budget=args.get("budget"),
        prefer=str(args.get("prefer", "balanced")),
        page_size=int(args.get("page_size", 10)),
    )
    top = result["items"][0]["name"] if result["items"] else "无"
    return _tool_call("recruitment_recommend", result, f"共 {result['total']} 名候选，首位 {top}")


def _career_call(session, save_id: int, args: dict[str, Any]) -> ToolCall:
    from ..analytics.career import player_career

    result = player_career(session, int(args["instance_id"]), allowed_save_ids={save_id})
    return _tool_call("career_timeline", result, f"{result['full_name']}：{result['coverage']['snapshots']} 次观测")


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
    usage: dict[str, int] | None = None,
) -> PlanResult:
    """按计划执行确定性工具，记录每一步轨迹。"""
    calls: list[ToolCall] = []
    trace: list[dict[str, object]] = []
    for name, arguments in plan:
        spec = TOOL_SPECS[name]
        # 作用域错误必须直接抛出，不能被“工具执行失败”兜底成通用错误。
        _assert_tool_scope(session, save_id, arguments)
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
    return PlanResult(
        calls=calls,
        trace=trace,
        mode=mode,
        usage=usage,
        cost_estimate=_cost_of(usage),
    )


def _usage_from(response: dict[str, Any]) -> dict[str, int] | None:
    usage = response.get("usage")
    if not isinstance(usage, dict):
        return None
    return {
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
        "total_tokens": int(usage.get("total_tokens") or 0),
    }


def _cost_of(usage: dict[str, int] | None) -> float | None:
    if usage is None:
        return None
    return round(
        usage["prompt_tokens"] / 1_000_000 * settings.agent_llm_input_price_per_mtok
        + usage["completion_tokens"] / 1_000_000 * settings.agent_llm_output_price_per_mtok,
        6,
    )


def chat_completion(
    messages: list[dict[str, str]],
    *,
    timeout: float | None = None,
) -> dict[str, Any]:
    """调用 OpenAI 兼容的 chat/completions；带超时、可重试错误与 usage。"""
    if not llm_enabled():
        raise LlmUnavailable("未配置 agent_llm_api_key 或 agent_llm_enabled=false")

    import httpx

    url = settings.agent_llm_base_url.rstrip("/") + "/" + settings.agent_llm_chat_path.lstrip("/")
    payload: dict[str, Any] = {
        "model": settings.agent_llm_model,
        "messages": messages,
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    attempt = 0
    last_error: Exception | None = None
    while attempt <= max(0, settings.agent_llm_max_retries):
        attempt += 1
        retry_pause = 0.0
        try:
            response = httpx.post(
                url,
                json=payload,
                timeout=timeout if timeout is not None else settings.agent_llm_timeout_seconds,
                headers={"Authorization": f"Bearer {settings.agent_llm_api_key}"},
            )
            if (
                response.status_code in {400, 422}
                and "response_format" in payload
                and "response_format" in response.text
            ):
                # 部分 OpenAI 兼容端点不支持 JSON 模式；去掉该参数再试一次。
                payload = {key: value for key, value in payload.items() if key != "response_format"}
                continue
            if response.status_code in {429, 500, 502, 503, 504}:
                # 429 常见于免费档限流：退避后再试，避免瞬时重试全部撞墙。
                retry_pause = min(1.5 * attempt, 6.0)
                raise httpx.HTTPStatusError("retryable status", request=response.request, response=response)
            response.raise_for_status()
            data = response.json()
            usage = _usage_from(data)
            if usage is not None:
                log.info("llm usage=%s cost=%s", usage, _cost_of(usage))
            return data
        except Exception as exc:  # noqa: BLE001 - 统一降级
            last_error = exc
            if attempt <= max(0, settings.agent_llm_max_retries):
                if retry_pause > 0:
                    time.sleep(retry_pause)
                continue
    raise LlmUnavailable(f"LLM 调用失败（{attempt} 次尝试）：{last_error}") from last_error


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
    return execute_plan(session, save_id, plan, mode="llm", usage=_usage_from(response))


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
