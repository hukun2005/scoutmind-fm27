"""V3.3.2-08 在线学习 API。

所有端点以当前存档为作用域；不暴露内部阈值与开发参数。
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import FmSave
from ..services import background_scan
from ..services import transfer_learning as learning
from .deps import get_active_save

router = APIRouter()


def _maybe_start_task(db: Session, save_id: int) -> dict[str, Any] | None:
    """有未处理数据时才创建学习任务，避免空转与重复任务。"""
    if learning.count_pending(db, save_id) <= 0:
        return None
    task, reused = background_scan.create_task(
        db, save_id, background_scan.TRANSFER_LEARNING, created_by="user"
    )
    return {"task": task, "reused": reused}


@router.get("/transfer-learning/status", summary="在线学习状态")
def get_status(
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    return learning.status(db, save.id)


@router.post("/transfer-learning/start", summary="开启自动学习并处理未读数据")
def start(
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    learning.set_enabled(db, save.id, True)
    started = _maybe_start_task(db, save.id)
    return {"status": learning.status(db, save.id)["status"], "started": started}


@router.post("/transfer-learning/pause", summary="暂停自动学习（保留已有学习成果）")
def pause(
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    status = learning.set_enabled(db, save.id, False)
    return {"status": status["status"], "enabled": status["enabled"]}


@router.post("/transfer-learning/resume", summary="恢复自动学习")
def resume(
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    status = learning.set_enabled(db, save.id, True)
    started = _maybe_start_task(db, save.id)
    return {"status": status["status"], "enabled": True, "started": started}


@router.get("/transfer-learning/events", summary="学习事件（分页、可筛选）")
def events(
    club_id: int | None = Query(default=None, gt=0),
    player_instance_id: int | None = Query(default=None, gt=0),
    event_type: str | None = Query(default=None, max_length=32),
    verification_status: str | None = Query(default=None, max_length=16),
    since: date | None = Query(default=None),
    until: date | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    try:
        return learning.list_events(
            db,
            save.id,
            club_id=club_id,
            player_instance_id=player_instance_id,
            event_type=event_type,
            verification_status=verification_status,
            since=since,
            until=until,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_filter", "message": str(exc)}) from exc


@router.get("/transfer-learning/clubs", summary="全球俱乐部学习画像（分页）")
def clubs(
    search: str | None = Query(default=None, max_length=64),
    league: str | None = Query(default=None, max_length=128),
    transaction_type: str | None = Query(default=None, max_length=16),
    min_sample: int | None = Query(default=None, ge=0, le=100000),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    try:
        return learning.list_clubs(
            db,
            save.id,
            search=search,
            league=league,
            transaction_type=transaction_type,
            min_sample=min_sample,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_filter", "message": str(exc)}) from exc


@router.get("/transfer-learning/clubs/{club_id}", summary="单个俱乐部学习画像")
def club_detail(
    club_id: int,
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    try:
        return learning.club_profile(db, save.id, club_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "club_not_found", "message": "俱乐部不存在"}) from exc


@router.get("/transfer-learning/focus-clubs", summary="重点学习俱乐部")
def focus_clubs(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    return learning.focus_clubs(db, save.id, limit=limit, offset=offset)


@router.get("/transfer-learning/strategies", summary="全球与重点俱乐部策略归纳")
def strategies(
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    return learning.strategies(db, save.id)


@router.get("/transfer-learning/activity", summary="最近学习动态")
def activity(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    return learning.activity(db, save.id, limit=limit)
