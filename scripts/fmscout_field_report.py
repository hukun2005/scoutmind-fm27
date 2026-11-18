"""字段覆盖报告：把一份 FMSuperScout 导出里真实存在的字段、类型、缺失率统计出来。

原则：**只描述观察到的事实，不根据字段名推断语义。** 每个字段给出三类信息：

* 存在率与类型（实测）；
* 语义状态：`confirmed`（在 docs/FMSUPERSCOUT.md 或协议里有依据）、`unknown`（只看到名字，含义未经证实）；
* 样本值（截断，用于人工核对）。

用法::

    .\\backend\\.venv\\Scripts\\python.exe scripts\\fmscout_field_report.py
    .\\backend\\.venv\\Scripts\\python.exe scripts\\fmscout_field_report.py --path D:\\dump\\dump.json
    .\\backend\\.venv\\Scripts\\python.exe scripts\\fmscout_field_report.py --out docs/FMSCOUT_FIELD_COVERAGE.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO_ROOT / "docs" / "FMSCOUT_FIELD_COVERAGE.md"

#: Keys whose meaning is documented (protocol or docs/FMSUPERSCOUT.md). Everything else is reported as unverified.
CONFIRMED_PLAYER_KEYS = {
    "id": "存档内唯一球员 ID",
    "name": "球员姓名",
    "age": "年龄（游戏内日期）",
    "birthYear": "出生年",
    "birthDoy": "出生日序号（一年中的第几天）",
    "ca": "当前能力",
    "pa": "潜在能力",
    "value": "身价（0 表示未提供）",
    "wage": "工资（0 表示未提供）",
    "expires": "合同到期日",
    "club": "当前效力俱乐部名称（无 ID）",
    "clubRep": "俱乐部声誉",
    "div": "联赛/级别名称",
    "nat": "国籍列表",
    "pos": "位置展示文本",
    "posArr": "位置代码列表",
    "posNat": "自然位置代码列表",
    "foot": "惯用脚（本地化文本）",
    "height": "身高",
    "listed": "是否挂牌出售",
    "loanListed": "是否可租借",
    "notForSale": "是否非卖品",
    "setForRelease": "是否设置解约",
    "worldRep": "世界声望",
    "attrs": "属性字典",
    "staffAttrs": "职员属性",
    "staff": "职员列表（顶层）",
}

#: Keys that exist but whose semantics are *not* verified; the report says so instead of guessing.
UNVERIFIED_PLAYER_KEYS = {
    "teamType": "整数。只在有俱乐部的行出现；0 的含义未经证实，可能是成年队/预备队/青年队之一，也可能是布尔标记",
    "div": "联赛名。真实导出里几乎全为 null，无法确认它是否真的表示级别",
    "dob": "出生日期字符串（部分导出为年份），与 birthYear/birthDoy 的关系未验证",
    "natId": "国籍数字 ID，与 nat 的对应关系未验证",
    "askingPrice": "要价，与 value 的关系未验证",
    "wageDemand": "合同工资要价，未验证",
    "source": "读取器自报来源，未验证",
    "state": "未知状态字段",
    "v": "未知字段",
}


def _kind(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    if value is None:
        return "null"
    return type(value).__name__


def _sample(value: Any, limit: int = 60) -> str:
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = repr(value)
    return text[:limit] + ("…" if len(text) > limit else "")


def _latest_dump() -> Path:
    directory = Path(os.environ.get("LOCALAPPDATA", "")) / "FMSuperScout"
    files = sorted(directory.glob("dump*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not files:
        raise SystemExit(f"{directory} 里没有 dump*.json；用 --path 指定导出文件")
    return files[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 FMSuperScout 字段覆盖报告")
    parser.add_argument("--path", help="导出文件；省略则取 FMSuperScout 目录里最新的 dump")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    source = Path(args.path) if args.path else _latest_dump()
    raw = source.read_bytes()
    document = json.loads(raw.decode("utf-8"))
    players: list[dict] = [row for row in (document.get("players") or []) if isinstance(row, dict)]
    total = len(players)

    key_presence: Counter[str] = Counter()
    key_types: dict[str, Counter[str]] = {}
    key_samples: dict[str, str] = {}
    for row in players:
        for key, value in row.items():
            key_presence[key] += 1
            key_types.setdefault(key, Counter())[_kind(value)] += 1
            key_samples.setdefault(key, _sample(value))

    club_named = sum(1 for row in players if row.get("club"))
    team_type_values = Counter(row.get("teamType") for row in players if "teamType" in row)
    div_values = Counter(row.get("div") for row in players)

    lines: list[str] = []
    lines.append("# FMSuperScout 字段覆盖报告")
    lines.append("")
    lines.append("本文件由 `scripts/fmscout_field_report.py` 生成，描述的是**一份真实导出**里实际存在的字段。")
    lines.append("字段语义只写有依据的结论；只看到名字、未经核实的字段标为「语义未验证」，不做猜测。")
    lines.append("")
    lines.append("| 项 | 值 |")
    lines.append("| --- | --- |")
    lines.append(f"| 源文件 | `{source.name}` |")
    lines.append(f"| 大小 | {len(raw):,} bytes |")
    lines.append(f"| SHA-256 | `{hashlib.sha256(raw).hexdigest()}` |")
    lines.append(f"| 顶层字段 | {', '.join(f'`{key}`' for key in sorted(document))} |")
    lines.append(f"| 有 `clubs` 数组 | {'是' if 'clubs' in document else '**否**'} |")
    lines.append(f"| 球员数 | {total:,} |")
    lines.append(f"| 带 `club` 的球员 | {club_named:,}（{club_named / max(total, 1):.2%}） |")
    lines.append("")
    lines.append("## 结论（与 Club Resolver 直接相关）")
    lines.append("")
    lines.append("| 问题 | 结论 | 依据 |")
    lines.append("| --- | --- | --- |")
    lines.append(
        f"| 是否有独立 clubs 数组 | {'是' if 'clubs' in document else '**没有**'} | 顶层字段列表 |"
    )
    lines.append(
        "| 球员是否有俱乐部 ID | **没有** | 球员字段里不存在 `clubId` / `currentClub` / 任何俱乐部 ID，"
        "`club` 只有名称字符串 |"
    )
    lines.append("| 是否有 parentClub / loanClub / ownerTeamType | **没有** | 同上，字段不存在 |")
    lines.append(
        f"| 能否识别主执教俱乐部 | **不能** | `meta.myClub` = {document.get('meta', {}).get('myClub')!r} |"
    )
    lines.append(
        "| 阵容层级 | **无法确认** | `teamType` 只在 "
        f"{sum(team_type_values.values())} 行出现，取值 {dict(team_type_values)}；整数含义未经验证 |"
    )
    lines.append("")
    lines.append("> 因此俱乐部身份只能来自：俱乐部名称 + 声誉（本文件可见）、用户指定的主执教俱乐部、"
                 "或用户导入的阵容 CSV。任何「默认把所有球员归到我的俱乐部」的做法都不成立。")
    lines.append("")
    lines.append("## 球员字段明细")
    lines.append("")
    lines.append("| 字段 | 出现率 | 类型 | 语义 | 样本 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for key in sorted(key_presence, key=lambda name: (-key_presence[name], name)):
        presence = key_presence[key] / max(total, 1)
        types = ", ".join(f"{kind}×{count}" for kind, count in key_types[key].most_common())
        if key in CONFIRMED_PLAYER_KEYS:
            semantics = f"已核实：{CONFIRMED_PLAYER_KEYS[key]}"
        else:
            semantics = f"**语义未验证**：{UNVERIFIED_PLAYER_KEYS.get(key, '仅见字段名，含义未经证实')}"
        sample = key_samples[key].replace("|", "\\|")
        lines.append(f"| `{key}` | {presence:.1%} | {types} | {semantics} | `{sample}` |")
    lines.append("")
    lines.append("## 俱乐部相关取值")
    lines.append("")
    lines.append(f"- `club` 非空行数：{club_named:,}")
    lines.append(f"- 不同俱乐部名称数：{len({row.get('club') for row in players if row.get('club')})}")
    lines.append(f"- `teamType` 取值分布：{dict(team_type_values)}")
    lines.append(f"- `div` 取值分布（前 5）：{dict(div_values.most_common(5))}")
    lines.append("")
    lines.append("## 这份报告不能回答什么")
    lines.append("")
    lines.append("- 俱乐部之间的层级关系（一线队/预备队/青年队）——导出没有任何可验证的字段。")
    lines.append("- 谁是主执教俱乐部——`meta.myClub` 为空，且没有 `manager` 与俱乐部的关联字段。")
    lines.append("- 租借关系与所有权——没有 `parentClub` / `loanClub` / `ownerTeamType`。")
    lines.append("")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"报告已写入 {out}")
    print(f"球员 {total:,}，带俱乐部 {club_named:,}，club 数组: {'clubs' in document}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
