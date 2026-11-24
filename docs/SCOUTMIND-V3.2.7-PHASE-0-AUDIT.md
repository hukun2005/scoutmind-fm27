# ScoutMind V3.2.7 Phase 0 仓库审计

- 审计日期：2026-11-24
- 任务书版本：V3.2.7 存档身份识别 + 多存档隔离 + 自动快照安全门
- 开发分支：`codex/v3.2.7-save-identity`
- 开发基线：`origin/main` = `776a9a53da18110e407397ab5af4bf30a711ce83`
- 工作目录：独立 Git Worktree `scoutmind-v3.2.7`（不影响原工作区）

> 本阶段只做审计，不改业务代码。所有“已实现/未实现”结论均以当前仓库源码为准，
> 不直接采信任务书里的旧状态描述。

---

## 1. GitHub 最新状态

| 项 | 实际值 |
| --- | --- |
| 远程仓库 | `https://github.com/hukun2005/scoutmind-fm27.git` |
| main 最新 SHA | `776a9a5`（与 `origin/main`、`codex/v3.2.6.1-date-verification`、`codex/v3.2.6-release-candidate` 相同） |
| 最新 main CI | run `45415099511`，`success`（2026-11-24T14:31:47Z） |
| 最新 Tag | 无 |
| 最新 Release | 无 |
| 当前开放 PR | #2、#3、#4、#5、#6 |

### 1.1 PR #6 冗余性判定

| 字段 | 值 |
| --- | --- |
| PR head | `codex/v3.2.6-release-candidate` @ `776a9a5` |
| PR base | `codex/v3.2.5.1-memscan-module-resolution` @ `f8c740e` |
| main HEAD | `776a9a5` |
| 结论 | PR head 已等于 main HEAD，其代码已全部包含在 main，**属冗余/待整理 PR** |

处理方式：**只记录，不关闭、不合并、不删除分支**（任务书明确禁止自动关闭 PR）。

### 1.2 工作区状态

- 主工作区 `repo` 有 1 个 `M`：`live-reader/ScoutMind.FMReader/Discovery/ReferenceChain.cs`。
  `git diff` 内容为空，仅为 LF/CRLF 行尾差异，无实际代码改动。按要求**未执行任何 reset/checkout**，
  保持原样。
- 为避免影响该工作区，V3.2.7 开发在独立 Worktree 中进行：
  `C:\Users\hukun\Documents\Trae-CN\temp_20261124_02\scoutmind-v3.2.7`。

---

## 2. 文档审计

已读：

- `AGENTS.md`（工程守则：迁移只增不改、服务端注入 save_id、状态口径 PASS/PARTIAL/FAIL/NOT_RUN/BLOCKED）
- `docs/SCOUTMIND-V3.2.6.1-IMPLEMENTATION-REPORT.md`
- `docs/SCOUTMIND-V3.2.6-MULTI-SAVE-REPORT.md`
- `docs/SCOUTMIND-V3.2.6-AUTO-SNAPSHOT-REPORT.md`

关键结论（与源码一致）：

1. 日期定位已真实完成 3 次独立进程会话验证，达到 `restart_verified`，引用链
   `chain:gp:0x586B520:date+0x7F4`，日期推进 `2026-11-06 → 2026-11-07`。
2. 自动快照唯一阻塞项是**存档身份未实现**：`SnapshotSafetyGate` 的 `SaveIdentityValid` 恒为 `false`。
3. 多存档隔离已有自动化证据，但真实双存档切换为 `NOT_RUN`，`SaveSwitchDetector` 不存在。

---

## 3. 当前架构（真实代码）

```text
FM27 进程
  └─ ScoutMind.FMReader (只读内存)
        GameBuildDetector / FmProcessLocator / WinMemorySource
        Discovery: WorldDateCandidateCollector → DateCandidateTracker → SnapshotSafetyGate
                   DateVerificationStore(JSON) / ReferenceChain
  └─ ScoutMind.Reader (CLI)
        CliCommandParser → Cli.RunAsync → 各命令
        world-date [--json] [--diagnostics] [--verify] [--state]
  └─ ScoutMind.Agent (桌面代理)
        AgentApplication.auto 每轮先跑 world-date --diagnostics --json
        ReaderSnapshotGate.Parse → 未 ENABLED 则“不扫描、不导入”
        scan 产出文件 → SyncOneAsync → BackendClient POST /imports/scan
  后端 FastAPI
        get_active_save() 解析“当前存档”（active 或 ?save_id=）
        /imports/scan、/captures、/players 等全部按 fm_save_id 过滤
        models: fm_saves + 各 save-scoped 表（均已有 fm_save_id）
```

没有常驻 Worker；`auto` 是前台循环。没有 `SaveIdentity/SaveEvidence/SaveSession` 实体。

---

## 4. 已有实现（不得重复开发）

### 4.1 数据表（`backend/app/models.py`）

已存在且带 `fm_save_id` 隔离：

- `fm_saves`（id/name/game_version/game_build/is_active/user_club_id/user_club_source）
- `import_jobs`（`uq_import_jobs_save_scan`）
- `player_instances`（`uq_instance_save_uid`）
- `player_snapshots`
- `unresolved_player_candidates` / `unresolved_player_observations` / `unresolved_player_actions`
- `capture_runs`（含 `date_source/date_confidence/date_read_status`，`uq_capture_save_date_reader_scope_revision`）
- `transfer_history`、`loan_records`、`squad_assignments`、`field_evidence_samples`、
  `player_observation_canonicals`、`transfer_event_candidates` 等

**不存在** `save_identities` / `save_evidence` / `save_sessions` / `save_identity_conflicts`。
`fm_saves` 也没有身份状态、指纹、可信度、last_seen 等字段。

### 4.2 后端 API

- `GET /saves`、`POST /saves`、`GET /saves/{id}/summary`（`routes_core.py`）
- `POST /imports/scan`（`?save_id=` 可选，默认 active save；`save_id` 由服务端校验 user 归属）
- `GET/POST/PATCH /captures`（全部 `fm_save_id == save.id` 过滤；import_job 也做归属校验）
- `deps.py`：`get_active_save`、`owned_save_or_404`、`instance_in_save_or_404`、
  `transfer_in_save_or_404`、`club_in_save_or_404`、`candidate_in_save_or_404`、
  `shortlist_in_save_or_404`、`instance_owned_or_404`、`alert_owned_or_404`
- AI 工具：`llm_planner.FORBIDDEN_ARGUMENTS = {"save_id","fm_save_id","user_id","session_id"}`，
  模型参数中的存档标识被拒绝。

### 4.3 Reader 接口

- `status`、`probe`、`scan`、`date`、`date-discovery`、`pointer-scan`、`date-locate`、
  `module-info`、`static-date-scan`、`date-read`、`world-date`、`compatibility list`
- `world-date`：`--json`、`--diagnostics`、`--verify <yyyy-MM-dd>`、`--state <file>`、`--max-mb`
- 无 `save-identity` 命令。
- `ProcessSessionIdentity.SessionKey = {PID}:{ProcessStartTime}:{Build}`，仅用于区分进程会话，
  **不是存档身份**。
- `WorldDateDiagnostics.Analyze(... saveKey ...)` 接收 `saveKey`，但 `FmWorldDateDiagnostics`
  固定传 `saveKey: null`；`SessionDiagnostics.SaveKey` 永远为 `null`。
- `SnapshotSafetyGate` 有 7 个输入，`SaveIdentityValid` 恒为 `false`。
- `DateVerificationStore` 提供 JSON 原子持久化 + 缺失/损坏安全降级，可作为存档身份状态存储的参考实现。

### 4.4 Agent 工作流程

- `auto`：先 `world-date --diagnostics --json`，`ReaderSnapshotGate` 非 `ENABLED` → 状态
  `date_unverified`，不扫描、不导入。
- 同一存档同日去重使用：
  `saveKey = config.SaveName`（空则 `"default"`），与 `state.SaveName` 比较。
  **这只是一个用户配置字符串，不是已验证的存档身份**（见风险 R1）。
- 采集后 `SyncOneAsync` 调 `POST /imports/scan`，请求中不携带任何存档身份，
  后端落到“当前 active save”。

### 4.5 现有测试覆盖

- 后端：`test_p1_security.py`、`test_unresolved_*`（含 `test_unresolved_save_isolation.py`）、
  `test_import_jobs_api.py`、`test_sm021_save_ownership.py`、`test_sm027_identity_scope.py`、
  `test_sm030_candidate_ownership.py`、`test_sm031_identity_match_isolation.py`、
  `test_sm032_api_ownership_audit.py`、`test_sm067_capture.py`、`test_capture_date_provenance.py`
- Reader：`WorldDateResolverTests`、`DateCandidateTrackerTests`、`DateCandidateDiagnosticsTests`、
  `DateVerificationStoreTests`、`ReferenceChainTests`、`SnapshotSafetyGateTests` 等
- Agent：`ReaderSnapshotGateTests`（ENABLED/BLOCKED/缺失/非法 JSON）、`AgentCoreTests`
- **无**存档身份、切换检测、Session 失效、采集期间切换相关测试。

### 4.6 本次审计实测基线

| 测试 | 命令 | 结果 |
| --- | --- | --- |
| Reader 自测 | `dotnet run --project live-reader/tests/ScoutMind.FMReader.Tests` | **PASS 184 · FAIL 0** |

（Reader CLI 测试与 Agent 测试在后续阶段回归时一并执行并记录。）

---

## 5. 未实现能力（V3.2.7 缺口）

1. `SaveIdentity`：无实体、无指纹、无身份状态/可信度、无证据记录。
2. `SaveEvidence`：没有证据收集与审计表。
3. `SaveSession`：没有会话实体；`SessionKey` 只是进程键，且不落库。
4. `SaveSwitchDetector`：完全不存在（任务书 Phase 3）。
5. 存档复合指纹：不存在；现有 `IdentitySignature` 是**日期候选**的身份，不是存档身份。
6. Worker/任务切换保护：没有常驻 Worker，也没有“任务绑定 save+session”的校验点。
7. 安全门接入：`SaveIdentityValid` 硬编码 `false`，`Session.SaveKey` 永远 `null`。
8. 真实双存档 A/B 验收：`NOT_RUN`；只有 1 个真实存档，禁止伪造。
9. 前端存档身份状态展示：无。
10. 真实验证证据目录 `docs/evidence/v3.2.7/`：不存在。

---

## 6. 需要修改的文件（按阶段）

| 阶段 | 文件 | 变更类型 |
| --- | --- | --- |
| Phase 1 | `docs/SCOUTMIND-V3.2.7-SAVE-IDENTITY-DESIGN.md`（新增） | 设计 |
| Phase 2 | `live-reader/ScoutMind.FMReader/Discovery/SaveIdentity*.cs`（新增） | 身份模型/证据/解析器/指纹 |
| Phase 2 | `live-reader/ScoutMind.FMReader/Discovery/SaveIdentityStore.cs`（新增） | 状态持久化 |
| Phase 2 | `live-reader/ScoutMind.Reader/CliCommandParser.cs`、`Cli.cs`（修改） | 新增 `save-identity` |
| Phase 3 | `Discovery/SaveSwitchDetector.cs`（新增） | 切换检测 |
| Phase 4 | `backend/app/models.py`（修改，追加） | 新表 |
| Phase 4 | `backend/alembic/versions/<new>.py`（新增） | 只新增迁移 |
| Phase 5 | `backend/app/api/deps.py`、`routes_capture.py`、`routes_core.py`（按需修改） | 存档上下文校验 |
| Phase 6 | `desktop-agent/ScoutMind.Agent/AgentApplication.cs`、`ReaderSnapshotGate.cs`（修改） | 接入身份 |
| Phase 7 | `Discovery/SnapshotSafetyGate.cs`、`WorldDateDiagnostics.cs`（修改） | 安全门升级，保持旧字段 |
| Phase 8 | Agent/后端新增 `SaveContextGuard` 类校验（新增） | 并发/切换保护 |
| Phase 9 | `live-reader/tests/...`、`backend/tests/test_save_*.py`、`desktop-agent/tests/...`（新增） | 测试 |
| Phase 11 | `frontend/*`（仅必要时） | 状态展示 |
| Phase 13 | `docs/SCOUTMIND-V3.2.7-*.md`（新增） | 交付文档 |

---

## 7. 潜在兼容性风险

| 编号 | 风险 | 影响 | 规避 |
| --- | --- | --- | --- |
| R1 | Agent 用 `config.SaveName`/`"default"` 充当存档键 | 两个存档同名或未配置时会被当成同一存档，同日去重可能错误丢弃扫描 | 以 Reader 解析出的 `save_identity` 替换；配置名仅作显示 |
| R2 | `world-date` 诊断 JSON 结构已固定 | 新增字段若改名/缺省会破坏 Agent 解析 | 只新增字段，保留 `snapshot.status/allowed/reasons` 与 `session/process/date_summary` |
| R3 | `SnapshotSafetyGate` 现有 7 输入签名被测试直接调用 | 改动签名会破坏 184 条基线 | 用新增可选参数/新重载，保留旧构造可用 |
| R4 | 历史 `fm_save_id` 无身份证据 | 不能批量标记 VERIFIED | 新记录默认 `LEGACY_UNVERIFIED`，仅新增迁移不改历史 |
| R5 | 存档文件哈希会随保存变化 | 误判为新存档 | 区分 `Save Identity` / `Save File Version` / `Content Hash`，哈希只作证据不单独定身份 |
| R6 | 同一进程可加载多个存档 | PID 不能作为身份 | 身份键必须来自内容证据，PID 仅用于 Session |
| R7 | 后端“active save”隐式绑定 | 切换存档后旧任务可能写错存档 | 导入/采集需携带并校验身份与会话，服务端拒绝不一致 |
| R8 | 只有 1 个真实存档 | 真实 A/B 测试无法执行 | 明确 `NOT_RUN`，输出用户操作说明，不伪造证据 |
| R9 | 现有 Reader 测试直接构造 `SnapshotSafetyInput` | 新增必填字段会编译失败 | 新字段给默认值或新增重载 |
| R10 | Alembic 已发布迁移不可改 | 只能在尾部新增 | 新迁移 `down_revision` 指向当前 head |

---

## 8. Phase 1 设计前置结论

1. **身份来源优先级**（任务书 §2.2）：真实 Save ID / 存档文件内部唯一标识 > 存档文件 SHA-256/稳定元数据/世界 ID >
   经理/俱乐部/联赛/日期/进程会话。第三优先级**不得单独**构成 VERIFIED。
2. **明确禁止**：PID、俱乐部名、经理名、当前联赛、单一内存地址、单一日历日期作为唯一身份。
3. **可复用**：`DateVerificationStore` 的原子 JSON 模式、`ReferenceChain` 的“稳定结构 + 可重解析”思路、
   `fm_saves` 作为身份的外键锚点。
4. **必须新建**：`SaveIdentity`、`SaveEvidence`、`SaveSession`、`SaveIdentityConflict`，
   并通过 `fm_save_id` 关联既有存档；历史数据标记 `LEGACY_UNVERIFIED`。
5. **自动快照**：本版本继续保持 `enable_automatic_snapshot = false`，即使身份链路通过也不开启。

---

## 9. 审计结论

- 基线明确：`main = 776a9a5`，工作区隔离在独立 Worktree，未改动用户内容。
- 多存档**数据隔离**已有实现与测试；**身份识别、切换检测、会话生命周期、安全门接入**均缺失。
- 自动快照仍为 `BLOCKED`，唯一新增依赖就是本版本的存档身份。
- 可以进入 Phase 1（身份模型设计），但不得跳过测试先行与分阶段提交。
