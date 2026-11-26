# Changelog

本文件记录 ScoutMind 的重要变更。编号对应 `docs/evidence/` 下的验收证据。

## [V3.2.9.2] - 2026-11-26

首版公开发布前稳定性收口（First Public Preview）。PR #14 + 本分支发布工程修复。

### 修复

- **存档切换后旧确认仍可写入（High）**：切换存档立即失效旧确认，确认绑定 generation，跨代写入被拒绝；真实 FM27 A/B/A（generation 1→2→3）验收通过。
- **`GET /api/v1/transfers` 500（High）**：列表接口引用未定义的 `all_rows`，每次请求都抛 `NameError`；改为在全量筛选集上计算覆盖率。
- **`/transfers` 的 `sort` 被静默忽略（Medium）**：支持 `transfer_date` / `effective_fee` 双向排序，非法字段返回 `400 invalid_sort`；`effective_fee` 空值排末尾，分页稳定。
- **审核并发写入（Medium）**：审核操作加入乐观锁与幂等键，重复提交不产生双重写入。
- **同名候选被截断（Medium）**：同名球员候选完整返回。
- **发布包端口误判（Medium）**：启动脚本先检查端口占用，避免健康检查连到其它实例并误报成功。
- **停止脚本找不到进程（Medium）**：按实际监听端口记录 PID，并按命令行中的发布包路径校验归属。

### 新增

- Verified 生命周期账本：确认、撤销、冲突全程可追溯。
- 转会证据关联与审核审计落库。
- 高频查询索引（转会、候选、采集、身份）。
- `GET /api/v1/transfers` 13 个回归测试：分页、筛选、排序、非法排序、空结果、缺失费用、附加条款、多存档隔离、列表与统计一致性、覆盖率跨页稳定。
- Windows 发布工程：`scripts/build-release.ps1`、`Start-ScoutMind.ps1`、`Stop-ScoutMind.ps1`、`Check-Environment.ps1`、`Backup-Database.ps1`、`backup_sqlite.py`。
- 后端可选托管生产前端（`SCOUTMIND_FRONTEND_DIST`）：单端口提供 API 与界面，刷新深链不 404，`/api/*` 未知路径仍返回 404。
- `config/app.example.json`、`docs/release/v3.2.9.2/` 发布文档。

### 迁移

- `b2c3d4e5f6a7`：身份审核并发与审计（PR #14）。
- 本分支未新增 migration；升级路径、重复升级与回滚均验证通过。

### 测试

- 后端 658 个用例 0 失败；FMReader 334、Reader 57、Agent 38；前端构建 + Playwright 9/9。
- 真实 FM27：`status` / `probe` / `scan`（44,144 名球员）/ 导入 / 重复上传去重全部通过。

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
