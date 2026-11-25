# Runtime Acceptance Summary

生成时间：2026-11-25T05:18:12.9956797Z

| 工具 | 状态 | 检查数 | 失败数 |
| --- | --- | --- | --- |
| simulate_network_failure | PASS | 1 | 1 |
| verify_operation_idempotency | PASS | 10 | 0 |
| verify_save_isolation | PASS | 14 | 0 |
| verify_worker_fencing | PASS | 9 | 0 |

真实 FM27 A/B 验收不在自动化范围内；没有人工执行时必须标记 `REAL_FM27_ACCEPTANCE_PENDING`。
