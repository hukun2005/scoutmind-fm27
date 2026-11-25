"""V3.2.7.4 运行期验收：operation_id 幂等、内容冲突与断网重连审计（真实 HTTP）。

验证：

1. 同 operation_id + 同内容 → 返回原结果（``duplicate=true``，同一 job/scan）；
2. 同 operation_id + 不同内容 → 409 ``operation_conflict``；
3. 同 scan_id + 不同内容 → 409 ``scan_payload_mismatch``；
4. 重放会递增 ``attempt_count`` 并写 ``operation_replayed``；
5. ``heartbeat(reconnected=true)`` 写 ``network_reconnected``。

``--database`` 指向临时 SQLite 时，会插入一条 ``rejected`` 任务以验证
「被拒绝的 operation 不能自动重放」；仅限本地临时库。

用法：
    python tools/runtime-acceptance/verify_operation_idempotency.py \
        --api http://127.0.0.1:8123/api/v1 --database <临时库路径> --output runtime-evidence
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
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
            with urllib.request.urlopen(req, timeout=120) as response:
                return response.status, json.loads(response.read() or b"null")
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read() or b"null")


def error_code(payload: Any) -> str | None:
    for key in ("error", "detail"):
        value = payload.get(key) if isinstance(payload, dict) else None
        if isinstance(value, dict) and value.get("code") is not None:
            return str(value["code"])
    return None


def payload_bytes(scan_id: str, marker: str = "same") -> bytes:
    document = {
        "schema_version": "1.0",
        "source": "synthetic_fixture",
        "scan": {"scan_id": scan_id, "observed_at": "2026-11-25T00:00:00"},
        "players": [],
        "transfers": [],
        "warnings": [f"acceptance-marker:{marker}"],
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
            "agent_id": "acceptance-idempotency",
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
        body={"confirmed_fingerprint": fingerprint, "basis": "运行期验收合成身份", "actor": "acceptance-idempotency"},
    )
    if status != 200:
        raise SystemExit(f"确认身份失败：{status} {payload}")
    status, payload = api.request(
        "POST",
        "/save-sessions/start",
        params={"save_id": save_id},
        body={"identity_id": identity_id, "session_key": f"{uuid.uuid4().int % 100000}:idem", "process_id": 404, "agent_id": "acceptance-idempotency"},
    )
    if status != 200:
        raise SystemExit(f"启动会话失败：{status} {payload}")
    return identity_id, int(payload["session_id"])


def insert_rejected_job(database: str, save_id: int, scan_id: str, operation_id: str) -> int:
    connection = sqlite3.connect(database, timeout=30)
    try:
        cursor = connection.execute(
            "INSERT INTO import_jobs (fm_save_id, scan_id, source, schema_version, status, attempt_count, "
            "operation_id, rejected_reason, player_count, transfer_count, warnings_json, coverage_json, "
            "received_at, created_at, updated_at) "
            "VALUES (?, ?, 'reader', '1.0', 'rejected', 1, ?, 'write_session_epoch_stale', 0, 0, '[]', '{}', "
            "datetime('now'), datetime('now'), datetime('now'))",
            (save_id, scan_id, operation_id),
        )
        connection.commit()
        return int(cursor.lastrowid)
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="operation_id 幂等与重连审计验收")
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--token")
    parser.add_argument("--database", help="临时 SQLite 路径；用于插入 rejected 任务")
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

    status, save = api.request("POST", "/saves", body={"name": f"idempotency-{run}"})
    if status != 201:
        raise SystemExit(f"创建存档失败：{status} {save}")
    save_id = int(save["id"])
    identity_id, session_id = register_verified(api, save_id, f"si:v1:test:idem:{run}")
    context = {"save_id": save_id, "save_identity_id": identity_id, "save_session_id": session_id}
    scan_id = f"idem-{run}"
    operation_id = f"op-idem-{run}"

    # --- 1. 首次导入 ---------------------------------------------------------------------------------
    status, first = api.request(
        "POST",
        "/imports/scan",
        params={**context, "operation_id": operation_id},
        raw=payload_bytes(scan_id, "v1"),
    )
    check("first_import", status == 201 and first.get("duplicate") is False, {"status": status, "duplicate": first.get("duplicate")}, "201 duplicate=false")

    # --- 2. 同 op 同内容重放 --------------------------------------------------------------------------
    status, replay = api.request(
        "POST",
        "/imports/scan",
        params={**context, "operation_id": operation_id},
        raw=payload_bytes(scan_id, "v1"),
    )
    check(
        "replay_same_operation_same_payload",
        status in {200, 201} and replay.get("duplicate") is True and replay.get("job_id") == first.get("job_id"),
        {"status": status, "duplicate": replay.get("duplicate"), "job_id": replay.get("job_id")},
        "duplicate=true 且同一 job",
    )

    # --- 3. 同 op 不同内容 ----------------------------------------------------------------------------
    status, conflict = api.request(
        "POST",
        "/imports/scan",
        params={**context, "operation_id": operation_id},
        raw=payload_bytes(f"{scan_id}-other", "v2"),
    )
    check(
        "same_operation_different_payload",
        status == 409 and error_code(conflict) == "operation_conflict",
        {"status": status, "code": error_code(conflict)},
        "409 operation_conflict",
    )

    # --- 4. 同 scan 不同内容、不同 op -----------------------------------------------------------------
    status, scan_conflict = api.request(
        "POST",
        "/imports/scan",
        params={**context, "operation_id": f"op-other-{run}"},
        raw=payload_bytes(scan_id, "v3"),
    )
    check(
        "same_scan_different_payload",
        status == 409 and error_code(scan_conflict) == "scan_payload_mismatch",
        {"status": status, "code": error_code(scan_conflict)},
        "409 scan_payload_mismatch",
    )

    # --- 5. attempt_count 与 operation_replayed -------------------------------------------------------
    listing = api.request("GET", "/imports", params={"save_id": save_id, "limit": 20})[1].get("items") or []
    job = next((item for item in listing if item.get("id") == first.get("job_id")), None)
    check("attempt_count_incremented", job is not None and int(job.get("attempt_count") or 0) >= 2, job, "attempt_count ≥ 2")

    audit = api.request("GET", "/save-identity-audit", params={"save_id": save_id, "limit": 200})[1]
    events = {item.get("event_type") for item in (audit.get("items") or [])}
    check("audit_operation_replayed", "operation_replayed" in events, sorted(events), "含 operation_replayed")
    check("audit_operation_conflict", "operation_conflict" in events, sorted(events), "含 operation_conflict")

    # --- 6. rejected operation 不能自动重放 ------------------------------------------------------------
    if args.database:
        rejected_scan = f"rejected-{run}"
        rejected_op = f"op-rejected-{run}"
        insert_rejected_job(args.database, save_id, rejected_scan, rejected_op)
        status, rejected = api.request(
            "POST",
            "/imports/scan",
            params={**context, "operation_id": rejected_op},
            raw=payload_bytes(rejected_scan, "rejected"),
        )
        check(
            "rejected_operation_not_replayed",
            status == 409 and error_code(rejected) == "operation_rejected",
            {"status": status, "code": error_code(rejected)},
            "409 operation_rejected",
        )
    else:
        partials.append("rejected_operation 未执行：未提供临时数据库路径（NOT_RUN）")

    # --- 7. 断网重连心跳写审计 ------------------------------------------------------------------------
    status, heartbeat = api.request(
        "POST",
        f"/save-sessions/{session_id}/heartbeat",
        params={"save_id": save_id},
        body={"identity_id": identity_id, "reconnected": True},
    )
    check("reconnected_heartbeat", status == 200, {"status": status, "session": heartbeat.get("status")}, "200")
    audit = api.request("GET", "/save-identity-audit", params={"save_id": save_id, "limit": 200})[1]
    events = {item.get("event_type") for item in (audit.get("items") or [])}
    check("audit_network_reconnected", "network_reconnected" in events, sorted(events), "含 network_reconnected")

    result = {
        "tool": "verify_operation_idempotency",
        "synthetic_identity": True,
        "real_fm27": False,
        "api": args.api,
        "checks": checks,
        "failures": failures,
        "partials": partials,
        "ok": not failures,
        "status": "PASS" if not failures else "FAIL",
    }
    target = args.output / "operation-idempotency-result.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"{'PASS' if not failures else 'FAIL'} operation-idempotency: {len(checks) - len(failures)}/{len(checks)}")
    for partial in partials:
        print(f"PARTIAL {partial}")
    for failure in failures:
        print(f"FAIL {failure}")
    print(f"证据：{target}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
