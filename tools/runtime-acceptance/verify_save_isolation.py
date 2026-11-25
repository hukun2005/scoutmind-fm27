"""V3.2.7.4 运行期验收：存档隔离与代次栅栏（真实 HTTP，合成身份）。

本脚本用**合成指纹**（``si:v1:test:*``）与合成扫描报文，验证后端协议本身：
存档 A/B 两套身份与会话互不越权；会话失效或代次推进后旧写入立刻被拒绝；
采集归属正确；审计事件齐全。

它不读取游戏、不伪造真实 FM27 结论。真实 A/B 切换必须人工执行，见
``docs/evidence/v3.2.7.4/REAL-FM27-ACCEPTANCE.md``。

用法：
    python tools/runtime-acceptance/verify_save_isolation.py \
        --api http://127.0.0.1:8123/api/v1 --output runtime-evidence
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

DEFAULT_API = "http://127.0.0.1:8000/api/v1"


class Api:
    """最小 HTTP 客户端；不加载 SDK，确保可审计。"""

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
            with urllib.request.urlopen(req, timeout=120) as response:
                return response.status, json.loads(response.read() or b"null")
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read() or b"null")


def error_code(payload: Any) -> str | None:
    if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
        value = payload["error"].get("code")
        return str(value) if value is not None else None
    if isinstance(payload, dict) and isinstance(payload.get("detail"), dict):
        value = payload["detail"].get("code")
        return str(value) if value is not None else None
    return None


def scan_payload(scan_id: str) -> bytes:
    return json.dumps(
        {
            "schema_version": "1.0",
            "source": "synthetic_fixture",
            "scan": {"scan_id": scan_id, "observed_at": "2026-11-25T00:00:00"},
            "players": [],
            "transfers": [],
        },
        ensure_ascii=False,
    ).encode("utf-8")


def register_and_verify(api: Api, save_id: int, fingerprint: str, agent_id: str) -> tuple[int, int]:
    """注册并人工确认合成身份，返回 (identity_id, session_id)。"""
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
            "game_build": "runtime-acceptance",
            "plugin_version": "0.0.0",
            "ambiguous": False,
            "evidence": [
                {
                    "type": "save_file_hash",
                    "source": "file",
                    "hash": fingerprint,
                    "version": "1",
                    "confidence": "medium",
                }
            ],
            "agent_id": agent_id,
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
        body={"confirmed_fingerprint": fingerprint, "basis": "运行期验收合成身份", "actor": agent_id},
    )
    if status != 200 or payload.get("identity_status") != "verified":
        raise SystemExit(f"确认身份失败：{status} {payload}")

    session_key = f"{uuid.uuid4().int % 100000}:runtime-acceptance"
    status, payload = api.request(
        "POST",
        "/save-sessions/start",
        params={"save_id": save_id},
        body={
            "identity_id": identity_id,
            "session_key": session_key,
            "process_id": 101,
            "game_build": "runtime-acceptance",
            "plugin_version": "0.0.0",
            "agent_id": agent_id,
        },
    )
    if status != 200 or payload.get("status") != "verified":
        raise SystemExit(f"启动会话失败：{status} {payload}")
    return identity_id, int(payload["session_id"])


def main() -> int:
    parser = argparse.ArgumentParser(description="存档隔离与代次栅栏验收（合成身份）")
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--token")
    parser.add_argument("--output", type=Path, default=Path("runtime-evidence"))
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    api = Api(args.api, args.token)
    run = uuid.uuid4().hex[:8]
    checks: list[dict[str, Any]] = []
    failures: list[str] = []

    def check(label: str, ok: bool, detail: Any, expect: str) -> None:
        checks.append({"label": label, "ok": ok, "expect": expect, "observed": detail})
        if not ok:
            failures.append(f"{label}: 期望 {expect}，实际 {detail}")

    # --- 两套存档 -----------------------------------------------------------------------------------------
    status, save_a = api.request("POST", "/saves", body={"name": f"acceptance-A-{run}"})
    check("create_save_a", status == 201, status, "201")
    status, save_b = api.request("POST", "/saves", body={"name": f"acceptance-B-{run}"})
    check("create_save_b", status == 201, status, "201")
    save_a_id, save_b_id = int(save_a["id"]), int(save_b["id"])

    fp_a = f"si:v1:test:a:{run}"
    fp_b = f"si:v1:test:b:{run}"
    identity_a, session_a = register_and_verify(api, save_a_id, fp_a, "acceptance-a")
    identity_b, session_b = register_and_verify(api, save_b_id, fp_b, "acceptance-b")
    check("identities_isolated", identity_a != identity_b and session_a != session_b, {"a": identity_a, "b": identity_b}, "不同身份/会话")

    context_a = {"save_id": save_a_id, "save_identity_id": identity_a, "save_session_id": session_a}
    context_b = {"save_id": save_b_id, "save_identity_id": identity_b, "save_session_id": session_b}

    # --- 正常采集 A ---------------------------------------------------------------------------------------
    status, capture_a = api.request(
        "POST",
        "/captures",
        params=context_a,
        body={
            "game_date": "2026-11-25",
            "reader_version": "runtime-acceptance",
            "game_build": "runtime-acceptance",
            "scan_scope": "players",
            "status": "scanning",
            "revision": 0,
        },
    )
    check("capture_a_created", status == 201 and int(capture_a.get("save_identity_id") or 0) == identity_a, status, "201 且归属 A")
    capture_a_id = int(capture_a["id"])

    status, outcome_a = api.request(
        "POST",
        "/imports/scan",
        params={**context_a, "operation_id": f"op-a-{run}"},
        raw=scan_payload(f"scan-a-{run}"),
    )
    check("import_a_succeeded", status == 201 and outcome_a.get("status") in {"succeeded", "partial"}, outcome_a.get("status"), "succeeded/partial")

    status, outcome_b = api.request(
        "POST",
        "/imports/scan",
        params={**context_b, "operation_id": f"op-b-{run}"},
        raw=scan_payload(f"scan-b-{run}"),
    )
    check("import_b_succeeded", status == 201 and outcome_b.get("status") in {"succeeded", "partial"}, outcome_b.get("status"), "succeeded/partial")

    # --- 跨存档写入必须被拒绝 -----------------------------------------------------------------------------
    status, cross = api.request(
        "POST",
        "/imports/scan",
        params={**context_b, "save_identity_id": identity_a, "save_session_id": session_a, "operation_id": f"op-cross-{run}"},
        raw=scan_payload(f"scan-cross-{run}"),
    )
    check(
        "cross_save_write_rejected",
        status in {404, 409}
        and error_code(cross) in {"save_context_mismatch", "save_identity_not_found", "write_session_epoch_stale", "write_fence_stale", "write_context_required"},
        {"status": status, "code": error_code(cross)},
        "404/409 安全拒绝",
    )

    # --- 切换：A 推进代次，旧会话立刻失去写资格 ------------------------------------------------------------
    status, switch = api.request(
        "POST",
        f"/save-sessions/{session_a}/switch",
        params={"save_id": save_a_id},
        body={"reason": "save_switch", "actor": "acceptance"},
    )
    check("switch_advances_generation", status == 200 and int(switch.get("generation") or 0) > 0, switch, "generation ≥ 1")
    generation_after_switch = int(switch.get("generation") or 0)

    status, stale_import = api.request(
        "POST",
        "/imports/scan",
        params={**context_a, "operation_id": f"op-stale-{run}"},
        raw=scan_payload(f"scan-stale-{run}"),
    )
    check("old_session_write_rejected", status == 409 and error_code(stale_import) in {"write_session_epoch_stale", "write_fence_stale", "save_context_mismatch", "save_session_invalidated"}, {"status": status, "code": error_code(stale_import)}, "409 旧会话不可写")

    # --- B 不受影响 ---------------------------------------------------------------------------------------
    status, outcome_b2 = api.request(
        "POST",
        "/imports/scan",
        params={**context_b, "operation_id": f"op-b2-{run}"},
        raw=scan_payload(f"scan-b2-{run}"),
    )
    check("b_unaffected", status == 201 and outcome_b2.get("status") in {"succeeded", "partial"}, outcome_b2.get("status"), "succeeded/partial")

    # --- 审计 ---------------------------------------------------------------------------------------------
    status, audit = api.request("GET", "/save-identity-audit", params={"save_id": save_a_id, "limit": 200})
    events = {item.get("event_type") for item in (audit.get("items") or [])}
    required = {"registered", "identity_verified", "session_created", "session_invalidated"}
    check("audit_a_events", status == 200 and required.issubset(events), sorted(events), f"包含 {sorted(required)}")

    status, audit_b = api.request("GET", "/save-identity-audit", params={"save_id": save_b_id, "limit": 200})
    identity_ids_b = {item.get("identity_id") for item in (audit_b.get("items") or [])}
    check("audit_b_isolated", status == 200 and identity_a not in identity_ids_b, sorted(identity_ids_b), "B 审计不含 A 身份")

    # --- 采集归属复核 -------------------------------------------------------------------------------------
    status, detail_a = api.request("GET", f"/save-identities/{identity_a}", params={"save_id": save_a_id})
    check(
        "gate_blocks_after_switch",
        status == 200 and detail_a.get("capture_allowed") is False,
        {"capture_allowed": detail_a.get("capture_allowed"), "blockers": detail_a.get("blockers")},
        "切换后 A 采集闸门关闭",
    )
    status, capture_detail = api.request("PATCH", f"/captures/{capture_a_id}", params=context_a, body={"status": "failed"})
    check("stale_capture_rejected", status == 409, {"status": status, "code": error_code(capture_detail)}, "409 旧会话不能更新采集")

    result = {
        "tool": "verify_save_isolation",
        "synthetic_identity": True,
        "real_fm27": False,
        "api": args.api,
        "checks": checks,
        "failures": failures,
        "ok": not failures,
        "generation_after_switch": generation_after_switch,
    }
    target = args.output / "save-isolation-result.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"{'PASS' if not failures else 'FAIL'} save-isolation: {len(checks) - len(failures)}/{len(checks)}")
    for failure in failures:
        print(f"FAIL {failure}")
    print(f"证据：{target}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
