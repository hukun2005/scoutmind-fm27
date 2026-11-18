# FMSuperScout 数据接入

ScoutMind 通过**独立适配层**读取 FMSuperScout 导出的数据。核心业务代码不依赖对方实现，只依赖 ScoutMind 自己的扫描协议。

## 1. 上游与许可证

| 项目 | 内容 |
| --- | --- |
| 项目 | FMSuperScout（Football Manager 27 / 26 的开源球探工具） |
| 仓库 | <https://github.com/mavarobli/FMSuperScout> |
| 许可证 | MIT |
| 我们如何使用 | 只读取它在本地写出的 JSON 导出文件；不复制其代码、不修改其文件 |

ScoutMind 不复用 FMSuperScout 的源码，只按其导出格式做字段映射。本文档记录格式依据，便于上游改版时快速定位差异。

## 2. 分层位置

```
FMSuperScout（第三方读取器）
  ↓ 本地 dump JSON（只读）
ScoutMind Data Adapter   backend/app/ingestion/adapters/fmscout.py
  ↓ 转换 + 字段映射报告
Scan Protocol v1         docs/DATA_PROTOCOL.md（source = fmsuperscout）
  ↓ 校验、身份匹配、快照追加（与其它扫描完全相同的路径）
ScoutMind Database
```

适配器是唯一知道对方格式的地方。它输出标准扫描报文，导入仍然走 `ScanImporter`，因此幂等、去重、行级拒绝、快照追加的保证与短信道一致。

## 3. 导出文件

FMSuperScout 在游戏内按 F9 导出一份 dump，默认写到：

- Windows：`%LOCALAPPDATA%\FMSuperScout\dump*.json`
- macOS：见上游文档（同样以 `dump` 开头、`.json` 结尾）

结构（依据上游源码中的读取逻辑）：

```json
{
  "meta": {
    "generated": "2027-03-01T18:30:00+00:00",
    "game": "FM27",
    "gameDate": "2027-03-01",
    "myClub": "Northbridge United",
    "myClubRep": 7456,
    "manager": "Local Manager"
  },
  "players": [
    {
      "id": 9001, "name": "Adam Wharton", "birthYear": 2004, "birthDoy": 37, "age": 23,
      "ca": 148, "pa": 165, "value": 42000000, "wage": 60000, "expires": "2029-06-30",
      "club": "Northbridge United", "clubRep": 7456, "div": "Premier Division",
      "nat": "England", "pos": "DM (C), MC", "posArr": ["DM", "MC"], "posNat": ["DM"],
      "worldRep": 5200,
      "attrs": {"Passing": 15, "Tackling": 13, "Stamina": 16, "OffTheBall": 12, "Corners": 6}
    }
  ],
  "staff": []
}
```

## 4. 字段映射

| dump 字段 | ScoutMind 协议字段 | 说明 |
| --- | --- | --- |
| `id` | `save_local_uid` / `record_id` | 存档内唯一 ID，作为身份匹配键 |
| `name` | `name` | 必填 |
| `birthYear` + `birthDoy` | `birth_date` | 只有年份时留空，改用 `age` |
| `age` | `age` | 协议 v1 新增字段；来源直接给年龄时不再由生日反推 |
| `ca` / `pa` | `ca` / `pa` | ≤0 或哨兵值 → `null` |
| `value` / `wage` | `market_value` / `wage` | `0xFFFFFFFF` 级哨兵 → `null` |
| `expires` | `contract_end` | 取前十位日期 |
| `club` | `clubs[].name` + `clubs[].uid` | uid 由名称派生（`fs-<slug>`） |
| `clubRep` | `clubs[].reputation` | `0xFFFF` → `null` |
| `div` | `clubs[].league` | 用于联赛级别比较 |
| `nat` | `nationality` | |
| `posNat` / `posArr` / `pos` | `position` | 优先自然位置，其次任何列出位置 |
| `attrs` | `attributes` | 见下方属性映射 |
| `meta.myClub` | `scan.user_club_uid` + `clubs[].is_user_club` | 阵容模块据此确定「我的球队」 |
| `meta.generated` | `scan.observed_at` | 唯一确定这份导出 |
| `meta.gameDate` | `scan.game_date` | 合同分桶与年龄参考 |

属性名从上游 PascalCase 映射到 ScoutMind 字典（例如 `OffTheBall → off_the_ball`、`JumpingReach → jumping`、
`FreeKicks → free_kick`）。上游有、ScoutMind 没有的属性（`Corners`、`LongThrows`、`Throwing`）会被忽略并写进报告。

哨兵与幽灵记录：

- `club` 为空且 `worldRep == 0xFFFF` 的行是尚未进入游戏世界的 newgen，跳过（与上游行为一致）；
- `0` CA、`0xFFFF` 声誉、`0xFFFFFFFF` 金额一律写 `NULL`，不用 0 冒充观测值。

## 5. 导出中不存在的数据

| 缺失 | 影响 |
| --- | --- |
| 出场时间、出场次数、进球、助攻 | 表现分析显示「不可用」 |
| 逐场与赛季统计块 | 表现分析的百分位、趋势不可用 |
| 转会记录 | 转会情报只能显示库里已有的数据 |
| 伤病记录 | 转会决策报告的伤病风险仍为「不可评估」 |
| 挂牌 / 租借状态 | 隐藏价值的两条规则标为「无法评估」 |

这些不是实现缺陷，而是数据源边界；适配报告会把它们逐条列出。

## 6. 三种导入方式

### 手动导入

```powershell
# 网页：数据与诊断 → 「FMSuperScout 接入」→ 预览字段映射 / 转换并导入
# 或直接把 dump 拖到「上传扫描数据」，后端按结构自动识别来源
.\scripts\import-fmscout.ps1                          # 自动找最新 dump 并导入
.\scripts\import-fmscout.ps1 -Path D:\dump\dump-1.json
.\scripts\import-fmscout.ps1 -Preview                 # 只输出映射报告，不写库
```

### 定时同步

```powershell
# 计划任务里每 30 分钟跑一次；同一份 dump 靠内容哈希幂等，重复执行不会产生重复快照
schtasks /create /tn "ScoutMind FMSuperScout" /tr "powershell -File C:\path\scripts\import-fmscout.ps1" /sc minute /mo 30
```

### 实时读取（实验）

```powershell
.\scripts\import-fmscout.ps1 -Watch -IntervalSeconds 15
```

FMSuperScout 每次 F9 都会写新 dump；脚本轮询目录，发现新文件就导入。它不接触游戏进程，因此比读取器更保守，
但延迟取决于导出频率。

## 7. 适配报告

每次转换都会产出报告，接口与界面都会显示：

- `players_total` / `players_skipped` / `players_converted` / `clubs_converted`
- `mapped_fields`：实际用到的协议字段
- `absent_fields`：导出里没有的字段（对应功能显示为不可用）
- `ignored_fields`：刻意忽略的字段与原因
- `attributes_ignored`：ScoutMind 没有对应键的属性
- `coverage`：每个关键字段的非空比例
- `warnings`：幽灵记录、缺少转会数据等提示

## 8. 已验证与未验证

| 项 | 状态 |
| --- | --- |
| 字段结构 | 依据上游源码的读取逻辑与属性表整理 |
| 适配器行为 | 单元测试覆盖：映射、哨兵、幽灵记录、幂等、预览不写库、自动识别 |
| 端到端 | 合成 dump → 导入 → 阵容评分 / 球探检索可正常出结果 |
| 真实 FM27 导出 | **未在本机验证**：需要你在装有 FM27 与 FMSuperScout 的机器上导出一份真实 dump 后核对字段 |
| 上游改版 | 未验证；`detect()` 只接受可识别的结构，字段变化会体现在报告的 `absent_fields` / `ignored_fields` 中 |

拿到真实导出后建议先跑 `-Preview`，确认 `players_converted` 与游戏内数量一致、`absent_fields` 符合预期，再执行导入。

## 9. 安全边界

- 只读：只读取 dump 文件，不打开、不写入、不锁定游戏进程与存档。
- 不改对方数据：不写 `%LOCALAPPDATA%\FMSuperScout` 目录，不修改 dump。
- 幂等：`scan_id = fmscout-<dump 内容 sha256 前 16 位>`，同一份导出重复导入返回 `duplicate=true`。
- 可追溯：原始 dump 与其它报文一样落盘（`backend/data/raw`），导入任务记录 `source=fmsuperscout`。
- 许可证：FMSuperScout 为 MIT；ScoutMind 不复用其代码，仅依据其公开格式做数据交换，双方许可证互不传染。
