"""AI decision-center endpoints: conversations, messages and structured answers."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..agents import service as agent_service
from ..db import get_db
from ..models import AgentConversation, AgentMessage, FmSave
from ..schemas import AskRequest, ConversationCreate
from ..utils import iso
from .deps import get_active_save, get_current_user

router = APIRouter()


@router.get("/agent/conversations")
def conversations(
    save_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Conversations of the save, newest first."""
    target = save_id or save.id
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
    conversation = AgentConversation(
        user_id=user.id,
        fm_save_id=body.save_id or save.id,
        title=body.title or "新的分析",
    )
    db.add(conversation)
    db.commit()
    return {"id": conversation.id, "title": conversation.title, "created_at": iso(conversation.created_at)}


@router.get("/agent/conversations/{conversation_id}/messages")
def messages(conversation_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Full message history including stored structured answers."""
    conversation = db.get(AgentConversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail={"code": "conversation_not_found", "message": "会话不存在"})
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
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """Ask a question; the answer is built only from deterministic tool results."""
    conversation = db.get(AgentConversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail={"code": "conversation_not_found", "message": "会话不存在"})
    user_message = AgentMessage(conversation_id=conversation.id, role="user", content=body.question)
    db.add(user_message)
    db.flush()
    try:
        answer, calls = agent_service.answer_question(
            db,
            body.save_id or save.id,
            body.question,
            instance_id=body.instance_id,
            club_id=body.club_id,
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
    if conversation.title == "新的分析":
        conversation.title = body.question[:40]
    db.commit()
    return {
        "message_id": assistant.id,
        "mode": answer.get("mode"),
        "answer": answer,
        "tool_calls": [call.payload() for call in calls],
    }
