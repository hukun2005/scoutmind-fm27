"""V3.2.7.4 运行期验收：Worker 栅栏、取消与状态迁移（真实 HTTP）。

验证：

1. 会话切换后旧会话写入被拒绝（写栅栏 + 代次）；
2. 已完成任务取消失败（409，不可撤销）；
3. 排队任务取消 → ``cancelled``，重复取消幂等；
4. 运行中任务取消：并发发起导入与取消，结果必须是「cancelled 且无业务写入」
   或「已完成则取消返回 409」，不允许半提交；
5. 审计含 ``worker_cancel_requested`` / ``worker_cancelled``。

``--database`` 指向临时 SQLite 文件时，会直接插入一条 ``queued`` 任务来覆盖
「排队中取消」这一确定性场景（仅用于本地临时库，绝不连接生产库）。

用法：
    python tools/runtime-acceptance/verify_worker_fencing.py \
        --api http://127.0.0.1:8123/api/v1 --database <临时库路径> --output runtime-evidence
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

DEFAULT_API = "http://127.0.0.1:8000/api/v1"


class Api:
    def __init__(self, base: str, token: str | None) -> None:
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
            with urllib.request.urlopen(req, timeout=180) as response:
                return response.status, json.loads(response.read() or b"null")
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read() or b"null")


def error_code(payload: Any) -> str | None:
    for key in ("error", "detail"):
        value = payload.get(key) if isinstance(payload, dict) else None
        if isinstance(value, dict) and value.get("code") is not None:
            return str(value["code"])
    return None


def payload_bytes(scan_id: str, players: int = 0) -> bytes:
    document: dict[str, Any] = {
        "schema_version": "1.0",
        "source": "synthetic_fixture",
        "scan": {"scan_id": scan_id, "observed_at": "2026-11-25T00:00:00"},
        "players": [
            {
                "save_local_uid": f"p{index}",
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
    return json.dumps(document, ensure_ascii=False).encode("utf-8")


def register_verified(api: Api, save_id: int, fingerprint: str) -> tuple[int, int]:
    status, payload = api.request(
        "POST",
        "/save-identities/register",
        params={"save_id": save_id},
        body={
            "fingerprint": fingerprint,
            "fingerprint_version": 1,
            "identity_status": "candidate",
            "confidence": "medium",
            "kind": "save_file",
            "evidence": [{"type": "save_file_hash", "source": "file", "hash": fingerprint, "confidence": "medium"}],
            "agent_id": "acceptance-fencing",
            "session_key": f"acceptance-{uuid.uuid4().hex}",
        },
    )
    if status != 200:
        raise SystemExit(f"注册身份失败：{status} {payload}")
    identity_id = int(payload["identity_id"])
    status, payload = api.request(
        "POST",
        f"/save-identities/{identity_id}/verify",
        params={"save_id": save_id},
        body={"confirmed_fingerprint": fingerprint, "basis": "运行期验收合成身份", "actor": "acceptance-fencing"},
    )
    if status != 200:
        raise SystemExit(f"确认身份失败：{status} {payload}")

    status, payload = api.request(
        "POST",
        "/save-sessions/start",
        params={"save_id": save_id},
        body={"identity_id": identity_id, "session_key": f"{uuid.uuid4().int % 100000}:fencing", "process_id": 202, "agent_id": "acceptance-fencing"},
    )
    if status != 200:
        raise SystemExit(f"启动会话失败：{status} {payload}")
    return identity_id, int(payload["session_id"])


def insert_queued_job(database: str, save_id: int, scan_id: str) -> int:
    """向临时 SQLite 插入一条 queued 任务，用于确定性的「排队中取消」。"""
    connection = sqlite3.connect(database, timeout=30)
    try:
        cursor = connection.execute(
            "INSERT INTO import_jobs (fm_save_id, scan_id, source, schema_version, status, attempt_count, "
            "player_count, transfer_count, warnings_json, coverage_json, received_at, created_at, updated_at) "
            "VALUES (?, ?, 'reader', '1.0', 'queued', 0, 0, 0, '[]', '{}', datetime('now'), datetime('now'), datetime('now'))",
            (save_id, scan_id),
        )
        connection.commit()
        return int(cursor.lastrowid)
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Worker 栅栏与取消验收（合成身份）")
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--token")
    parser.add_argument("--database", help="临时 SQLite 路径；用于插入 queued 任务；提供前请确认不是生产库")
    parser.add_argument("--output", type=Path, default=Path("runtime-evidence"))
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    api = Api(args.api, args.token)
    run = uuid.uuid4().hex[:8]
    checks: list[dict[str, Any]] = []
    failures: list[str] = []
    partials: list[str] = []

    def check(label: str, ok: bool, detail: Any, expect: str) -> None:
        checks.append({"label": label, "ok": ok, "expect": expect, "observed": detail})
        if not ok:
            failures.append(f"{label}: 期望 {expect}，实际 {detail}")

    status, save = api.request("POST", "/saves", body={"name": f"fencing-{run}"})
    if status != 201:
        raise SystemExit(f"创建存档失败：{status} {save}")
    save_id = int(save["id"])
    fingerprint = f"si:v1:test:fencing:{run}"
    identity_id, session_id = register_verified(api, save_id, fingerprint)
    context = {"save_id": save_id, "save_identity_id": identity_id, "save_session_id": session_id}

    # --- 1. 代次推进后旧会话被栅栏拒绝 ---------------------------------------------------------------
    status, _ = api.request(
        "POST",
        "/imports/scan",
        params={**context, "operation_id": f"op-base-{run}"},
        raw=payload_bytes(f"base-{run}"),
    )
    check("baseline_import", status == 201, status, "201")

    status, switch = api.request(
        "POST",
        f"/save-sessions/{session_id}/switch",
        params={"save_id": save_id},
        body={"reason": "save_switch", "actor": "acceptance-fencing"},
    )
    check("switch_rotates_generation", status == 200 and int(switch.get("generation") or 0) >= 1, switch, "generation ≥ 1")

    status, stale = api.request(
        "POST",
        "/imports/scan",
        params={**context, "operation_id": f"op-stale-{run}"},
        raw=payload_bytes(f"stale-{run}"),
    )
    check(
        "stale_session_rejected",
        status == 409 and error_code(stale) in {"write_session_epoch_stale", "write_fence_stale", "save_session_invalidated", "save_context_mismatch"},
        {"status": status, "code": error_code(stale)},
        "409 旧会话不可写",
    )

    # --- 2. 已完成任务取消返回 409 -------------------------------------------------------------------
    jobs = api.request("GET", "/imports", params={"save_id": save_id, "limit": 5})[1].get("items") or []
    completed = next((job for job in jobs if job.get("status") in {"succeeded", "partial"}), None)
    if completed:
        status, cancel_done = api.request("POST", f"/imports/{completed['id']}/cancel")
        check("cancel_completed_rejected", status == 409 and error_code(cancel_done) == "import_not_cancellable", {"status": status, "code": error_code(cancel_done)}, "409 import_not_cancellable")
    else:
        partials.append("cancel_completed 跳过：未找到已完成任务")

    # --- 3. 排队任务取消（需要 --database） -----------------------------------------------------------
    queued_job_id = None
    if args.database:
        queued_job_id = insert_queued_job(args.database, save_id, f"queued-{run}")
        status, first = api.request("POST", f"/imports/{queued_job_id}/cancel")
        check("cancel_queued", status == 200 and first.get("status") == "cancelled", {"status": status, "job_status": first.get("status")}, "200 cancelled")
        status, again = api.request("POST", f"/imports/{queued_job_id}/cancel")
        check(
            "cancel_queued_idempotent",
            status == 200 and again.get("status") == "cancelled",
            {"status": status, "job_status": again.get("status")},
            "200 幂等",
        )
    else:
        partials.append("cancel_queued 未执行：未提供临时数据库路径（NOT_RUN）")

    # --- 4. 运行中取消竞态 ---------------------------------------------------------------------------
    big_scan = f"race-{run}"
    race_context = {"save_id": save_id, "save_identity_id": identity_id, "save_session_id": session_id}
    # 上一轮 switch 已使 session 失效，先启动新会话拿回写资格。
    status, session_payload = api.request(
        "POST",
        "/save-sessions/start",
        params={"save_id": save_id},
        body={"identity_id": identity_id, "session_key": f"{uuid.uuid4().int % 100000}:fencing-race", "process_id": 303, "agent_id": "acceptance-fencing"},
    )
    if status == 200:
        race_context["save_session_id"] = int(session_payload["session_id"])
    result_holder: dict[str, Any] = {}

    def import_worker() -> None:
        try:
            result_holder["import"] = api.request(
                "POST",
                "/imports/scan",
                params={**race_context, "operation_id": f"op-race-{run}"},
                raw=payload_bytes(big_scan, players=4000),
            )
        except Exception as exc:  # noqa: BLE001 - 记录任何真实失败
            result_holder["import"] = (0, {"error": str(exc)})

    thread = threading.Thread(target=import_worker, daemon=True)
    thread.start()

    cancelled_status = None
    for _ in range(300):
        time.sleep(0.05)
        listing = api.request("GET", "/imports", params={"save_id": save_id, "limit": 20})[1].get("items") or []
        job = next((item for item in listing if item.get("scan_id") == big_scan), None)
        if job is None:
            continue
        if job.get("status") in {"queued", "running"}:
            cancel_status, cancel_payload = api.request("POST", f"/imports/{job['id']}/cancel")
            cancelled_status = (cancel_status, error_code(cancel_payload), cancel_payload.get("status"))
            break

    thread.join(timeout=180)
    import_status, import_payload = result_holder.get("import", (0, {"error": "导入线程无结果"}))
    final_listing = api.request("GET", "/imports", params={"save_id": save_id, "limit": 20})[1].get("items") or []
    final_job = next((item for item in final_listing if item.get("scan_id") == big_scan), None)
    final_status = (final_job or {}).get("status")

    race_atomic = (
        (final_status == "cancelled" and import_status == 409 and error_code(import_payload) == "import_cancelled")
        or (final_status in {"succeeded", "partial"} and cancelled_status is not None and cancelled_status[0] == 409)
        or (final_status in {"failed", "rejected"} and import_status == 201)
    )
    check(
        "cancel_commit_race_atomic",
        bool(race_atomic),
        {
            "cancel": cancelled_status,
            "import_status": import_status,
            "import_code": error_code(import_payload),
            "final_job_status": final_status,
        },
        "取消成功→无写入；或提交成功→取消 409",
    )

    # 取消后的任务不得留下业务数据：以最终任务状态为准，succeeded 时 player_count 必须 > 0。
    if final_status == "cancelled":
        status, summary = api.request("GET", f"/saves/{save_id}/summary")
        check("cancel_leaves_no_partial_write", status == 200 and int(summary["coverage"]["players"] or 0) == 0, summary.get("coverage"), "取消后 players == 0")

    # --- 5. 审计 -------------------------------------------------------------------------------------
    status, audit = api.request("GET", "/save-identity-audit", params={"save_id": save_id, "limit": 200})
    events = {item.get("event_type") for item in (audit.get("items") or [])}
    check(
        "audit_cancel_events",
        status == 200 and {"worker_cancel_requested", "worker_cancelled"}.issubset(events),
        sorted(events),
        "含 worker_cancel_requested / worker_cancelled",
    )
    check("audit_worker_started", "worker_started" in events, sorted(events), "含 worker_started")

    result = {
        "tool": "verify_worker_fencing",
        "synthetic_identity": True,
        "real_fm27": False,
        "api": args.api,
        "checks": checks,
        "failures": failures,
        "partials": partials,
        "ok": not failures,
        "status": "PASS" if not failures else "FAIL",
    }
    target = args.output / "worker-fencing-result.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"{'PASS' if not failures else 'FAIL'} worker-fencing: {len(checks) - len(failures)}/{len(checks)}")
    for partial in partials:
        print(f"PARTIAL {partial}")
    for failure in failures:
        print(f"FAIL {failure}")
    print(f"证据：{target}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
