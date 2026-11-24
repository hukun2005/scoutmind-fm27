# ScoutMind V3.2.7.2 实施报告：存档身份 E2E 与安全采集

- 分支：`codex/v3.2.7.2-save-identity-e2e`
- 基线：`origin/main = 187f4ad`
- 日期：2026-11-25
- 任务：`Save Identity E2E & Capture Safety`
- 状态：实现与本地回归完成；真实 FM27 游戏内切换、远端 CI 为未完成项（见 [STATUS](evidence/v3.2.7.2/STATUS.md)）

## 1. 目标与边界

在 V3.2.7 已建立的身份/会话底座上，补齐三件事：

1. **端到端**：Reader 产出证据 → Agent 上报 → 后端判定 → 会话心跳 → 采集写入必须携带并校验上下文。
2. **切换安全**：游戏内切换存档时，旧会话立即失效，正在进行的采集/导入必须失败而不是写进另一个存档。
3. **可审计、可回滚**：身份生命周期与会话事件写入不可变审计；导入事务失败不留半成品，同一 `scan_id` 可重试。

不做：不重写 V3.2.7 核心；不自动合并 main；不发布 Release；不把未验证状态写成已验证；不伪造 FM27 数据。

## 2. 协议（save-identity/v1）

完整字段与状态机见 [SCOUTMIND-V3.2.7.2-IDENTITY-PROTOCOL.md](SCOUTMIND-V3.2.7.2-IDENTITY-PROTOCOL.md)。

- 指纹：`si:v1:file:<sha256>`、`si:v1:unresolved:<build>`。
- 身份状态：`unknown / discovered / candidate / verified / conflict / invalidated`。
- 会话状态：`created / verified / switching / invalidated / closed`。
- `session_key = PID:进程启动时间:Build`。
- 错误体统一为 `{"error": {"code", "message"}}`。

### 2.1 注册封顶（服务端唯一判定）

`identity_status` 只是客户端声明，后端取 `min(声明, 证据允许)`：

| 证据 | 允许的最高状态 |
| --- | --- |
| 无证据 | `unknown` |
| 仅任意证据 | `discovered` |
| 第二优先级证据（`save_file_hash` 等） | `candidate` |
| 第一优先级证据（`game_internal_save_id` / `world_id`），或 `user_confirmed` + 次证据 | `verified` |
| `si:v1:unresolved:` 指纹 | 最多 `discovered` |
| `ambiguous=true` | 不得 `verified` |

只有 `/save-identities/{id}/verify`（`actor` + `basis`）或第一优先级证据能让身份 `verified`；仅次证据时客户端声明 `verified` 会被降为 `candidate`（E2E 已覆盖）。

### 2.2 冲突

同一存档已存在 `verified` 身份，又上报**不同指纹**且声明/证据允许 `verified`：

- 新身份落 `conflict`，旧 `verified` 保留；
- 写入 `save_identity_conflicts`（`open`）与 `conflict_detected` 审计；
- 采集闸门因未解决冲突阻断；
- 不自动替换、不合并。

## 3. 后端实现

### 3.1 数据模型与迁移

`backend/app/models.py`：

- `SaveIdentity`：新增 `verified_at`、`verified_by`。
- `SaveSession`：新增 `agent_id`、`last_heartbeat_at`。
- 新增 `SaveIdentityAuditEvent`（表 `save_identity_audit_events`），挂 `before_update` / `before_delete` 监听，直接抛 `ValueError`，保证审计不可变。

迁移 `backend/alembic/versions/d4b7c1e2f9a3_save_identity_lifecycle.py`（`down_revision = c3d8f1a2b407`）：

- `batch_alter_table` 增加可空列；
- 创建审计表与 4 个索引；
- `downgrade` 只删除本轮新增列/表/索引，不触碰 V3.2.7 结构；
- 未修改任何历史迁移。

### 3.2 服务层

`backend/app/services/save_identity.py`：

- `cap_declared_status`：证据封顶。
- `register_identity`：幂等；唯一约束冲突回滚复用；终态 `conflict/invalidated` 不被普通上报洗白；异指纹冲突处理。
- `verify_identity`：指纹必须一致、需第二优先级证据、无效身份不可确认、写 `user_confirmed` 证据与审计。
- `start_session`：`session_key` 幂等；身份必须属于当前存档；`conflict/invalidated` 拒绝；build 不一致 409；未验证身份只能得到 `created`。
- `heartbeat`：身份缺失、指纹不一致、build 不一致 → 会话失效（提交后返回 409）；心跳超时 → `invalidated(expired)`；非 `verified` 身份 → 409 且不放行。
- `end_session` / `invalidate_session` / `block_capture`。
- `capture_gate`：返回 `capture_allowed` 与 `blockers`（未解决冲突、最近会话状态、心跳超时）。
- `record_audit`：所有生命周期事件统一落审计。

### 3.3 API

`backend/app/api/routes_save_identity.py`（全部 `Depends(get_active_save)`）：

| 方法 | 路径 |
| --- | --- |
| POST | `/save-identities/register` |
| POST | `/save-identities/{id}/verify` |
| GET | `/save-identities` |
| GET | `/save-identities/{id}` |
| POST | `/save-sessions/start` |
| POST | `/save-sessions/{id}/heartbeat` |
| POST | `/save-sessions/{id}/end` |
| POST | `/save-sessions/{id}/invalidate` |
| GET | `/save-identity-audit` |

`backend/app/api/routes_capture.py`：`PATCH /captures/{id}` 接受 `save_identity_id` / `save_session_id`，调用 `resolve_save_context`；归属不一致 409；声明时回填归属列。

## 4. Agent 实现（C#）

- `SaveIdentityGate.cs`：新增 `SaveIdentityEvidence`、`SaveIdentitySnapshot`，所有放行结果附带快照，供上报证据。
- `BackendClient.cs`：新增 `SaveContextQuery`、`BackendJsonResult`、采集创建/PATCH、身份注册、会话开始/心跳/失效；`PostScanAsync` 可携带上下文查询串。
- `SaveIdentitySync.cs`：
  - 缺指纹/会话键直接失败；
  - 指纹变化先失效旧会话（`save_switched`）再注册新身份；
  - 注册 → 开会话；start 返回非 `verified` 时立即失效且不保存会话；
  - 已有会话则心跳，失败清空；
  - 只有同时持有 identity+session 才返回 `Context`。
- `AgentApplication.cs`（仅 `auto` 路径）：
  - 放行后 `EnsureAsync`，失败 → `identity_sync_failed` 跳过本轮；
  - 扫描前创建 capture；扫描/传输失败 PATCH `failed`；
  - 扫描后 `ChangeKey` 变化 → 全部失败 `save_changed_during_capture` + 失效会话 + PATCH `failed`；
  - 导入后 `EnsureAsync` 复核失败 → `FailAll(save_session_invalidated)`；
  - 成功 PATCH `completed`；循环结束失效会话（`agent_stopped`）。
- 手动 `sync`/`scan --sync` 保持历史行为（不携带上下文），兼容旧脚本。

## 5. Worker 事务与幂等

`backend/app/ingestion/importer.py` 现有保证（本轮补充真实断言）：

- `_begin_job` 先独立提交 `running`；
- `_apply` 异常 → rollback + `_mark_failed`；
- `final_guard` 失败 → rollback + `_mark_failed("提交前身份校验失败：…")` 并抛出；
- 成功重复提交 → `duplicate=true`，不重复写；
- 遗留 `running` 由 `recover_interrupted_imports` 置 `failed`，同一 `scan_id` 可重试。

新增 `backend/tests/test_import_transaction_safety.py` 覆盖：守卫失败无残留、中途异常无残留、失败后同 `scan_id` 重试、成功重复提交幂等。

## 6. 前端

新增 `/save-identity`（`frontend/src/views/SaveIdentityView.vue`）：

- 状态计数与筛选；
- 身份详情：指纹、置信度、证据等级、确认人/时间；
- 证据表、最近会话表、审计表；
- 采集闸门提示与阻断原因；
- 切换活动存档自动刷新（监听 `dataRevision`）；
- 明确标注“只读，不提升任何状态”。

类型与 API：`frontend/src/types/saveIdentity.ts`、`frontend/src/api/saveIdentity.ts`。

## 7. 验证结果

| 项目 | 结果 |
| --- | --- |
| 后端全量 | 550 passed / 8 skipped / 0 failed |
| 身份 API 专项 | 17 passed |
| 迁移专项 | 2 passed（含 downgrade 保留 V3.2.7 schema） |
| 事务安全专项 | 4 passed |
| Agent | 31 passed |
| Reader / CLI | 214 / 57 passed |
| 前端 | `npm run build`（vue-tsc + vite）通过 |
| 真实 HTTP E2E | 24 / 24 PASS |
| 迁移预检 | `downgrade_below_992_safe=true`，head `d4b7c1e2f9a3` |

证据：[docs/evidence/v3.2.7.2](evidence/v3.2.7.2/STATUS.md)。

## 8. 兼容性与升级

- 新增列均可空，旧数据无需回填；旧客户端不传上下文时 `PATCH /captures` 维持历史行为。
- 新表只增不改；已发布迁移未编辑。
- 前端新增路由，不影响既有页面。
- 回滚：`alembic downgrade c3d8f1a2b407` 或回退代码提交。

## 9. 未完成项与风险

- **NOT_RUN**：真实 FM27 游戏内 A→B 切换与采集；真实指纹重新测量；Agent `auto` 长时间真实循环。
- **PARTIAL**：远端 CI（含 PG16）在推送后复跑，本地不替代远端结论。
- 风险：第一优先级证据可直接确认身份；未解决冲突需人工处置；手动 `sync` 仍不携带上下文。详见 [FINAL-REPORT](evidence/v3.2.7.2/FINAL-REPORT.md)。
