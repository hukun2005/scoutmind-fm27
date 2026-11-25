# RT-001 ~ RT-025 测试矩阵（V3.2.7.4）

执行环境：Windows / Python 3.13 / .NET 10 / Node（本地）+ GitHub Actions。
执行方式：真实后端 HTTP（临时 SQLite）、真实 pytest、真实 `dotnet test`、真实 `npm run build`。

状态：`PASS` / `PARTIAL` / `FAIL` / `NOT_RUN` / `BLOCKED_BY_ENVIRONMENT`。

| 编号 | 测试 | 执行 | 结果 | 证据 / 说明 |
| --- | --- | --- | --- | --- |
| RT-001 | A 正常采集 | `verify_save_isolation.py` 合成身份导入 A | **PASS** | `import_a_succeeded`；真实游戏见 RT-025 |
| RT-002 | A 切换 B | `verify_save_isolation.py` + `test_session_epoch.py::test_switch_*` | **PASS** | A 切 A'、A/B 双存档；旧会话 `invalidated` |
| RT-003 | A 旧 Worker 提交 | `old_session_write_rejected` | **PASS** | 409 `write_session_epoch_stale` / `save_session_invalidated` |
| RT-004 | B 新 Worker 提交 | `b_unaffected` + `test_identity_switch_keeps_new_session_writable` | **PASS** | 新会话可导入 |
| RT-005 | A/B 并发切换 | `test_concurrent_switches_never_lose_updates`（同存档） | **PARTIAL** | 同存档并发切换 PASS；A/B 跨存档并发未单独执行 |
| RT-006 | Agent 重启 | `V3274AgentTests`（上下文往返/损坏隔离）+ `SaveIdentitySyncTests` | **PARTIAL** | 单测 PASS；真实 Agent 重启集成见 RT-025 |
| RT-007 | Backend 重启 | `test_startup_recovery_cancels_requested_and_audits` + `recover_interrupted_imports` | **PASS** | `worker_recovered` + `backend_restarted` |
| RT-008 | 上传中断网 | `test_sm010_upload_hardening.py`（客户端断开/慢上传/分块超限） | **PASS** | 中断不产生部分提交 |
| RT-009 | 提交后客户端超时 | `test_same_operation_same_payload_returns_duplicate_and_counts_attempt` | **PASS** | 重放返回原 job，`duplicate=true` |
| RT-010 | operation_id 重复 | 同上 + `verify_operation_idempotency.py` | **PASS** | 同一 job/scan |
| RT-011 | operation_id 内容变化 | `test_same_operation_different_payload_conflicts` | **PASS** | 409 `operation_conflict` |
| RT-012 | 旧 Session 重试 | `test_after_switch_old_context_cannot_import` | **PASS** | 409 |
| RT-013 | 取消排队任务 | `verify_worker_fencing.py` + `test_cancel_finished_job_*` | **PASS** | 200 直接 `cancelled`，重复取消幂等 |
| RT-014 | 取消运行任务 | `test_cancel_during_apply_rolls_back_and_marks_cancelled` | **PASS** | 回滚、无部分数据 |
| RT-015 | 取消与提交竞态 | `verify_worker_fencing.py::cancel_commit_race_atomic`（4000 行并发） | **PASS** | 「取消成功→无写入」或「提交成功→取消 409」 |
| RT-016 | 连续断网 | `TransportFailureIsRetriedOnceWithBoundedBackoff` + `simulate_network_failure.ps1 -Mode Unreachable` | **PASS** | 2 次尝试、单次 500ms 退避，不无限重试；真实拔网 NOT_RUN |
| RT-017 | Legacy API | `test_unified_import_identity.py`（无上下文拒绝 / legacy 审计 / 可关闭） | **PARTIAL** | 受保护入口 PASS；`/imports/fmscout`、`/imports/transfers/history` 仍走 legacy 允许策略，见 WRITE-FENCE-VALIDATION §4 |
| RT-018 | CLI sync | `SaveIdentitySyncTests`（未验证会话不上传、指纹变化失效旧会话） | **PASS** | 无身份上下文不写 |
| RT-019 | transfers 导入 | `test_unified_import_identity.py` + `_require_write_fence` | **PASS** | 身份一致 |
| RT-020 | squad-csv 导入 | 同上 | **PASS** | 身份一致 |
| RT-021 | SQLite migration | `alembic upgrade/downgrade/upgrade` + `check_migration_safety.py` | **PASS** | 见 DATABASE-VALIDATION |
| RT-022 | PostgreSQL 16 migration | CI `postgres-migrations` job | **PASS（CI）** | 本地 BLOCKED_BY_ENVIRONMENT |
| RT-023 | 审计完整性 | `verify_save_isolation.py::audit_*`、`verify_worker_fencing.py::audit_*`、`verify_operation_idempotency.py::audit_*` | **PASS** | 见 FINAL-REPORT §4 事件表 |
| RT-024 | 前端诊断页面 | `npm run build`（vue-tsc + vite） | **PARTIAL** | 类型与构建 PASS；未在浏览器中做交互截图（本机无 Playwright 浏览器） |
| RT-025 | 真实 FM27 A/B 切换 | 人工两轮（2026-11-25） | **PARTIAL** | 第 1 轮 B 跨存档污染（D-01）；修复后第 2 轮 A→B→A 均 PASS（独立 `save_id` + 身份/会话/审计）；C/D/E 仍 NOT_RUN，见 [REAL-FM27-ACCEPTANCE.md](./REAL-FM27-ACCEPTANCE.md) |

## 执行记录位置

| 产物 | 路径 |
| --- | --- |
| 运行期验收汇总 | `docs/evidence/v3.2.7.4/runtime/SUMMARY.md` |
| 存档隔离 | `docs/evidence/v3.2.7.4/runtime/save-isolation-result.json` |
| Worker 栅栏/取消 | `docs/evidence/v3.2.7.4/runtime/worker-fencing-result.json` |
| operation 幂等 | `docs/evidence/v3.2.7.4/runtime/operation-idempotency-result.json` |
| 后端全量 pytest | `docs/evidence/v3.2.7.4/runtime/pytest-summary.txt` |
| CI | GitHub Actions run `45546259776`（PR #8）、`45546286541`（main） |

## 切换与提交并发的判定语义

PostgreSQL READ COMMITTED 下，切换与导入在同一个 `save_write_gates` 行上串行化：

- 切换先提交 → 导入 `assert_current` 失败 → `rejected`（RT-003 的预期）；
- 导入先提交 → 切换随后推进代次；这批数据属于切换前完成的最后写入，合法。

因此「切换期间恰好提交成功的导入」不是跨库污染，不得据此判 FAIL。
