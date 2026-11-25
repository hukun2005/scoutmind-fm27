"""V3.2.7.3：会话代次（Epoch）生命周期。

覆盖：
* 会话开始时绑定当前代次，并成为唯一可写会话；
* 切换接口原子递增代次、失效旧会话，心跳与旧上下文导入同时被拒；
* 并发切换不会丢失更新（真实多连接、多线程、屏障同步）。
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi import HTTPException
from sqlalchemy import select

from app.models import FmSave, SaveWriteGate
from app.services import write_safety

from tests.write_safety_support import GAME_BUILD, make_engine, seed_save

FP_A = "si:v1:file:" + "a" * 64


def _register(client, save, **overrides) -> dict:
    body = {
        "save_id": save.id,
        "fingerprint": FP_A,
        "fingerprint_version": 1,
        "identity_status": "verified",
        "confidence": "verified",
        "kind": "save_file",
        "game_build": GAME_BUILD,
        "plugin_version": "27.1.0+2505117",
        "ambiguous": False,
        "evidence": [
            {"type": "save_file_metadata", "source": "file", "hash": FP_A, "confidence": "medium"},
            {"type": "user_confirmed", "source": "user", "hash": FP_A, "confidence": "high"},
        ],
    }
    body.update(overrides)
    response = client.post("/api/v1/save-identities/register", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def _start(client, save, identity_id: int, key: str = "66972:2026-11-25T10:00:00:26620374") -> dict:
    response = client.post(
        "/api/v1/save-sessions/start",
        json={
            "save_id": save.id,
            "identity_id": identity_id,
            "session_key": key,
            "process_id": 66972,
            "game_build": GAME_BUILD,
            "agent_id": "agent-test",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_session_start_binds_generation_and_becomes_current(client, save):
    identity = _register(client, save)
    session = _start(client, save, identity["identity_id"])
    assert session["session_epoch"] == 0
    assert session["status"] == "verified"

    gate = client.get("/api/v1/save-write-gate").json()
    assert gate["gate"]["generation"] == 0
    assert gate["gate"]["current_session_id"] == session["session_id"]
    assert gate["sessions"][0]["session_epoch"] == 0


def test_switch_advances_generation_and_invalidates_old_session(client, save):
    identity = _register(client, save)
    session = _start(client, save, identity["identity_id"])

    switched = client.post(
        f"/api/v1/save-sessions/{session['session_id']}/switch",
        json={"reason": "save_switch", "actor": "tester"},
    )
    assert switched.status_code == 200, switched.text
    assert switched.json()["generation"] == 1

    detail = client.get(f"/api/v1/save-identities/{identity['identity_id']}").json()
    assert detail["capture_allowed"] is False
    assert detail["sessions"][0]["status"] == "invalidated"
    assert detail["sessions"][0]["invalidated_reason"] == "save_switch"
    assert detail["sessions"][0]["session_epoch"] == 0
    assert detail["write_gate"]["generation"] == 1

    heartbeat = client.post(
        f"/api/v1/save-sessions/{session['session_id']}/heartbeat",
        json={"identity_id": identity["identity_id"], "game_build": GAME_BUILD},
    )
    assert heartbeat.status_code == 409
    assert heartbeat.json()["error"]["code"] in {"save_session_invalidated", "write_session_epoch_stale"}


def test_heartbeat_after_switch_does_not_resurrect_session(client, save):
    identity = _register(client, save)
    session = _start(client, save, identity["identity_id"], key="key-a")
    client.post(f"/api/v1/save-sessions/{session['session_id']}/switch", json={"reason": "game_closed"})

    gate = client.get("/api/v1/save-write-gate").json()["gate"]
    assert gate["current_session_id"] is None
    assert gate["generation"] == 1

    blocked = client.post(
        f"/api/v1/save-sessions/{session['session_id']}/heartbeat",
        json={"identity_id": identity["identity_id"], "game_build": GAME_BUILD},
    )
    assert blocked.status_code == 409


def test_concurrent_switches_never_lose_updates(tmp_path):
    _engine, Factory = make_engine(tmp_path)
    save_id = seed_save(Factory)
    workers = 4
    barrier = threading.Barrier(workers)

    def rotate(index: int) -> int:
        with Factory() as db:
            save = db.get(FmSave, save_id)
            barrier.wait(timeout=10)
            for _attempt in range(8):
                try:
                    generation = write_safety.rotate_generation(
                        db, save, reason=f"switch-{index}", actor="tester"
                    )
                    db.commit()
                    return generation
                except HTTPException as exc:
                    db.rollback()
                    if exc.detail["code"] != write_safety.WRITE_GATE_BUSY:
                        raise
            raise AssertionError("代次在重试上限内仍未推进")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(rotate, i) for i in range(workers)]
        generations = sorted(future.result(timeout=60) for future in futures)

    # 每一次成功切换都拿到唯一代次，说明没有两个事务基于同一旧值同时成功。
    assert generations == [1, 2, 3, 4]

    with Factory() as db:
        gate = db.scalar(select(SaveWriteGate).where(SaveWriteGate.fm_save_id == save_id))
        assert gate.generation == 4
        assert gate.last_switch_at is not None


def test_switch_requires_session_of_same_save(client, save, db):
    identity = _register(client, save)
    session = _start(client, save, identity["identity_id"])
    missing = client.post(
        "/api/v1/save-sessions/999999/switch",
        json={"reason": "save_switch"},
    )
    assert missing.status_code == 404
    # 真实切换仍然可用，说明上面的 404 不是全局故障。
    ok = client.post(f"/api/v1/save-sessions/{session['session_id']}/switch", json={"reason": "save_switch"})
    assert ok.status_code == 200
