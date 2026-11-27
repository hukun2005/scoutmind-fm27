"""V3.3.2 真实数据验收：对运行中的后端调用搜索、AI 足球总监与性能场景。

只读为主；为了让「关注」分类有真实数据，会在当前存档里加入一名球员到关注名单（可重复执行）。
输出 JSON 到 docs/reports/v332_realdata_verification.json。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8000/api/v1"
OUT = Path(__file__).resolve().parents[2] / "docs" / "reports" / "v332_realdata_verification.json"


def timed(fn):
    started = time.perf_counter()
    value = fn()
    return round((time.perf_counter() - started) * 1000, 1), value


def main() -> int:
    client = httpx.Client(timeout=180)
    report: dict = {"checks": {}, "timings": {}, "notes": []}

    boot = client.get(f"{BASE}/meta/bootstrap").json()
    active = boot["active_save_id"]
    saves = {item["id"]: item for item in boot.get("saves", [])}
    report["active_save_id"] = active
    report["saves"] = [
        {key: item.get(key) for key in ("id", "name", "player_count", "snapshot_count", "transfer_count")}
        for item in saves.values()
    ]

    players = client.get(f"{BASE}/players", params={"save_id": active, "page_size": 5}).json()
    first = players["items"][0]
    name = first["name"]
    report["sample_player"] = {"name": name, "instance_id": first["instance_id"], "club": first.get("club")}

    elapsed, body = timed(
        lambda: client.get(f"{BASE}/search", params={"q": name, "type": "players", "save_id": active}).json()
    )
    report["timings"]["search_player_name_ms"] = elapsed
    report["checks"]["search_player_name"] = {
        "status": "PASS" if any(item["entity_id"] == first["instance_id"] for item in body["categories"]["players"]) else "FAIL",
        "hits": len(body["categories"]["players"]),
    }

    elapsed, body = timed(
        lambda: client.get(f"{BASE}/search", params={"q": "ST", "type": "players", "save_id": active}).json()
    )
    report["timings"]["search_position_ms"] = elapsed
    report["checks"]["search_position"] = {
        "status": "PASS" if body["categories"]["players"] else "FAIL",
        "hits": len(body["categories"]["players"]),
    }

    club_name = first.get("club")
    if club_name:
        elapsed, body = timed(
            lambda: client.get(f"{BASE}/search", params={"q": club_name, "type": "clubs", "save_id": active}).json()
        )
        report["timings"]["search_club_ms"] = elapsed
        report["checks"]["search_club"] = {
            "status": "PASS" if body["categories"]["clubs"] else "FAIL",
            "hits": len(body["categories"]["clubs"]),
            "first": body["categories"]["clubs"][0] if body["categories"]["clubs"] else None,
        }

    elapsed, ctx = timed(lambda: client.get(f"{BASE}/agent/director/context", params={"save_id": active}).json())
    report["timings"]["director_context_ms"] = elapsed
    report["checks"]["director_context"] = {
        "status": "PASS" if ctx.get("club") and ctx["counts"]["players"] > 0 else "FAIL",
        "club": (ctx.get("club") or {}).get("name"),
        "players": ctx["counts"]["players"],
        "snapshots": ctx["counts"]["snapshots"],
        "data_updated_at": ctx.get("data_updated_at"),
        "gaps": ctx.get("data_gaps"),
    }

    def verify_recommendations(items: list[dict], save_id: int) -> dict:
        """核对推荐卡片指向的球员是否真实存在且姓名一致（身份一致性，不是建议质量）。"""
        checked = []
        for item in items[:3]:
            instance_id = item.get("instance_id")
            if not isinstance(instance_id, int):
                continue
            profile = client.get(f"{BASE}/players/{instance_id}", params={"save_id": save_id}).json()
            summary = profile.get("summary") or {}
            checked.append(
                {
                    "instance_id": instance_id,
                    "recommended_name": item.get("name"),
                    "resolved_name": summary.get("name"),
                    "resolved_position": summary.get("position"),
                    "match": summary.get("name") == item.get("name"),
                }
            )
        passed = sum(1 for entry in checked if entry["match"])
        return {"checked": len(checked), "matched": passed, "items": checked}

    def ask(question: str) -> tuple[float, dict]:
        return timed(
            lambda: client.post(
                f"{BASE}/agent/director/ask",
                params={"save_id": active},
                json={"question": question},
            ).json()
        )

    for key, question in (
        ("gaps", "我的球队最需要补强什么位置？"),
        ("development", "哪些球员值得重点培养？"),
        ("sell", "哪些球员可以考虑出售？"),
        ("age", "帮我分析球队年龄结构"),
        ("squad", "分析我的球队阵容"),
    ):
        elapsed, answer = ask(question)
        report["timings"][f"director_{key}_ms"] = elapsed
        report["checks"][f"director_{key}"] = {
            "status": "PASS" if answer.get("conclusion") and answer.get("intent") == key else "FAIL",
            "intent": answer.get("intent"),
            "mode": answer.get("mode"),
            "recommendations": len(answer.get("recommendations") or []),
            "data_gaps": answer.get("data_gaps"),
            "sections": [section.get("title") for section in answer.get("sections") or []],
            "identity_check": verify_recommendations(answer.get("recommendations") or [], active),
        }

    watch = client.get(f"{BASE}/watchlist", params={"save_id": active}).json()
    if not watch.get("items"):
        client.post(f"{BASE}/watchlist/items", json={"instance_id": first["instance_id"], "note": "V3.3.2 验收"})
    elapsed, body = timed(
        lambda: client.get(f"{BASE}/search", params={"q": name, "type": "watchlist", "save_id": active}).json()
    )
    report["timings"]["search_watchlist_ms"] = elapsed
    report["checks"]["search_watchlist"] = {
        "status": "PASS" if body["categories"]["watchlist"] else "FAIL",
        "hits": len(body["categories"]["watchlist"]),
        "first": body["categories"]["watchlist"][0] if body["categories"]["watchlist"] else None,
    }
    elapsed, answer = ask("帮我分析当前关注名单")
    report["timings"]["director_watchlist_ms"] = elapsed
    report["checks"]["director_watchlist"] = {
        "status": "PASS" if answer.get("intent") == "watchlist" else "FAIL",
        "intent": answer.get("intent"),
        "recommendations": len(answer.get("recommendations") or []),
        "identity_check": verify_recommendations(answer.get("recommendations") or [], active),
    }

    transfer_save = next((item["id"] for item in saves.values() if (item.get("transfer_count") or 0) > 0), None)
    if transfer_save is not None:
        elapsed, body = timed(
            lambda: client.get(
                f"{BASE}/search", params={"q": "permanent", "type": "transfers", "save_id": transfer_save}
            ).json()
        )
        report["timings"]["search_transfers_ms"] = elapsed
        report["checks"]["search_transfers"] = {
            "status": "PASS" if body["categories"]["transfers"] else "FAIL",
            "save_id": transfer_save,
            "hits": len(body["categories"]["transfers"]),
            "first": body["categories"]["transfers"][0] if body["categories"]["transfers"] else None,
        }
        report["notes"].append("转会搜索使用含演示转会数据的存档；真实存档本身没有转会记录，未伪造。")
    else:
        report["checks"]["search_transfers"] = {"status": "NOT_RUN", "reason": "所有存档都没有转会记录"}

    other = next((item["id"] for item in saves.values() if item["id"] != active), None)
    if other is not None:
        other_players = client.get(f"{BASE}/players", params={"save_id": other, "page_size": 1}).json()
        if other_players.get("items"):
            other_name = other_players["items"][0]["name"]
            body = client.get(f"{BASE}/search", params={"q": other_name, "type": "players", "save_id": active}).json()
            hit_other = any(item["meta"].get("save_id") == other for item in body["categories"]["players"])
            report["checks"]["save_isolation"] = {
                "status": "PASS" if not hit_other else "FAIL",
                "other_save_id": other,
                "other_player": other_name,
            }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    failed = [key for key, value in report["checks"].items() if value.get("status") == "FAIL"]
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except httpx.HTTPError as exc:
        print(f"后端不可用：{exc}", file=sys.stderr)
        raise SystemExit(2)
