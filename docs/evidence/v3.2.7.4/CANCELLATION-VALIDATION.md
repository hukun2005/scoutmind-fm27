# Worker Cancellation 验证报告（V3.2.7.4）

- 模块：`backend/app/ingestion/importer.py`、`backend/app/ingestion/cancellation.py`、`backend/app/api/routes_core.py`
- 迁移：`b5d9c2e7f4a1_v3274_worker_cancellation.py`
- 结论：**PASS（后端与 SQLite 实测）/ PARTIAL（跨进程 Worker 取消）**

## 1. 状态机

```text
queued ──取消──> cancelled              （原子条件更新，无需 Worker）
queued ──claim──> running ──成功──> succeeded / partial
running ──取消──> cancel_requested ──检查点回滚──> cancelled
running ──失败──> failed
running ──安全拒绝──> rejected
```

- 取消是**状态转换**，不删除任务，不删除审计；
- `ImportJob.status` 加宽到 32，避免 `cancel_requested` 截断；
- `attempt_count` 记录领取与重放次数，用于诊断反复失败的客户端。

## 2. 取消 API

`POST /imports/{job_id}/cancel`

| 当前状态 | 结果 | 审计 |
| --- | --- | --- |
| `queued` | `200`，直接 `cancelled` | `worker_cancel_requested` + `worker_cancelled` |
| `running` | `200`，`cancel_requested`，Worker 在检查点回滚 | `worker_cancel_requested` |
| `cancelled` | `200`，`already_cancelled=true`（幂等，不重复审计） | 无新增 |
| `succeeded/partial/failed/rejected` | `409 import_not_cancellable` | 无 |
| 非本人存档 | `404` | 无 |

权限：按 `job → fm_save_id → save.user_id` 校验，不使用客户端传入的存档 ID。

## 3. 原子边界

1. 领取：`_claim_job` 以 `UPDATE ... WHERE status='queued'` 条件领取，`rowcount != 1` 放弃；
2. 提交前：`_apply` 后再次检查 `cancellation.is_requested`：
   - 已请求 → `rollback()` → 独立事务写 `cancelled` 与审计；
   - 未请求 → `write_accepted` 审计与业务写入**同一事务**提交；
3. 提交后：取消只能返回 409，已提交事务不可撤销；
4. 排队取消与 Worker 领取并发：条件更新在同一行串行化，先到者生效。

## 4. 检查点

- 每 200 行（`_CANCEL_CHECKPOINT_ROWS`）检查一次；
- `_upsert_players` / `_upsert_transfers` 循环首行检查；
- 取消只影响当前事务，不会留下部分写入。

## 5. 重启恢复

`recover_interrupted_imports`：

- `running` / `queued` → `failed`，每任务写 `worker_recovered`；
- `cancel_requested` → `cancelled`，写 `worker_recovered`；
- 每次启动写一条 `backend_restarted`（`save_id = null`）。

## 6. 测试与实测

后端用例 `backend/tests/test_worker_cancellation.py`：

1. 运行中取消 → 回滚，球员数不变，状态 `cancelled`；
2. 领取前取消 → 不写业务数据，状态 `cancelled`；
3. `cancelled` 后用新 operation 重试成功；
4. 启动恢复审计（failed/cancelled 迁移）；
5. HTTP：完成态取消 409；queued 取消 200 + 幂等 + 审计各 1 条。

运行期真实 HTTP（`tools/runtime-acceptance/verify_worker_fencing.py`）：

- 直接插入 queued 任务 → 取消 → `200 cancelled` → 再次取消 `200 already_cancelled`；
- 4000 行导入与取消并发 → 结果为「取消成功且无写入」或「已提交且取消 409」；
- 审计含 `worker_started` / `worker_cancel_requested` / `worker_cancelled`。

## 7. 已知限制（PARTIAL）

| 限制 | 影响 | 说明 |
| --- | --- | --- |
| 取消信号为进程内 `threading.Event` | 多进程部署时，另一进程的 Worker 不会收到取消信号 | 与 `import_slot` 的部署假设一致：单写进程。`cancel_requested` 已落库，进程重启时由 `recover_interrupted_imports` 转为 `cancelled` |
| 检查点粒度为 200 行 | 超大 payload 取消有短暂延迟 | 不产生部分写入，只影响响应时间 |
| 提交瞬间取消 | 返回 409 | 设计如此：已提交不可撤销 |

若 V3.2.7.5 引入多进程 Worker，需要把检查点改为「每 N 行查询一次数据库状态」，
并把本文件从 PARTIAL 更新为 PASS。
