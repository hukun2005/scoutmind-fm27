"""把一份真实 FMSuperScout 导出登记为回归测试样本（P0-3）。

做三件事：

1. 读取导出的 JSON，去掉与个人相关的元数据（主教练、主机名等），保留游戏数据与字段结构；
2. 复制到 ``backend/tests/fixtures/fmsuperscout/real_sample_NN.json``；
3. 在 ``manifest.json`` 追加一条记录（文件名、版本、导出时间、SHA-256、脱敏了哪些字段）。

用法::

    .\\backend\\.venv\\Scripts\\python.exe scripts\\register_fixture.py
    .\\backend\\.venv\\Scripts\\python.exe scripts\\register_fixture.py --path D:\\dump\\dump-1.json
    .\\backend\\.venv\\Scripts\\python.exe scripts\\register_fixture.py --keep-manager

默认从 ``%LOCALAPPDATA%\\FMSuperScout`` 找最新的 ``dump*.json``。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "backend" / "tests" / "fixtures" / "fmsuperscout"
MANIFEST = FIXTURE_DIR / "manifest.json"

#: Meta keys that carry operator identity rather than game data. They are removed before the sample is committed.
PII_META_KEYS = ("manager", "managers", "host", "_scanManager", "machine", "user")


def default_dump_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", "")) / "FMSuperScout"


def latest_dump(directory: Path) -> Path:
    """Newest ``dump*.json`` in the FMSuperScout data folder."""
    if not directory.exists():
        raise SystemExit(
            f"找不到 FMSuperScout 数据目录：{directory}\n"
            "先在 FMSuperScout 里按 F9 导出一次，或用 --path 指定文件。"
        )
    candidates = sorted(directory.glob("dump*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not candidates:
        raise SystemExit(f"{directory} 里没有 dump*.json。先在 FMSuperScout 里导出一次。")
    return candidates[0]


def next_name() -> str:
    """Next free ``real_sample_NN.json`` name."""
    index = 1
    while (FIXTURE_DIR / f"real_sample_{index:02d}.json").exists():
        index += 1
    return f"real_sample_{index:02d}.json"


def sanitize(document: dict) -> list[str]:
    """Remove operator identity from ``meta``; return the list of removed keys."""
    meta = document.get("meta")
    if not isinstance(meta, dict):
        return []
    removed = [key for key in PII_META_KEYS if key in meta]
    for key in removed:
        meta.pop(key, None)
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description="登记一份真实 FMSuperScout 导出为回归样本")
    parser.add_argument("--path", help="导出文件路径；省略则取 FMSuperScout 目录里最新的 dump")
    parser.add_argument("--dump-dir", default=str(default_dump_dir()), help="FMSuperScout 数据目录")
    parser.add_argument("--keep-manager", action="store_true", help="保留 meta.manager（默认删除）")
    parser.add_argument("--name", help="目标文件名，默认 real_sample_NN.json")
    parser.add_argument("--notes", default="", help="写进 manifest 的备注")
    parser.add_argument(
        "--max-players",
        type=int,
        default=0,
        help="只保留前 N 名球员（优先保留有俱乐部的），用于把 90MB 的真实导出压成可提交的样本；0 表示不裁剪",
    )
    args = parser.parse_args()

    source = Path(args.path) if args.path else latest_dump(Path(args.dump_dir))
    if not source.exists():
        raise SystemExit(f"文件不存在：{source}")

    raw = source.read_bytes()
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"不是有效的 JSON：{exc}") from exc
    if not isinstance(document, dict) or "players" not in document or "meta" not in document:
        raise SystemExit("这不是 FMSuperScout 导出：缺少 meta 或 players")

    meta = document.get("meta") or {}
    source_total = len(document.get("players") or [])
    trimmed = 0
    if args.max_players and source_total > args.max_players:
        players = document.get("players") or []
        # 优先保留有俱乐部的球员，再按 CA 从高到低补足：样本要能覆盖最"有信息量"的行。
        with_club = [item for item in players if isinstance(item, dict) and item.get("club")]
        rest = sorted(
            (item for item in players if isinstance(item, dict) and not item.get("club")),
            key=lambda item: (-(item.get("ca") or 0), -(item.get("pa") or 0)),
        )
        document["players"] = (with_club + rest)[: args.max_players]
        trimmed = source_total - len(document["players"])
    # 职员列表与测试无关，只留两条：既让"staff 被忽略"这条报告仍有依据，又不把 30MB 塞进仓库。
    staff = document.get("staff")
    if isinstance(staff, list) and len(staff) > 2:
        document["staff"] = staff[:2]
    removed = [] if args.keep_manager else sanitize(document)
    sanitized = json.dumps(document, ensure_ascii=False, separators=(",", ":"))
    target = FIXTURE_DIR / (args.name or next_name())
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    target.write_text(sanitized, encoding="utf-8")

    digest = hashlib.sha256(sanitized.encode("utf-8")).hexdigest()
    source_digest = hashlib.sha256(raw).hexdigest()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {"samples": []}
    manifest.setdefault("samples", [])
    entry = {
        "file": target.name,
        "game": meta.get("game"),
        "plugin_version": meta.get("pluginVersion") or meta.get("gameVersion"),
        "generated": meta.get("generated"),
        "players": len(document.get("players") or []),
        "source_players": source_total,
        "trimmed_players": trimmed,
        "source_sha256": source_digest,
        "sha256": digest,
        "sanitized": removed,
        "notes": args.notes or f"来自 {source.name}",
    }
    # 同一份内容重复登记时替换旧条目，避免 manifest 里出现重复文件。
    manifest["samples"] = [item for item in manifest["samples"] if item.get("file") != target.name]
    manifest["samples"].append(entry)
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"来源      : {source}")
    print(f"样本文件  : {target.relative_to(Path.cwd()) if target.is_relative_to(Path.cwd()) else target}")
    print(f"球员数    : {entry['players']}（源 {source_total} 名，裁剪 {trimmed}）")
    print(f"游戏/版本 : {entry['game']} / {entry['plugin_version']}")
    print(f"导出时间  : {entry['generated']}")
    print(f"SHA-256   : {digest}")
    print(f"脱敏字段  : {', '.join(removed) if removed else '（无，或已用 --keep-manager 保留）'}")
    print()
    print("下一步：")
    print("  cd backend")
    print("  .\\.venv\\Scripts\\python.exe -m pytest tests/test_fmscout_real_data.py -v")
    print("真实样本用例现在会实际执行（不再 skip）。若有失败，把输出发我。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
