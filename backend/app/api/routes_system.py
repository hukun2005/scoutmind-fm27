"""V3.3.2-07 系统体验 API：首次启动、数据中心、诊断与安全修复。

所有端点都以当前存档为作用域，只输出用户可理解的状态；诊断只读，修复只执行安全项。
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import FmSave
from ..services import user_experience
from .deps import get_active_save

router = APIRouter()

RepairTarget = Literal["club_links", "player_identity", "contract", "delete_duplicates"]


class RepairRequest(BaseModel):
    targets: list[RepairTarget] = Field(default_factory=lambda: ["club_links"])
    dry_run: bool = False


@router.get("/system/onboarding", summary="首次启动检查与数据准备摘要")
def onboarding(
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    return user_experience.onboarding(db, save)


@router.get("/system/data-health", summary="统一数据中心状态（只读）")
def data_health(
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    return user_experience.data_health(db, save)


@router.post("/system/diagnostics", summary="只读数据诊断（幂等）")
def diagnostics(
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    return user_experience.diagnostics(db, save)


@router.post("/system/repair", summary="只执行可安全修复的数据项")
def repair(
    payload: RepairRequest | None = None,
    db: Session = Depends(get_db),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    body = payload or RepairRequest()
    return user_experience.repair(db, save, targets=body.targets, dry_run=body.dry_run)
