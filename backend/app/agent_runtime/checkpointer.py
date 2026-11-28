"""Checkpoint 后端：桌面默认独立 SQLite（WAL），测试用内存，PostgreSQL 需显式依赖。

不与业务库共用连接：Checkpoint 写入频率高，独立文件可以避免与导入事务争抢主库锁。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from ..config import settings
from .exceptions import CheckpointUnsupported, RuntimeUnavailable


def checkpoint_path() -> Path:
    configured = (settings.agent_checkpoint_path or "").strip()
    path = Path(configured).expanduser() if configured else settings.data_dir / "agent_checkpoints.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def build_checkpointer(kind: str = "auto") -> Any:
    """构造 checkpointer；``kind="memory"`` 只允许测试显式使用。"""
    if kind == "memory":
        try:
            from langgraph.checkpoint.memory import InMemorySaver
        except ImportError as exc:  # pragma: no cover - 依赖缺失时明确失败
            raise RuntimeUnavailable("LangGraph 未安装，无法使用内存 Checkpoint") from exc
        return InMemorySaver()

    if settings.database_url.startswith("postgres"):
        try:
            from langgraph.checkpoint.postgres import PostgresSaver  # noqa: F401
        except ImportError as exc:
            raise CheckpointUnsupported(
                "PostgreSQL Checkpoint 需要安装 langgraph-checkpoint-postgres，当前部署未启用"
            ) from exc
        raise CheckpointUnsupported("PostgreSQL Checkpoint 需要由部署层注入连接，当前 Runtime 不支持自动建连")

    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
    except ImportError as exc:
        raise RuntimeUnavailable("LangGraph checkpoint 依赖缺失（langgraph-checkpoint-sqlite）") from exc

    path = checkpoint_path()
    connection = sqlite3.connect(str(path), check_same_thread=False)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        saver = SqliteSaver(connection)
        saver.setup()
    except Exception:
        connection.close()
        raise
    return saver


def delete_thread_checkpoints(checkpointer: Any, thread_id: str) -> bool:
    """删除单个任务的 checkpoint（保留业务审计）；后端不支持时返回 False。"""
    remover = getattr(checkpointer, "delete_thread", None)
    if remover is None:
        return False
    try:
        remover(thread_id)
        return True
    except Exception:  # noqa: BLE001 - 清理失败不影响任务结果
        return False
