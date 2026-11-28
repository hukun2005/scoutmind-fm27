"""Test fixtures: an isolated SQLite database and an API client bound to it."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

TMP_ROOT = Path(tempfile.mkdtemp(prefix="scoutmind-tests-"))
os.environ["SCOUTMIND_DATABASE_URL"] = f"sqlite:///{(TMP_ROOT / 'test.db').as_posix()}"
os.environ["SCOUTMIND_DATA_DIR"] = str(TMP_ROOT / "data")
os.environ.pop("SCOUTMIND_API_TOKEN", None)
# 测试必须与开发机 backend/.env 解耦：即使本机配置了真实模型，也不能在测试中发起真实网络调用。
os.environ["SCOUTMIND_AGENT_LLM_ENABLED"] = "false"
os.environ["SCOUTMIND_AGENT_LLM_API_KEY"] = ""
# V3.3.2-08：测试直接调用学习服务，避免导入接口在后台线程争用测试数据库。
os.environ.setdefault("SCOUTMIND_LEARNING_AUTO_START", "0")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import build_engine, get_db  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import Base, FmSave, User  # noqa: E402

ENGINE = build_engine(settings.database_url)
SessionFactory = sessionmaker(bind=ENGINE, expire_on_commit=False)


@pytest.fixture()
def db() -> Session:
    """A session bound to a freshly recreated test database."""
    from app.services import query_cache

    query_cache.clear()
    Base.metadata.drop_all(ENGINE)
    Base.metadata.create_all(ENGINE)
    session = SessionFactory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def save(db: Session) -> FmSave:
    """A default user and save."""
    user = User(username="local", display_name="测试用户")
    db.add(user)
    db.commit()
    record = FmSave(user_id=user.id, name="测试存档", game_version="27.0", game_build="test", is_active=True)
    db.add(record)
    db.commit()
    return record


@pytest.fixture()
def client(db: Session) -> TestClient:
    """API client wired to the test session."""
    app = create_app()

    def _override() -> Session:
        return db

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as test_client:
        yield test_client
