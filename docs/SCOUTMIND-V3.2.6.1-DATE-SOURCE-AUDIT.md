# ScoutMind V3.2.6.1 日期来源审计与调用链审计

- 审计日期：2026-11-24
- 审计范围：`live-reader` 的日期发现/选择链路，`desktop-agent` 的自动采集链路，相关文档与测试
- 审计方式：静态代码走查 + 单元测试 + **真实 FM27 只读验证（2026-11-24，两次独立进程）**

## 1. 结论摘要

1. `world-date` 的命令链路是明确的：CLI → `FmWorldDate` → `WorldDateLocator.Scan` → `WorldDateResolver.Resolve`。
2. 旧实现的选中依据是“结构签名 + 参考日期间隔 + 日期最新”，**没有对象类型证据，也没有人工界面日期验证**，因此只能算启发式。
3. 旧实现把“最新日期”直接作为 `selected_date` 输出，存在把**比赛日期、转会日期、新闻日期**误当成当前日期的风险。
4. `desktop-agent auto` 之前直接使用 `scan` 输出的 `game_date` 导入，**没有日期可信度门槛**，属于高风险路径。
5. 本次已在 Reader 侧新增完整候选诊断、逻辑身份、可信度状态机与安全门；在 Agent 侧新增安全门解析与导入前拦截。
6. 真实 FM27 验证已完成：完整预算下命中 142 条日期记录，`2026-11-06` 所在记录与另外 9 条同构记录共享结构签名，
   因此 Reader 判为 `ambiguous`，真实跨重启验证为 **BLOCKED**；自动快照保持关闭。详见
   `SCOUTMIND-V3.2.6.1-REAL-DATE-VALIDATION.md` 与 `SCOUTMIND-V3.2.6.1-RESTART-VALIDATION.md`。

## 2. 最近一次世界日期调用链

```text
ScoutMind.LiveReader world-date
  └─ Cli.RunWorldDateAsync
       ├─ FmWorldDate.ResolveAsync (live-reader/ScoutMind.FMReader/Engine/FmWorldDate.cs)
       │    ├─ GameBuildDetector.Detect            // 进程 + 构建号 + 插件版本
       │    ├─ VersionGate.Evaluate                // 构建/插件兼容性
       │    ├─ WinMemorySource.Open                // 只读打开游戏内存
       │    ├─ WorldDateLocator.Scan               // 结构签名扫描
       │    └─ WorldDateResolver.Resolve           // 启发式选择
       └─ 输出 selected_date / candidate_count / selection_reason / confidence
```

诊断链路（本次新增）：

```text
ScoutMind.LiveReader world-date --diagnostics [--verify yyyy-MM-dd] [--state <文件>]
  └─ Cli.RunWorldDateDiagnosticsAsync
       └─ FmWorldDateDiagnostics.Analyze
            ├─ GameBuildDetector + VersionGate
            ├─ WinMemorySource.Open
            ├─ WorldDateCandidateCollector.Collect   // 保留全部签名命中
            ├─ DateCandidateTracker.Observe          // 逻辑身份 + 跨读取/跨进程状态
            ├─ DateVerificationStore.Load/Save       // 验证证据持久化
            └─ SnapshotSafetyGate.Evaluate           // 自动快照安全门
```

## 3. 日期候选是怎么来的

`WorldDateLocator` 使用的结构签名：

| 相对日期字段 | 含义 | 约束 |
| --- | --- | --- |
| `+0x00` | 日期值 | 合法 FM 日期，年份 2000..2060 |
| `+0x04` | 参考日期 | 与日期相差 30..400 天 |
| `+0x08` | 哨兵 | `0xFFFFFFFF` |
| `+0x0C` | 零字段 | `0` |
| `+0x10` | 零字段 | `0` |

该结构能证明“这块内存看起来像一个 FM 日期记录”，**不能证明它就是当前世界日期**。

## 4. 旧实现的选择逻辑与风险

- 过滤：非法日期、年份越界、参考日期间隔不在 30..400 天；
- 排序：按日期值取最新；
- 并列：同一天多条 → `ambiguous`；
- 输出：`confidence` 仅为文本，未参与任何自动快照决策。

风险清单：

| 风险 | 说明 | 现状 |
| --- | --- | --- |
| `LATEST_DATE_IS_NOT_CURRENT` | 最新日期可能是未来比赛、转会窗口或新闻日期 | 已改为：未经界面验证一律 `heuristic`，且自动快照 BLOCKED |
| `NO_SAVE_IDENTITY` | 同日同存档只导入一次的限制依赖 `game_date`，无法证明是同一存档 | 安全门显式要求存档身份，当前恒为 BLOCKED |
| `NO_OBJECT_EVIDENCE` | 无法区分比赛/转会/新闻/日历对象 | 已支持对象类型提示，并在无提示时标记 `UNKNOWN_DATE` |
| `NO_RESTART_REASSOCIATION` | 游戏重启后绝对地址变化，旧结果无法复用 | 已引入“模块 + 结构指纹”的逻辑身份 |
| `AUTO_IMPORT_WITH_UNTRUSTED_DATE` | Agent 自动导入没有可信度门槛 | 已加入安全门，未通过时不扫描、不导入 |

## 5. 历史证据回顾（来自既有文档，未在本次重新验证）

`docs/SCOUTMIND-V3.2.2.4-DATE-DISCOVERY-REPORT.md` 等历史文档记录过 2026-10-26、2026-10-28、2026-10-31 等日期观测。
这些属于**历史证据**，本次没有真实 FM27 环境，无法重新复核，因此不作为 V3.2.6.1 的通过依据。

## 6. 本次审计结论

- 调用链没有发现隐式的“系统时间当游戏日期”逻辑；
- 但旧的选择逻辑不足以支撑自动快照，必须由安全门强制阻断；
- 候选诊断、逻辑身份、状态机与安全门已补齐；
- 引用链身份（模块静态 RVA + 指针偏移）已实现并通过自动化测试；
- 真实 FM27 验证已执行（两次独立进程），但因同构日期记录共享签名，身份不唯一，
  结构指纹版的跨重启验证与自动快照均保持 BLOCKED；
- 引用链版已完成真实验证：3 次独立进程（110436 → 113432 → 58416）均与界面日期
  `2026-11-06` 一致，第三次达到 `restart_verified`；
- 自动快照仍保持 BLOCKED，唯一原因是存档身份未实现。
