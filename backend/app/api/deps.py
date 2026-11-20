"""Shared FastAPI dependencies: authentication, default user and active save resolution."""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import FmSave, PlayerInstance, RecruitmentShortlist, Transfer, User

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

def owned_save_or_404(session: Session, save_id: int | None, user: User) -> FmSave:
    """按 id 取存档并校验归属；None 表示调用方已解析出 active save。

    统一用 404 而不是 403：不泄露"这个 id 存在但不属于你"。
    """
    if save_id is None:
        raise HTTPException(status_code=404, detail={"code": "save_not_found", "message": "存档不存在"})
    save = session.get(FmSave, save_id)
    if save is None or save.user_id != user.id:
        raise HTTPException(status_code=404, detail={"code": "save_not_found", "message": "存档不存在"})
    return save


def instance_in_save_or_404(session: Session, instance_id: int, save: FmSave) -> PlayerInstance:
    """球员实例必须属于该存档；否则 404。"""
    instance = session.get(PlayerInstance, instance_id)
    if instance is None or instance.fm_save_id != save.id:
        raise HTTPException(status_code=404, detail={"code": "player_not_found", "message": "球员不存在"})
    return instance


def transfer_in_save_or_404(session: Session, transfer_id: int, save: FmSave) -> Transfer:
    """交易必须属于该存档；否则 404。"""
    transfer = session.get(Transfer, transfer_id)
    if transfer is None or transfer.fm_save_id != save.id:
        raise HTTPException(status_code=404, detail={"code": "transfer_not_found", "message": "交易不存在"})
    return transfer


def shortlist_in_save_or_404(session: Session, shortlist_id: int, save: FmSave) -> RecruitmentShortlist:
    """短名单必须属于该存档；否则 404。"""
    shortlist = session.get(RecruitmentShortlist, shortlist_id)
    if shortlist is None or shortlist.fm_save_id != save.id:
        raise HTTPException(status_code=404, detail={"code": "shortlist_not_found", "message": "短名单不存在"})
    return shortlist


def club_in_save_or_404(session: Session, club_id: int, save: FmSave):
    """俱乐部必须属于该存档；否则 404。"""
    from ..models import Club

    club = session.get(Club, club_id)
    if club is None or club.fm_save_id != save.id:
        raise HTTPException(status_code=404, detail={"code": "club_not_found", "message": "俱乐部不存在"})
    return club

