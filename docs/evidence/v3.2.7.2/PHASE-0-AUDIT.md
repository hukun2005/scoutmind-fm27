# V3.2.7.2 Phase 0：最新仓库全面审计

**审计时间：** 2026-11-25（Asia/Shanghai）
**审计对象：** origin/main `187f4ad4e4717487265bdc4c95af697bdb66a1c6`
**开发分支：** `codex/v3.2.7.2-save-identity-e2e`（独立 worktree `scoutmind-v3.2.7.2`，从 `origin/main` 新建）
**结论：** V3.2.7 的 Reader 身份解析、后端隔离校验、Agent 安全门已经存在且可复用；缺口集中在 **后端身份/会话的 HTTP 生命周期**、**Agent 到后端的身份上报**、**采集上下文（CaptureContext）真实传递**、**身份审计日志** 与 **真实切换验收**。

---

## 1. 最新 main SHA

```text
git fetch origin --prune
git rev-parse origin/main  -> 187f4ad4e4717487265bdc4c95af697bdb66a1c6
git rev-parse HEAD         -> 187f4ad4e4717487265bdc4c95af697bdb66a1c6
```

最近提交（`git log --oneline -5`）：

```text
187f4ad docs(v3.2.7): 记录已合并至 main
d702868 docs(v3.2.7): 更新实现报告中的真实验收结论
2f70074 test(v3.2.7): 归档 save_context 跨存档隔离真实后端联调证据
230d3ca V3.2.7: 补充 A/B 双存档与重启一致性实测证据
738875c docs(v3.2.7): record real evidence and status
```

相关分支：`main`、`codex/v3.2.7-save-identity` 均指向 `187f4ad`；`codex/v3.2.6-release-candidate`、`codex/v3.2.6.1-date-verification` 停在 `776a9a5`。本版本新增 `codex/v3.2.7.2-save-identity-e2e`。

## 2. 工作区状态

- 新建 worktree 前：`git status --porcelain` 为空，`codex/v3.2.7-save-identity` 干净。
- 新 worktree：`<repo-v3272>`，HEAD = `origin/main`，无未提交修改。
- 未执行 `reset --hard`、未强制 checkout、未删除任何未提交文件。
- 未触碰既有 worktree `scoutmind-v3.2.7`（V3.2.7 分支）与 `repo`（V3.2.6.1 分支）。

## 3. 现有代码路径

### Reader（C#，live-reader）

| 文件 | 作用 |
|---|---|
| `live-reader/ScoutMind.FMReader/Discovery/SaveIdentityModels.cs` | 身份枚举、证据类型、指纹算法（`si:v1:`）、`SaveIdentityResolver`、会话键 |
| `live-reader/ScoutMind.FMReader/Discovery/SaveIdentityStore.cs` | 本地状态文件、用户确认指纹持久化 |
| `live-reader/ScoutMind.FMReader/Discovery/SaveSwitchDetector.cs` | 切换检测状态机与防抖 |
| `live-reader/ScoutMind.FMReader/Discovery/SnapshotSafetyGate.cs` | 快照安全门（恒关闭自动快照评估） |
| `live-reader/ScoutMind.FMReader/Engine/FmSaveIdentityDiagnostics.cs` | `save-identity --diagnostics --json` 输出 |
| `live-reader/ScoutMind.Reader/Cli.cs` | `save-identity` / `--verify` / `--diagnostics` 命令 |
| `live-reader/tests/ScoutMind.FMReader.Tests/SaveIdentityTests.cs`、`SaveSwitchDetectorTests.cs`、`SnapshotSafetyGateTests.cs` | 身份/切换/安全门单测 |

### Desktop Agent（C#，desktop-agent）

| 文件 | 作用 |
|---|---|
| `desktop-agent/ScoutMind.Agent/AgentApplication.cs` | 自动采集主循环、每轮身份门 + 日期门、扫描后身份复核 |
| `desktop-agent/ScoutMind.Agent/SaveIdentityGate.cs` | 解析 Reader 身份 JSON，非 `verified` 一律 BLOCKED |
| `desktop-agent/ScoutMind.Agent/ReaderSnapshotGate.cs` | 日期/快照门 |
| `desktop-agent/ScoutMind.Agent/BackendClient.cs` | `POST /imports/scan`、`POST /captures`、`GET /imports?scan_id=` |
| `desktop-agent/ScoutMind.Agent/CaptureStateStore.cs` | 本地采集状态（`identity_blocked` / `identity_changed` 等） |
| `desktop-agent/tests/ScoutMind.Agent.Tests/SaveIdentityGateTests.cs` | 身份门单测 |

### Backend（Python，backend）

| 文件 | 作用 |
|---|---|
| `backend/app/api/save_context.py` | `resolve_save_context` / `build_final_guard` / `assert_job_context`，四个安全错误码 |
| `backend/app/api/routes_core.py` | `/imports/scan`、`/imports/transfers`、`/imports/squad-csv` 接入身份/会话查询参数与 `final_guard` |
| `backend/app/api/routes_capture.py` | `/captures` 接入身份/会话校验并记录归属；`PATCH /captures/{id}` 无上下文校验 |
| `backend/app/ingestion/importer.py` | `ScanImporter.import_payload(identity_id, session_id, final_guard)`；提交前 `final_guard` 失败即 `rollback` + `_mark_failed` |
| `backend/app/models.py#L1135-L1232` | `SaveIdentity` / `SaveEvidence` / `SaveSession` / `SaveIdentityConflict` |
| `backend/alembic/versions/c3d8f1a2b407_save_identity.py` | 纯增量迁移（head） |
| `backend/tests/test_save_isolation.py` | 身份/会话隔离、`final_guard`、`assert_job_context` 单测 |
| `backend/tests/test_save_identity_migration.py` | 迁移新增表/列、历史存档 `LEGACY_UNVERIFIED`、downgrade 只删新增对象 |

### Frontend（Vue 3）

- `frontend/src/views/AgentView.vue`：Agent/采集状态。
- `frontend/src/components/CapturePanel.vue`、`frontend/src/api/captures.ts`：采集记录。
- `frontend/src/views/IdentityResolutionView.vue`（路由 `/identity`）：**球员身份冲突复核**，与存档身份无关。

### 文档

- `docs/SCOUTMIND-V3.2.7-IMPLEMENTATION-REPORT.md`、`docs/SCOUTMIND-V3.2.7-PHASE-0-AUDIT.md`、`docs/SCOUTMIND-V3.2.7-SAVE-IDENTITY-DESIGN.md`、`docs/evidence/v3.2.7/STATUS.md`。
- `docs/ARCHITECTURE.md`、`docs/API.md`、`docs/DATA_PROTOCOL.md`、`docs/SECURITY.md`、`docs/DATA_MODEL.md`、`docs/MODELS.md`、`docs/ROADMAP.md` 均存在，但**均未描述存档身份/会话**（`grep save_identity|save-identity|存档身份` 无命中）。

## 4. 已实现功能（V3.2.7，可复用）

1. **身份指纹**：`si:v1:file:<sha256>`（卷序列号 + FileId）与 `si:v1:unresolved:<build>`；内容哈希只作版本证据；第三优先级证据（经理/俱乐部/进程）不进入指纹。
2. **身份状态**：`unknown/discovered/candidate/verified/conflict/invalidated`；只有强证据或用户确认可到 `verified`。
3. **切换检测**：`SaveSwitchDetector` + `session_key = PID:进程启动时间:Build`。
4. **后端表结构**：四张身份相关表 + `import_jobs` / `capture_runs` 的可空归属列。
5. **写接口隔离**：`resolve_save_context` 校验身份/会话归属、状态、build 一致性；错误码可区分。
6. **提交前复核**：`build_final_guard()` 用独立事务重读已提交状态；导入失败整体回滚并标记任务失败。`ScanImporter` 对 `succeeded/partial` 的重复 `scan_id` 直接返回原结果（基础幂等）。
7. **采集归属**：`POST /captures` 记录 `save_identity_id` / `save_session_id`。
8. **Agent 安全门**：每轮 `save-identity --diagnostics --json` → `verified` + 强证据 + `automatic_snapshot_enabled` + `snapshot_eligible` 才放行；扫描后再复核 `ChangeKey`，变化则 `save_changed_during_capture` 作废本轮。
9. **自动快照关闭**：`SaveIdentityResolver.AutomaticSnapshotEnabled = false`，`SnapshotEligible` 恒 `false`。

## 5. 尚未实现功能（本版本缺口）

| 缺口 | 证据 |
|---|---|
| 后端**没有**存档身份注册/查询/验证 HTTP API | `grep save-identit` 仅命中 `save_context.py`、`routes_core.py`、`routes_capture.py`；无 `routes_save_identity.py` |
| 后端**没有**会话 start/heartbeat/end/invalidate API | `SaveSession` 只有迁移写入与测试直接建行 |
| Agent **不向后端**上报身份/会话 | `BackendClient` 只有 `/imports/scan`、`/captures`、`GET /imports`；`PostCaptureAsync` 不带身份/会话查询参数 |
| `Captures` 上报不带 `save_identity_id` / `save_session_id` | `AgentApplication.cs` 未拼接查询参数 |
| 身份验证审计（验证前/后状态、证据、操作者）无表、无接口 | 仅有 `SaveEvidence`；无 `IdentityAuditEvent` |
| `assert_job_context` **未接入**任何 Worker/恢复路径 | 仅测试引用；导入为请求内同步执行，无独立 Worker 进程 |
| 采集期间切换的**后端侧**阻断（会话失效、任务取消）无真实实现 | Agent 侧本地作废；后端无“切换中”自动置位逻辑 |
| `PATCH /captures/{id}` 不做身份/会话校验 | `routes_capture.py#L196-L229` |
| 前端无存档身份诊断页 | `/identity` 是球员身份冲突页 |
| 真实“采集中切换”与网络中断验收 | V3.2.7 `STATUS.md` 标 `NOT_RUN` |
| PostgreSQL 16 迁移真实验证 | 本机无 PG16，V3.2.7 记 `NOT_RUN` |

## 6. 已有测试及覆盖范围

| 套件 | 覆盖 |
|---|---|
| `backend/tests/test_save_isolation.py` | 跨存档身份、未验证/冲突身份、跨存档会话、失效会话、切换中会话、build 不一致、正确上下文导入落归属、`build_final_guard` 独立事务、`assert_job_context` |
| `backend/tests/test_save_identity_migration.py` | 迁移新增表/列、历史存档标记、downgrade 仅删新增对象、归属列可空 |
| `test_capture_date_provenance.py`、`test_sm067_capture.py` | 采集日期来源与采集记录（不含身份上下文） |
| `live-reader/tests/.../SaveIdentityTests.cs` | 指纹、证据分层、歧义、歧义不得给稳定指纹、内容哈希不影响身份 |
| `SaveSwitchDetectorTests.cs`、`SnapshotSafetyGateTests.cs` | 切换检测、安全门恒关闭 |
| `desktop-agent/tests/.../SaveIdentityGateTests.cs` | 非 verified 一律 BLOCKED、缺强证据 BLOCKED、快照开关关闭 BLOCKED |
| `test_pg_migrations.py` | PG 迁移（需 PG 服务，本机未运行） |

## 7. 需要修改的文件

**Backend（新增为主，改动最小）**

- 新增 `backend/app/api/routes_save_identity.py`：身份注册/查询/验证、会话 start/heartbeat/end/invalidate、诊断摘要。
- 新增 `backend/app/api/save_identity_service.py`（或同级 service）：注册幂等、状态机升级规则、冲突处理、审计写入。
- 新增 `backend/app/schemas.py` 中的身份/会话 Pydantic 模型（追加，不改现有）。
- 新增迁移 `backend/alembic/versions/*_save_identity_audit.py`：`save_identity_audit_events`、会话过期/心跳所需列（若现有列不足）。
- 修改 `backend/app/models.py`：追加审计表与会话心跳字段（不改已有列语义）。
- 修改 `backend/app/main.py`：注册新 router。
- 修改 `backend/app/api/routes_capture.py`：`PATCH /captures/{id}` 增加上下文校验；采集启动/提交前后语义。
- 修改 `backend/app/api/save_context.py`：仅在需要时补充会话过期/心跳判断（保持既有错误码）。
- 新增 `backend/tests/test_save_identity_api.py`、`test_save_identity_audit.py`、`test_capture_switch_safety.py`。
- 修改 `backend/tests/test_save_identity_migration.py`：追加新迁移断言（不删旧断言）。

**Desktop Agent**

- 修改 `SaveIdentityGate.cs`：解析并暴露 `identity` 证据、`session_key`、`fingerprint_version`。
- 修改 `BackendClient.cs`：新增身份注册、会话 start/heartbeat/end/invalidate 调用，`/captures` 带上下文参数。
- 修改 `AgentApplication.cs`：注册 → 开会话 → 心跳 → 采集 → 提交后复核的闭环；网络失败时本地诊断。
- 修改 `CaptureStateStore.cs`：状态与后端会话 id 关联。
- 新增/扩展 `ScoutMind.Agent.Tests`。

**Reader**

- 仅在协议字段不足时扩展 `SaveIdentityModels.cs` 的序列化（`FmSaveIdentityDiagnostics.cs`），不改判定逻辑。

**Frontend**

- 新增 `frontend/src/api/saveIdentity.ts`、`types/saveIdentity.ts`、`views/SaveIdentityView.vue`（或扩展 `AgentView.vue`）+ 路由。
- 修改 `frontend/src/router/index.ts`。

**文档**

- 新增 `docs/SCOUTMIND-V3.2.7.2-IDENTITY-PROTOCOL.md`、`docs/SCOUTMIND-V3.2.7.2-IMPLEMENTATION-REPORT.md`、`docs/evidence/v3.2.7.2/STATUS.md`、`FINAL-REPORT.md`。
- 更新 `docs/API.md`、`docs/SECURITY.md`、`docs/DATA_PROTOCOL.md`、`README.md`、`docs/ROADMAP.md`。

## 8. 不需要修改的文件

- `backend/alembic/versions/c3d8f1a2b407_save_identity.py` 及所有历史迁移（禁止修改已发布迁移）。
- `backend/app/ingestion/importer.py` 的身份/守卫主流程（已满足“提交前复核 + 回滚”；仅在需要时补审计写入）。
- `backend/app/api/routes_core.py` 的导入路由（已接入 `resolve_save_context` 与 `build_final_guard`）。
- `live-reader/ScoutMind.FMReader/Discovery/SaveIdentityModels.cs` 的解析与指纹算法（不改判定规则）。
- `live-reader/ScoutMind.FMReader/Discovery/SnapshotSafetyGate.cs`（自动快照继续关闭）。
- 既有测试文件中的断言（只追加，不删减、不降级）。
- `frontend/src/views/IdentityResolutionView.vue`（球员身份冲突，与存档身份无关）。

## 9. 主要风险

| 风险 | 说明 | 缓解 |
|---|---|---|
| 身份状态被上报“洗白” | Agent 上报 `verified` 时后端若直接信任，会把 CANDIDATE 提升为 VERIFIED | 后端只接受证据与规则判定；用户确认必须记录主体与依据；单测覆盖非法升级 |
| 会话过期策略缺失 | 无心跳则旧会话可长期提交 | 新增心跳 + `last_heartbeat_at` + 过期判定；过期返回 `save_session_invalidated` |
| 真实切换证据不足 | 目前只有后端 HTTP 场景与单测，没有游戏内“采集期间切换” | Phase 8 提供验收脚本与步骤；无环境标 `NOT_RUN`，不得写 PASS |
| 幂等键不含存档上下文 | 现有幂等以 `(fm_save_id, scan_id)` 为主 | 保持 `scan_id` 幂等并追加身份/会话归属；重复提交返回原结果 |
| 并发注册 | 唯一约束 `(fm_save_id, identity_version, identity_fingerprint)` 可能抛 IntegrityError | 注册走“查-插-捕获唯一冲突-重查”幂等路径 |
| PG16 未验证 | 本机无 PG16 | 依靠 CI `postgres-migrations`；本地标 `NOT_RUN` |
| Agent/后端协议漂移 | 手写 JSON 字段名不一致 | Phase 1 先定协议文档 + 双端契约测试 |
| 自动快照误开 | 任何路径把 `snapshot_eligible` 置真 | 保持 `AutomaticSnapshotEnabled=false`；安全门单测守护 |

---

**Phase 0 结论：** 可以进入 Phase 1。V3.2.7 核心不重写，新增能力以“扩展路由 + 新增 service + 新增迁移 + Agent 调用”为主。
