"""V3.2.7.2 真实验收：存档身份/会话/采集上下文端到端（真实 HTTP + 真实 SQLite）。

不启动 FM27 时，本脚本只证明后端协议行为；真实“游戏内切换存档”仍记为 NOT_RUN。
身份指纹取自 2026-11-24 对真实存档 A/B 的实测结果（见 docs/evidence/v3.2.7/save-context/live-http.json），
本脚本不伪造 FM27 内存读取。

用法：
    python scripts/acceptance-save-identity-e2e.py
证据写入 docs/evidence/v3.2.7.2/save-identity-e2e/。
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
EVIDENCE = ROOT / "docs" / "evidence" / "v3.2.7.2" / "save-identity-e2e"

FINGERPRINT_A = "si:v1:file:b887415ab528890d6364a3bb2e5a36e485b8e9a823229ba553863a8c67418083"
FINGERPRINT_B = "si:v1:file:ab0bd79502eec32b392f86847344014073486a0c218362b0faccef58e8672665"
GAME_BUILD = "26620374"

scenarios: list[dict[str, Any]] = []
failures: list[str] = []


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def request(
    base: str,
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    url = f"{base}{path}{query}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as error:
        payload = json.loads(error.read() or b"null")
        return error.code, payload


def record(
    label: str,
    method: str,
    path: str,
    params: dict[str, Any] | None,
    body: dict[str, Any] | None,
    status: int,
    payload: Any,
    *,
    expect_status: int,
    check: str,
    ok: bool,
) -> None:
    scenarios.append(
        {
            "label": label,
            "request": {"method": method, "path": path, "params": params or {}, "body": body},
            "response": {"status": status, "body": payload},
            "expect": {"status": expect_status, "check": check},
            "ok": ok and status == expect_status,
        }
    )
    if status != expect_status or not ok:
        failures.append(f"{label}: 期望 {expect_status}/{check}，实际 {status}")


def error_code(payload: Any) -> str | None:
    if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
        value = payload["error"].get("code")
        return str(value) if value is not None else None
    return None


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="sm-saveidentity-e2e-"))
    db_path = work / "live.db"
    data_dir = work / "data"
    log_path = EVIDENCE / "server.log"
    env = os.environ.copy()
    env["SCOUTMIND_DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    env["SCOUTMIND_DATA_DIR"] = str(data_dir)
    env.pop("SCOUTMIND_API_TOKEN", None)

    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, check=True)
    port = free_port()
    base = f"http://127.0.0.1:{port}/api/v1"
    log_handle = log_path.open("w", encoding="utf-8")
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "info"],
        cwd=BACKEND,
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )

    try:
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                status, payload = request(base, "GET", "/health")
                if status == 200:
                    break
            except Exception:  # noqa: BLE001 - 启动探活
                time.sleep(0.4)
        else:
            raise RuntimeError("后端未在 60 秒内启动")

        record("health", "GET", "/health", None, None, 200, payload, expect_status=200, check="status=ok", ok=payload.get("status") == "ok")

        status, save_a = request(base, "POST", "/saves", body={"name": "E2E 存档 A", "game_version": "27.1", "game_build": GAME_BUILD})
        record("create_save_a", "POST", "/saves", None, {"name": "E2E 存档 A"}, status, save_a, expect_status=201, check="返回存档 A", ok=isinstance(save_a, dict) and "id" in save_a)
        status, save_b = request(base, "POST", "/saves", body={"name": "E2E 存档 B", "game_version": "27.1", "game_build": GAME_BUILD})
        record("create_save_b", "POST", "/saves", None, {"name": "E2E 存档 B"}, status, save_b, expect_status=201, check="返回存档 B", ok=isinstance(save_b, dict) and "id" in save_b)
        save_a_id = int(save_a["id"])
        save_b_id = int(save_b["id"])

        register_a = {
            "fingerprint": FINGERPRINT_A,
            "fingerprint_version": 1,
            "identity_status": "candidate",
            "confidence": "medium",
            "kind": "save_file",
            "game_build": GAME_BUILD,
            "plugin_version": "27.1",
            "evidence": [
                {"type": "save_file_hash", "source": "file", "hash": "b887415ab5", "confidence": "medium"},
            ],
            "agent_id": "acceptance-e2e",
            "session_key": f"{os.getpid()}:agent-start:{GAME_BUILD}",
        }
        status, identity_a = request(base, "POST", "/save-identities/register", body=register_a, params={"save_id": save_a_id})
        record("register_a_candidate", "POST", "/save-identities/register", {"save_id": save_a_id}, register_a, status, identity_a, expect_status=200, check="identity_status=candidate", ok=identity_a.get("identity_status") == "candidate")
        identity_a_id = int(identity_a["identity_id"])

        status, duplicate = request(base, "POST", "/save-identities/register", body=register_a, params={"save_id": save_a_id})
        record("register_a_idempotent", "POST", "/save-identities/register", {"save_id": save_a_id}, register_a, status, duplicate, expect_status=200, check="同一 identity_id 且证据不重复", ok=duplicate.get("identity_id") == identity_a_id and len(duplicate.get("evidence", [])) == len(identity_a.get("evidence", [])))

        declared_verified = {**register_a, "identity_status": "verified", "confidence": "verified"}
        status, capped = request(base, "POST", "/save-identities/register", body=declared_verified, params={"save_id": save_a_id})
        record("client_cannot_self_verify", "POST", "/save-identities/register", {"save_id": save_a_id}, declared_verified, status, capped, expect_status=200, check="客户端声明 verified 仍被证据封顶为 candidate", ok=capped.get("identity_status") == "candidate")

        session_a1 = {
            "identity_id": identity_a_id,
            "session_key": f"{os.getpid()}:a1:{GAME_BUILD}",
            "process_id": os.getpid(),
            "process_start_time": now_iso(),
            "game_build": GAME_BUILD,
            "plugin_version": "27.1",
            "agent_id": "acceptance-e2e",
        }
        status, session_created = request(base, "POST", "/save-sessions/start", body=session_a1, params={"save_id": save_a_id})
        record("session_for_candidate_is_created", "POST", "/save-sessions/start", {"save_id": save_a_id}, session_a1, status, session_created, expect_status=200, check="未验证身份只能得到 created", ok=session_created.get("status") == "created")
        session_a1_id = int(session_created["session_id"])

        heartbeat_unverified = {"identity_id": identity_a_id, "fingerprint": FINGERPRINT_A, "game_build": GAME_BUILD}
        status, heartbeat_body = request(base, "POST", f"/save-sessions/{session_a1_id}/heartbeat", body=heartbeat_unverified, params={"save_id": save_a_id})
        record("heartbeat_blocks_unverified", "POST", f"/save-sessions/{session_a1_id}/heartbeat", {"save_id": save_a_id}, heartbeat_unverified, status, heartbeat_body, expect_status=409, check="save_identity_unverified", ok=error_code(heartbeat_body) == "save_identity_unverified")

        verify_body = {"confirmed_fingerprint": FINGERPRINT_A, "basis": "验收：人工确认界面生涯与存档 A 一致", "actor": "acceptance"}
        status, verified_a = request(base, "POST", f"/save-identities/{identity_a_id}/verify", body=verify_body, params={"save_id": save_a_id})
        record("verify_a", "POST", f"/save-identities/{identity_a_id}/verify", {"save_id": save_a_id}, verify_body, status, verified_a, expect_status=200, check="identity_status=verified", ok=verified_a.get("identity_status") == "verified")

        session_a2 = {**session_a1, "session_key": f"{os.getpid()}:a2:{GAME_BUILD}"}
        status, session_verified = request(base, "POST", "/save-sessions/start", body=session_a2, params={"save_id": save_a_id})
        record("session_after_verify", "POST", "/save-sessions/start", {"save_id": save_a_id}, session_a2, status, session_verified, expect_status=200, check="status=verified", ok=session_verified.get("status") == "verified")
        session_a2_id = int(session_verified["session_id"])

        heartbeat_ok = {"identity_id": identity_a_id, "fingerprint": FINGERPRINT_A, "game_build": GAME_BUILD}
        status, heartbeat_body = request(base, "POST", f"/save-sessions/{session_a2_id}/heartbeat", body=heartbeat_ok, params={"save_id": save_a_id})
        record("heartbeat_ok", "POST", f"/save-sessions/{session_a2_id}/heartbeat", {"save_id": save_a_id}, heartbeat_ok, status, heartbeat_body, expect_status=200, check="status=verified", ok=heartbeat_body.get("status") == "verified")

        capture_body = {"game_date": "2026-11-25", "reader_version": "0.1.0", "game_build": GAME_BUILD, "scan_scope": "players", "status": "scanning", "revision": 0}
        context = {"save_id": save_a_id, "save_identity_id": identity_a_id, "save_session_id": session_a2_id}
        status, capture = request(base, "POST", "/captures", body=capture_body, params=context)
        record("capture_with_verified_context", "POST", "/captures", context, capture_body, status, capture, expect_status=201, check="采集记录带身份/会话归属", ok=capture.get("save_identity_id") == identity_a_id and capture.get("save_session_id") == session_a2_id)
        capture_id = int(capture["id"])

        patch_ok = {"status": "completed"}
        status, patched = request(base, "PATCH", f"/captures/{capture_id}", body=patch_ok, params=context)
        record("capture_patch_with_context", "PATCH", f"/captures/{capture_id}", context, patch_ok, status, patched, expect_status=200, check="status=completed", ok=patched.get("status") == "completed")

        cross = {"identity_id": identity_a_id, "session_key": f"{os.getpid()}:b-cross:{GAME_BUILD}", "game_build": GAME_BUILD}
        status, cross_body = request(base, "POST", "/save-sessions/start", body=cross, params={"save_id": save_b_id})
        record("cross_save_session_rejected", "POST", "/save-sessions/start", {"save_id": save_b_id}, cross, status, cross_body, expect_status=409, check="save_context_mismatch", ok=error_code(cross_body) == "save_context_mismatch")

        switch_heartbeat = {"identity_id": identity_a_id, "fingerprint": FINGERPRINT_B, "game_build": GAME_BUILD}
        status, switch_body = request(base, "POST", f"/save-sessions/{session_a2_id}/heartbeat", body=switch_heartbeat, params={"save_id": save_a_id})
        record("switch_invalidates_session", "POST", f"/save-sessions/{session_a2_id}/heartbeat", {"save_id": save_a_id}, switch_heartbeat, status, switch_body, expect_status=409, check="指纹不一致 → 会话失效", ok=error_code(switch_body) == "save_context_mismatch")

        status, detail = request(base, "GET", f"/save-identities/{identity_a_id}", params={"save_id": save_a_id})
        blocked = not detail.get("capture_allowed") and any("invalidated" in item for item in detail.get("blockers", []))
        record("gate_blocks_after_switch", "GET", f"/save-identities/{identity_a_id}", {"save_id": save_a_id}, None, status, detail, expect_status=200, check="capture_allowed=false 且阻断原因为会话失效", ok=blocked)

        status, stale_patch = request(base, "PATCH", f"/captures/{capture_id}", body={"status": "failed"}, params=context)
        record("stale_session_cannot_patch", "PATCH", f"/captures/{capture_id}", context, {"status": "failed"}, status, stale_patch, expect_status=409, check="save_session_invalidated", ok=error_code(stale_patch) == "save_session_invalidated")

        status, reg_a_again = request(base, "POST", "/save-identities/register", body=declared_verified, params={"save_id": save_a_id})
        record("return_after_switch", "POST", "/save-identities/register", {"save_id": save_a_id}, declared_verified, status, reg_a_again, expect_status=200, check="身份仍为 verified", ok=reg_a_again.get("identity_status") == "verified")

        session_a3 = {**session_a1, "session_key": f"{os.getpid()}:a3:{GAME_BUILD}"}
        status, session_recovered = request(base, "POST", "/save-sessions/start", body=session_a3, params={"save_id": save_a_id})
        record("session_recovered", "POST", "/save-sessions/start", {"save_id": save_a_id}, session_a3, status, session_recovered, expect_status=200, check="status=verified", ok=session_recovered.get("status") == "verified")
        session_a3_id = int(session_recovered["session_id"])

        status, gate_ok = request(base, "GET", f"/save-identities/{identity_a_id}", params={"save_id": save_a_id})
        record("gate_allows_recovered", "GET", f"/save-identities/{identity_a_id}", {"save_id": save_a_id}, None, status, gate_ok, expect_status=200, check="capture_allowed=true", ok=gate_ok.get("capture_allowed") is True and gate_ok.get("blockers") == [])

        register_b_on_a = {
            **register_a,
            "fingerprint": FINGERPRINT_B,
            "identity_status": "verified",
            "confidence": "verified",
            "evidence": [
                {"type": "save_file_hash", "source": "file", "hash": "ab0bd795", "confidence": "medium"},
                {"type": "game_internal_save_id", "source": "memory", "hash": "internal-b", "confidence": "high"},
            ],
        }
        status, conflict = request(base, "POST", "/save-identities/register", body=register_b_on_a, params={"save_id": save_a_id})
        record("different_fingerprint_conflict", "POST", "/save-identities/register", {"save_id": save_a_id}, register_b_on_a, status, conflict, expect_status=200, check="新指纹被标记 conflict，旧 verified 不被替换", ok=conflict.get("identity_status") == "conflict" and conflict.get("identity_id") != identity_a_id)

        status, gate_conflict = request(base, "GET", f"/save-identities/{identity_a_id}", params={"save_id": save_a_id})
        conflict_blocked = not gate_conflict.get("capture_allowed") and any("冲突" in item for item in gate_conflict.get("blockers", []))
        record("gate_blocks_on_conflict", "GET", f"/save-identities/{identity_a_id}", {"save_id": save_a_id}, None, status, gate_conflict, expect_status=200, check="存在未处理冲突 → 停止采集", ok=conflict_blocked)

        status, audit_a = request(base, "GET", "/save-identity-audit", params={"save_id": save_a_id, "limit": 200})
        event_types = {item.get("event_type") for item in audit_a.get("items", [])}
        required = {"registered", "user_confirmed", "session_started", "session_invalidated", "conflict_detected"}
        record("audit_trail", "GET", "/save-identity-audit", {"save_id": save_a_id, "limit": 200}, None, status, {"total": audit_a.get("total"), "event_types": sorted(event_types)}, expect_status=200, check="包含注册/确认/会话失效/冲突审计", ok=required.issubset(event_types))

        status, audit_b = request(base, "GET", "/save-identity-audit", params={"save_id": save_b_id, "limit": 200})
        record("audit_save_isolation", "GET", "/save-identity-audit", {"save_id": save_b_id, "limit": 200}, None, status, {"total": audit_b.get("total")}, expect_status=200, check="存档 B 无 A 的审计事件", ok=audit_b.get("total") == 0)

        environment = {
            "captured_at": now_iso(),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "database": str(db_path),
            "api": base,
            "server_pid": server.pid,
            "game_build": GAME_BUILD,
            "real_save_fingerprints": {
                "A": FINGERPRINT_A,
                "B": FINGERPRINT_B,
                "provenance": "2026-11-24 实测真实 .fm 文件（docs/evidence/v3.2.7/save-context/live-http.json）；本轮未启动 FM27",
            },
            "limits": "真实 HTTP + 真实 SQLite；未运行 FM27 游戏内切换，故“游戏内切换存档采集”仍为 NOT_RUN",
        }
        (EVIDENCE / "environment.json").write_text(json.dumps(environment, ensure_ascii=False, indent=2), encoding="utf-8")
        result = {"environment": environment, "scenarios": scenarios, "failures": failures, "ok": not failures}
        (EVIDENCE / "live-http.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        sums = []
        for name in ("environment.json", "live-http.json", "server.log", "migration-safety.json"):
            target = EVIDENCE / name
            if target.exists():
                digest = hashlib.sha256(target.read_bytes()).hexdigest()
                sums.append(f"{digest}  {name}")
        (EVIDENCE / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="utf-8")
    finally:
        server.terminate()
        try:
            server.wait(timeout=15)
        except subprocess.TimeoutExpired:
            server.kill()
        log_handle.close()
        shutil.rmtree(work, ignore_errors=True)

    total = len(scenarios)
    print(f"PASS {total - len(failures)} / {total}")
    for failure in failures:
        print(f"FAIL {failure}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
