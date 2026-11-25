"""V3.2.7.5 运行期验收共享工具：临时后端进程生命周期 + 协议客户端。

供 ``verify_network_recovery.py``（C）、``verify_cancel_two_process.py``（D）、
``verify_backend_restart_recovery.py``（E）复用。

安全边界与 ``run_acceptance.ps1`` 一致：

* 只监听 ``127.0.0.1``；
* 只使用临时 SQLite 与临时数据目录，绝不连接生产库；
* 使用合成指纹（``si:v1:test:*``）与合成扫描报文，不冒用真实 Reader 结论；
* 不读取游戏内存，不修改任何游戏文件。
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"


def free_port() -> int:
    """向操作系统要一个当前空闲的回环端口。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class Api:
    """极简 JSON 协议客户端；传输失败返回 ``(0, {"error": ...})`` 而不是抛异常。"""

    def __init__(self, base: str, token: str | None = None) -> None:
        self.base = base.rstrip("/")
        self.token = token

    def request(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        params: dict[str, Any] | None = None,
        raw: bytes | None = None,
        timeout: int = 120,
    ) -> tuple[int, Any]:
        query = f"?{urllib.parse.urlencode(params)}" if params else ""
        data = raw if raw is not None else (json.dumps(body).encode("utf-8") if body is not None else None)
        req = urllib.request.Request(f"{self.base}{path}{query}", data=data, method=method)
        req.add_header("Accept", "application/json")
        if self.token:
            req.add_header("X-ScoutMind-Token", self.token)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.status, json.loads(response.read() or b"null")
        except urllib.error.HTTPError as error:
            try:
                payload = json.loads(error.read() or b"null")
            except Exception:  # noqa: BLE001 - 记录原始状态码
                payload = None
            return error.code, payload
        except Exception as exc:  # noqa: BLE001 - 传输失败按协议记录
            return 0, {"error": {"code": "transport_error", "message": f"{type(exc).__name__}: {exc}"}}

    def error_code(self, payload: Any) -> str | None:
        if isinstance(payload, dict):
            for key in ("error", "detail"):
                value = payload.get(key)
                if isinstance(value, dict) and value.get("code") is not None:
                    return str(value["code"])
        return None


def payload_bytes(scan_id: str, players: int = 0, marker: str | None = None) -> bytes:
    """合成扫描报文；``players > 0`` 时生成对应数量的球员用于制造真实导入耗时。

    球员 UID 带 ``scan_id`` 前缀：后端按 ``(save, save_local_uid)`` upsert 球员实例，
    不同扫描若复用同一批 UID 会互相覆盖，``players`` 计数就不再随扫描累加，断言会失真。
    同一 ``scan_id`` 重发时 UID 不变，这才是「同一份报文重试」的真实语义。
    """
    document: dict[str, Any] = {
        "schema_version": "1.0",
        "source": "synthetic_fixture",
        "scan": {"scan_id": scan_id, "observed_at": "2026-11-25T00:00:00"},
        "players": [
            {
                "save_local_uid": f"{scan_id}-p{index}",
                "name": f"Player {index}",
                "club_uid": "C1",
                "age": 20 + index % 15,
                "ca": 100 + index % 100,
                "pa": 120 + index % 80,
            }
            for index in range(players)
        ],
        "transfers": [],
    }
    if marker:
        document["warnings"] = [f"acceptance-marker:{marker}"]
    return json.dumps(document, ensure_ascii=False).encode("utf-8")


class BackendProcess:
    """临时后端进程：临时 SQLite + alembic + uvicorn，支持正常停止与硬杀。"""

    def __init__(self, port: int | None = None, workdir: Path | None = None) -> None:
        self.port = port or free_port()
        self.workdir = Path(workdir or Path(tempfile.mkdtemp(prefix="scoutmind-cde-")))
        self.db_path = self.workdir / "acceptance.db"
        self.data_dir = self.workdir / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_url = "sqlite:///" + self.db_path.as_posix()
        self.api = Api(f"http://127.0.0.1:{self.port}/api/v1")
        self._proc: subprocess.Popen[bytes] | None = None
        self._stdout_log = self.workdir / "backend-stdout.log"
        self._stderr_log = self.workdir / "backend-stderr.log"
        # 验收默认 warning；排查断线行为时可调到 info 以观察访问日志。
        self.log_level = "warning"
        self.starts = 0

    # -- 进程管理 ---------------------------------------------------------------------------------------------------

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["SCOUTMIND_DATABASE_URL"] = self.db_url
        env["SCOUTMIND_DATA_DIR"] = str(self.data_dir)
        return env

    def migrate(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=BACKEND_DIR,
            env=self._env(),
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            raise SystemExit(f"alembic upgrade head 失败：{result.stderr[-2000:]}")

    def start(self) -> None:
        self.starts += 1
        out = open(self._stdout_log, "ab")
        err = open(self._stderr_log, "ab")
        out.write(f"\n=== backend start #{self.starts} ===\n".encode())
        out.flush()
        self._proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--app-dir",
                str(BACKEND_DIR),
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--log-level",
                self.log_level,
            ],
            env=self._env(),
            stdout=out,
            stderr=err,
        )
        out.close()
        err.close()

    def wait_healthy(self, timeout: float = 60.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status, _ = self.api.request("GET", "/health", timeout=5)
            if status == 200:
                return True
            if self._proc is not None and self._proc.poll() is not None:
                return False
            time.sleep(0.25)
        return False

    def start_and_wait(self, timeout: float = 60.0) -> None:
        self.start()
        if not self.wait_healthy(timeout):
            stderr = self._stderr_log.read_text(encoding="utf-8", errors="replace")[-2000:]
            raise SystemExit(f"临时后端未在 {timeout}s 内就绪；stderr 末尾：\n{stderr}")

    def stop(self) -> None:
        """正常停止（等价于服务优雅退出）。"""
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=15)
        self._proc = None

    def kill(self) -> None:
        """硬杀（模拟崩溃；不做任何清理，交给重启后的恢复逻辑）。"""
        if self._proc is not None and self._proc.poll() is None:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(self._proc.pid)],
                    capture_output=True,
                    timeout=30,
                )
            else:
                self._proc.kill()
            self._proc.wait(timeout=30)
        self._proc = None

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    # -- 验收协议步骤 -------------------------------------------------------------------------------------------------

    def setup_save_context(self, run: str, agent_id: str = "acceptance-cde") -> dict[str, int]:
        """创建存档 + 合成身份（verified）+ 可写会话，返回写入上下文。"""
        status, save = self.api.request("POST", "/saves", body={"name": f"cde-{run}"})
        if status != 201:
            raise SystemExit(f"创建存档失败：{status} {save}")
        save_id = int(save["id"])
        fingerprint = f"si:v1:test:cde:{run}"
        status, payload = self.api.request(
            "POST",
            "/save-identities/register",
            params={"save_id": save_id},
            body={
                "fingerprint": fingerprint,
                "fingerprint_version": 1,
                "identity_status": "candidate",
                "confidence": "medium",
                "kind": "save_file",
                "evidence": [
                    {"type": "save_file_hash", "source": "file", "hash": fingerprint, "confidence": "medium"}
                ],
                "agent_id": agent_id,
                "session_key": f"acceptance-{uuid.uuid4().hex}",
            },
        )
        if status != 200:
            raise SystemExit(f"注册身份失败：{status} {payload}")
        identity_id = int(payload["identity_id"])
        status, payload = self.api.request(
            "POST",
            f"/save-identities/{identity_id}/verify",
            params={"save_id": save_id},
            body={"confirmed_fingerprint": fingerprint, "basis": "运行期验收合成身份", "actor": agent_id},
        )
        if status != 200:
            raise SystemExit(f"确认身份失败：{status} {payload}")
        status, payload = self.api.request(
            "POST",
            "/save-sessions/start",
            params={"save_id": save_id},
            body={
                "identity_id": identity_id,
                "session_key": f"{uuid.uuid4().int % 100000}:cde-{run}",
                "process_id": 404,
                "agent_id": agent_id,
            },
        )
        if status != 200:
            raise SystemExit(f"启动会话失败：{status} {payload}")
        # 键名与写接口的查询参数一致，调用方可以直接 {**context, "operation_id": ...}。
        return {
            "save_id": save_id,
            "save_identity_id": identity_id,
            "save_session_id": int(payload["session_id"]),
        }

    def heartbeat(self, context: dict[str, int], reconnected: bool = False) -> tuple[int, Any]:
        return self.api.request(
            "POST",
            f"/save-sessions/{context['save_session_id']}/heartbeat",
            params={"save_id": context["save_id"]},
            body={"identity_id": context["save_identity_id"], "reconnected": reconnected},
        )

    def save_summary(self, save_id: int) -> dict[str, Any]:
        status, summary = self.api.request("GET", f"/saves/{save_id}/summary", timeout=60)
        if status != 200:
            raise SystemExit(f"读取存档汇总失败：{status} {summary}")
        return summary

    def coverage(self, save_id: int) -> dict[str, int]:
        """存档覆盖度：``players`` 是去重后的球员实例数，``snapshots`` 每次成功导入按次追加。

        「是否重复写入」看 ``snapshots``：同一份报文被写两次，快照会翻倍，而球员实例不会。
        """
        coverage = self.save_summary(save_id).get("coverage", {})
        return {
            "players": int(coverage.get("players") or 0),
            "snapshots": int(coverage.get("snapshots") or 0),
            "transfers": int(coverage.get("transfers") or 0),
        }

    def jobs_for_scan(self, save_id: int, scan_id: str) -> list[dict[str, Any]]:
        listing = self.api.request("GET", "/imports", params={"save_id": save_id, "limit": 200})[1]
        return [item for item in (listing.get("items") or []) if item.get("scan_id") == scan_id]

    def audit_events(self, save_id: int) -> set[str]:
        audit = self.api.request("GET", "/save-identity-audit", params={"save_id": save_id, "limit": 500})[1]
        return {item.get("event_type") for item in (audit.get("items") or [])}

    def cleanup(self) -> None:
        self.stop()


def new_check_list() -> tuple[list[dict[str, Any]], list[str]]:
    return [], []


_LOCAL_PATH = re.compile(r"[A-Za-z]:\\[^\s\"']*")


def _redact(value: Any) -> Any:
    """把证据里的本机绝对路径替换为占位符，避免把用户名/临时目录带进仓库。"""
    if isinstance(value, dict):
        return {key: _redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return _LOCAL_PATH.sub("<local-path>", value)
    return value


def write_evidence(
    output: Path,
    filename: str,
    *,
    tool: str,
    checks: list[dict[str, Any]],
    failures: list[str],
    partials: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    result = {
        "tool": tool,
        "synthetic_identity": True,
        "real_fm27": False,
        "checks": checks,
        "failures": failures,
        "partials": partials or [],
        "ok": not failures,
        "status": "PASS" if not failures else "FAIL",
    }
    if extra:
        result.update(extra)
    result = _redact(result)
    target = output / filename
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{'PASS' if not failures else 'FAIL'} {tool}: {len(checks) - len(failures)}/{len(checks)}")
    for partial in result["partials"]:
        print(f"PARTIAL {partial}")
    for failure in failures:
        print(f"FAIL {failure}")
    print(f"证据：{target}")
    return target
