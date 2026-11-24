# ScoutMind V3.2.6.1 实现报告

- 完成日期：2026-11-24
- 分支：`codex/v3.2.6.1-date-verification`（基于 `codex/v3.2.6-release-candidate`）
- 关联 PR：#6（V3.2.6 Release Candidate）
- 任务性质：日期可信度审计、候选追踪、安全门与验证文档；**不新增游戏业务字段**

## 1. 交付内容

### 1.1 Reader（`live-reader/ScoutMind.FMReader`）

新增：

| 文件 | 作用 |
| --- | --- |
| `Discovery/DateCandidateModels.cs` | 候选分类、排除原因、可信度等级、诊断/报告模型 |
| `Discovery/CandidateIdentity.cs` | 模块 + 结构指纹逻辑身份（不含日期值） |
| `Discovery/ReferenceChain.cs` | 模块静态引用链：发现、解析、链签名（跨重启身份补强） |
| `Discovery/WorldDateCandidateCollector.cs` | 保留全部签名命中、原始字节、稳定性复读、对象提示 |
| `Discovery/DateVerificationStore.cs` | 验证状态 JSON 原子持久化（缺失/损坏安全降级） |
| `Discovery/DateCandidateTracker.cs` | 跨读取/跨进程追踪、分类、选择、可信度状态机 |
| `Discovery/SnapshotSafetyGate.cs` | 自动快照硬性条件与逐条原因 |
| `Discovery/WorldDateDiagnostics.cs` | 采集 → 追踪 → 安全门编排 |
| `Engine/FmWorldDateDiagnostics.cs` | 真实进程入口（构建检测、只读内存、状态持久化） |

修改：

- `ScoutMind.Reader/CliCommandParser.cs`：`world-date` 新增 `--diagnostics`、`--verify <yyyy-MM-dd>`、`--state <文件>`；
- `ScoutMind.Reader/Cli.cs`：新增诊断输出（JSON 与中文文本）、退出码映射、帮助文本。

### 1.2 Agent（`desktop-agent/ScoutMind.Agent`）

| 文件 | 变更 |
| --- | --- |
| `ReaderSnapshotGate.cs` | 新增：解析 Reader 的 `snapshot` 判定，缺失/异常/日期为空一律 BLOCKED |
| `AgentApplication.cs` | `auto` 每轮扫描前先执行 `world-date --diagnostics --json`，未通过则**不扫描、不导入** |

### 1.3 文档

- `docs/SCOUTMIND-V3.2.6.1-DATE-SOURCE-AUDIT.md`
- `docs/SCOUTMIND-V3.2.6.1-DATE-CANDIDATE-TRACKING.md`
- `docs/SCOUTMIND-V3.2.6.1-REAL-DATE-VALIDATION.md`
- `docs/SCOUTMIND-V3.2.6.1-RESTART-VALIDATION.md`
- `docs/SCOUTMIND-V3.2.6.1-IMPLEMENTATION-REPORT.md`（本文）

## 2. 行为变化

| 场景 | 旧行为 | 新行为 |
| --- | --- | --- |
| `world-date` | 输出“最新日期”与文本可信度 | 行为保持不变（向后兼容） |
| `world-date --diagnostics` | 不存在 | 输出全部候选、排除原因、证据、限制与安全门 |
| 候选数量 | 只保留选中值 | 保留 + 排除 = 全部签名命中，禁止静默丢弃 |
| 自动快照 | 直接使用 `scan` 的 `game_date` | 必须先通过 Reader 安全门，否则保持关闭 |
| 存档身份 | 未实现 | 安全门显式标记为未验证，自动快照 BLOCKED |

## 3. 测试结果

| 测试 | 命令 | 结果 |
| --- | --- | --- |
| Reader 自测 | `dotnet run --project live-reader/tests/ScoutMind.FMReader.Tests` | 184 PASS / 0 FAIL |
| CLI 测试 | `dotnet run --project live-reader/tests/ScoutMind.Reader.Tests` | 55 PASS / 0 FAIL |
| Agent 测试 | `dotnet test desktop-agent/tests/ScoutMind.Agent.Tests` | 16 PASS / 0 FAIL |

新增测试覆盖：

- 候选全部进入报告、间隔不合理排除、重复签名歧义；
- 对象提示排除比赛对象、未来日期 → `FUTURE_EVENT`；
- 稳定性复读、结构指纹不包含日期；
- 跨进程堆指针变化 → 指纹不变；标量字段变化 → 指纹必须变化（版本 2 指针归一化）；
- 无界面证据只能 `heuristic`、界面一致 → `session_verified`；
- 日期不一致不写确认日期、日期回退降级；
- 三次独立会话 → `restart_verified`；
- 地址变化后重新关联、构建号变化清空验证；
- 安全门默认 BLOCKED、`restart_verified` + 存档身份未知仍 BLOCKED；
- 状态存储往返与损坏降级；
- 引用链：一跳/两跳解析、槽位越界与结构不符不解析、同构重复中只有带链记录被保留、
  同一 RVA/偏移链在三次独立进程会话后 `restart_verified`；
- Agent 安全门解析（ENABLED / BLOCKED / 缺失 / 非法 JSON）。

## 4. 验证状态

| 项目 | 状态 |
| --- | --- |
| 静态分析 | PASS |
| 自动化测试 | PASS |
| 模拟数据验证 | PASS |
| 真实 FM27 日期验证（结构指纹版） | **已执行 / BLOCKED**（142 条命中，10 条同构记录共享签名 → `ambiguous`） |
| 真实跨重启验证（结构指纹版） | **已执行 2 个进程会话 / BLOCKED**（结构身份不唯一，未达 `restart_verified`） |
| 引用链身份实现 | **已实现 / 自动化测试 PASS** |
| 真实 FM27 日期验证（引用链版） | **PASS**（3 次独立进程均与界面日期 `2026-11-06` 一致） |
| 真实跨重启验证（引用链版） | **PASS / `restart_verified`**（PID 110436 → 113432 → 58416） |
| 存档身份验证 | **NOT_IMPLEMENTED** |
| 自动快照 | **BLOCKED**（唯一原因：存档身份未验证） |

真实环境验证已在 2026-11-24 完成（FM27 build 26620374 / plugin 27.1，两次独立进程），
证据保存在 `docs/evidence/v3.2.6.1/`。真实数据同时暴露并修复了 v1 指纹的假阳性问题：

- v1 指纹包含堆指针，跨重启必然漂移（`heap:b16a56d8d23b4675` → `heap:ef7f58074afe9022`）；
- 版本 2 对结构窗口内的指针做归一化，并把尾部收敛到单条记录内；
- 修复后同一会话重扫得到 142 条命中，`2026-11-06` 与另外 9 条相邻日期记录共享签名，
  追踪器判为 `ambiguous`。这是真实的结构同质性，不是实现缺陷。

因此**结构指纹版**不能声明“真实日期已验证”，其自动快照保持关闭。

引用链版本（`identity_signature = chain:...`）已完成真实验证：

- 3 次完全关闭/重启（PID 110436 → 113432 → 58416），每次堆地址和结构指纹都变化；
- 三次引用链签名始终为 `chain:gp:0x586B520:date+0x7F4`，第三次达成 `restart_verified`；
- 每次都用 `date-read --rva 0x586B520 --field 0x7F4` 独立复核，均解析到 `2026-11-06`；
- 结构同构的 10 条相邻记录仍作为排除诊断保留，未被误选。

证据：`docs/evidence/v3.2.6.1/world-date-reference-chain-session-{1,2,3}.json` 与
`reference-chain-recheck-session-{1,2,3}.json`。

自动快照仍为 `BLOCKED`：安全门只剩“存档身份未经验证”一条原因。
在存档身份接入真实校验前，不得因为 `restart_verified` 而放行自动快照。

## 5. 兼容性

- 协议：**无变更**（未新增/修改协议字段）；
- 数据库：**无迁移**；
- 前端：**无变更**；
- 旧命令：`world-date`、`world-date --json` 输出字段保持不变；
- 诊断 JSON 仅**新增** `identity_signature` 与 `reference_chain`（诊断性质），旧字段不变；
- 新增状态文件默认写入 `%LOCALAPPDATA%\ScoutMind\date-verification.json`，不影响既有配置。

## 6. 风险与后续

1. 对象类型提示尚未接入对象分类器，生产环境候选默认为 `UNKNOWN_DATE`；
2. 存档身份识别尚未实现，自动快照必须继续保持关闭；
3. 引用链已用于区分同构记录，但“模块静态可达”只说明该对象在活的世界状态里，不单独证明它就是世界日期；
4. 引用链版本的**真实验证已完成**（3 次独立进程 → `restart_verified`），
   但仍需在日期推进/回退场景补验，才能说明日期变化后身份依然稳定；
5. 只有存档身份接入真实校验后，才允许重新评估自动快照。

## 7. PR 更新

- 原 PR #6 仍然适用，本次变更以独立任务分支提交，并同步到 V3.2.6 Release Candidate；
- 未创建重复 PR，也未修改 PR 的合并策略。
