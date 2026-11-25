# Changelog

本文件记录 ScoutMind 的重要变更。编号对应 `docs/evidence/` 下的验收证据。

## [V3.2.7.4] - 2026-11-25

真实运行闭环与 PR #8 最终审核。

### 修复

- **身份切换后新会话不可写（High）**：`rotate_generation` 未保留新会话，已传 `next_session_id` 并加回归测试。
- **采集入口缺少 Write Fence（Medium）**：`POST /captures`、`PATCH /captures/{id}` 现在与导入一致，提交前 `assert_current`。
- **operation 幂等未绑定 payload（Medium）**：同 operation 不同内容返回 `409 operation_conflict`；同 scan 不同内容返回 `409 scan_payload_mismatch`；被拒绝 operation 重放返回 `409 operation_rejected`。
- **Agent 启动恢复无上下文上传（Medium）**：新增 `.context.json` 固定任务上下文；缺失/损坏或指纹不一致直接隔离。

### 新增

- Worker 取消状态机：`queued → cancelled`（原子）、`running → cancel_requested → cancelled`；新增 `POST /imports/{id}/cancel`、`attempt_count`、`cancel_requested_at`、`cancelled_at`、`cancellable`。
- 启动恢复审计：`worker_recovered`、`backend_restarted`。
- 审计事件：`identity_verified`、`identity_conflict`、`session_created`、`write_accepted`、`network_reconnected`。
- Desktop Agent：`diagnostics`、`jobs list|inspect <scan_id>`、`network status`；连接失败单次 500ms 退避。
- 前端：`SaveIdentityView` 增加 Worker/网络只读诊断（任务状态、尝试次数、心跳、重连与重启计数）。
- `tools/runtime-acceptance/`：一键运行期验收（环境检查、存档隔离、Worker 栅栏、operation 幂等、断网模拟、证据脱敏汇总）。

### 迁移

- `b5d9c2e7f4a1`：`import_jobs.status` 加宽至 32，新增 `attempt_count`、`cancel_requested_at`、`cancelled_at` 与 `ix_import_jobs_status`；downgrade 先收敛状态再收窄。

### 文档

- `docs/evidence/v3.2.7.4/`：Phase 0 审计、PR #8 审核、CI/数据库/写入栅栏/取消/网络/真实 FM27 验收、RT 矩阵、最终报告。

### 已知限制

- `/imports/fmscout`、`/imports/transfers/history` 仍走 legacy 允许策略（PARTIAL，计划 V3.2.7.5 收紧）。
- 取消信号为进程内事件，单写进程部署假设。
- 真实 FM27 A/B、断网、重启验收：2026-11-25 真实执行，`REAL_FM27_ACCEPTANCE_FAIL`——A 通过，B 出现跨存档污染（D-01：扫描报文无存档标识 + Agent 不传目标存档，B 写入 A 的 `save_id`）；C/D/E 未执行。
