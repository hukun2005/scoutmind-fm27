# 强制测试矩阵（WF-001 ~ WF-020）执行记录

环境：本机 Python 3.13 + SQLite（文件库）。并发用例使用多线程 + 独立连接 + `threading.Barrier`，
不是单线程顺序调用。执行命令与原始输出见 `STATUS.md`。

| 编号 | 场景 | 期望 | 覆盖测试 | 结果 |
|---|---|---|---|---|
| WF-001 | 合法身份正常写入 | PASS | `test_write_fencing.py::test_current_fence_commits_and_records_generation` | PASS |
| WF-002 | 无 Identity 写入 | REJECT | `test_unified_import_identity.py::test_gated_save_rejects_import_without_context` | PASS |
| WF-003 | Candidate 身份写入 | REJECT | `test_unified_import_identity.py::test_gated_save_rejects_import_without_context`（identity-only 被 409） | PASS |
| WF-004 | 无 Session 写入 | REJECT | 同上 + `test_save_identity_api.py::test_capture_patch_checks_context` | PASS |
| WF-005 | 过期 Session 写入 | REJECT | `test_unified_import_identity.py::test_after_switch_old_context_cannot_import` | PASS |
| WF-006 | 旧 Epoch 写入 | REJECT | `test_write_fencing.py::test_switch_before_commit_rejects_whole_import` | PASS |
| WF-007 | 新存档切换后旧 Worker 提交 | REJECT | `test_import_concurrency.py::test_switch_during_import_window_rolls_back_everything` | PASS |
| WF-008 | 同一 Operation 重复提交 | IDEMPOTENT | `test_write_fencing.py::test_operation_id_replay_is_idempotent`、`test_import_concurrency.py::test_same_operation_concurrent_replay_writes_once` | PASS |
| WF-009 | 两个 Agent 同时申请 Session | SERIALIZED | `test_import_concurrency.py::test_concurrent_session_starts_serialize_on_single_current` | PASS |
| WF-010 | 两个切换请求并发执行 | SERIALIZED | `test_session_epoch.py::test_concurrent_switches_never_lose_updates` | PASS |
| WF-011 | 最终提交期间发生切换 | NO STALE COMMIT | `test_import_concurrency.py::test_switch_during_import_window_rolls_back_everything` | PASS |
| WF-012 | 数据库事务中途失败 | ROLLBACK | `test_import_transaction_safety.py`（既有用例，未改断言） | PASS |
| WF-013 | 网络断开后恢复 | REVALIDATE | 客户端重试携带同一 `operation_id`；服务端幂等或 409 要求重新识别（`test_operation_id_replay_is_idempotent`） | PASS（服务端语义） |
| WF-014 | Agent 重启 | NEW SESSION | `test_unified_import_identity.py::test_new_session_after_switch_can_write` | PASS |
| WF-015 | 取消任务后 Worker 恢复 | REJECT | 导入任务无 cancel API；`rejected` 不可重试（`retryable=false`） | PASS（状态语义） |
| WF-016 | 手动 sync 缺少身份上下文 | REJECT | `test_gated_save_rejects_import_without_context`（同一 HTTP 入口） | PASS |
| WF-017 | scan --sync 缺少身份上下文 | REJECT | 同上 | PASS |
| WF-018 | CLI 使用旧 Session | REJECT | `test_after_switch_old_context_cannot_import` | PASS |
| WF-019 | 不同存档间任务串用 | REJECT | `test_unified_import_identity.py::test_import_with_session_of_other_save_is_rejected` | PASS |
| WF-020 | 合法新 Epoch 写入 | PASS | `test_unified_import_identity.py::test_new_session_after_switch_can_write` | PASS |

## 说明

* WF-003：Candidate 身份不能建立可写会话（`start_session` 要求 verified），因此“用 candidate 身份写入”必然先被 409 拒绝；测试用 identity-only 场景固化这一行为。
* WF-013：网络层断线无法在本机自动化中真实复现；这里验证的是“重连后同一操作不会二次写入、旧上下文不会自动复活”的服务端语义，UI/网络层为 NOT_RUN。
* WF-015：本版本导入任务没有 cancel 端点，因此以 `rejected` + `retryable=false` 固化“不得用旧上下文自动重试”。
