"""Database engine, session factory and FastAPI dependency."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import settings
from .models import Base


def build_engine(url: str, **kwargs: Any) -> Engine:
    """Create an engine configured for the SQLite development default or a PostgreSQL deployment."""
    connect_args: dict[str, Any] = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    engine = create_engine(url, connect_args=connect_args, future=True, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


engine = build_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


def init_db() -> None:
    """Create every table declared on the models.

    Alembic owns the schema in every supported deployment; this helper exists for tests and for explicitly
    bootstrapping a throwaway database. It never stamps a migration version.
    """
    settings.ensure_directories()
    Base.metadata.create_all(bind=engine)


def schema_ready() -> bool:
    """True when the core schema is present, so the app can fail loud before serving requests."""
    from sqlalchemy import inspect

    return inspect(engine).has_table("players")


def alembic_managed() -> bool:
    """True when the schema carries an Alembic version stamp."""
    from sqlalchemy import inspect

    return inspect(engine).has_table("alembic_version")


def get_db() -> Iterator[Session]:
    """Yield a request-scoped session and always close it."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
