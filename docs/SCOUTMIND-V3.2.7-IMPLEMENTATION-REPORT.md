# ScoutMind FM27 V3.2.7 实施报告

**版本代号：** Save Identity & Multi-Save Intelligence
**分支：** `codex/v3.2.7-save-identity`（基于 `origin/main`，**未合并 main、未发 Release**）
**基线：** `776a9a53da18110e407397ab5af4bf30a711ce83`

## 一、结论摘要

V3.2.7 建立了从“识别存档 → 生成身份 → 检测切换 → 持久化 → 后端隔离 → Agent 安全门”的完整链路，并保持最高优先级约束：

- **自动快照在本版本仍为关闭**：`SaveIdentityResolver.AutomaticSnapshotEnabled = false`，`SnapshotEligible` 恒为 `false`，`SnapshotIdentityFacts.From()` 会把任何 `eligible` 强制压成 `false`。
- **真实环境身份尚未可唯一确定**：当前存在多个候选存档文件且未定位到游戏内 Save ID / World ID，身份停在 `DISCOVERED`（`si:v1:unresolved:26620374`）。因此自动采集被身份安全门阻断。
- **没有伪造验证证据**：双存档 A/B、重启一致性等真实测试未执行，一律记为 `NOT_RUN`，详见 `docs/evidence/v3.2.7/STATUS.md`。
- 未使用 PID、俱乐部名、经理名、单一联赛或单一内存地址作为身份唯一依据；PID 只构成会话键的一部分。

## 二、分阶段结果

| Phase | 内容 | 状态 |
|---|---|---|
| 0 | 仓库/GitHub/架构审计 | DONE → `docs/SCOUTMIND-V3.2.7-PHASE-0-AUDIT.md` |
| 1 | 身份模型设计 | DONE → `docs/SCOUTMIND-V3.2.7-SAVE-IDENTITY-DESIGN.md` |
| 2 | 指纹、证据分层、解析器、Reader `save-identity` | DONE |
| 3 | `SaveSwitchDetector` 状态机与防抖 | DONE |
| 4 | 数据库持久化与迁移 | DONE |
| 5 | 后端身份/会话隔离 | DONE |
| 6 | Agent 接入身份安全门 | DONE |
| 7 | 安全门接入身份/会话 | DONE |
| 8 | 提交前最终校验与并发接口 | DONE |
| 9 | 自动化测试补齐 | DONE |
| 10 | 真实环境验收 | PARTIAL：本机身份/日期证据已捕获；A/B 切换 `NOT_RUN` |
| 11 | 前端状态 | SKIPPED：现有前端无存档身份数据源，`/identity` 页面属于球员 UID 复核，与本版本无关 |
| 12 | 全量回归 | DONE |
| 13 | 交付文档与证据目录 | DONE |

## 三、身份与证据模型

- 指纹：`si:v1:file:<sha256>`（有稳定元数据时）或 `si:v1:unresolved:<build>`（未解析）。
- 证据分层：
  1. `GAME_INTERNAL_SAVE_ID` / `WORLD_ID`（当前未定位）
  2. `SAVE_FILE_METADATA`（卷序列号 + FileId）/ `SAVE_FILE_HASH` / `SAVE_FILE_HEADER`
  3. `CAREER_METADATA` / `GAME_SESSION_METADATA`（**不得单独认证**）
- 状态机：`UNKNOWN → DISCOVERED → CANDIDATE → VERIFIED`，另有 `CONFLICT` / `INVALIDATED`。
- 归档区分 `Save Identity`、`Save File Version`、`Save File Content Hash`：保存导致内容哈希变化不会改变身份。
- 会话键：`PID:进程启动时间(Build ISO):Build`，仅用于会话，不用于身份。

真实环境实测：同一进程两次 `save-identity` 得到相同 `session_key`，但指纹只会是 `si:v1:unresolved:26620374`。

## 四、后端隔离

新增 `backend/app/api/save_context.py`：

- 错误码：`save_context_mismatch`、`save_identity_unverified`、`save_session_invalidated`、`save_switch_in_progress`。
- 规则：未声明上下文时保持历史行为；声明后身份必须属于当前存档、不是未验证/冲突/失效状态；会话必须 `verified`，不得跨身份、跨存档或 build 不一致。
- `build_final_guard()`：导入提交前用**独立事务**重新读取已提交状态，失败则回滚全部行并把任务标为失败（防止“只在启动时验证一次”）。
- `assert_job_context()`：为未来 Worker/恢复任务提供任务上下文比对，旧会话不能提交新数据。
- `ImportJob` / `CaptureRun` 记录 `save_identity_id` / `save_session_id`；导入响应与任务详情回显这两个字段。

## 五、Agent 安全门

- 每轮自动采集先执行 `save-identity --diagnostics --json`，要求：`status=verified`、指纹与会话键存在、至少一条第一/第二优先级强证据、`snapshot_eligible=true`、`automatic_snapshot_enabled=true`；任一不满足即 BLOCKED。
- 身份门通过后才执行 `world-date --diagnostics --json`，两者同时通过才允许采集。
- 去重键从 `config.SaveName` 改为稳定的身份指纹（消除 R1 风险）。
- 采集后复核身份：指纹或会话变化时把本轮结果移入失败目录（`save_changed_during_capture`），不写入旧存档。
- 由于本版本 `snapshot_eligible` 恒为 false，自动采集实际保持关闭。

## 六、数据库

新增迁移 `c3d8f1a2b407_save_identity.py`（`down_revision=b7e2c9d4a105`，纯增量）：

- 新表：`save_identities`、`save_evidences`、`save_sessions`、`save_identity_conflicts`。
- 可空列：`import_jobs.save_identity_id/save_session_id`、`capture_runs.save_identity_id/save_session_id`。
- 历史 `fm_saves` 标记为 `unknown / none / unresolved / si:v1:unresolved:legacy:<id>`，并写入 `LEGACY_UNVERIFIED` 证据，**不提升为已验证**。
- `downgrade` 只移除本版本新增对象，不触碰历史表数据。

## 七、回归结果

| 套件 | 结果 |
|---|---|
| FMReader 自测（`dotnet run --project live-reader\tests\ScoutMind.FMReader.Tests`） | 214 通过 / 0 失败 |
| Reader CLI 测试（`ScoutMind.Reader.Tests`） | 57 通过 / 0 失败 |
| Agent 测试（`dotnet test desktop-agent\tests\ScoutMind.Agent.Tests`） | 24 通过 / 0 失败 |
| 后端 pytest（SQLite） | 全部通过（exit 0） |
| 迁移测试 `tests/test_save_identity_migration.py` | 3 通过 |
| `scripts/check_migration_safety.py` | 通过 |
| 前端 `npm run build` | 通过 |
| `dotnet build ScoutMind.sln -c Release` | 0 错误 |
| PostgreSQL 16 迁移 | `NOT_RUN`（本机无 PG16 实例） |
| GitHub Actions（本分支） | `NOT_RUN`（分支未推送，不记为 PASS） |

说明：首次全量回归时 `test_sm005_transfer_perf[500000]` 曾因机器负载超过 5s 阈值失败，单独运行通过；最终回归在空载下全部通过，未修改任何性能断言。

## 八、真实环境验收

详见 `docs/evidence/v3.2.7/STATUS.md`：

- `identity-live-run-1.json` / `identity-live-run-2.json`：进程存在（Build 26620374），多存档歧义 → `discovered`，两次会话键一致。
- `world-date-live.json`：本轮日期状态为 `heuristic`（2026-11-07，引用链未变）。
- A/B 切换、重启一致性、采集期间切换、PG16 等：`NOT_RUN`。

## 九、安全边界确认

- 未合并 `main`，未创建 Release/Tag，未删除分支，未关闭 PR #6。
- 未修改任何历史 Alembic migration。
- 未删除或弱化既有测试断言。
- 未把 UNKNOWN/DISCOVERED 提升为 VERIFIED。
- 自动快照与自动导入在本版本持续 BLOCKED。
