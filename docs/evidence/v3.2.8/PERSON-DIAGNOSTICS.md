# Phase 6：只读诊断命令（真实运行）

> 运行日期：2026-11-25 · 游戏：FM27 27.1 · 构建 26620374 · 插件 27.1 · 进程 pid 72012
> 证据文件：`person-dump-summary-2026-11-25.json`、`person-dump-xref-2026-11-25.json`、`person-dump-calibration-2026-11-25.json`

## 1. 命令模式

| 模式 | 命令 | 输出 |
| --- | --- | --- |
| 摘要（默认） | `dump` / `dump --summary` | 进程、版本、候选 Person 数、有效/无效对象、姓名/生日读取成功率、关联成功率、冲突数、Verified 数 |
| 关联统计 | `dump --xref` | 关联成功数/成功率、冲突数、关联状态分布 |
| 校准统计 | `dump --calibration` | 抽样数、姓名/生日有效数、结构通过数、不稳定数、置信度、状态、失败原因计数 |
| 单记录转储 | `dump <index> [length]` / `dump --person <index> --length <n>` | 旧版行为：非零指针与内联 ASCII 串（保留） |

- 默认不再转储球员记录，也不再默认输出全量进程内存。
- 所有模式只读；不写内存、不写存档、不修改保护属性、不注入 DLL。
- 摘要/关联/校准输出已脱敏，不含 Person 指针或完整内存地址；指针只出现在显式使用的旧版单记录转储中。

## 2. 摘要字段

| 字段 | 含义 |
| --- | --- |
| `located_count` | 定位到的候选 Person 数 |
| `sampled` | 跨区域等距抽样数 |
| `valid_object_count` | 指针与结构校验通过的抽样数 |
| `invalid_pointer_count` | 指针为 0 或结构被拒绝的抽样数 |
| `name_read_count` / `name_read_success_rate` | 姓名读取成功数与成功率 |
| `date_of_birth_read_count` / `date_of_birth_read_success_rate` | 生日读取成功数与成功率 |
| `attribute_link_unique` / `attribute_link_success_rate` | 属性记录唯一关联数与成功率 |
| `conflict_count` | 多候选或身份冲突数 |
| `verified_count` | Verified 数量；本进程无持久化存储，固定为 0 |
| `full_memory_dump` | 固定为 `false` |

## 3. 本次真实运行结果

### 3.1 摘要（`dump --summary --located 800 --samples 60`）

| 指标 | 值 |
| --- | --- |
| 定位数量 | 800 |
| 抽样数量 | 60 |
| 有效对象 | 60 |
| 无效指针 | 0 |
| 姓名读取 | 48/60（0.80） |
| 生日读取 | 60/60（1.00） |
| 属性记录唯一关联 | 60/60（1.00） |
| 冲突 | 0 |
| Verified | 0 |
| 全量内存转储 | 否 |

### 3.2 关联统计（`dump --xref --located 800 --samples 60`）

- 关联成功率 1.00，冲突 0；状态分布全部为 `SingleCandidate`。
- 12/60 条记录姓名为空，依靠 UID + 生日完成唯一关联。

### 3.3 校准统计（`dump --calibration --located 800 --samples 24 --reads 3`）

- 姓名有效 19/24，生日有效 24/24，不稳定 0，置信度 0.40，状态 `Unverified`。
- 状态为 `Unverified` 是抽样覆盖率导致（部分记录姓名槽为空），不是读取失败；报告未升级为 Verified。

### 3.4 旧版单记录转储

`dump 165 256` 返回 `read_ok = true`，旧行为保持可用。

## 4. 限制

- 抽样为 60/800，用于诊断健康度，不代表全库统计。
- `verified_count` 固定为 0：本进程没有 Canonical Identity 持久化，也不在本命令中执行 Mark(Verified)。
- 姓名读取率 0.80 反映部分记录姓名槽为 0；这些记录仍可通过 UID + 生日建立唯一关联，但不满足 Phase 5 的姓名前置条件。
- 校准状态 `Unverified` 是当前抽样覆盖率的真实结果；没有用历史数据替代现场检测。

## 5. 复现

```text
ScoutMind.FMReader.Diag.exe dump --summary --located 800 --samples 60
ScoutMind.FMReader.Diag.exe dump --xref --located 800 --samples 60
ScoutMind.FMReader.Diag.exe dump --calibration --located 800 --samples 24 --reads 3
ScoutMind.FMReader.Diag.exe dump 165 256
```

## 6. 测试

- ScoutMind.FMReader.Tests：281/281 PASS（新增 4 项诊断摘要测试）。
- 覆盖：完整样本成功率、姓名缺失不默认为成功、同名不同 UID 冲突计数、空输入不崩溃。
