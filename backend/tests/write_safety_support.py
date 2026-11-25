"""V3.2.7.3 测试支持：隔离数据库、已验证身份、可写会话与写入门票。

这些 helper 直接操作 ORM，用于需要**多个独立连接**的真实并发测试；
HTTP 层行为在 ``test_unified_import_identity.py`` 中通过 TestClient 覆盖。
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db import build_engine
from app.models import Base, FmSave, SaveIdentity, SaveSession, SaveWriteGate, User
from app.services import write_safety
from app.utils import utcnow

FINGERPRINT = "si:v1:file:" + "a" * 64
FINGERPRINT_B = "si:v1:file:" + "b" * 64
GAME_BUILD = "26620374"


def make_engine(tmp_path: Path):
    """每个测试一个独立 SQLite 文件库，允许跨线程多连接。"""
    engine = build_engine(f"sqlite:///{(tmp_path / 'write-safety.db').as_posix()}")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


def seed_save(Factory) -> int:
    with Factory() as db:
        user = User(username="local", display_name="测试用户")
        db.add(user)
        db.flush()
        save = FmSave(user_id=user.id, name="测试存档", game_version="27.0", game_build=GAME_BUILD, is_active=True)
        db.add(save)
        db.commit()
        return save.id


def add_verified_identity(db: Session, save_id: int, fingerprint: str = FINGERPRINT) -> SaveIdentity:
    now = utcnow()
    identity = SaveIdentity(
        fm_save_id=save_id,
        identity_version=1,
        identity_status="verified",
        identity_confidence="verified",
        identity_fingerprint=fingerprint,
        identity_kind="save_file",
        game_build=GAME_BUILD,
        first_seen_at=now,
        last_seen_at=now,
        verified_at=now,
        verified_by="tester",
    )
    db.add(identity)
    db.flush()
    return identity


def add_session(
    db: Session,
    save_id: int,
    identity_id: int,
    *,
    key: str = "session-1",
    bind: bool = True,
    status: str = "verified",
) -> SaveSession:
    now = utcnow()
    session = SaveSession(
        fm_save_id=save_id,
        save_identity_id=identity_id,
        session_key=key,
        game_build=GAME_BUILD,
        agent_id="agent-test",
        session_status=status,
        session_started_at=now,
        last_heartbeat_at=now,
        last_verified_at=now,
    )
    db.add(session)
    db.flush()
    if bind:
        write_safety.bind_session_to_gate(db, db.get(FmSave, save_id), session)
    return session


def prepare_write_env(db: Session, save_id: int, *, key: str = "session-1") -> tuple[SaveIdentity, SaveSession, SaveWriteGate]:
    """给一个已存在的存档准备：已验证身份 + 已绑定代次的会话 + gate。"""
    identity = add_verified_identity(db, save_id)
    session = add_session(db, save_id, identity.id, key=key)
    db.commit()
    gate = db.scalar(select(SaveWriteGate).where(SaveWriteGate.fm_save_id == save_id))
    assert gate is not None
    return identity, session, gate
