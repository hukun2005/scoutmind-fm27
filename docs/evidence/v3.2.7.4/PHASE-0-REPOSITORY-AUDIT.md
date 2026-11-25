# V3.2.7.4 Phase 0 — 仓库现状审计

生成时间：2026-11-25（Asia/Shanghai）
审计方式：只读代码审阅 + `git`/`gh` 远程查询 + 本轮实测；未修改任何生产代码。

## 1. 基线

| 项目 | 值 |
| --- | --- |
| 远程仓库 | https://github.com/hukun2005/scoutmind-fm27 |
| `origin/main` | `9a6145f4979d63990071476e9ce1aae147db1fe4`（`Merge pull request #8`） |
| PR #8 head | `7628c3c2f0e62dfa55dd2ada2a232600b24376ec` |
| PR #8 base | `6aaaa31ca4d1b0c362eb34a0099529b903cf17df` |
| PR #8 状态 | `MERGED`，合并时间 `2026-11-25T04:36:10Z`，merge commit `9a6145f` |
| V3.2.7.3 功能提交 | `7628c3c feat(v3.2.7.3): 统一写入保护与 Session Epoch 并发安全` |
| V3.2.7.4 分支 | `codex/v3.2.7.4-runtime-closure`（基于 `9a6145f` 新建，远程此前不存在） |
| 独立 worktree | `..\scoutmind-v3274`（不触碰 `scoutmind-v3273` 的未提交修改） |

### 1.1 与任务书的偏差（如实声明）

任务书 §0.1 要求「PR #8 未通过最终审核之前，不得开始将 V3.2.7.4 的生产代码合并到主分支」，§1.3 要求「PR #8 已合并则以最新 main 为基线」。
实际上 **PR #8 已于 2026-11-25T04:36:10Z 被合并**（用户在此前的会话中明确指令「合并到 main」）。
因此本版本：

* 无法回滚撤销该合并（禁止 `reset --hard`/`push --force`）；
* 以 `9a6145f` 为基线开发 V3.2.7.4；
* 在 `PR8-FINAL-SECURITY-REVIEW.md` 中对已合并代码做**事后**最终审核，发现问题以新 PR 修复，不修改历史结论。

### 1.2 工作区状态

* `scoutmind-v3273`：分支 `codex/v3.2.7.3-write-safety`，工作区干净（HEAD `7628c3c`），未提交修改 0 个。
* `scoutmind-v3274`：新建 worktree，分支 `codex/v3.2.7.4-runtime-closure`，HEAD `9a6145f`，工作区干净。
* 未完成 PR：#2、#3、#4、#5、#6（V3.2.3~V3.2.6 历史分支，与本版本无关，不合并、不删除）。

### 1.3 CI 结果（PR #8，真实可查）

| 工作流 | run_id | commit | 6 个 job | 结果 |
| --- | --- | --- | --- | --- |
| CI（PR head） | `45546259776` | `7628c3c` | Backend / security / .NET / frontend / Playwright / PostgreSQL | 全部 `pass` |
| CI（合并后 main） | `45546286541` | merge `9a6145f` | 同上 | 全部 `pass` |

具体 job 与耗时：

* `.NET readers and agent` — pass（1m15s / 1m9s）
* `Backend (pytest + migrations)` — pass（16m25s / 13m37s）
* `Frontend (typecheck + build)` — pass（1m1s / 1m3s）
* `Playwright (governance)` — pass（59s / 1m20s）
* `PostgreSQL migration compatibility` — pass（47s / 1m1s）
* `Upload / identity / agent isolation regressions` — pass（2m38s / 2m10s）

## 2. 现有能力盘点

### 2.1 身份协议（`save-identity/v1`）

* 服务实现：`backend/app/services/save_identity.py`
* 数据模型：`SaveIdentity`、`SaveEvidence`、`SaveIdentityConflict`、`SaveIdentityAuditEvent`（`backend/app/models.py#L1145-L1295`）
* 规则要点：
  * 客户端只能上报证据，后端按证据封顶状态（`cap_declared_status`），不信任客户端自称 `verified`。
  * 相同指纹幂等更新；同一存档出现不同指纹且声明 `verified` → 建立 `conflict`，不自动替换。
  * 人工确认 `POST /save-identities/{id}/verify` 需指纹一致 + 第二优先级证据。
  * 冲突/失效只能显式 verify 恢复，普通上报不能洗白。

### 2.2 会话与代次（Session / Epoch）

* `SaveSession`（`models.py#L1200-L1228`）：`session_status ∈ {created, verified, switching, invalidated, closed}`，含 `session_epoch`。
* `SaveWriteGate`（`models.py#L1231-L1250`）：每个存档唯一，`generation` 单调递增，`current_session_id` 为唯一可写会话。
* 心跳超时 `HEARTBEAT_TIMEOUT = 120s`；超时/身份不一致/代次落后都会使会话失效。
* 代次推进：`rotate_generation` 使用条件 UPDATE（CAS），失败重试 5 次后返回 `write_gate_busy`；同一事务内失效所有旧会话并写 `save_switched` 审计。
* 会话绑定：`bind_session_to_gate` 在身份变化时先推进代次；`POST /save-sessions/{id}/switch` 显式切换。

### 2.3 Write Fence

* `WriteContext` / `WriteFence` / `acquire_write_fence` / `WriteFence.assert_current`（`backend/app/services/write_safety.py`）。
* `assert_current` 是**与业务写入同一事务**的带代次条件 UPDATE（`generation = ? AND current_session_id = ?`），`rowcount != 1` 即拒绝；不是「先查后写」。
* 错误码：`write_context_required`、`write_fence_stale`、`write_session_epoch_stale`、`write_gate_busy`、`write_operation_reused`。
* 拒绝路径：导入器回滚全部写入 → 任务标记 `rejected` + `rejected_reason` → 写 `write_rejected` 审计 → HTTP 409。

### 2.4 导入入口现状

| 入口 | 位置 | 上下文/门票现状 |
| --- | --- | --- |
| `POST /imports/scan` | `routes_core.py#L376-L463` | `_require_write_fence` → context + fence；导入器内 `fence.assert_current` |
| `POST /imports/transfers` | `routes_core.py#L195-L253` | 同上 |
| `POST /imports/squad-csv` | `routes_core.py#L256-L294` | `fence.assert_current` 后 commit |
| `POST /captures`、`PATCH /captures/{id}` | `routes_capture.py#L132-L253` | 仅 `resolve_write_context`，**未取 fence**（TOCTOU 窗口，Phase 1 记为缺口） |
| `GET /imports`、`GET /imports/{job_id}` | `routes_core.py#L317-L373` | 只读，按用户校验归属 |
| Desktop Agent 自动采集 | `AgentApplication.cs#L327-L468` | 身份/会话同步后带 context 上传 |
| Agent 启动恢复队列 | `AgentApplication.cs#L276-L281` | **`context=null` 上传（绕过身份上下文）** |
| CLI `scan --sync` / `sync` | `AgentApplication.SyncAsync` | 同 Agent 上传路径 |
| 后台导入线程 | `ScanImporter` | 使用创建时的固定 fence |
| 启动恢复 | `importer.recover_interrupted_imports` | `running → failed` + `interrupted` 行 |

### 2.5 任务生命周期（现状）

* `import_jobs.status`：`running`（创建即 running）→ `succeeded` / `partial` / `failed` / `rejected`。
* 无 `queued`、无 `cancel_requested`、无 `cancelled`；无取消 API；无 `attempt_count`。
* 启动时 `recover_interrupted_imports` 把 `running` 全部置 `failed`（`main.py` startup 调用）。
* 幂等：`(fm_save_id, scan_id)` 已成功/部分成功 → 返回 duplicate；`(fm_save_id, operation_id)` 唯一索引兜底并发。

### 2.6 真实游戏验收能力

* 已有合法只读采集链路：`live-reader/`（原生 Reader）+ Reader 集成测试 + `docs/evidence` 历史真实样本。
* **不存在** `tools/runtime-acceptance/`；无 A/B 切换验收脚本、无脱敏证据收集器。
* 本机是否具备 FM27 可运行环境需运行时探测；未探测前不得声称真实验收通过。

### 2.7 前端诊断现状

* `frontend/src/views/SaveIdentityView.vue`：身份列表、证据、会话（含代次、最近心跳、失效原因）、审计事件；事件驱动刷新（`session.dataRevision`），非定时轮询。
* API 封装：`frontend/src/api/saveIdentity.ts`（`GET /save-identities`、`GET /save-identities/{id}`、`GET /save-identity-audit`）。
* 未展示 Worker/导入任务状态、网络状态、最近拒绝摘要。

## 3. 缺口清单（本版本必须补齐）

| 编号 | 缺口 | 影响 | 计划 |
| --- | --- | --- | --- |
| G-01 | 无真实取消：`rejected` 被当作取消使用 | 无法停止 queued/running 任务 | Phase 3：状态机 + `POST /imports/{job_id}/cancel` + 检查点 + 原子边界 |
| G-02 | `operation_id` 未绑定 `payload_checksum`：同 ID 不同内容被当作重复成功 | 误把新内容当旧请求（RT-011） | Phase 4：校验和冲突拒绝 + `operation_conflict` 审计 |
| G-03 | 被拒绝的 operation 重放返回 200 duplicate | 客户端误判成功 | Phase 4：返回 409 `operation_rejected`（幂等、不写入） |
| G-04 | 同 `scan_id` 不同内容返回 duplicate | 内容漂移被静默忽略 | Phase 4：`scan_payload_mismatch` 冲突 |
| G-05 | 无 `attempt_count` | 无法审计重试次数 | Phase 4：新增列 + 每次请求递增 |
| G-06 | Agent 启动恢复队列 `context=null` 上传 | 绕过身份上下文、可能被 legacy 路径接受 | Phase 5：持久化任务上下文 + 重新识别后才允许上传 |
| G-07 | Agent 无指数退避上限、无网络状态机 | 连续断网高频重试 | Phase 4/5：指数退避 + 上限 + `network_reconnected` 上报 |
| G-08 | Agent 无诊断子命令 | 现场排障困难 | Phase 5：`diagnostics/identity status/session status/jobs list/jobs inspect/network status` |
| G-09 | 无 `tools/runtime-acceptance/` | 无法做真实 A/B 验收 | Phase 6：PowerShell + Python 一键工具，缺环境时 `REAL_FM27_ACCEPTANCE_PENDING` |
| G-10 | 前端无 Worker/网络/拒绝摘要 | 运行态不可见 | Phase 7：仅增强 `SaveIdentityView.vue` |
| G-11 | 审计缺 `worker_*`/`operation_replayed`/`operation_conflict`/`network_reconnected`/`backend_restarted` | 审计不完整 | Phase 8：补齐事件（复用 `save_identity_audit_events.evidence_summary`） |
| G-12 | `/captures` 只解析上下文、不取 fence | 切换与提交之间存在 TOCTOU | Phase 3 顺带修复：取 fence 并在提交前 `assert_current` |

## 4. 不重复实现清单

以下能力已存在且**本版本不重写**：

1. 身份证据封顶、冲突检测、人工确认（`save_identity.py`）。
2. 代次 CAS 推进与旧会话失效（`write_safety.rotate_generation`）。
3. 同事务 fence 校验（`WriteFence.assert_current`）。
4. `(fm_save_id, scan_id)` 与 `(fm_save_id, operation_id)` 幂等与唯一约束。
5. 导入失败回滚与 `rejected` 标记。
6. 启动时中断任务恢复（`recover_interrupted_imports`）。
7. 前端 `SaveIdentityView` 的身份/会话/审计展示骨架。
8. Agent 的 Reader 调用、manifest/完整性校验、隔离目录（`pending/processing/failed/duplicate`）机制。

## 5. 本版本新增能力（范围锁定）

* 后端：`queued`/`running`/`cancel_requested`/`cancelled` 状态机、取消 API、检查点取消、幂等取消、取消与提交原子边界、`attempt_count`、payload 校验和冲突、审计事件补齐。
* 新增 Alembic 迁移（唯一 revision，`down_revision=e1c9a7b3d452`），只加列/索引，不改历史迁移，不回填业务数据。
* Agent：任务上下文持久化（save/identity/session/generation/operation_id/payload_checksum/created_at）、重启重识别、指数退避、诊断子命令。
* 工具：`tools/runtime-acceptance/`（环境检查、AI 隔离/幂等/fencing 校验脚本、证据收集、一键入口）。
* 前端：仅增强 `SaveIdentityView.vue`（Worker 状态、网络状态、审计摘要）。
* 文档：`docs/evidence/v3.2.7.4/` 全套报告；`CHANGELOG.md`、`README.md`、`docs/ROADMAP.md` 更新。

## 6. 技术方案确认（本阶段的结论）

1. **取消语义**：取消是状态转换而非删除。`queued` 直接 `cancelled`；`running` 进入 `cancel_requested`，Worker 在安全检查点响应；提交前最后一次检查与 commit 同事务；提交成功后到达的取消请求返回 `409` 且不改变已提交结果。
2. **原子边界**：取消检查点 + 条件状态 UPDATE（`WHERE status IN ('queued','running','cancel_requested')`）与业务提交同事务；已提交事务不可撤销，只记录。
3. **幂等**：取消重复调用返回同一终态；operation 重放返回原结果；内容不一致返回冲突，绝不写入。
4. **Agent 恢复**：队列任务在上传前必须持有「创建时固定」的上下文；重启后先重新识别身份，指纹一致才允许用新会话恢复上传（operation_id 与校验和不变），指纹不一致则隔离。
5. **真实 FM27**：本机未验证前所有真实验收项记为 `REAL_FM27_ACCEPTANCE_PENDING`/`NOT_RUN`。

## 7. 状态口径

本版本所有报告统一使用：`PASS` / `PARTIAL` / `FAIL` / `NOT_RUN` / `BLOCKED_BY_ENVIRONMENT` / `BLOCKED_BY_BILLING` / `BLOCKED_BY_PERMISSION`。
没有真实执行证据的项目不得写 `PASS`。
