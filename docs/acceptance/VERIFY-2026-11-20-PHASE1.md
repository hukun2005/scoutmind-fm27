# FM27.1 真实环境验收记录（2026-11-20）

- 游戏：Football Manager 2027（Steam appId 4530370）
- 版本：27.1.0，Build **26620374**
- 插件：`game_plugin.dll` 27.1.0+2505117
- Reader：ScoutMind.LiveReader 0.1.0（native 引擎，publish/win-x64）
- 存档：真实存档（FM 内加载），后端 active save = 2
- 执行时间：2026-11-20 18:46–19:00（Asia/Shanghai）

## 1. 版本与闸门

| 检查项 | 结果 |
| --- | --- |
| 进程识别 | PASS（pid 96248，`fm.exe`） |
| AppId / Build / 版本 | PASS：4530370 / 26620374 / 27.1.0 |
| 插件版本 | PASS：27.1.0+2505117 |
| 版本闸门 | PASS：`Compatible`，命中 verified 条目 |
| 配置一致性 | PASS：`configcheck → consistent: true` |
| 执行布局一致性 | PASS：`FM27_1 与上游执行布局完全一致（50 字段，0 差异）` |

## 2. 字段级可信度（诊断报告）

| 探测 | 状态 | 阻塞 | 说明 |
| --- | --- | --- | --- |
| player | Passed | 是 | CA/PA 范围 32/32 |
| club | Passed | 是 | 俱乐部字段可读 |
| team | Passed | 否 | 球队类型 17/17（有合同链样本） |
| contract | **Failed** | 否 | 17 个可解析合同里 12 个到期日异常（数据完整性，见遗留风险） |
| loan | NotApplicable | 是 | 27.1 布局无租借偏移 |
| transfer | Inconclusive | 否 | 未定位转会记录 |
| integrity | Passed | 是 | 样本 96 |
| attributes ×3 | Passed | 是 | 技术/精神/身体 |
| position / nation / team_relation | Passed | 是 | — |
| execution_layout | Passed | 是 | 诊断布局 = 执行布局 |
| women_database | Inconclusive | 否 | 未验证 |

整体：`Verified`，`ScanAllowed = True`。

## 3. 真实扫描

| 项目 | 结果 |
| --- | --- |
| 命令 | `ScoutMind.LiveReader.exe scan --engine native --output exports\scan-sm004` |
| 状态 | `ScanCompleted`，退出码 0 |
| 球员 | **50,365** |
| 俱乐部 | 55 |
| 扫描 ID | `fmreader-10b7ca13d376d611`（第二次 `...2b1622c970762f8b`） |
| 日志 | 未出现读取失败、未出现"无法映射"中止 |
| 内存修改 | 无（只读引擎，未写入游戏内存） |

### 确定性

同一游戏状态下连续扫描两次：球员 50,365 / 俱乐部 55，**字段级零差异**（`scripts/compare_scans.py` → "两次扫描数据完全一致"）。

### 与历史扫描的差异（非缺陷）

与 2026-11-19 扫描（50,839）相比：565 名球员消失、91 名新增、CA/身价等 8,163 处变化——期间用户在游戏中推进了存档（比赛、转会、青训），属于真实数据变化，不是读取不确定性。两次同时刻扫描已证明确定性。

## 4. 导入验证

报文转换：`Diag protocol`（camelCase → snake_case），51.5 MB。

| 项目 | 结果 |
| --- | --- |
| 目标存档 | save 2（active，真实数据） |
| HTTP | 201 |
| 快照 | 50,365 |
| 新身份 | 约 6.4k（新球员），其余按 save_local_uid 命中既有身份 |
| 重复 UID（occurrence 0） | 0 |
| 身份冲突 | 见导入报告（缺生日/生日冲突场景按新规则记录） |

## 5. 转会覆盖率

- 数据源（FMSuperScout 导出 / native dump）**没有历史转会数组** → `transfer_history.available = false`。
- 球员行中的 `transferTo`/`transferDate` 只产生 `status='agreed'` 的待生效记录，不计入历史成交。
- 历史交易需通过独立通道导入（`/imports/transfers`）。

## 6. 结论

| 验收项 | 状态 |
| --- | --- |
| 版本 / Build / 插件 / 闸门 | PASS |
| 字段可信度分层（不越级提升） | PASS |
| 真实扫描（50,365 球员） | PASS |
| 确定性（两次一致） | PASS |
| 导入（快照/身份/无重复 UID） | PASS |
| 转会历史可用性表达 | PASS |
| 合同到期日异常 | **PARTIAL**（数据完整性问题，不阻塞扫描，已记录） |

## 7. 遗留风险

1. 合同探测在真实样本上 5/17 到期日合法：部分合同对象语义不同（可能不是 standard contract），已标记为非阻塞数据完整性信号，待后续单独分析。
2. 俱乐部归属覆盖率仍低（球员行 `club_uid` 覆盖有限），属于映射层限制，不是布局问题。
3. 身高字段仍为 Candidate（31/48,089 与参考导出有 1–6 cm 差异），未提升为 Verified。
