"""V3.3.2 进程内查询缓存：按存档与数据版本隔离，数据变化立即失效。

只缓存可重算的统计结果（覆盖度、阵容统计、引援评分）。缓存键包含 ``save_id`` 与
``data_revision``（最大快照/实例/转会 ID + 战术模板更新时间），因此：

* 任何一次导入新增快照或转会都会改变版本号，旧缓存不会再被命中；
* 不同存档的键不同，不会串数据；
* 另有 60 秒 TTL，避免长期占用内存。

不缓存关注项、备注、球员详情等用户可感知的即时数据。
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Hashable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import PlayerInstance, PlayerSnapshot, TacticalProfile, Transfer
from ..utils import iso

TTL_SECONDS = 60.0
MAX_ENTRIES = 128

_lock = threading.Lock()
_store: dict[Hashable, tuple[float, Any]] = {}


def data_revision(session: Session, save_id: int) -> tuple[Any, ...]:
    """当前存档的数据版本；只做四次主键/索引聚合，成本固定且很小。"""
    snapshot_id = session.scalar(select(func.max(PlayerSnapshot.id)))
    instance_id = session.scalar(select(func.max(PlayerInstance.id)))
    transfer_id = session.scalar(select(func.max(Transfer.id)))
    profile_updated = session.scalar(select(func.max(TacticalProfile.updated_at)))
    return (
        save_id,
        int(snapshot_id or 0),
        int(instance_id or 0),
        int(transfer_id or 0),
        iso(profile_updated) if profile_updated is not None else "",
    )


def _freeze(value: Any) -> Hashable:
    """把字典参数转成可哈希的稳定键。"""
    if isinstance(value, dict):
        return tuple(sorted((key, _freeze(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def cached(
    session: Session,
    save_id: int,
    name: str,
    params: Any,
    compute: Callable[[], Any],
    ttl: float = TTL_SECONDS,
) -> Any:
    """命中返回缓存；未命中执行 ``compute`` 并写入。异常不缓存。"""
    key = (save_id, data_revision(session, save_id), name, _freeze(params))
    now = time.monotonic()
    with _lock:
        hit = _store.get(key)
        if hit is not None and now - hit[0] < ttl:
            return hit[1]
    value = compute()
    with _lock:
        if len(_store) >= MAX_ENTRIES:
            _store.clear()
        _store[key] = (now, value)
    return value


def clear() -> None:
    """清空全部条目；测试与显式失效（如导入完成回调）使用。"""
    with _lock:
        _store.clear()


def stats() -> dict[str, int]:
    """当前条目数，供健康检查/报告使用。"""
    with _lock:
        return {"entries": len(_store)}
