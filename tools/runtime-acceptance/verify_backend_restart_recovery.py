"""V3.2.7.5 运行期验收 E：重启恢复（真实后端进程崩溃与重启，非游戏内）。

对应验收项（REAL-FM27-ACCEPTANCE E 场景的后端部分）：

1. 后端正常运行时任务可提交、可完成（状态持久化基线）；
2. 大导入进行中硬杀后端进程（模拟崩溃，非优雅退出）；
3. 提交方（独立子进程）感知连接中断；
4. 重启后端（同一临时数据库）；
5. 启动恢复：``recover_interrupted_imports`` 把遗留 ``running`` 收敛为 ``failed``，
   审计含 ``worker_recovered`` / ``backend_restarted``；
6. 任务状态持久化：崩溃前的已完成任务仍然是 ``succeeded``；
7. 崩溃的导入没有留下任何业务行（SQLite 事务回滚），旧 Worker 不能再产生写入；
8. 同一 ``scan_id`` 重试恰好写一次，不产生重复写入；
9. 会话状态跨重启持久：有效会话仍可写；代次推进后旧会话被拒绝（不被复活）。

用法：
    python tools/runtime-acceptance/verify_backend_restart_recovery.py --output <证据目录>

注意：Agent 进程重启 + 真实 FM27 的部分必须由人工执行（需要游戏进程），
见 docs/evidence/v3.2.7.5/ 下的手动步骤；本脚本不覆盖也不代表那部分结论。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend_harness import BackendProcess, payload_bytes, write_evidence  # noqa: E402

SUBMITTER_CODE = r'''
"""submitter 子进程：提交导入并把 HTTP 结果写入 JSON 文件（由主脚本 kill 后读取）。"""
import json, sys
sys.path.insert(0, sys.argv[1])
from backend_harness import Api, payload_bytes

api_url, save_id, identity_id, session_id, scan_id, operation_id, players, result_path = sys.argv[2:10]
api = Api(api_url)
params = {
    "save_id": save_id,
    "save_identity_id": identity_id,
    "save_session_id": session_id,
    "operation_id": operation_id,
}
status, payload = api.request(
    "POST", "/imports/scan", params=params, raw=payload_bytes(scan_id, players=int(players)), timeout=180,
)
with open(result_path, "w", encoding="utf-8") as handle:
    json.dump({"status": status, "payload": payload}, handle, ensure_ascii=False)
'''


def main() -> int:
    parser = argparse.ArgumentParser(description="后端重启恢复验收（合成身份）")
    parser.add_argument("--output", type=Path, default=Path("runtime-evidence"))
    parser.add_argument("--players", type=int, default=12000, help="崩溃时正在导入的球员数量")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()

    run = uuid.uuid4().hex[:8]
    checks: list[dict[str, Any]] = []
    failures: list[str] = []
    partials: list[str] = []

    def check(label: str, ok: bool, detail: Any, expect: str) -> None:
        checks.append({"label": label, "ok": ok, "expect": expect, "observed": detail})
        if not ok:
            failures.append(f"{label}: 期望 {expect}，实际 {detail}")

    first = BackendProcess()
    workdir = first.workdir
    try:
        first.migrate()
        first.start_and_wait()
        context = first.setup_save_context(run)
        api = first.api
        baseline_scan = f"persist-{run}"
        crash_scan = f"crash-{run}"

        # --- 1. 崩溃前：一个已完成任务作为持久化基线 ---------------------------------------------------------
        status, done = api.request(
            "POST",
            "/imports/scan",
            params={**context, "operation_id": f"op-persist-{run}"},
            raw=payload_bytes(baseline_scan, players=10),
        )
        check("baseline_import_succeeded", status == 201, {"status": status}, "201")
        baseline_players = 10

        # --- 2/3. 大导入进行中硬杀后端 ------------------------------------------------------------------------
        result_path = workdir / "crash-submitter-result.json"
        submitter = subprocess.Popen(
            [
                sys.executable,
                "-c",
                SUBMITTER_CODE,
                str(Path(__file__).resolve().parent),
                api.base,
                str(context["save_id"]),
                str(context["save_identity_id"]),
                str(context["save_session_id"]),
                crash_scan,
                f"op-crash-{run}",
                str(args.players),
                str(result_path),
            ],
            cwd=str(Path(__file__).resolve().parent),
        )

        killed_while_running = False
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline and submitter.poll() is None:
            time.sleep(0.05)
            listing = api.request("GET", "/imports", params={"save_id": context["save_id"], "limit": 20})[1]
            job = next((item for item in (listing.get("items") or []) if item.get("scan_id") == crash_scan), None)
            if job is not None and job.get("status") == "running":
                first.kill()
                killed_while_running = True
                break

        submitter.wait(timeout=60)
        submitter_result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else {"status": None}
        check(
            "backend_killed_mid_import",
            killed_while_running,
            {"killed_while_running": killed_while_running, "submitter_status": submitter_result.get("status")},
            "在 running 状态硬杀后端",
        )
        check(
            "submitter_saw_transport_failure",
            submitter_result.get("status") == 0,
            {"status": submitter_result.get("status")},
            "0（客户端感知连接中断）",
        )

        # --- 4. 崩溃现场：库里遗留 running，业务行未提交 ---------------------------------------------------------
        connection = sqlite3.connect(first.db_path, timeout=30)
        try:
            rows = connection.execute(
                "SELECT status, player_count FROM import_jobs WHERE scan_id = ?", (crash_scan,)
            ).fetchall()
        finally:
            connection.close()
        crash_row = rows[0] if rows else None
        check(
            "crash_left_running_job_without_rows",
            crash_row is not None and crash_row[0] == "running" and int(crash_row[1] or 0) == 0,
            {"row": crash_row},
            "status=running 且 player_count=0（事务未提交）",
        )

        # --- 5. 重启后端 --------------------------------------------------------------------------------------
        second = BackendProcess(workdir=workdir)
        second.start_and_wait()
        api = second.api

        # --- 6/7. 启动恢复 + 持久化 -------------------------------------------------------------------------------
        listing = api.request("GET", "/imports", params={"save_id": context["save_id"], "limit": 20})[1]
        items = {item.get("scan_id"): item for item in (listing.get("items") or [])}
        recovered = items.get(crash_scan)
        persisted = items.get(baseline_scan)
        check(
            "startup_recovered_running_to_failed",
            recovered is not None and recovered.get("status") == "failed",
            {"crash_job_status": (recovered or {}).get("status")},
            "running → failed（可重试）",
        )
        check(
            "job_state_persisted",
            persisted is not None and persisted.get("status") == "succeeded",
            {"baseline_job_status": (persisted or {}).get("status")},
            "崩溃前的 succeeded 保持不变",
        )
        audit = api.request("GET", "/save-identity-audit", params={"save_id": context["save_id"], "limit": 200})[1]
        events = {item.get("event_type") for item in (audit.get("items") or [])}
        check("audit_worker_recovered", "worker_recovered" in events, sorted(events), "含 worker_recovered")
        check("audit_backend_restarted", "backend_restarted" in events, sorted(events), "含 backend_restarted")

        summary = second.save_summary(context["save_id"]).get("coverage", {})
        players_after_restart = int(summary.get("players") or 0)
        check(
            "no_zombie_write_from_killed_worker",
            players_after_restart == baseline_players,
            {"players": players_after_restart, "baseline": baseline_players},
            "崩溃的导入没有留下任何业务行",
        )

        # --- 8. 同一 scan_id 重试恰好写一次 ------------------------------------------------------------------------
        second.heartbeat(context)
        status, retry = api.request(
            "POST",
            "/imports/scan",
            params={**context, "operation_id": f"op-crash-{run}"},
            raw=payload_bytes(crash_scan, players=10),
        )
        check(
            "retry_after_crash_writes_once",
            status == 201 and retry.get("duplicate") is not True,
            {"status": status, "duplicate": retry.get("duplicate")},
            "201（重试被允许）",
        )
        summary = second.save_summary(context["save_id"]).get("coverage", {})
        players_after_retry = int(summary.get("players") or 0)
        check(
            "no_duplicate_write_after_restart",
            players_after_retry == baseline_players + 10,
            {"players": players_after_retry, "expected": baseline_players + 10},
            "恰好 +10（无重复）",
        )

        # --- 9. 会话跨重启：有效会话可写；旧代次被拒 ------------------------------------------------------------------
        status, baseline_replay = api.request(
            "POST",
            "/imports/scan",
            params={**context, "operation_id": f"op-persist-{run}"},
            raw=payload_bytes(baseline_scan, players=10),
        )
        check(
            "succeeded_scan_replays_duplicate",
            status in {200, 201} and baseline_replay.get("duplicate") is True,
            {"status": status, "duplicate": baseline_replay.get("duplicate")},
            "duplicate=true（已完成任务不重写）",
        )
        status, switch = api.request(
            "POST",
            f"/save-sessions/{context['save_session_id']}/switch",
            params={"save_id": context["save_id"]},
            body={"reason": "save_switch", "actor": "acceptance-restart"},
        )
        check("switch_rotates_generation", status == 200 and int(switch.get("generation") or 0) >= 1, switch, "generation ≥ 1")
        status, stale = api.request(
            "POST",
            "/imports/scan",
            params={**context, "operation_id": f"op-stale-{run}"},
            raw=payload_bytes(f"stale-{run}", players=5),
        )
        check(
            "old_epoch_rejected_after_restart",
            status == 409 and api.error_code(stale) in {"write_session_epoch_stale", "write_fence_stale", "save_session_invalidated"},
            {"status": status, "code": api.error_code(stale)},
            "409（重启不会复活旧代次会话）",
        )

        outcome = {
            "run_id": run,
            "players": args.players,
            "backend_starts": [first.starts, second.starts],
            "workdir": str(workdir),
        }
        second.stop()
    finally:
        for backend in (first,):
            backend.cleanup()
        if not args.keep:
            import shutil

            shutil.rmtree(workdir, ignore_errors=True)

    write_evidence(
        args.output,
        "backend-restart-recovery-result.json",
        tool="verify_backend_restart_recovery",
        checks=checks,
        failures=failures,
        partials=partials,
        extra=outcome,
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
