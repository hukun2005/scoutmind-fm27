"""V3.2.7.5 运行期验收 D：取消任务（真实 Worker + 多进程，非游戏内）。

对应验收项（REAL-FM27-ACCEPTANCE D 场景的协议级部分）。与
``verify_worker_fencing.py`` 的区别：导入提交与取消来自**两个不同的客户端
进程**，Worker 运行在后端进程里——不存在任何共享内存事件，取消只能通过
真实 HTTP 传播：

1. 进程 A（submitter 子进程）提交一个大导入（数千球员，耗时数秒）；
2. 进程 B（本脚本）轮询任务进入 ``running`` 后发起 ``POST /imports/{id}/cancel``；
3. 后端 Worker（进程 C）在下一个安全检查点感知取消并回滚；
4. 断言最终状态原子：``cancelled 且无业务写入`` 或 ``已提交则取消 409``；
5. 重复取消幂等；
6. 取消不留半提交数据；
7. 审计含 ``worker_cancel_requested`` / ``worker_cancelled``。

用法：
    python tools/runtime-acceptance/verify_cancel_two_process.py --output <证据目录>
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend_harness import BackendProcess, payload_bytes, write_evidence  # noqa: E402

SUBMITTER_CODE = r'''
"""submitter 子进程：提交一个大导入并把 HTTP 结果写入 JSON 文件。"""
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
    parser = argparse.ArgumentParser(description="双进程取消验收（真实 Worker，合成身份）")
    parser.add_argument("--output", type=Path, default=Path("runtime-evidence"))
    parser.add_argument("--players", type=int, default=8000, help="大导入的球员数量（决定导入耗时）")
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

    backend = BackendProcess()
    try:
        backend.migrate()
        backend.start_and_wait()
        context = backend.setup_save_context(run)
        api = backend.api
        scan_id = f"cancel-{run}"
        operation_id = f"op-cancel-{run}"

        # --- 进程 A：submitter 子进程 ----------------------------------------------------------------------
        result_path = backend.workdir / "submitter-result.json"
        submitter = subprocess.Popen(
            [
                sys.executable,
                "-c",
                SUBMITTER_CODE,
                str(Path(__file__).resolve().parent),
                backend.api.base,
                str(context["save_id"]),
                str(context["save_identity_id"]),
                str(context["save_session_id"]),
                scan_id,
                operation_id,
                str(args.players),
                str(result_path),
            ],
            cwd=str(Path(__file__).resolve().parent),
        )

        # --- 进程 B：轮询并在 running 后取消 ------------------------------------------------------------------
        job: dict[str, Any] | None = None
        cancel_status, cancel_payload = 0, {}
        cancel_sent = False
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline and submitter.poll() is None:
            time.sleep(0.05)
            listing = api.request("GET", "/imports", params={"save_id": context["save_id"], "limit": 20})[1]
            job = next((item for item in (listing.get("items") or []) if item.get("scan_id") == scan_id), None)
            if job is None:
                continue
            if job.get("status") in {"queued", "running"} and not cancel_sent:
                cancel_status, cancel_payload = api.request("POST", f"/imports/{job['id']}/cancel")
                cancel_sent = True
                break

        submitter.wait(timeout=180)
        submitter_result = {"status": None, "payload": {"error": "submitter 未产出结果"}}
        if result_path.exists():
            submitter_result = json.loads(result_path.read_text(encoding="utf-8"))
        else:
            partials.append("submitter 结果文件缺失（可能导入太快结束或未开始）")

        final_listing = api.request("GET", "/imports", params={"save_id": context["save_id"], "limit": 20})[1]
        final_job = next((item for item in (final_listing.get("items") or []) if item.get("scan_id") == scan_id), None)
        final_status = (final_job or {}).get("status")

        check("job_observed_in_progress", final_job is not None and cancel_sent, {"cancel_sent": cancel_sent, "final_status": final_status}, "任务被观察到且取消请求已发出")

        import_status = submitter_result.get("status")
        import_code = api.error_code(submitter_result.get("payload"))
        atomic = (
            (final_status == "cancelled" and import_status == 409 and import_code == "import_cancelled")
            or (final_status in {"succeeded", "partial"} and cancel_status == 409)
            or (final_status in {"failed", "rejected"} and import_status == 201)
        )
        check(
            "cancel_commit_race_atomic",
            bool(atomic),
            {
                "cancel_http": cancel_status,
                "cancel_code": api.error_code(cancel_payload),
                "import_http": import_status,
                "import_code": import_code,
                "final_status": final_status,
            },
            "取消成功→409 import_cancelled；或提交完成→取消 409",
        )

        # --- Worker 感知取消 -----------------------------------------------------------------------------------
        audit = api.request("GET", "/save-identity-audit", params={"save_id": context["save_id"], "limit": 200})[1]
        events = {item.get("event_type") for item in (audit.get("items") or [])}
        if final_status == "cancelled":
            check("worker_sensed_cancellation", "worker_cancelled" in events and "worker_cancel_requested" in events, sorted(events), "含 worker_cancel_requested/worker_cancelled")
        else:
            partials.append(f"worker_sensed_cancellation 未执行：任务以 {final_status} 结束（取消输给了提交）")

        # --- 取消不留半提交数据 ---------------------------------------------------------------------------------
        summary = backend.save_summary(context["save_id"]).get("coverage", {})
        players_written = int(summary.get("players") or 0)
        if final_status == "cancelled":
            check("no_partial_write", players_written == 0, {"players": players_written}, "取消后 players == 0")
        elif final_status in {"succeeded", "partial"}:
            check("complete_write", players_written == args.players, {"players": players_written, "expected": args.players}, "提交完成后 players == 导入数")

        # --- 重复取消幂等 ---------------------------------------------------------------------------------------
        if final_job is not None and cancel_sent:
            status, again = api.request("POST", f"/imports/{final_job['id']}/cancel")
            idempotent = (final_status == "cancelled" and status == 200 and again.get("status") == "cancelled") or (
                final_status in {"succeeded", "partial"} and status == 409
            )
            check("repeat_cancel_idempotent", idempotent, {"status": status, "code": api.error_code(again), "body_status": again.get("status")}, "cancelled→200 幂等；completed→409")
        else:
            partials.append("repeat_cancel 未执行：任务未出现或取消未发出")

        # --- 排队中取消（确定性场景，直插临时库） -----------------------------------------------------------------
        queued_job_id = None
        try:
            import sqlite3

            connection = sqlite3.connect(backend.db_path, timeout=30)
            try:
                cursor = connection.execute(
                    "INSERT INTO import_jobs (fm_save_id, scan_id, source, schema_version, status, attempt_count, "
                    "player_count, transfer_count, warnings_json, coverage_json, received_at, created_at, updated_at) "
                    "VALUES (?, ?, 'reader', '1.0', 'queued', 0, 0, 0, '[]', '{}', datetime('now'), datetime('now'), datetime('now'))",
                    (context["save_id"], f"queued-{run}"),
                )
                connection.commit()
                queued_job_id = int(cursor.lastrowid)
            finally:
                connection.close()
        except Exception as exc:  # noqa: BLE001
            partials.append(f"queued 取消未执行：插入失败 {exc}")
        if queued_job_id is not None:
            status, first_cancel = api.request("POST", f"/imports/{queued_job_id}/cancel")
            check("cancel_queued", status == 200 and first_cancel.get("status") == "cancelled", {"status": status, "job_status": first_cancel.get("status")}, "200 cancelled")
            status, second_cancel = api.request("POST", f"/imports/{queued_job_id}/cancel")
            check("cancel_queued_idempotent", status == 200 and second_cancel.get("status") == "cancelled", {"status": status, "job_status": second_cancel.get("status")}, "200 幂等")

        outcome = {"run_id": run, "players": args.players, "workdir": str(backend.workdir)}
    finally:
        backend.cleanup()
        if not args.keep:
            import shutil

            shutil.rmtree(backend.workdir, ignore_errors=True)

    write_evidence(
        args.output,
        "cancel-two-process-result.json",
        tool="verify_cancel_two_process",
        checks=checks,
        failures=failures,
        partials=partials,
        extra=outcome,
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
