"""存档身份 / 会话上下文校验（V3.2.7 Phase 5）。

写接口（导入、采集登记）在客户端声明了 ``save_identity_id`` / ``save_session_id`` 时，必须证明：

* 身份属于当前存档，且不是 UNKNOWN / DISCOVERED / CANDIDATE / CONFLICT / INVALIDATED；
* 会话属于当前存档（并属于该身份），且处于 ``verified``，不是已失效或切换中；
* 身份与会话的 game build 不矛盾。

任一不满足都返回统一安全错误；未声明时保持旧行为（Phase 6 起由 Agent 强制携带）。
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import FmSave, SaveIdentity, SaveSession

SAVE_CONTEXT_MISMATCH = "save_context_mismatch"
SAVE_IDENTITY_UNVERIFIED = "save_identity_unverified"
SAVE_SESSION_INVALIDATED = "save_session_invalidated"
SAVE_SWITCH_IN_PROGRESS = "save_switch_in_progress"

#: 这些身份状态永远不允许写入数据。
BLOCKED_IDENTITY_STATUSES = {"conflict", "invalidated"}
#: 这些身份状态表示“已发现但未验证”，只能用于诊断。
UNVERIFIED_IDENTITY_STATUSES = {"unknown", "discovered", "candidate"}
#: 只有验证通过的会话可以提交数据。
ACTIVE_SESSION_STATUSES = {"verified"}
#: 这些会话状态表示旧会话已被终止，不能再写。
ENDED_SESSION_STATUSES = {"invalidated", "closed"}
#: 切换中的会话必须暂停任务，而不是报旧会话失效。
SWITCHING_SESSION_STATUSES = {"switching"}


@dataclass(frozen=True)
class SaveContext:
    """一次写请求解析出的身份与会话；未声明时为 None。"""

    identity: SaveIdentity | None = None
    session: SaveSession | None = None

    @property
    def identity_id(self) -> int | None:
        return self.identity.id if self.identity is not None else None

    @property
    def session_id(self) -> int | None:
        return self.session.id if self.session is not None else None


def _fail(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def resolve_save_context(
    db: Session,
    save: FmSave,
    identity_id: int | None,
    session_id: int | None,
) -> SaveContext:
    """校验客户端声明的身份/会话上下文；不声明则原样放行（历史手工流程）。"""
    if identity_id is None and session_id is None:
        return SaveContext()

    identity = None
    if identity_id is not None:
        identity = db.get(SaveIdentity, identity_id)
        if identity is None or (identity.fm_save_id is not None and identity.fm_save_id != save.id):
            raise _fail(409, SAVE_CONTEXT_MISMATCH, "存档身份不属于当前存档")
        if identity.identity_status in BLOCKED_IDENTITY_STATUSES:
            raise _fail(409, SAVE_CONTEXT_MISMATCH, "存档身份处于冲突或失效状态，已阻止写入")
        if identity.identity_status in UNVERIFIED_IDENTITY_STATUSES:
            raise _fail(409, SAVE_IDENTITY_UNVERIFIED, "存档身份尚未验证，已阻止写入")

    session = None
    if session_id is not None:
        session = db.get(SaveSession, session_id)
        if session is None or (session.fm_save_id is not None and session.fm_save_id != save.id):
            raise _fail(409, SAVE_CONTEXT_MISMATCH, "会话不属于当前存档")
        if session.session_status in SWITCHING_SESSION_STATUSES:
            raise _fail(409, SAVE_SWITCH_IN_PROGRESS, "存档正在切换，已暂停写入")
        if session.session_status in ENDED_SESSION_STATUSES or session.session_status not in ACTIVE_SESSION_STATUSES:
            raise _fail(409, SAVE_SESSION_INVALIDATED, "会话已失效，不能提交新数据")
        if identity is not None and session.save_identity_id not in (None, identity.id):
            raise _fail(409, SAVE_CONTEXT_MISMATCH, "会话与声明的存档身份不一致")
        identity_build = identity.game_build if identity is not None else None
        if identity_build and session.game_build and identity_build != session.game_build:
            raise _fail(409, SAVE_CONTEXT_MISMATCH, "存档身份的 game build 与会话不一致")

    return SaveContext(identity=identity, session=session)
