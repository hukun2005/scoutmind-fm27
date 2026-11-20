"""AI decision-center endpoints: conversations, messages and structured answers."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..agents import service as agent_service
from ..db import get_db
from ..models import AgentConversation, AgentMessage, AiReport, FmSave
from ..schemas import AskRequest, ConversationCreate
from ..utils import iso
from .deps import get_active_save, get_current_user

def _owned_save(db: Session, save_id: int, user) -> FmSave:
    """校验存档属于当前用户；不存在或不属于就按"找不到"处理，不泄露存在性。"""
    target = db.get(FmSave, save_id)
    if target is None or target.user_id != user.id:
        raise HTTPException(status_code=404, detail={"code": "save_not_found", "message": "存档不存在"})
    return target


def _conversation_for(db: Session, conversation_id: int, user, save_id: int) -> AgentConversation:
    """会话必须同时属于当前用户与当前存档。

    会话是"某个存档的 AI 分析"，跨存档读取等于读取另一份存档的数据，因此一律拒绝；
    不区分"不存在"和"不属于你"，避免通过状态码探测别人的会话 id。
    """
    conversation = db.get(AgentConversation, conversation_id)
    if conversation is None or conversation.user_id != user.id or conversation.fm_save_id != save_id:
        raise HTTPException(status_code=404, detail={"code": "conversation_not_found", "message": "会话不存在"})
    return conversation


router = APIRouter()


@router.get("/agent/conversations")
def conversations(
    save_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Conversations of the save, newest first."""
    target = _owned_save(db, save_id, user).id if save_id else save.id
    rows = list(
        db.scalars(
            select(AgentConversation)
            .where(AgentConversation.fm_save_id == target, AgentConversation.user_id == user.id)
            .order_by(AgentConversation.created_at.desc())
        )
    )
    counts = dict(
        db.execute(
            select(AgentMessage.conversation_id, func.count())
            .where(AgentMessage.conversation_id.in_([row.id for row in rows] or [-1]))
            .group_by(AgentMessage.conversation_id)
        ).all()
    )
    return {
        "items": [
            {
                "id": row.id,
                "title": row.title,
                "created_at": iso(row.created_at),
                "message_count": int(counts.get(row.id, 0)),
            }
            for row in rows
        ],
        "total": len(rows),
    }


@router.post("/agent/conversations", status_code=201)
def create_conversation(
    body: ConversationCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Create an empty conversation."""
    target_save = _owned_save(db, body.save_id, user) if body.save_id else save
    conversation = AgentConversation(
        user_id=user.id,
        fm_save_id=target_save.id,
        title=body.title or "新的分析",
    )
    db.add(conversation)
    db.commit()
    return {"id": conversation.id, "title": conversation.title, "created_at": iso(conversation.created_at)}


@router.get("/agent/conversations/{conversation_id}/messages")
def messages(
    conversation_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Full message history including stored structured answers (same user, same save)."""
    conversation = _conversation_for(db, conversation_id, user, save.id)
    rows = list(
        db.scalars(
            select(AgentMessage)
            .where(AgentMessage.conversation_id == conversation_id)
            .order_by(AgentMessage.created_at, AgentMessage.id)
        )
    )
    return {
        "items": [
            {
                "id": row.id,
                "role": row.role,
                "content": row.content,
                "created_at": iso(row.created_at),
                "tool_calls": json.loads(row.tool_calls_json or "[]"),
                "answer": json.loads(row.answer_json) if row.answer_json else None,
            }
            for row in rows
        ],
        "total": len(rows),
    }


@router.post("/agent/conversations/{conversation_id}/messages", status_code=201)
def ask(
    conversation_id: int,
    body: AskRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Ask a question; the answer is built only from deterministic tool results."""
    conversation = _conversation_for(db, conversation_id, user, save.id)
    if body.save_id is not None and body.save_id != conversation.fm_save_id:
        raise HTTPException(
            status_code=400,
            detail={"code": "save_mismatch", "message": "会话属于另一个存档，不能跨存档提问"},
        )
    target_save_id = conversation.fm_save_id
    user_message = AgentMessage(conversation_id=conversation.id, role="user", content=body.question)
    db.add(user_message)
    db.flush()
    try:
        answer, calls = agent_service.answer_question(
            db,
            target_save_id,
            body.question,
            instance_id=body.instance_id,
            club_id=body.club_id,
            user_id=user.id,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail={"code": "agent_error", "message": str(exc)}) from exc
    assistant = AgentMessage(
        conversation_id=conversation.id,
        role="assistant",
        content=str(answer.get("conclusion", "")),
        answer_json=json.dumps(answer, ensure_ascii=False, default=str),
        tool_calls_json=json.dumps([call.payload() for call in calls], ensure_ascii=False, default=str),
    )
    db.add(assistant)
    db.add(
        AiReport(
            fm_save_id=target_save_id,
            conversation_id=conversation.id,
            question=body.question,
            answer=str(answer.get("conclusion", "")),
            reliability_json=json.dumps(answer.get("reliability") or {}, ensure_ascii=False, default=str),
            citations_json=json.dumps(answer.get("citations") or [], ensure_ascii=False, default=str),
            tool_calls_json=json.dumps([call.payload() for call in calls], ensure_ascii=False, default=str),
        )
    )
    if conversation.title == "新的分析":
        conversation.title = body.question[:40]
    db.commit()
    return {
        "message_id": assistant.id,
        "mode": answer.get("mode"),
        "answer": answer,
        "tool_calls": [call.payload() for call in calls],
    }


@router.get("/agent/reports")
def reports(
    save_id: int | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Stored AI reports with their reliability split and citations."""
    target = _owned_save(db, save_id, user).id if save_id else save.id
    rows = list(
        db.scalars(
            select(AiReport)
            .where(AiReport.fm_save_id == target)
            .order_by(AiReport.created_at.desc())
            .limit(limit)
        )
    )
    return {
        "items": [
            {
                "id": row.id,
                "question": row.question,
                "answer": row.answer,
                "conversation_id": row.conversation_id,
                "reliability": json.loads(row.reliability_json or "{}"),
                "citations": json.loads(row.citations_json or "[]"),
                "created_at": iso(row.created_at),
            }
            for row in rows
        ],
        "total": len(rows),
    }
