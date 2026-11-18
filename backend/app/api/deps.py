"""Shared FastAPI dependencies: authentication, default user and active save resolution."""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import FmSave, User

DEFAULT_USERNAME = "local"


def require_token(x_scoutmind_token: str | None = Header(default=None, alias="X-ScoutMind-Token")) -> None:
    """Enforce the local API token when one is configured."""
    if not settings.api_token:
        return
    if x_scoutmind_token != settings.api_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthorized", "message": "缺少或错误的本地授权令牌"},
        )


def get_current_user(session: Session = Depends(get_db)) -> User:
    """The implicit local operator account, created on first use."""
    user = session.scalar(select(User).where(User.username == DEFAULT_USERNAME))
    if user is None:
        user = User(username=DEFAULT_USERNAME, display_name="本地用户")
        session.add(user)
        session.commit()
    return user


def get_active_save(
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    save_id: int | None = None,
) -> FmSave:
    """Return the requested save or the user's active/default one."""
    if save_id is not None:
        save = session.get(FmSave, save_id)
        if save is None or save.user_id != user.id:
            raise HTTPException(status_code=404, detail={"code": "save_not_found", "message": "存档不存在"})
        return save
    save = session.scalar(select(FmSave).where(FmSave.user_id == user.id, FmSave.is_active.is_(True)).limit(1))
    if save is None:
        save = FmSave(user_id=user.id, name="我的 FM27 存档", is_active=True)
        session.add(save)
        session.commit()
    return save
