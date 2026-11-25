# Write Fence / Session Epoch 验证报告（V3.2.7.4）

- 协议：`write-safety/v1`
- 核心实现：`backend/app/services/write_safety.py`
- 审核对象：`main` @ `9a6145f`（PR #8 已合并），V3.2.7.4 分支内修复
- 审核结论：**PASS（核心 11 条入口）**，另有 2 条 legacy 通道记录为 PARTIAL（见 §4）

## 1. 协议不变量

| 不变量 | 实现 | 结论 |
| --- | --- | --- |
| 每个存档只有一个写入代次（generation） | `save_write_gates.generation`，CAS `+1` | PASS |
| 只有 `gate.current_session_id` 可写 | `resolve_write_context` 校验 epoch + 当前会话 | PASS |
| 旧会话写入原子失效 | `WriteFence.assert_current` 同事务条件 `UPDATE`，`rowcount != 1` 拒绝 | PASS |
| 切换与写入不丢更新 | CAS 重试（5 次）+ `write_gate_busy` | PASS |
| 身份切换推进代次且新会话可写 | F-01 修复：`rotate_generation(next_session_id=...)` | PASS |
| 采集写入也受 fence 保护 | F-02 修复：`_assert_capture_fence` | PASS |
| 错误码稳定 | `write_context_required` / `write_fence_stale` / `write_session_epoch_stale` / `write_gate_busy` / `write_operation_reused` | PASS |

## 2. 入口清单（11 条）

| # | 入口 | 保护方式 | 结论 | 用例 |
| --- | --- | --- | --- | --- |
| 1 | `POST /imports/scan` | `_require_write_fence` + commit 前 `assert_current` | PASS | `test_session_epoch.py`、`test_unified_import_identity.py` |
| 2 | `POST /imports/transfers` | 同上 | PASS | `test_unified_import_identity.py` |
| 3 | `POST /imports/squad-csv` | 同上 | PASS | `test_unified_import_identity.py` |
| 4 | `POST /captures` | `resolve_write_context` + `acquire_write_fence` + `assert_current` | PASS（F-02 修复） | `test_identity_switch_regression.py::capture_*` |
| 5 | `PATCH /captures/{id}` | 同上 | PASS（F-02 修复） | 同上 |
| 6 | `POST /save-identities/register` | 冻结/冲突检测 + 审计 | PASS | `test_save_identity_api.py` |
| 7 | `POST /save-identities/{id}/verify` | 人工确认 + 证据封顶 | PASS | `test_save_identity_api.py` |
| 8 | `POST /save-sessions/start` | 身份/存档绑定、epoch 绑定 | PASS | `test_session_epoch.py` |
| 9 | `POST /save-sessions/{id}/switch` | `rotate_generation` + 旧会话失效 | PASS（F-01 修复） | `test_identity_switch_regression.py` |
| 10 | `POST /save-sessions/{id}/heartbeat` | epoch 校验 + 超时（120s） | PASS | `test_session_epoch.py`、运行期 `verify_operation_idempotency.py` |
| 11 | `POST /save-sessions/{id}/end` / `invalidate` | 失效并写审计 | PASS | `test_save_identity_api.py` |

客户端侧（不新增 API）：

| 客户端 | 保护 | 结论 |
| --- | --- | --- |
| Desktop Agent `sync` | 请求携带 `save_identity_id` / `save_session_id` / `operation_id` | PASS |
| Agent `scan --sync` | 同上，operation_id 来自固定上下文 | PASS |
| 后台 Worker | 使用创建任务时的 fence，不重新解析当前存档 | PASS |
| 自动重试 / 启动恢复 | 固定 `.context.json`；指纹不一致移入隔离目录 | PASS |
| CLI `sync` | 同 Agent；无法确定身份时拒绝上传 | PASS |

## 3. 并发与边界

- **切换先提交**：导入 `assert_current` 命中 `rowcount = 0` → `409 write_session_epoch_stale`，任务标记 `rejected`。
- **导入先提交**：切换随后推进代次；该导入属于切换前最后一批数据，合法。
- **同 operation 并发**：唯一约束 + 条件更新；后到者进入重放路径（同内容 duplicate，不同内容 409）。
- **SQLite busy**：`rotate_generation` 返回 `write_gate_busy`；调用方重试重建会话（F-06 已知限制）。

## 4. 未纳入 11 条入口的 legacy 通道（PARTIAL）

以下通道保留旧客户端兼容，**未要求** Write Context：

| 通道 | 当前行为 | 风险 | 计划 |
| --- | --- | --- | --- |
| `POST /imports/fmscout` | 直接调用 `ScanImporter`，走 legacy 允许策略并写 `legacy_write` 审计 | 已启用 gate 的存档仍可被无上下文客户端写入 | V3.2.7.5 要求上下文，`write_safety_legacy_allowed` 默认改 `False` |
| `POST /imports/transfers/history` | 直接写历史交易，无 fence | 同上（仅交易数据） | V3.2.7.5 加 fence 或显式 `--allow-legacy` |

这两条不在 V3.2.7.4 的 11 条强制入口内（任务书 §3.3 未列出），但审核中确认它们真实存在，
因此**不标记 PASS**，记录为 PARTIAL/已知缺口，避免「全部入口已保护」的错误结论。

## 5. 实测证据

- `tools/runtime-acceptance/verify_save_isolation.py`（真实 HTTP）：
  - A/B 双存档身份隔离；
  - 跨存档写入拒绝；
  - 切换后旧会话导入/采集更新均 409；
  - B 不受 A 切换影响；
  - A 闸门在切换后关闭。
- `tools/runtime-acceptance/verify_worker_fencing.py`：
  - 代次推进后旧会话写入 409；
  - 取消状态机与审计。
- 结果文件：`docs/evidence/v3.2.7.4/runtime/save-isolation-result.json`、`worker-fencing-result.json`。
