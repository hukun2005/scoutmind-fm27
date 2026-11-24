"""真实 FM27 手动受控验收：用真实 Reader 输出驱动后端身份/会话/采集闸门。

适用场景：Reader 的自动采集门固定关闭（snapshot_eligible=false），无法用 `agent auto`
完成游戏内切换验收。本脚本消费你在游戏内分别对存档 A、B 执行的真实
`save-identity --diagnostics --json` 输出（以及可选的 `scan` 输出），通过真实 HTTP
驱动后端，验证：

1. A/B 身份注册、人工确认、会话心跳与采集写入；
2. 在 A 的会话上用 B 指纹心跳 → 会话失效、采集闸门阻断；
3. 失效后旧会话不能再 PATCH 采集或导入；
4. 审计记录完整。

脚本不伪造任何身份数据：指纹、证据、build、session_key 全部来自 Reader JSON；
指纹为 unresolved、证据为空、ambiguous 或 A/B 指纹相同时直接拒绝执行。

用法（在仓库根目录）：

    python scripts/manual-real-save-switch.py \
        --save-a 1 --save-b 2 \
        --identity-a real-fm27/A-identity.json \
        --identity-b real-fm27/B-identity.json \
        --scan-a real-fm27/A-scan.json --scan-b real-fm27/B-scan.json \
        --actor "你的名字" --basis "人工确认生涯与存档一致" \
        --output docs/evidence/v3.2.7.2/real-fm27
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any

DEFAULT_API = "http://127.0.0.1:8000/api/v1"
ALLOWED_EVIDENCE = {
    "game_internal_save_id",
    "world_id",
    "save_file_hash",
    "save_file_metadata",
    "save_file_header",
    "career_metadata",
    "game_session_metadata",
    "user_confirmed",
    "legacy_unverified",
}
scenarios: list[dict[str, Any]] = []
failures: list[str] = []


def request(
    base: str,
    method: str,
    path: str,
    *,
    body: Any = None,
    params: dict[str, Any] | None = None,
    raw: bytes | None = None,
) -> tuple[int, Any]:
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    url = f"{base}{path}{query}"
    data = raw if raw is not None else (json.dumps(body).encode("utf-8") if body is not None else None)
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"null")


def error_code(payload: Any) -> str | None:
    if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
        value = payload["error"].get("code")
        return str(value) if value is not None else None
    return None


def check(label: str, path: str, status: int, payload: Any, expect: int, predicate: bool, detail: str) -> None:
    ok = status == expect and predicate
    scenarios.append(
        {
            "label": label,
            "path": path,
            "status": status,
            "expect_status": expect,
            "expect": detail,
            "ok": ok,
            "response": payload,
        }
    )
    if not ok:
        failures.append(f"{label}: 期望 {expect}/{detail}，实际 {status} {json.dumps(payload, ensure_ascii=False)[:300]}")


def load_reader_identity(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    identity = data.get("identity") or {}
    session = data.get("session") or {}
    fingerprint = str(identity.get("fingerprint") or "")
    if not fingerprint:
        raise SystemExit(f"{path} 缺少 identity.fingerprint")
    if not fingerprint.startswith("si:v1:file:"):
        raise SystemExit(f"{path} 指纹不是 file 指纹（{fingerprint}），无法用于真实验收")
    if data.get("ambiguous"):
        raise SystemExit(f"{path} 标记 ambiguous=true，按协议不得作为 verified")
    evidence = data.get("evidence") or []
    unknown = sorted({str(item.get("type")) for item in evidence} - ALLOWED_EVIDENCE)
    if unknown:
        raise SystemExit(f"{path} 含协议未定义的证据类型：{', '.join(unknown)}")
    if not evidence:
        raise SystemExit(f"{path} 没有证据，无法注册为 candidate/verified")
    if not session.get("session_key") or not session.get("game_build"):
        raise SystemExit(f"{path} 缺少 session_key 或 game_build；请重跑 save-identity --diagnostics --json")
    return data


def register_payload(reader: dict[str, Any], agent_id: str) -> dict[str, Any]:
    identity = reader["identity"]
    session = reader["session"]
    return {
        "fingerprint": identity["fingerprint"],
        "fingerprint_version": int(identity.get("version") or 1),
        "identity_status": "candidate",
        "confidence": str(identity.get("confidence") or "medium"),
        "kind": str(identity.get("kind") or "save_file"),
        "game_build": session.get("game_build"),
        "plugin_version": session.get("plugin_version"),
        "evidence": [
            {
                "type": item.get("type"),
                "source": item.get("source"),
                "hash": item.get("hash"),
                "version": item.get("version"),
                "confidence": item.get("confidence") or "medium",
                "observed_at": item.get("observed_at"),
            }
            for item in reader.get("evidence", [])
        ],
        "agent_id": agent_id,
        "session_key": session.get("session_key"),
    }


def process_id_of(session_key: str) -> int | None:
    head = session_key.split(":", 1)[0]
    return int(head) if head.isdigit() else None


def main() -> int:
    parser = argparse.ArgumentParser(description="真实 FM27 存档切换受控验收")
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--save-a", type=int, required=True)
    parser.add_argument("--save-b", type=int, required=True)
    parser.add_argument("--identity-a", type=Path, required=True)
    parser.add_argument("--identity-b", type=Path, required=True)
    parser.add_argument("--scan-a", type=Path)
    parser.add_argument("--scan-b", type=Path)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--basis", default="人工确认游戏内生涯与存档一致")
    parser.add_argument("--agent-id", default="manual-acceptance")
    parser.add_argument("--output", type=Path, default=Path("docs/evidence/v3.2.7.2/real-fm27"))
    args = parser.parse_args()

    if args.save_a == args.save_b:
        raise SystemExit("存档 A/B 必须是两个不同的后端存档")
    reader_a = load_reader_identity(args.identity_a)
    reader_b = load_reader_identity(args.identity_b)
    fingerprint_a = reader_a["identity"]["fingerprint"]
    fingerprint_b = reader_b["identity"]["fingerprint"]
    if fingerprint_a == fingerprint_b:
        raise SystemExit("A/B 指纹相同：请确认游戏内确实切换了存档后重新采集身份诊断")

    args.output.mkdir(parents=True, exist_ok=True)
    api = args.api.rstrip("/")
    context_a: dict[str, int] = {"save_id": args.save_a}
    context_b: dict[str, int] = {"save_id": args.save_b}

    # --- 存档 A -------------------------------------------------------------------------------------------
    status, payload = request(api, "POST", "/save-identities/register", body=register_payload(reader_a, args.agent_id), params={"save_id": args.save_a})
    check("register_a", "/save-identities/register", status, payload, 200, payload.get("identity_status") in {"candidate", "verified"}, "注册 A（证据来自 Reader）")
    identity_a = int(payload["identity_id"])
    context_a["save_identity_id"] = identity_a

    verify_body = {"confirmed_fingerprint": fingerprint_a, "basis": args.basis, "actor": args.actor}
    status, payload = request(api, "POST", f"/save-identities/{identity_a}/verify", body=verify_body, params={"save_id": args.save_a})
    check("verify_a", f"/save-identities/{identity_a}/verify", status, payload, 200, payload.get("identity_status") == "verified", "人工确认 A → verified")

    session_a_body = {
        "identity_id": identity_a,
        "session_key": reader_a["session"]["session_key"],
        "process_id": process_id_of(reader_a["session"]["session_key"]),
        "game_build": reader_a["session"].get("game_build"),
        "plugin_version": reader_a["session"].get("plugin_version"),
        "agent_id": args.agent_id,
    }
    status, payload = request(api, "POST", "/save-sessions/start", body=session_a_body, params={"save_id": args.save_a})
    check("start_session_a", "/save-sessions/start", status, payload, 200, payload.get("status") == "verified", "A 会话 verified")
    session_a = int(payload["session_id"])
    context_a["save_session_id"] = session_a

    heartbeat_a = {"identity_id": identity_a, "fingerprint": fingerprint_a, "game_build": reader_a["session"].get("game_build")}
    status, payload = request(api, "POST", f"/save-sessions/{session_a}/heartbeat", body=heartbeat_a, params={"save_id": args.save_a})
    check("heartbeat_a", f"/save-sessions/{session_a}/heartbeat", status, payload, 200, payload.get("status") == "verified", "A 心跳通过")

    capture_a: int | None = None
    if args.scan_a:
        capture_body = {
            "game_date": date.today().isoformat(),
            "reader_version": reader_a["session"].get("plugin_version") or "unknown",
            "game_build": reader_a["session"].get("game_build"),
            "scan_scope": "players",
            "status": "scanning",
            "revision": 0,
        }
        status, payload = request(api, "POST", "/captures", body=capture_body, params=context_a)
        check("capture_a", "/captures", status, payload, 201, int(payload.get("save_identity_id") or 0) == identity_a, "A 采集归属正确")
        capture_a = int(payload["id"])
        status, payload = request(api, "POST", "/imports/scan", raw=args.scan_a.read_bytes(), params=context_a)
        check("import_a", "/imports/scan", status, payload, 201, payload.get("status") in {"succeeded", "partial"}, "A 扫描导入完成")
        status, payload = request(api, "PATCH", f"/captures/{capture_a}", body={"status": "completed"}, params=context_a)
        check("complete_capture_a", f"/captures/{capture_a}", status, payload, 200, payload.get("status") == "completed", "A 采集完成")

    # --- 存档 B -------------------------------------------------------------------------------------------
    status, payload = request(api, "POST", "/save-identities/register", body=register_payload(reader_b, args.agent_id), params={"save_id": args.save_b})
    check("register_b", "/save-identities/register", status, payload, 200, payload.get("identity_status") in {"candidate", "verified"}, "注册 B（证据来自 Reader）")
    identity_b = int(payload["identity_id"])
    context_b["save_identity_id"] = identity_b

    verify_body_b = {"confirmed_fingerprint": fingerprint_b, "basis": args.basis, "actor": args.actor}
    status, payload = request(api, "POST", f"/save-identities/{identity_b}/verify", body=verify_body_b, params={"save_id": args.save_b})
    check("verify_b", f"/save-identities/{identity_b}/verify", status, payload, 200, payload.get("identity_status") == "verified", "人工确认 B → verified")

    session_b_body = {**session_a_body, "identity_id": identity_b, "session_key": reader_b["session"]["session_key"], "process_id": process_id_of(reader_b["session"]["session_key"]), "game_build": reader_b["session"].get("game_build")}
    status, payload = request(api, "POST", "/save-sessions/start", body=session_b_body, params={"save_id": args.save_b})
    check("start_session_b", "/save-sessions/start", status, payload, 200, payload.get("status") == "verified", "B 会话 verified")
    session_b = int(payload["session_id"])
    context_b["save_session_id"] = session_b

    heartbeat_b = {"identity_id": identity_b, "fingerprint": fingerprint_b, "game_build": reader_b["session"].get("game_build")}
    status, payload = request(api, "POST", f"/save-sessions/{session_b}/heartbeat", body=heartbeat_b, params={"save_id": args.save_b})
    check("heartbeat_b", f"/save-sessions/{session_b}/heartbeat", status, payload, 200, payload.get("status") == "verified", "B 心跳通过")

    if args.scan_b:
        capture_body = {
            "game_date": date.today().isoformat(),
            "reader_version": reader_b["session"].get("plugin_version") or "unknown",
            "game_build": reader_b["session"].get("game_build"),
            "scan_scope": "players",
            "status": "scanning",
            "revision": 0,
        }
        status, payload = request(api, "POST", "/captures", body=capture_body, params=context_b)
        check("capture_b", "/captures", status, payload, 201, int(payload.get("save_identity_id") or 0) == identity_b, "B 采集归属正确")
        capture_b = int(payload["id"])
        status, payload = request(api, "POST", "/imports/scan", raw=args.scan_b.read_bytes(), params=context_b)
        check("import_b", "/imports/scan", status, payload, 201, payload.get("status") in {"succeeded", "partial"}, "B 扫描导入完成")
        status, payload = request(api, "PATCH", f"/captures/{capture_b}", body={"status": "completed"}, params=context_b)
        check("complete_capture_b", f"/captures/{capture_b}", status, payload, 200, payload.get("status") == "completed", "B 采集完成")

    # --- 切换：A 的会话上报 B 指纹 -------------------------------------------------------------------------
    stale_heartbeat = {"identity_id": identity_a, "fingerprint": fingerprint_b, "game_build": reader_b["session"].get("game_build")}
    status, payload = request(api, "POST", f"/save-sessions/{session_a}/heartbeat", body=stale_heartbeat, params={"save_id": args.save_a})
    check("switch_invalidates_a", f"/save-sessions/{session_a}/heartbeat", status, payload, 409, error_code(payload) == "save_context_mismatch", "A 会话因 B 指纹失效")

    status, detail = request(api, "GET", f"/save-identities/{identity_a}", params={"save_id": args.save_a})
    check(
        "gate_blocks_after_switch",
        f"/save-identities/{identity_a}",
        status,
        detail,
        200,
        detail.get("capture_allowed") is False and any("invalidated" in item for item in detail.get("blockers", [])),
        "A 采集闸门阻断（会话已失效）",
    )

    if capture_a is not None:
        status, payload = request(api, "PATCH", f"/captures/{capture_a}", body={"status": "failed"}, params=context_a)
        check("stale_capture_rejected", f"/captures/{capture_a}", status, payload, 409, error_code(payload) == "save_session_invalidated", "失效会话不能再写采集")

    status, audit = request(api, "GET", "/save-identity-audit", params={"save_id": args.save_a, "limit": 200})
    events = {item.get("event_type") for item in audit.get("items", [])}
    check("audit_a", "/save-identity-audit", status, {"total": audit.get("total"), "event_types": sorted(events)}, 200, {"registered", "user_confirmed", "session_started", "session_invalidated"}.issubset(events), "A 审计含注册/确认/会话失效")

    status, audit_b = request(api, "GET", "/save-identity-audit", params={"save_id": args.save_b, "limit": 200})
    check("audit_b_isolated", "/save-identity-audit", status, {"total": audit_b.get("total")}, 200, audit_b.get("total", 0) >= 1 and identity_a not in {item.get("identity_id") for item in audit_b.get("items", [])}, "B 审计不含 A 身份")

    result = {
        "captured_at": date.today().isoformat(),
        "api": api,
        "save_a": args.save_a,
        "save_b": args.save_b,
        "fingerprints": {"a": fingerprint_a, "b": fingerprint_b},
        "scenarios": scenarios,
        "failures": failures,
        "ok": not failures,
        "limits": "真实 Reader 输出 + 真实 HTTP；仍属于手动受控验收，不覆盖 Agent auto 循环",
    }
    target = args.output / "manual-switch-result.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    (args.output / "manual-switch-result.sha256").write_text(f"{digest}  {target.name}\n", encoding="utf-8")

    print(f"PASS {len(scenarios) - len(failures)} / {len(scenarios)}")
    for failure in failures:
        print(f"FAIL {failure}")
    print(f"证据：{target}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
