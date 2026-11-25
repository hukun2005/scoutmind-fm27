"""V3.2.7.5 运行期验收 C：断网恢复（真实后端进程 + 真实 HTTP，非游戏内）。

对应验收项（REAL-FM27-ACCEPTANCE C 场景的协议级部分）：

1. 正常提交数据（真实 HTTP 导入成功）；
2. 断开连接——两种真实形态：
   a. 请求已完整发出但客户端未收到响应（原始 socket 在服务端处理期间断开）；
   b. 后端不可达（进程停止，连接被拒）；
3. 客户端识别断网（传输错误可见、可记录）；
4. 恢复网络（后端重新就绪）；
5. 恢复连接（``heartbeat(reconnected=true)`` 写 ``network_reconnected`` 审计）；
6. 用原 ``operation_id`` 重试"已提交但未收到响应"的请求；
7. 不重复写入（同一 job、行数不变）；
8. 旧 Session / 旧 Generation 不会被断网恢复复活（代次推进后旧会话仍被拒绝）。

用法：
    python tools/runtime-acceptance/verify_network_recovery.py --output <证据目录>

注意：本脚本验证的是「真实后端协议与进程行为」；真实 Agent 进程与真实 FM27
游戏内的断网恢复必须由人工执行，见 docs/evidence/v3.2.7.5/ 下的手动步骤。
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend_harness import BackendProcess, payload_bytes, write_evidence  # noqa: E402


def abort_after_send(port: int, method: str, path: str, body: bytes, hold_seconds: float = 1.5) -> None:
    """完整发出一个 HTTP/1.1 请求，在服务端处理期间直接断开连接，不读响应。

    模拟「请求已提交但客户端永远没收到响应」——与 Agent 超时后按 scan_id /
    operation_id 核实的服务端语义完全对应。
    """
    with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
        request = (
            f"{method} {path} HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{port}\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode("utf-8")
        sock.sendall(request + body)
        # 让服务端有时间接收请求并开始处理，再断开：更接近真实断网而不是协议错误。
        time.sleep(hold_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description="断网恢复验收（真实后端，合成身份）")
    parser.add_argument("--output", type=Path, default=Path("runtime-evidence"))
    parser.add_argument("--keep", action="store_true", help="保留临时目录（排错用）")
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
        scan_id = f"net-{run}"
        operation_id = f"op-net-{run}"
        params = {**context, "operation_id": operation_id}

        # --- 1. 正常提交 ----------------------------------------------------------------------------------
        status, first = api.request("POST", "/imports/scan", params=params, raw=payload_bytes(scan_id, players=50))
        check(
            "normal_submit",
            status == 201 and first.get("duplicate") is False,
            {"status": status, "duplicate": first.get("duplicate"), "job_id": first.get("job_id")},
            "201 duplicate=false",
        )
        job_id = first.get("job_id")
        baseline = backend.save_summary(context["save_id"]).get("coverage", {})
        baseline_players = int(baseline.get("players") or 0)

        # --- 2a-1. 响应丢失但服务端已完成：原 operation_id 重试必须命中幂等 --------------------------------------
        # 用原始 socket 发出完整请求；等服务端把导入做完（任务 succeeded）后再断开，模拟「响应在途丢失」。
        lost_scan = f"{scan_id}-lost"
        lost_op = f"{operation_id}-lost"
        lost_params = {**context, "operation_id": lost_op}
        sock = socket.create_connection(("127.0.0.1", backend.port), timeout=10)
        sock.sendall(
            (
                f"POST /api/v1/imports/scan?{ '&'.join(f'{k}={v}' for k, v in lost_params.items()) } HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{backend.port}\r\n"
                "Content-Type: application/json\r\n"
                f"Content-Length: {len(payload_bytes(lost_scan, players=50))}\r\n"
                "Connection: close\r\n"
                "\r\n"
            ).encode("utf-8")
            + payload_bytes(lost_scan, players=50)
        )
        lost_job: dict[str, Any] | None = None
        for _ in range(120):
            time.sleep(0.5)
            listing = api.request("GET", "/imports", params={"save_id": context["save_id"], "limit": 20})[1]
            items = listing.get("items") or []
            lost_job = next((item for item in items if item.get("scan_id") == lost_scan), None)
            if lost_job is not None and lost_job.get("status") in {"succeeded", "partial", "failed", "rejected"}:
                break
        sock.close()  # 响应已产生但从未被客户端读取
        after_lost = int(backend.save_summary(context["save_id"]).get("coverage", {}).get("players") or 0)
        check(
            "response_lost_server_completed",
            lost_job is not None and lost_job.get("status") in {"succeeded", "partial"},
            {"job_status": (lost_job or {}).get("status"), "players": after_lost},
            "服务端完成导入（succeeded/partial）",
        )
        status, lost_replay = api.request("POST", "/imports/scan", params=lost_params, raw=payload_bytes(lost_scan, players=50))
        check(
            "retry_lost_operation_idempotent",
            status in {200, 201}
            and lost_replay.get("duplicate") is True
            and lost_replay.get("job_id") == (lost_job or {}).get("id"),
            {"status": status, "duplicate": lost_replay.get("duplicate"), "job_id": lost_replay.get("job_id"), "original_job_id": (lost_job or {}).get("id")},
            "duplicate=true 且同一 job",
        )
        players_after_lost = int(backend.save_summary(context["save_id"]).get("coverage", {}).get("players") or 0)
        check(
            "response_lost_no_double_write",
            players_after_lost == after_lost,
            {"players": players_after_lost, "before_retry": after_lost},
            "重试后行数不变",
        )

        # --- 2a-2. 处理中途断开：服务端行为如实记录，原 operation_id 重试必须恰好写一次 -----------------------------
        # 客户端在服务端处理期间直接断开。无论服务端最终是「完成」「失败」还是「未创建任务」，
        # 重试同一 operation_id 后行数必须恰好 +50，绝不 +100。
        abort_scan = f"{scan_id}-abort"
        abort_op = f"{operation_id}-abort"
        abort_params = {**context, "operation_id": abort_op}
        before_abort = int(backend.save_summary(context["save_id"]).get("coverage", {}).get("players") or 0)
        abort_after_send(
            backend.port,
            "POST",
            f"/api/v1/imports/scan?{ '&'.join(f'{k}={v}' for k, v in abort_params.items()) }",
            payload_bytes(abort_scan, players=50),
        )
        abort_job: dict[str, Any] | None = None
        for _ in range(20):
            time.sleep(0.5)
            listing = api.request("GET", "/imports", params={"save_id": context["save_id"], "limit": 20})[1]
            items = listing.get("items") or []
            abort_job = next((item for item in items if item.get("scan_id") == abort_scan), None)
            if abort_job is not None and abort_job.get("status") in {"succeeded", "partial", "failed", "rejected"}:
                break
        status, abort_retry = api.request("POST", "/imports/scan", params=abort_params, raw=payload_bytes(abort_scan, players=50))
        players_after_abort_retry = int(backend.save_summary(context["save_id"]).get("coverage", {}).get("players") or 0)
        listing = api.request("GET", "/imports", params={"save_id": context["save_id"], "limit": 50})[1]
        abort_jobs = [item for item in (listing.get("items") or []) if item.get("scan_id") == abort_scan]
        check(
            "mid_disconnect_retry_writes_exactly_once",
            players_after_abort_retry == before_abort + 50 and len(abort_jobs) == 1,
            {
                "observed_after_disconnect": {"job": abort_job, "players": before_abort},
                "retry_status": status,
                "players_after_retry": players_after_abort_retry,
                "jobs_for_scan": len(abort_jobs),
            },
            "断开后重试：恰好 +50 且 scan 只有 1 个 job（无论服务端是否已完成被中断的请求）",
        )

        # --- 2b. 后端不可达 ---------------------------------------------------------------------------------
        backend.stop()
        status, outage = api.request(
            "POST",
            "/imports/scan",
            params=params,
            raw=payload_bytes(f"{scan_id}-outage", players=5),
            timeout=8,
        )
        check(
            "outage_detected_as_transport_error",
            status == 0 and outage.get("error", {}).get("code") == "transport_error",
            {"status": status, "code": api.error_code(outage)},
            "status=0 transport_error（客户端可识别断网）",
        )
        hb_status, _hb = backend.heartbeat(context, reconnected=False)
        check("heartbeat_during_outage_fails", hb_status == 0, {"status": hb_status}, "0（传输失败）")

        # --- 4/5. 恢复网络并重连 -----------------------------------------------------------------------------
        backend.start_and_wait()
        hb_status, hb_payload = backend.heartbeat(context, reconnected=True)
        check("reconnected_heartbeat_ok", hb_status == 200, {"status": hb_status, "body": hb_payload}, "200")
        audit = api.request("GET", "/save-identity-audit", params={"save_id": context["save_id"], "limit": 200})[1]
        events = {item.get("event_type") for item in (audit.get("items") or [])}
        check("audit_network_reconnected", "network_reconnected" in events, sorted(events), "含 network_reconnected")

        # --- 6/7. 重连后原 operation_id 重试不重复写入 ----------------------------------------------------------
        status, replay = api.request("POST", "/imports/scan", params=params, raw=payload_bytes(scan_id, players=50))
        check(
            "retry_same_operation_id",
            status in {200, 201} and replay.get("duplicate") is True and replay.get("job_id") == job_id,
            {"status": status, "duplicate": replay.get("duplicate"), "job_id": replay.get("job_id")},
            "duplicate=true 且同一 job",
        )
        after = backend.save_summary(context["save_id"]).get("coverage", {})
        after_players = int(after.get("players") or 0)
        listing = api.request("GET", "/imports", params={"save_id": context["save_id"], "limit": 50})[1]
        jobs_for_scan = [item for item in (listing.get("items") or []) if item.get("scan_id") == scan_id]
        check(
            "no_duplicate_write",
            after_players == baseline_players and len(jobs_for_scan) == 1,
            {
                "players_before": baseline_players,
                "players_after": after_players,
                "jobs_for_scan": len(jobs_for_scan),
            },
            "重放后行数不变且 scan 只有 1 个 job",
        )

        # --- 8. 旧会话 / 旧代次不复活 --------------------------------------------------------------------------
        status, switch = api.request(
            "POST",
            f"/save-sessions/{context['save_session_id']}/switch",
            params={"save_id": context["save_id"]},
            body={"reason": "save_switch", "actor": "acceptance-net"},
        )
        check("switch_rotates_generation", status == 200 and int(switch.get("generation") or 0) >= 1, switch, "generation ≥ 1")
        status, stale = api.request(
            "POST",
            "/imports/scan",
            params=params,
            raw=payload_bytes(f"{scan_id}-stale", players=5),
        )
        check(
            "stale_session_not_resurrected_after_reconnect",
            status == 409 and api.error_code(stale) in {"write_session_epoch_stale", "write_fence_stale", "save_session_invalidated"},
            {"status": status, "code": api.error_code(stale)},
            "409 旧会话不可写",
        )
        status, fresh = api.request(
            "POST",
            "/save-sessions/start",
            params={"save_id": context["save_id"]},
            body={
                "identity_id": context["save_identity_id"],
                "session_key": f"{uuid.uuid4().int % 100000}:cde-{run}-re",
                "process_id": 405,
                "agent_id": "acceptance-net",
            },
        )
        if status == 200:
            new_session = int(fresh["session_id"])
            status, wrote = api.request(
                "POST",
                "/imports/scan",
                params={**context, "save_session_id": new_session, "operation_id": f"op-net-{run}-re"},
                raw=payload_bytes(f"{scan_id}-after-switch", players=5),
            )
            check("fresh_session_writes_after_switch", status == 201, {"status": status}, "201")
        else:
            partials.append(f"新会话未建立：{status} {fresh}")

        outcome = {
            "run_id": run,
            "backend_starts": backend.starts,
            "workdir": str(backend.workdir),
        }
    finally:
        backend.cleanup()
        if not args.keep:
            import shutil

            shutil.rmtree(backend.workdir, ignore_errors=True)

    write_evidence(
        args.output,
        "network-recovery-result.json",
        tool="verify_network_recovery",
        checks=checks,
        failures=failures,
        partials=partials,
        extra=outcome,
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
