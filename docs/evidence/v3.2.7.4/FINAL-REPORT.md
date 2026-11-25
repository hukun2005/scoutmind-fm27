# V3.2.7.4 最终报告：真实运行闭环与 PR #8 最终审核

- 分支：`codex/v3.2.7.4-runtime-closure`
- 基线：`main` @ `9a6145f`
- 日期：2026-11-25
- 总体状态：**工程闭环 PASS / 真实 FM27 验收 REAL_FM27_ACCEPTANCE_PENDING**

## 0. 偏差声明（必须如实记录）

任务书假设 PR #8 仍待合并。事实上用户在上一轮明确要求「合并到 main」，PR #8 已于
`2026-11-25T04:36:10Z` 合并（merge commit `9a6145f`，head `7628c3c`）。

因此本版本：

- 以最新 `main` 为基线，PR #8 只能做**事后安全审核**；
- 审核发现的缺陷在 V3.2.7.4 分支修复，不回写 PR #8 历史；
- 未执行 `reset --hard` / `clean -fd` / `push --force`；未修改已发布迁移；未删除测试或降低断言。

## 1. 各阶段结果

| Phase | 内容 | 状态 | 产物 |
| --- | --- | --- | --- |
| 0 | 仓库现状审计 | PASS | [PHASE-0-REPOSITORY-AUDIT.md](./PHASE-0-REPOSITORY-AUDIT.md) |
| 1 | PR #8 最终安全审核 | PASS（发现 3 项缺陷） | [PR8-FINAL-SECURITY-REVIEW.md](./PR8-FINAL-SECURITY-REVIEW.md) |
| 2 | CI / SQLite / PostgreSQL 审核 | PASS（本地 PG BLOCKED） | [CI-VALIDATION.md](./CI-VALIDATION.md)、[DATABASE-VALIDATION.md](./DATABASE-VALIDATION.md) |
| 3 | Worker Cancellation | PASS | [CANCELLATION-VALIDATION.md](./CANCELLATION-VALIDATION.md) |
| 4 | 网络恢复 + operation 幂等 | PASS | [NETWORK-RECOVERY-VALIDATION.md](./NETWORK-RECOVERY-VALIDATION.md) |
| 5 | Desktop Agent 运行闭环 | PASS（单测） | `ScanTaskContext.cs`、`V3274AgentTests.cs` |
| 6 | 一键验收工具 | PASS（33 项真实 HTTP 检查） | `tools/runtime-acceptance/` |
| 7 | 前端诊断增强 | PASS（构建） | `SaveIdentityView.vue` |
| 8 | 审计事件完整性 | PASS | 本文 §4 |
| 9 | RT-001~025 | 21 PASS / 3 PARTIAL / 1 NOT_RUN | [TEST-MATRIX.md](./TEST-MATRIX.md) |
| 10 | 文档 | PASS | 本目录 |
| 11 | 提交与 PR | 已创建 PR #9（**未合并、未发布、未删分支、未开自动快照**） | https://github.com/hukun2005/scoutmind-fm27/pull/9 |

## 2. 关键修复

### F-01（High）身份切换把新会话一起失效

`bind_session_to_gate` 调用 `rotate_generation` 未传 `next_session_id`，新会话被同一条
`invalidated` 更新命中，导致切换后新身份永远不可写。已修复并加回归测试
`test_identity_switch_keeps_new_session_writable`。

### F-02（Medium）采集入口缺少 fence

`POST /captures`、`PATCH /captures/{id}` 现在与导入一致：`acquire_write_fence` + 提交前
`assert_current`，被拒写 `write_rejected` 并返回 409。

### F-03（Medium）operation 幂等未绑定 payload

新增 `operation_conflict` / `scan_payload_mismatch` / `operation_rejected`；
同 operation 不同内容、同 scan 不同内容、被拒绝操作重放均返回 409，不写入。

### F-04（Medium）Agent 启动恢复无上下文上传

新增 `.context.json`（save/identity/session/generation/operation_id/payload_sha256/created_at）：
缺失或损坏 → 隔离；指纹不一致 → 隔离；一致 → 以新会话、原 operation_id 恢复。
`SyncOneAsync` 不再以 `context=null` 上传。

### 其他

- 排队任务取消改为原子直达 `cancelled`（不再依赖 Worker 领取）；
- `attempt_count`、`cancel_requested_at`、`cancelled_at`、`cancellable` 进入任务模型与 API；
- 审计事件名对齐任务书：`identity_verified`、`identity_conflict`、`session_created`；
- 新增 `write_accepted`（与业务写入同一事务）；
- Agent 新增 `diagnostics` / `jobs list|inspect` / `network status`；
- 前端 `SaveIdentityView` 增加 Worker/网络只读诊断（不提供取消/重试按钮）。

## 3. 变更文件

后端：

- `backend/app/models.py`
- `backend/alembic/versions/b5d9c2e7f4a1_v3274_worker_cancellation.py`
- `backend/app/ingestion/importer.py`、`cancellation.py`
- `backend/app/api/routes_core.py`、`routes_capture.py`
- `backend/app/services/write_safety.py`、`save_identity.py`
- `backend/app/schemas.py`
- 测试：`tests/test_worker_cancellation.py`、`test_operation_conflicts.py`、`test_identity_switch_regression.py`、
  `test_unified_import_identity.py`、`test_save_identity_api.py`

Desktop Agent：

- `ScanTaskContext.cs`（新）、`ScanQueue.cs`、`BackendClient.cs`、`SaveIdentitySync.cs`、
  `AgentCommandLine.cs`、`AgentApplication.cs`
- 测试：`tests/.../V3274AgentTests.cs`、`AgentCoreTests.cs`（fixture 修正）

前端：

- `src/views/SaveIdentityView.vue`、`src/types/imports.ts`

工具与文档：

- `tools/runtime-acceptance/*`（8 个文件）
- `docs/evidence/v3.2.7.4/*`
- `CHANGELOG.md`、`README.md`、`docs/ROADMAP.md`

## 4. 审计事件完整性

| 事件 | 触发点 | 验证 |
| --- | --- | --- |
| `registered` | 身份注册/更新 | test_save_identity_api |
| `identity_verified` | 人工确认 | runtime save-isolation |
| `identity_conflict` | 指纹冲突 | test_save_identity_api |
| `session_created` | 会话开始/重启 | runtime save-isolation |
| `session_invalidated` | 切换/失效 | runtime save-isolation |
| `session_heartbeat` | 常规心跳 | save_identity |
| `session_ended` | 正常结束 | test_save_identity_api |
| `network_reconnected` | 重连心跳 | runtime operation-idempotency |
| `save_switched` | 代次推进 | write_safety |
| `write_accepted` | 导入成功提交 | importer（同事务） |
| `write_rejected` | fence 拒绝 | write_safety |
| `capture_blocked` | 采集闸门关闭 | save_identity |
| `worker_started` | Worker 领取 | runtime worker-fencing |
| `worker_cancel_requested` | 取消请求 | runtime worker-fencing |
| `worker_cancelled` | 取消完成 | runtime worker-fencing |
| `worker_recovered` | 启动恢复 | test_worker_cancellation |
| `operation_replayed` | 同内容重放 | runtime operation-idempotency |
| `operation_conflict` | 同 op 不同内容 | runtime operation-idempotency |
| `operation_replay_rejected` | rejected 重放 | test_operation_conflicts |
| `backend_restarted` | 每次启动 | test_worker_cancellation |
| `legacy_write_allowed` | legacy 通道 | test_unified_import_identity |

## 5. 测试与证据

- 后端全量：576 tests / 0 failed / 3 skipped（PostgreSQL），见 `runtime/pytest-summary.txt`
- Agent：38 个测试全部通过
- 前端：`npm run build` 通过
- 运行期：`docs/evidence/v3.2.7.4/runtime/*-result.json`（33 项检查 PASS）
- CI：run `45546259776`、`45546286541` 六 job 全成功；本分支 PR CI 以 PR 页面为准

## 6. 已知限制（未标记 PASS）

| 限制 | 状态 | 计划 |
| --- | --- | --- |
| `/imports/fmscout`、`/imports/transfers/history` 仍走 legacy 允许策略 | PARTIAL | V3.2.7.5 要求 Write Context，默认关闭 legacy |
| 取消信号为进程内事件 | PARTIAL | 多进程 Worker 时改为数据库状态轮询 |
| 本地 PostgreSQL 并发 | BLOCKED_BY_ENVIRONMENT | 使用 CI 或具备 Docker 的机器 |
| Playwright 本地 E2E | NOT_RUN（CI 已通过） | `npx playwright install chromium` |
| 真实 FM27 A/B / 断网 / 重启 | **REAL_FM27_ACCEPTANCE_PENDING** | 按 [REAL-FM27-ACCEPTANCE.md](./REAL-FM27-ACCEPTANCE.md) 人工执行 |
| 前端诊断交互截图 | PARTIAL | 浏览器可用时补 |

## 7. 结论

- 写入安全协议、取消状态机、operation 幂等、Agent 固定上下文与诊断工具在本环境中**真实执行通过**；
- 由于没有真实 FM27 环境，**不得宣称真实运行闭环已完成**；状态为 `REAL_FM27_ACCEPTANCE_PENDING`；
- PR 创建后不自动合并、不发布、不删除分支、不开启自动快照。
