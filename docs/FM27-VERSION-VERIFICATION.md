# FM27 版本兼容性验证（当前状态）

本文是版本兼容的**当前**说明，机器可读事实源：

- `config/compatibility.json`（读取器闸门）
- `live-reader/ScoutMind.FMReader/Versioning/verified-versions.json`（引擎闸门）

两者必须同时为 `verified`，读取器才会进入 `Compatible` 并允许 `probe`/`scan`。

## 1. 当前状态（2026-11-20 真实验收）

| 项 | 值 |
| --- | --- |
| 游戏 | Football Manager 27，appId `4530370`，build **26620374**，版本 27.1.0 |
| 插件 | `game_plugin.dll` **27.1.0+2505117**（`fm_Data\Plugins\x86_64`） |
| 读取器兼容条目 | **verified**（`verifiedAt` 2026-11-19） |
| 引擎兼容条目 | **verified**（build + plugin 命中 `FM27_1`） |
| 扫描 | 允许；同一存档连续 10 次真实扫描全部成功 |

证据：

- 2026-11-19 游戏界面核对：30 人清单的俱乐部/身高/合同到期/球衣号/位置/国籍一致（用户确认）；
- 2026-11-19 交叉校验：367 配对中 CA/PA/身高/出生年 367/367、合同到期 256/256、俱乐部 2/2；
- 2026-11-20 连续 10 次真实扫描：同状态窗口逐字节一致，见
  [docs/acceptance/VERIFY-2026-11-20-SM012-READER.md](acceptance/VERIFY-2026-11-20-SM012-READER.md)；
- 2026-11-20 字段元数据：50 个字段中 11 Verified / 7 Candidate / 32 Pending（`Diag fields`）。

## 2. 四个维度不能混为一谈

| 维度 | 当前结论 | 说明 |
| --- | --- | --- |
| 版本兼容 | **PASS** | build 26620374 + plugin 27.1.0+2505117 已验证；27.0 组合仍是 candidate，会被拒绝 |
| 字段可信度 | **PARTIAL** | 50 字段：11 Verified / 7 Candidate / 32 Pending；Candidate 不得宣传为 Verified |
| 扫描稳定性 | **PASS** | 10 次连续扫描成功；同状态逐字节一致；失败/取消/并发路径有单测 |
| 业务数据完整性 | **PARTIAL** | 合同到期字段异常（32 个可解析合同中 24 个年份不在 2000..2060），未修复 |

### 2.1 合同到期字段异常（未解决）

真实报告 `expiry_diagnostics`：`可解码 8，序日非法 0，年份越界 0，年份异常 24，未设置 0，哨兵值 0`。
即 24/32 合同对象的到期日能按 FM 日期解码，但年份不在合同应有的 2000..2060，说明 `CON_EXPIRY` 偏移在这些对象上
读到的不是"合同到期日"（可能是另一类合同/条款对象）。合同探测保持**非阻塞**数据质量信号，`CON_EXPIRY` 仍是
Candidate，不会因"整体可扫描"升级。

## 3. 两道闸门

| 闸门 | 位置 | 依据 | 拒绝时的表现 |
| --- | --- | --- | --- |
| 读取器兼容清单 | `config/compatibility.json` → `CompatibilityService` | `status=verified` 才进入 `Compatible` | 状态 `Unknown`，`probe`/`scan` 不执行 |
| 引擎版本闸门 | `verified-versions.json` | 构建号 + 插件主次版本，`verified` 才允许读内存 | `probe`/`scan` 返回失败原因 |

两者独立：任一处未 verified 都不会读内存。27.0（build 26577676 / 插件 27.0.1+2503222）目前是 candidate，
会被拒绝；这是设计行为，不是缺陷。

## 4. 为什么不能"编译通过就宣称支持"

上游 FMSuperScout 的 FM27 偏移最初按 27.0 钉；27.1 的布局差异必须逐类核对，否则可能读到"看起来合理但错位"的数据。
`verified-versions.json` 的 `note` 与 `evidence` 记录了每次真实验证；只有新增证据才能把 candidate 改成 verified。

## 5. 新增构建的验证步骤

1. 启动游戏，运行 `ScoutMind.LiveReader.exe status`，确认检测到的 build 与插件版本；
2. 在 `verified-versions.json` 与 `config/compatibility.json` 中登记 candidate 条目（默认拒绝）；
3. 按对象逐类核对（球员身份/能力/属性/位置、合同、俱乐部、球队），记录期望值与实际值；
4. 连续扫描两次，确认球员 id、CA/PA、合同一致；导入后检查球员数量与覆盖率；
5. 把证据写入两个清单的 `evidence`，才能改为 verified。

## 6. 诊断命令

```powershell
# 引擎视角
.\live-reader\tools\ScoutMind.FMReader.Diag\bin\Release\net10.0\ScoutMind.FMReader.Diag.exe status
... fields   # 逐字段偏移/类型/可信度/证据
... report .\exports\report.json

# 读取器视角（含兼容清单闸门）
.\publish\win-x64\ScoutMind.LiveReader.exe status
.\publish\win-x64\ScoutMind.LiveReader.exe probe --engine native
```

## 7. 历史说明

2026-11-18 之前，27.1 被标为 candidate 并拒绝扫描，是因为当时只按 27.0 偏移做静态判断、尚未完成真实核对。
2026-11-19 的界面核对与 367 配对交叉校验完成后，两个清单才改为 verified；旧结论不应再被引用为当前状态。
