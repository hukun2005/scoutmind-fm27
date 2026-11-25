"""进程内取消信号（V3.2.7.4，V3.2.7.5 补充跨进程兜底）。

导入 Worker 与 HTTP 取消请求通常运行在同一个后端进程内，此时本注册表提供最快速的取消响应。
跨进程部署时本注册表无法直接生效，因此 Worker 的安全检查点还会读取数据库中的任务状态
（``cancel_requested`` / ``cancelled``），并且终态写入带有 ``status='running'`` 守卫：
取消一旦先落库，业务写入整体回滚，不会被覆盖成 ``succeeded``。
"""

from __future__ import annotations

import threading

_events: dict[int, threading.Event] = {}
_lock = threading.Lock()


def request_cancel(job_id: int) -> None:
    """为某个导入任务置位取消信号；重复调用无副作用。"""
    with _lock:
        _events.setdefault(int(job_id), threading.Event()).set()


def is_requested(job_id: int) -> bool:
    with _lock:
        event = _events.get(int(job_id))
        return event is not None and event.is_set()


def clear(job_id: int) -> None:
    """任务进入终态后清理信号，避免注册表无限增长。"""
    with _lock:
        _events.pop(int(job_id), None)
