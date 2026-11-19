# 原生读取引擎整合 · 阶段报告

目标：把 FMSuperScout 的 Windows 只读内存内核整合进 ScoutMind，让用户只需启动 FM27 + ScoutMind，
不再单独安装/启动 FMSuperScout。**代码完成 ≠ 真实数据读取成功**，本文件按阶段如实记录。

## 阶段状态

| 阶段 | 内容 | 状态 |
| --- | --- | --- |
| Phase 1 | 固定上游 commit、许可证、源码构建 | **完成** |
| Phase 2 | 新建 `ScoutMind.FMReader`，接入读取内核 | **完成** |
| Phase 3 | 协议适配（players/clubs/contracts/coverage/warnings） | **完成**，并已在真实后端导入验证 |
| Phase 4 | FM27 27.1 真实版本适配 | **未完成（被闸门正确拒绝）** |
| Phase 5 | 接入 Reader / Desktop Agent / FastAPI | **完成** |
| Phase 6 | 真实存档端到端验收 | **未完成（依赖 Phase 4）** |

## Phase 1：上游固定与许可证

| 项 | 值 |
| --- | --- |
| 仓库 | https://github.com/mavarobli/FMSuperScout |
| commit | `6cf8f87af24108d17667e415bb43f1c99eb6995e` |
| 许可证 | MIT，原文保留在 `third_party/FMSuperScout/LICENSE` |
| 纳入文件 | 6 个：`Dumper.cs`、`Fields.cs`、`Host.cs`、`Json.cs`、`MemScan.cs`、`MemScan.Win.cs` |
| 排除 | `app/`、`scanner/`、`plugin/`、`installer/`、`stats/`、`mac/`、`MemScan.Mac.cs` |
| 本地修改 | 1 处：`Dumper.OutDir` 支持 `SCOUTMIND_FMREADER_OUTDIR`（`patches/0001-outdir-override.patch`） |

构建结果：`dotnet build -c Release` 成功，只有 1 条上游 nullable 警告（`MemScan.Win.cs:167`）。

## Phase 2：引擎

新增 `live-reader/ScoutMind.FMReader`：

| 文件 | 作用 |
| --- | --- |
| `Engine/IFmScanEngine.cs` | `GetStatusAsync` / `ProbeAsync` / `ScanAsync` + 结果模型 |
| `Engine/FMSuperScoutMemoryEngine.cs` | 定位 → 闸门 → 上游读取 → 协议映射；失败即失败 |
| `Engine/FmProcessLocator.cs` | 进程识别（必须是带 `fm_Data` 的 `fm.exe`）、插件版本、AppId |
| `Engine/…DumpProvider` | 调 `Dumper.TryDump`，dump 写到 ScoutMind 临时目录 |
| `Versioning/VersionGate.cs` | 构建号 + 插件主次版本；只有 `verified` 放行 |
| `Versioning/verified-versions.json` | 已验证清单（本机 27.1 为 `candidate`） |
| `Integration/UpstreamDumpMapper.cs` | 上游结构 → 标准协议（不把上游结构传给 Python） |
| `Integration/upstream-attributes.json` | 属性映射表，由后端 `ATTRIBUTE_MAP` 生成，避免两套真相 |

只读约束：上游使用 `ReadProcessMemory`；ScoutMind 不写入、不注入、不 hook。

## Phase 3：协议适配

输出遵循 `docs/DATA_PROTOCOL.md`：

| 域 | 支持 | 说明 |
| --- | --- | --- |
| players | 是 | 稳定 ID、姓名、出生日期、国籍、位置、CA/PA、身价、工资、合同到期、身高、惯用脚、世界声望、属性、状态 |
| clubs | 是 | 从球员行的俱乐部名称派生稳定 uid（与后端 `name:<slug>` 算法一致），带入声誉 |
| contracts | 是 | `contract_end`；无法解析则留空并告警 |
| teams / team_tiers | **否** | 上游只给整数 `teamType`，语义未验证，因此不映射，写 `coverage=false` |
| loans / ownership | **否** | 上游无 `parentClub` / `loanClub` / `ownerTeamType`，写 false 并告警 |
| agreed_transfers | **否** | 同上 |
| completed transfers | **否** | 上游 dump 不含转会历史 |
| statistics | **否** | 上游 dump 不含逐场统计 |
| coverage / warnings | 是 | 每个缺失域都写 false，并说明原因 |

真实后端集成验证：把映射出的 300 人报文 `POST /api/v1/imports/scan`，
返回 `status=succeeded`、`players_created=300`、`rows_rejected=0`；重复投递返回 `duplicate=true`（幂等）。
覆盖度 `player_fields=0.9167`，`warnings` 完整列出转会/租借/梯队/teamType 等缺口。

## Phase 4：FM27 27.1 适配（未完成）

事实：

```
游戏    appId=4530370  build=26620374  版本=27.1.0
插件    27.1.0+2505117（FileVersion 27.1）
上游    FMSuperScout 1.7.3，Fields.FM27 支持 27.0（SupportedMinor=0）
```

结论：上游偏移按 27.0 钉，本机是 27.1，**不能视为已支持**。闸门把该构建标为 `candidate` 并拒绝读内存：

```
probe → passed=false
reason: 构建 26620374 未验证：… 本机是 27.1，偏移未逐类核对。
```

为什么不能硬上：偏移错位读到的是"别的数值"，扫描会成功、数据会看起来正常，但全错。任务书也禁止
"编译通过即宣称支持"。要把状态改成 `verified`，必须按
[`docs/FM27-VERSION-VERIFICATION.md`](FM27-VERSION-VERIFICATION.md) 逐类对照游戏内界面核对 CA/PA、属性、
合同、俱乐部归属，并留下记录。

## Phase 5：接入

| 变更 | 说明 |
| --- | --- |
| `ScoutMind.Reader` 引用 `ScoutMind.FMReader` | 发布产物自带引擎，无外部依赖 |
| 新增 `NativeScanBackend` / `IScanBackend` / `ScanBackendFactory` | 默认用内置引擎；`--engine external` 才用外部扫描器 |
| `ScannerAdapter` 保留 | 需要外部扫描器时仍可用，只是不再是默认路径 |
| `--engine native|external` | 新增命令行选项，默认自动选择 |
| Agent 诊断 | `agent.json` 视图增加 `engine` 字段 |
| `publish-windows.ps1` | 发布提示改为"直接 scan，不需要外部扫描器" |

`publish\win-x64` 实际产出：`ScoutMind.LiveReader.exe`（37.7 MB，自包含单文件）+ `ScoutMind.Agent.exe`（37.8 MB）。

## Phase 6：真实端到端（未完成）

当前机器上 FM27 未运行（进程表里没有 `fm.exe`），且构建未验证，因此：

```
ScoutMind.LiveReader.exe status → 状态 Unknown，兼容性 Candidate，未执行 probe/scan
ScoutMind.FMReader.Diag probe   → passed=false（版本闸门拒绝）
```

这就是当前唯一诚实的结论：**自动识别游戏与版本已可用；只读扫描在 27.1 上被拒绝**。
一旦按 Phase 4 完成核对并更新两处清单，`scan` 才会读内存并把报文写进
`publish\win-x64\scan --output <目录>`，之后 `/imports/scan` 导入即可。

## 自动化测试

| 套件 | 结果 |
| --- | --- |
| `ScoutMind.FMReader.Tests`（新增） | **39 项全部通过**：进程识别、版本闸门、未知版本拒绝、球员/俱乐部/合同/属性映射、协议 JSON、租借与梯队缺失告警、读取失败、真实样本回归（300 人） |
| `ScoutMind.Reader.Tests`（既有） | **46 项全部通过** |
| 后端 | 109 项通过（未改动协议，仅验证接受原生报文） |

## 未解决 / 下一步

1. **Phase 4 是唯一阻塞项**：需要有人对着运行中的 FM27 逐类核对 27.1 偏移（CA/PA、属性、合同、俱乐部、球队层级），
   把结果写进 `verified-versions.json` 与 `config/compatibility.json`。我无法代替游戏内界面核对。
2. 上游能提供的阵容层级只有整数 `teamType`；即使偏移全部核对通过，梯队仍需阵容 CSV（已有实现）。
3. 转会历史与逐场统计上游 dump 不含；要补需要另找数据源，不在"整合读取核心"的范围内。
4. 若后续上游发布 27.1 布局，按 `third_party/FMSuperScout/UPSTREAM.md` 升级并重跑本报告的测试即可。

---

# 追加：27.1 布局隔离与自动化探测（2026-11-19）

在第一阶段报告之后，按"27.1 自动化版本适配"任务补了第二到第五阶段的基础设施，并把第六阶段推进到
"真实进程探测已跑通、等待加载存档"。

## 新增内容

| 阶段 | 交付 | 状态 |
| --- | --- | --- |
| 一 分析 | `docs/FM27-27.1-ANALYSIS.md`：全部布局定义、27.0 关键偏移、四处版本识别、探测逻辑、不可验证字段、27.1 适配清单 | 完成 |
| 二 布局隔离 | `FM27_0_Layout`、`FM27_1_Layout`、`LayoutResolver`、`CompatibilityRegistry`、`GameBuildDetector` | 完成 |
| 三 自动探测 | 球员/俱乐部/球队/合同/租借/转会/完整性 7 组只读探测，带时间预算与样本上限 | 完成 |
| 四 字段校验 | 范围、类型、堆指针合法性、对象关系、跨字段一致性（CA≤PA、到期日与出生日期、球员必须出现在自己球队向量里） | 完成 |
| 五 诊断报告 | `DiagnosticReport`：构建/插件/布局/逐探测/逐字段/整体状态（Verified/Candidate/Rejected/Unknown） | 完成 |
| 六 真实验证 | 在真实 FM27 进程（Build 26620374）上跑通探测；游戏停在主菜单，样本不完整，**未通过**，如实记录 | 进行中 |

## 关键设计

- **布局隔离**：27.0 与 27.1 是两份独立对象；27.1 的偏移是"复制假设"，每个字段都是 `Unknown`，
  只有经 `Mark(field, Verified, evidence)` 才升级。修改 27.1 不影响 27.0（有测试固定）。
- **两道闸门 + 注册表**：读取器兼容清单、引擎版本闸门、兼容性注册表三者都放行才读内存；
  注册表里 `verified_fields` 为空就是不放过。
- **探测不伪造**：租借字段不存在 → `NotApplicable`；转会记录无 vtable → 无样本时 `Inconclusive`；
  任何 `Failed` 都让整体变 `Rejected`。
- **单一数值不算成功**：每个探测都是多字段 + 关系 + 跨字段组合；报告明确写"结构自洽不能证明数值正确"。

## 真实运行记录

见 [`docs/acceptance/LIVE-2026-11-19.md`](acceptance/LIVE-2026-11-19.md)：

```
整体 Rejected（主菜单、未加载存档）
player 32 样本：CA/PA 范围、俱乐部名称、UID 唯一性全部通过；合同链 24/32 可达
club 32 样本：通过
integrity 64 样本：通过
```

这些数字**不足以**把 27.1 标成 verified，也**不足以**断定布局错误——需要加载存档后重跑。

## 测试

| 套件 | 结果 |
| --- | --- |
| `ScoutMind.FMReader.Tests` | **60 项通过**（新增布局隔离、解析器、注册表、7 组探测、报告状态机） |
| `ScoutMind.Reader.Tests` | 46 项通过 |
| 后端 | 109 项通过 |

## 下一步（唯一阻塞项）

加载存档后重跑 `Diag report`，然后按 `docs/FM27-VERSION-VERIFICATION.md` 逐类对照游戏内数值；
把结果写进 `compatibility-registry.json` 的 `verified_fields`，再改 `verified-versions.json` 与
`config/compatibility.json`。在此之前 27.1 扫描保持禁止。
