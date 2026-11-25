"""进程内取消信号（V3.2.7.4）。

导入 Worker 与 HTTP 取消请求运行在同一个后端进程内（与 ``uploads.import_slot`` 的进程内
限流假设一致）。跨进程部署时本注册表无法直接生效：此时取消仍会写入数据库状态，
Worker 在任务结束前无法感知，最终由 ``GET /imports/{id}`` 显示 ``cancel_requested`` 或已完成的真实状态。
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
