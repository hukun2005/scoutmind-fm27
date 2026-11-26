# V3.2.8 Phase 0：仓库与读取器审计

- 执行日期：2026-11-25（Asia/Shanghai）
- 执行范围：只读审计。未写入游戏内存、未修改存档、未注入进程、未改 DLL。
- 状态口径：PASS / FAIL / PARTIAL / NOT_RUN / UNKNOWN。

## 1. 仓库基线

| 项 | 值 |
| --- | --- |
| 工作副本 | `temp_20261124_02/scoutmind-v3274`（git worktree） |
| 审计起始 HEAD | `5e90f650740ee9cd090331a4739dc47a88997119`（`codex/v3.2.7.4-runtime-closure`） |
| 远程 | `https://github.com/hukun2005/scoutmind-fm27.git` |
| `origin/main` | `89fe8fa7134c34a85c30693d037929a000625168` |
| 已执行 | `git fetch origin --prune`（本次重新获取，未使用历史 SHA） |
| 开发分支 | `codex/v3.2.8-person-calibration`（从 `5e90f65` 创建，未推送） |
| 本次提交 | `4bda99a` protect existing diagnostics；`c181b2b` preserve manual-e evidence |

其他 worktree（未改动）：`repo`、`scoutmind-v3.2.7`、`scoutmind-v3.2.7.2`、`scoutmind-v3273`。

### 1.1 开放 PR

`gh pr list` 返回 5 个遗留 PR（均为 v3.2.3–v3.2.6.1，早于当前基线）：

- #6 `codex/v3.2.6-release-candidate`
- #5 `codex/v3.2.5.1-memscan-module-resolution`
- #4 `codex/v3.2.5-native-intelligence-release`
- #3 `codex/v3.2.4-release-hardening`
- #2 `codex/v3.2.3-nightly`

本阶段不处理这些 PR，仅记录。

### 1.2 GitHub Actions

最近 8 次 run 全部 `failure`，包含 `main` 上 PR #10 合并后的 push（run `45626244655`）。
→ **CI 现状 = FAIL**。该失败早于本阶段，不作为本阶段结论，但必须在 Phase 12 读取日志定位根因，不得靠重跑掩盖。

## 2. 本地未提交成果保护

审计开始时工作区状态：

```
 M live-reader/tools/ScoutMind.FMReader.Diag/Program.cs
?? docs/evidence/v3.2.7.5/manual-e/
```

处理方式（遵守 §1.2：不 `reset --hard`、不 `clean -fd`、不强制 checkout）：

| 成果 | 位置 | 行数 | 处理 |
| --- | --- | --- | --- |
| `calibrate` 命令 | [Program.cs](../../../live-reader/tools/ScoutMind.FMReader.Diag/Program.cs#L649-L741) | 93 | 原样提交（`4bda99a`），未改实现 |
| `xref` 命令 | [Program.cs](../../../live-reader/tools/ScoutMind.FMReader.Diag/Program.cs#L743-L804) | 62 | 原样提交，未改实现 |
| `dump` 命令 | [Program.cs](../../../live-reader/tools/ScoutMind.FMReader.Diag/Program.cs#L806-L879) | 74 | 原样提交，未改实现 |
| `docs/evidence/v3.2.7.5/manual-e/` | 3 个 JSON | 123 | 原样提交（`c181b2b`） |

- 三个命令合计新增 232 行；无对应单元测试。
- 原始 `Program.cs` 副本另存于工作区外：`_work/backup/Program.cs.20261125.bak`（44,018 字节）。
- `manual-e` 副本另存于工作区外：`_work/backup/manual-e/`。
- `_work` 下 Python 探查脚本（`find_name.py`、`trace_name.py`、`find_ptr.py`、`inspect_obj.py`、`probe_person.py`、`probe_two_hop.py`、`index_hypothesis.py`）位于工作区外，保持原样，不纳入仓库。

## 3. 现有 Native Reader 架构

事实来源：实际代码。**注意 `live-reader/README.md` 已过时**——它声称读取器不读内存，但 `ScoutMind.FMReader` 已包含只读 `ReadProcessMemory` 实现。

```
ScoutMind.Reader（CLI / 版本闸门 / 外部扫描器进程）
  └─ SteamLocator / ProcessDetector / PluginProbe / CompatibilityService / VersionGate
ScoutMind.FMReader（原生只读读取）
  ├─ Engine/WinMemorySource      : IMemorySource 真实实现，包住上游 MemScan
  ├─ Engine/HeapObjectLocator    : 堆扫描 + RTTI 分类，产出 LocatedObject
  ├─ Engine/FMSuperScoutMemoryEngine : 扫描闸门 + 探测 + 采集
  ├─ Probes/ObjectProbes         : 字段合理性/关系一致性探测
  ├─ Layouts/                    : ILayout / LayoutBase / FM27_0 / FM27_1 / LayoutResolver
  ├─ Versioning/                 : VersionGate / CompatibilityRegistry / CompatibilityConfig
  ├─ Discovery/                  : 日期、存档身份、快照安全门
  └─ Integration/                : UID 判定、属性映射
third_party/FMSuperScout          : MemScan（Windows 只读 API 封装）+ 上游 Fields
```

### 3.1 布局与版本闸门

- `FM27_0_Layout`：27.0，偏移逐字抄录上游 `Fields.FM27`。
- `FM27_1_Layout`：27.1，偏移表**复制自 27.0**，全部字段初始 `Pending`。
- `LayoutResolver`：按 Steam 构建号白名单解析；`26620374` → `FM27_1`，`26577676` → `FM27_0`。未登记构建返回 `null`，拒绝扫描。
- `VersionGate` + `verified-versions.json`：`26620374` 标 `verified`，允许 `AllowScan=true`。
- `CompatibilityRegistry` + `compatibility-registry.json`：把 `verified_fields` 逐字段 `Mark(Verified)`（`CompatibilityRegistry.cs:73-79`），把 `upstream_agreement_fields` 标 `Candidate`。
- 扫描闸门：`layout.BlockingStatus == Verified` 才允许扫描（`FMSuperScoutMemoryEngine.cs:565`）。

## 4. Phase 0 必答问题

| # | 问题 | 结论 | 证据 |
| --- | --- | --- | --- |
| 1 | 是否有 Person 模型？ | **无独立 Person 类**。只有 `LocatedObject(Address, BlockOffset, PersonOffset, DbOffset)` + `PERO_*` 偏移。 | `Probes/ObjectProbes.cs:5-20` |
| 2 | 属性记录从哪里读？ | `player.Block + PLAO_*`；`Block = Address - RTTI offset`。 | `ObjectProbes.cs:92-99`；`MemScan.Win.cs:362-376` |
| 3 | 身份由什么字段确定？ | `player.Db + OBJ_DUNI`（`DbOff=0`，即对象基址 `+0x0C`），经 `PlayerIdentityClassifier` 判定哨兵/非法 UID。 | `FMSuperScoutMemoryEngine.cs:325`；`Integration/PlayerIdentityClassifier.cs` |
| 4 | 是否存在姓名直接关联属性记录的逻辑？ | **没有**。姓名与数值都从同一个 `LocatedObject` 的不同块读取，缺少跨对象关联与交叉校验。 | `ObjectProbes.ReadPlayerName`（619-631） |
| 5 | 是否有同名球员冲突处理？ | 读取层无。后端有 `identity_conflicts` / `identity_matches` 审计表，但读取层只按 UID。 | `backend/app/models.py` |
| 6 | 指针解析是否有内存区域保护？ | 有。vtable 必须落在 `game_plugin` 或 `GameAssembly` 模块内（`InGp/InGa`）；读取经 `TryReadBlock/IsReadable`；失败抛 `MemoryUnreadableException`。 | `WinMemorySource.cs:74-97`；`HeapObjectLocator.cs:218-233` |
| 7 | 能否区分无效指针 / 读取失败 / 结构不匹配？ | **部分**。无效指针→`0/null`；读取失败→异常或 `ProbeStatus.Failed`；结构不匹配→`Classify` 返回 `null`。无统一状态枚举。 | 同上 |
| 8 | 是否有写游戏内存的代码？ | 未发现 `WriteProcessMemory` / `VirtualProtectEx` / `CreateRemoteThread`。`OpenProcess` 仅 `PROCESS_VM_READ | PROCESS_QUERY_INFORMATION`（自扫描再加 `DUP_HANDLE | CREATE_PROCESS`）。 | `third_party/FMSuperScout/src/MemScan.Win.cs:36,47` |
| 9 | FM27.1 布局配置在哪里？ | `FM27_1_Layout.cs`、`verified-versions.json`、`compatibility-registry.json`、`config/compatibility.json`。 | 已核对 |
| 10 | 三个诊断命令能否运行？ | **构建 PASS**（`dotnet build -c Release`：0 警告 0 错误）。真实内存调用依赖 FM 进程，本次未运行 → **NOT_RUN**。 | `ScoutMind.FMReader.Diag.exe` |

## 5. Person 读取路径

1. `FmProcessLocator.Locate()` 找到 `fm.exe` → `WinMemorySource.Open()`。
2. `HeapObjectLocator.ScanFor(ObjKind.Player, …)` 按 1 MB 批次扫描可读区域。
3. 每个 8 字节槽读 vtable；vtable 必须落在 `game_plugin`/`GameAssembly`。
4. `MemScan.Classify(vtable, address, Fields.FM27)` 用 RTTI 元数据取动态偏移，判定 `Player`。
5. 产出 `LocatedObject(Address, BlockOff=-off, PersonOff=0, DbOff=0)`。
6. **因此当前 `Person == Address`（对象基址），并非独立的 person 子对象。**
7. 姓名：`memory.NestedString(Person + PERO_COMMON_NAME/FIRST/SECOND)` → `NestedString` 规则为 `[addr]→outer→inner`，UTF-8 字符串在 `inner+4`，读到 NUL 后 `Trim()`。

## 6. 属性记录读取路径

1. `CA = UInt16(Block + PLAO_CA=0x264)`，`PA = UInt16(Block + 0x266)`。
2. `Height = UInt16(Block + 0x22E)`；`Positions = Byte(Block + 0x150 + i)`，`i∈[0,15)`。
3. `DOB = UInt32(Person + PERO_DOB=0x88)`，按 `FmDate.Decode`：高 16 位年、低 9 位年内序日。
4. `UID = UInt32(Db + OBJ_DUNI=0x0C)`。
5. 探测只做范围/关系检查（CA/PA ≤ 200、CA ≤ PA、身高 140–230、DOB 年 1940–2015）。

## 7. 已有测试

仓库使用自带控制台测试运行器（无 xunit / NuGet）。**`ScoutMind.FMReader` 与 `ScoutMind.FMReader.Tests` 不在 `ScoutMind.sln` 中**，`dotnet build ScoutMind.sln` 不覆盖它们。

| 测试项目 | 覆盖重点 | 文件数 |
| --- | --- | --- |
| `live-reader/tests/ScoutMind.Reader.Tests` | CLI、兼容性、状态机、扫描信封、VDF | 11 |
| `live-reader/tests/ScoutMind.FMReader.Tests` | 布局、探测、指针、定位、日期、存档身份、稳定性、UID 映射 | 22 |

与 Person 相关、可复用的既有测试：`LocatorTests.cs`、`PointerAndLocatorTests.cs`、`LayoutAndProbeTests.cs`、`ExecutionLayoutTests.cs`、`StabilityTests.cs`、`FakeMemory.cs`。

## 8. 现有风险

| ID | 风险 | 证据 | 影响 |
| --- | --- | --- | --- |
| R1 | **静态注册表把姓名字段标为 Verified，与当前实测不一致** | `compatibility-registry.json` 将 `PERO_COMMON_NAME/PERO_FIRST_NAME/PERO_SECOND_NAME` 列入 `verified_fields`；而 `manual-e/calibration-notes.json` 记录姓名仅 3/32、80 个样本在 `+0x50/+0x58/+0x60` 全为 0 | `Mark(Verified)` 入口只依赖静态 JSON，无运行时复核；这是 Phase 5 安全门控要堵的缺口 |
| R2 | `Person` 语义偏差 | `MemScan.Win.Classify` 返回 `PersonOff=0`，`LocatedObject.Person` 实际是对象基址 | 所有 `PERO_*` 偏移都假设存在独立 person 子对象，可能整体错位 |
| R3 | 姓名位于独立“姓名池”，无指针路径 | `manual-e` F3/F4/F5/F6：全内存反查 0 命中、两级指针 0 命中、整数下标假设自相矛盾 | 路线 A 无法落地；姓名需索引/哈希间接解析 |
| R4 | 版本检测不一致 | `agent-restart-result.json` 记录运行版本 `6000.3.18f1-custom` 且判定 build 不支持；`calibration-notes.json` 记录 build `26620374`、gate allow | 需在下次真实运行统一检测，避免用历史值当 PASS 依据 |
| R5 | CI 持续失败 | 最近 8 次 run 全 failure | Phase 12 必须读日志定位，不得重跑掩盖 |
| R6 | 文档漂移 | `live-reader/README.md` 声称不读内存 | 误导审计与后续开发 |
| R7 | FMReader / Diag 未进解决方案 | `ScoutMind.sln` 无 `FMReader` 条目 | CI 与本地 `dotnet build` 覆盖不到原生读取代码 |
| R8 | 缺少候选/状态模型 | 无 `PersonLayoutCandidate`、无 `Verified` 状态机、无 xref 结果状态枚举 | Phase 1–5 需要新增最小模型 |

## 9. 需要修改的最小文件范围（Phase 1 起）

- 新增 `live-reader/ScoutMind.FMReader/Calibration/PersonLayoutCandidate.cs`：候选布局（`CandidateId`、`GameVersion`、`BuildNumber`、`NameOffsetCandidates`、`DateOfBirthOffsetCandidate`、`PointerValidationRules`、`Confidence`、`Evidence`、`VerificationStatus`），**不写进生产布局常量**。
- 新增 `live-reader/ScoutMind.FMReader/Calibration/PersonCandidateProbe.cs`：对 `+0x50/+0x58/+0x60/+0x88` 逐字段记录原始值、解码值、有效性、失败原因；只经 `IMemorySource` 只读访问。
- 新增 `live-reader/tests/ScoutMind.FMReader.Tests/PersonLayoutCandidateTests.cs`：用 `FakeMemory` 覆盖空指针、无效指针、不可读、乱码、Unicode、缺失生日、多候选。
- 扩展 `tools/ScoutMind.FMReader.Diag/Program.cs` 的 `calibrate`：保留旧参数，新增候选逐字段输出。
- **不改** `FM27_0_Layout` / `FM27_1_Layout` 的偏移常量；**不改** `verified-versions.json` / `compatibility-registry.json` 的既有 Verified 声明（Phase 5 另行加运行时门控）。
- 证据目录：`docs/evidence/v3.2.8/`。

## 10. 与任务书的差异

| 任务书 | 实际代码 | 处理 |
| --- | --- | --- |
| 独立 Person 对象/模型 | 无 Person 类，`Person==Address` | 以实际结构为准，记录为 R2 |
| `PersonLayoutCandidate` 字段 | 项目无该模型 | Phase 1 新增 |
| 姓名支持 Unicode/重音 | `NestedString` 用 UTF-8 + `Trim()`，无额外规范化 | Phase 2 校验层补 |
| 日期“真实日期类型” | 现用 `(Year, DayOfYear)`，未转 `DateOnly` | Phase 2 保留 RawValue + 转换结果 |
| `Mark(Verified)` 入口 | 现有入口为 `CompatibilityRegistry.Apply` → `LayoutBase.Mark` | Phase 5 在该入口前加运行时前置检查 |

## 11. 状态汇总

| 项目 | 状态 |
| --- | --- |
| Phase 0 仓库审计 | PASS |
| 本地未提交成果保护 | PASS（已提交 + 工作区外备份） |
| 诊断命令构建 | PASS |
| 三个命令真实内存运行 | NOT_RUN（依赖 FM 进程，本阶段未执行） |
| 现有测试执行（基线） | PASS：`ScoutMind.FMReader.Tests` 215/215；`ScoutMind.Reader.Tests` 57/57（本地 Release） |
| CI | FAIL（既有问题，待 Phase 12） |

下一步：Phase 1——Person 候选布局调查，输出 `PERSON-LAYOUT-CANDIDATES.md`；本阶段不得执行 `Mark(Verified)`。
