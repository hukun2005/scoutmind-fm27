# PR #8 最终安全审核（V3.2.7.3 写入安全 / Session Epoch）

审核对象：`codex/v3.2.7.3-write-safety`（head `7628c3c`）→ 已合并到 `main`（`9a6145f`）
审核时间：2026-11-25
审核方式：源码逐行审阅 + 既有测试用例核对 + 迁移与约束核对（本地实测见 `@/docs/evidence/v3.2.7.4/CI-VALIDATION.md`、`DATABASE-VALIDATION.md`）
审核结论：**PARTIAL — 发现 1 项 High 缺陷、2 项 Medium 缺陷，必须在 V3.2.7.4 修复后再合并**

> 偏差声明：PR #8 已于 `2026-11-25T04:36:10Z` 合并（用户在上一轮明确要求合并到 main）。本审核为**事后审核**，历史结论不回写；缺陷在 V3.2.7.4 分支修复。禁止 `reset --hard`/`push --force`，不修改已发布迁移。

## 1. 审核范围与对照表

| 任务书要求 | 实现位置 | 结论 |
| --- | --- | --- |
| 每次有效存档切换生成新 generation | `write_safety.rotate_generation`（CAS + 旧会话失效） | PASS |
| 每个 Session 绑定唯一 save + identity | `save_identity.start_session`、`SaveSession.save_identity_id` | PASS |
| 只有当前 Session 可写 | `resolve_write_context` + `WriteFence.assert_current` | PASS |
| 旧 Session 写入原子失效 | 同一事务内条件 UPDATE 失效 | PASS |
| 两个 Session 不得同时写 | `gate.current_session_id` 唯一 + fence 条件 | PASS |
| Session 重启不得继承旧写入资格 | `resolve_write_context` 校验 epoch/current_session/心跳 | PASS（同 session_key 同身份可续用，见 §4） |
| Epoch 不得回退 | 仅 `+1` CAS，无降级路径 | PASS |
| 并发切换不得丢更新 | `rowcount` 判定 + 5 次重试 | PASS |
| 切换与业务写入原子边界 | `assert_current` 同事务 | PASS（含边界语义说明 §5） |
| A/B 切换冲突 | `bind_session_to_gate` 身份变化推进代次 | **FAIL（F-01）** |
| 重复导入幂等 | `(save, scan_id)` / `(save, operation_id)` | PASS |
| 超时重试不重复写入 | operation_id 查询先于写入 | PASS |
| 同 operation 不同 payload 拒绝 | 未校验 checksum | **FAIL（F-03）** |
| 并发重复提交 | 唯一约束 + `DuplicateScanError` | PASS |
| 被拒绝 operation 再次请求 | 返回 200 + status=rejected | **PARTIAL（F-03b）** |
| Worker 写入入口全部受保护 | scan/transfers/squad-csv ✓；captures 仅 context | **PARTIAL（F-02）** |
| Agent / CLI 写入身份上下文 | `BackendClient` 查询参数携带 | PASS（启动恢复除外，F-04） |
| Worker 重试不换身份/Session | 导入器使用创建时 fence | PASS |
| 后台任务恢复 | `recover_interrupted_imports` | PASS（但缺少审计事件，Phase 8 补） |
| 旧客户端策略 | `write_safety_legacy_allowed` + `legacy_write` 审计 | PARTIAL（默认仍放开，见 F-05） |
| 身份切换与存档内容绑定 | fingerprint 存入 `WriteContext`，导入器 `final_guard` | PASS |
| 错误码稳定 | 5 个专用 code + `save_context_mismatch` 等 | PASS |

## 2. 缺陷

### F-01（High）身份切换会把新会话一起失效，导致新身份无法写入

位置：[write_safety.py](file:///C:/Users/hukun/Documents/Trae-CN/temp_20261124_02/scoutmind-v3274/backend/app/services/write_safety.py#L355-L369)

`bind_session_to_gate` 在检测到 `gate.current_identity_id != session.save_identity_id` 时调用：

```python
rotate_generation(db, save, reason="identity_switch", actor="agent",
                  next_identity_id=session.save_identity_id)
```

未传 `next_session_id`。而 `rotate_generation` 会把 `fm_save_id` 下**除 `next_session_id`（默认 -1）外**所有 `created/verified/switching` 会话置为 `invalidated`。此时刚 `db.flush()` 的新会话也在其中，于是：

1. 新会话状态变为 `invalidated`；
2. `bind_session_to_gate` 随后仍把它设为 `gate.current_session_id`；
3. 下一次 `resolve_write_context` 命中 `_ENDED_SESSION_STATUSES` → `409 save_session_invalidated`。

即：同一 `fm_save_id` 上身份从 A 换成 B（存档文件被覆盖/替换）后，新会话**永远无法写入**，且 gate 指向一个失效会话，形成死锁式状态。既有测试 `test_identity_switch_advances_generation_and_invalidates_old_session` 只断言了 generation 与 `current_session_id`，未断言新会话仍为 `verified`，因此 CI 未捕获。

修复（V3.2.7.4）：`rotate_generation(..., next_session_id=session.id, next_identity_id=...)`；新增回归测试，断言新会话 `session_status == "verified"`、`session_epoch == generation`、且能成功导入；旧会话仍 `invalidated` 且导入被拒。

### F-02（Medium）`/captures` 只解析上下文，不取 fence

位置：[routes_capture.py](file:///C:/Users/hukun/Documents/Trae-CN/temp_20261124_02/scoutmind-v3274/backend/app/api/routes_capture.py#L132-L253)

`POST /captures`、`PATCH /captures/{id}` 调用 `resolve_write_context` 后直接 commit，未使用 `acquire_write_fence` + `assert_current`。上下文解析与提交之间存在切换窗口：请求 A 解析成功 → 切换提交 → A 仍然提交采集记录。采集记录属于审计数据而非存档业务数据，危害有限，但与「所有写入入口统一保护」的声明不一致。

修复（V3.2.7.4）：与 scan/transfers 一致，取 fence 并在同一事务提交前 `assert_current`；被拒时写 `write_rejected` 审计并返回 409。

### F-03（Medium）operation 幂等未绑定 payload 内容

位置：[importer.py](file:///C:/Users/hukun/Documents/Trae-CN/temp_20261124_02/scoutmind-v3274/backend/app/ingestion/importer.py#L155-L215)

两个问题：

1. `operation_id` 命中既有 `succeeded/partial/rejected` 任务时直接 `_duplicate_outcome` 返回，**不比较 payload checksum**。攻击者/故障客户端用同一 `operation_id` 提交不同内容，会被当作重复成功，新内容被静默丢弃（客户端误以为写入成功）。同一 `scan_id` 不同内容同理（`existing.status in {succeeded, partial}` 直接重复返回）。
2. 被拒绝的 operation 重放返回 HTTP 200（`status=rejected`），客户端可能把「被拒绝」当「已完成」。

修复（V3.2.7.4）：

* 幂等命中时比较 `job.checksum` 与本次 `payload_checksum(raw)`；不一致 → `409 operation_conflict`（新 code）+ 审计 `operation_conflict`，绝不写入。
* 被拒绝 operation 重放 → `409 operation_rejected`，携带原 `rejected_reason` 与 `job_id`，不重复写入。
* 新增 `attempt_count`，每次请求（含重复/冲突）递增并写审计。

### F-04（Medium）Agent 启动恢复队列无条件上传（context=null）

位置：[AgentApplication.cs](file:///C:/Users/hukun/Documents/Trae-CN/temp_20261124_02/scoutmind-v3274/desktop-agent/ScoutMind.Agent/AgentApplication.cs#L276-L281)

启动恢复按 `processing → pending → scans` 顺序补传历史任务，`context` 传 `null`。结果：

* 对已启用 gate 的存档 → 每次启动都必然 409，任务反复失败；
* 对无 gate 的历史存档 → 走 legacy 路径写入，**绕过身份/Session**。

修复（V3.2.7.4）：任务创建时持久化固定上下文（save/identity/session/generation/operation_id/payload_checksum/created_at）；启动恢复必须先重新识别身份，指纹一致才允许以新会话恢复上传（operation_id 与 checksum 不变），不一致则移入隔离目录并标记 `context_mismatch`；禁止 `context=null` 上传（可通过显式 `--allow-legacy` 仅用于本地排障，且默认关闭）。

### F-05（Low）legacy 写入默认仍放开

`settings.write_safety_legacy_allowed` 默认 `True`；无 gate 且未携带上下文的历史客户端仍可写入，仅有 `legacy_write` 审计，无到期时间。与任务书「可配置的收紧计划」一致，但建议在 V3.2.7.5 将默认值改为 `False` 并提供一次性迁移开关。本版本保持默认值不变（避免破坏现有本地工作流），在文档中标记为 PARTIAL。

### F-06（Low）`rotate_generation` 遇到 SQLite 写锁时 `rollback()` 会丢弃调用方未提交的新会话

位置：`write_safety.rotate_generation` 的 `OperationalError` 分支。`bind_session_to_gate` 在 `db.flush()` 之后调用，若此时 SQLite 返回 busy，`rollback()` 会撤销新会话插入，随后路由返回 409 `write_gate_busy`。可接受（客户端重试会重新创建），但需在文档中说明，避免被误判为数据丢失。

## 3. 未发现问题的关键路径（已核对）

1. `WriteFence.assert_current` 使用 `UPDATE ... WHERE generation=? AND current_session_id=?`，`rowcount != 1` 拒绝；与业务写入同事务，不存在先查后写窗口。
2. `rotate_generation` 使用 CAS + 重试；并发切换测试断言 generation 单调且无丢失。
3. 旧会话的 `rejected` 任务保留 `rejected_reason`，可在 `GET /imports/{id}` 查询。
4. 错误码与 HTTP 状态稳定：`409` + `detail.code`。
5. 迁移 `e1c9a7b3d452` 只新增表/列/索引；SQLite 往返与 PostgreSQL 迁移 CI 均通过。

## 4. Session 重启语义（审核结论）

* 同 `session_key` 且同 `save_identity_id`：`start_session` 复用会话、刷新心跳、重新绑定当前代次（`_bind_session_epoch`）。这是「Agent 重启后续用同一会话」的预期行为，不构成跨身份继承。
* 不同身份复用 `session_key` → `409 save_context_mismatch`。
* 失效/关闭会话复用 `session_key` → `409 save_session_invalidated`。
* 心跳代次落后 → `409`，且心跳不会把旧会话「续回来」。

## 5. 代次切换与提交的边界语义

PostgreSQL READ COMMITTED 下，`fence.assert_current` 会锁定 `save_write_gates` 行；并发切换在同一行上串行化，**先提交者生效**：

* 切换先提交 → 导入的 `rowcount = 0` → 回滚 + `rejected`（预期拒绝）；
* 导入先提交 → 切换随后推进代次；该导入属于切换前完成的最后一批数据（可接受，且与「切换后旧 Worker 不得再提交」不矛盾）。

该语义需写入 `docs/evidence/v3.2.7.4/RT-MATRIX.md`，避免把「切换与导入并发」误判为数据错误。

## 6. 结论

* 身份协议、Session 绑定、Write Fence 的核心设计（同事务条件更新）成立。
* 由于 F-01 会让「同存档换身份」场景完全不可写，F-03 会让幂等成为内容漂移的漏洞，**V3.2.7.4 必须在合并前修复 F-01/F-02/F-03/F-04**。
* F-05/F-06 记录为已知限制，不影响本版本合并门槛。

## 7. 修复跟踪

| 缺陷 | 修复阶段 | 回归用例 |
| --- | --- | --- |
| F-01 | Phase 3 | `test_identity_switch/new_session_stays_writable` |
| F-02 | Phase 3 | `test_captures/fence_rejects_after_switch` |
| F-03 | Phase 4 | `test_operation_conflict/*`、`test_rejected_operation_replay/*` |
| F-04 | Phase 5 | Agent `RestartSyncTests` |
| F-05 | 文档（V3.2.7.5 计划） | — |
| F-06 | 文档 | — |
