"""历史转会导入与覆盖率（SM-013）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from ..db import get_db
from ..ingestion.transfer_history import import_transfer_file, transfer_coverage
from ..models import FmSave
from .deps import get_active_save, get_current_user
from .uploads import read_request_payload, upload_slot

router = APIRouter()


def _owned_save(db: Session, save_id: int, user) -> FmSave:
    target = db.get(FmSave, save_id)
    if target is None or target.user_id != user.id:
        raise HTTPException(status_code=404, detail={"code": "save_not_found", "message": "存档不存在"})
    return target


@router.get("/transfers/coverage", summary="历史转会覆盖率与导入批次")
def coverage(
    save_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """覆盖率只统计已导入的历史记录；没有 completed 就明确说"历史不可用"。"""
    target = _owned_save(db, save_id, user) if save_id else save
    return transfer_coverage(db, target.id)


@router.post("/imports/transfers/history", status_code=201, summary="导入历史转会（CSV/JSON）")
async def import_history(
    request: Request,
    save_id: int | None = Query(default=None),
    source_name: str | None = Query(default=None, max_length=64),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    save: FmSave = Depends(get_active_save),
) -> dict[str, Any]:
    """独立的历史转会通道：只写交易，不要求球员快照。

    数据源必须真的提供历史交易；状态未知的行会被拒绝，绝不默认 completed。
    """
    target = _owned_save(db, save_id, user) if save_id else save
    filename = None
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        # 文件名只用于推断格式与来源名；实际字节仍走统一的分块上传限制。
        filename = _filename_from_headers(request.headers.get("content-disposition", ""))

    async with upload_slot():
        raw = await read_request_payload(request, what="历史转会文件")
    if not raw:
        raise HTTPException(status_code=422, detail={"code": "empty_payload", "message": "文件内容为空"})
    try:
        report = import_transfer_file(
            db, target.id, raw, filename=filename, source_name=source_name
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail={"code": "invalid_transfer_file", "message": str(exc)}) from exc
    db.commit()
    return report.payload()


def _filename_from_headers(disposition: str) -> str | None:
    """从 Content-Disposition 里取出文件名（只用于识别格式/来源，不做路径处理）。"""
    marker = "filename="
    if marker not in disposition:
        return None
    value = disposition.split(marker, 1)[1].split(";", 1)[0].strip().strip('"')
    return value or None
