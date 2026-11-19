"""比较两次扫描的协议内容，验证"同一存档、同一构建"下的确定性。

用法：
    python scripts/compare_scans.py scan1.json scan2.json

只比较数据字段，忽略扫描 ID、观测时间等每次必然不同的字段。
输出：球员/俱乐部的数量、字段级差异计数，以及最多 10 条差异明细。
退出码：0 = 完全一致；1 = 有差异；2 = 用法或解析错误。
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

VOLATILE_SCAN_KEYS = {"scan_id", "observed_at", "started_at", "finished_at", "duration_ms"}


def normalized(name: str) -> str:
    """把 camelCase / snake_case 归一，便于按字段名判断是否属于每次必变的部分。"""
    return name.replace("_", "").lower()


VOLATILE_NORMALIZED = {normalized(item) for item in VOLATILE_SCAN_KEYS}


def load(path: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if "players" not in data:
        raise SystemExit(f"{path} 不是扫描信封（缺少 players）")
    return data


def keyed(records: list[dict], key_fields: tuple[str, ...]) -> dict[str, dict]:
    """按稳定键建索引；键缺失时退回索引本身，避免把两条记录混成一个。"""
    result: dict[str, dict] = {}
    for index, record in enumerate(records):
        parts = [str(record.get(field)) for field in key_fields if record.get(field) is not None]
        key = "|".join(parts) if parts else f"#{index}"
        if key in result:
            key = f"{key}#{index}"
        result[key] = record
    return result


def diff_records(left: dict[str, dict], right: dict[str, dict]) -> tuple[Counter, list[str]]:
    counts: Counter = Counter()
    samples: list[str] = []
    only_left = set(left) - set(right)
    only_right = set(right) - set(left)
    if only_left:
        counts["only_in_first"] += len(only_left)
    if only_right:
        counts["only_in_second"] += len(only_right)
    for key in sorted(only_left)[:5]:
        samples.append(f"仅第一次：{key}")
    for key in sorted(only_right)[:5]:
        samples.append(f"仅第二次：{key}")

    for key in sorted(set(left) & set(right)):
        first, second = left[key], right[key]
        for field in sorted(set(first) | set(second)):
            if normalized(field) in VOLATILE_NORMALIZED:
                continue
            if first.get(field) != second.get(field):
                counts[f"field:{field}"] += 1
                if len(samples) < 10:
                    samples.append(f"{key} 的 {field}：{first.get(field)!r} ≠ {second.get(field)!r}")
    return counts, samples


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2

    first, second = load(sys.argv[1]), load(sys.argv[2])
    print(f"第一次：scan_id={first.get('scan', {}).get('scan_id')} 球员={len(first['players'])} 俱乐部={len(first.get('clubs', []))}")
    print(f"第二次：scan_id={second.get('scan', {}).get('scan_id')} 球员={len(second['players'])} 俱乐部={len(second.get('clubs', []))}")

    first_scan = {k: v for k, v in first.get("scan", {}).items() if normalized(k) not in VOLATILE_NORMALIZED}
    second_scan = {k: v for k, v in second.get("scan", {}).items() if normalized(k) not in VOLATILE_NORMALIZED}
    scan_counts = Counter(
        f"scan.{field}" for field in set(first_scan) | set(second_scan) if first_scan.get(field) != second_scan.get(field)
    )

    players = diff_records(
        keyed(first["players"], ("save_local_uid", "name", "birth_date")),
        keyed(second["players"], ("save_local_uid", "name", "birth_date")),
    )
    clubs = diff_records(keyed(first.get("clubs", []), ("uid", "name")), keyed(second.get("clubs", []), ("uid", "name")))

    print("\n球员差异：", dict(players[0]))
    print("俱乐部差异：", dict(clubs[0]))
    print("scan 元数据差异：", dict(scan_counts))
    for line in (players[1] + clubs[1])[:10]:
        print("  -", line)

    identical = not players[0] and not clubs[0] and not scan_counts
    print("\n结论：", "两次扫描数据完全一致" if identical else "存在差异，需要逐个核对")
    return 0 if identical else 1


if __name__ == "__main__":
    raise SystemExit(main())
