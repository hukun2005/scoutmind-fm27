# V3.2.7.3 最终报告：统一写入保护与并发安全

任务：V3.2.7.2 PR #7 深度审核 + V3.2.7.3「并发安全与统一导入保护」
分支：`codex/v3.2.7.3-write-safety`（基于 `origin/main` = `6aaaa31`）
状态：**实现与本地验证完成；PR 已创建，未合并 main。**
证据索引：`PHASE-0-AUDIT.md`、`PR7-SECURITY-AUDIT.md`、`IMPORT-ENTRYPOINT-MATRIX.md`、`TEST-MATRIX.md`、`STATUS.md`

## A. 仓库状态

| 项 | 值 |
|---|---|
| 工作分支 | `codex/v3.2.7.3-write-safety` |
| 基点 | `6aaaa31`（PR #7 合并提交，`origin/main`） |
| 直接改 main | 否 |
| 合并 main / Release | 否（按任务书要求停手） |
| 删除测试 / 降低断言 / 改历史 migration | 否 |
| 新迁移链 | `d4b7c1e2f9a3 → e1c9a7b3d452`（head） |
| 未提交/未跟踪残留 | 仅本版本新增与修改文件（见 `STATUS.md` §7） |

## B. PR #7（V3.2.7.2）审核结果

审核方式：逐函数阅读真实代码 + 真实并发测试复现。完整清单见 `PR7-SECURITY-AUDIT.md`。

**结论：身份层可以保留，写入层存在 3 个 P0。**

| ID | 问题 | 影响 | 本版本处理 |
|---|---|---|---|
| P0-1 | `final_guard` 与业务提交分属两个事务（TOCTOU） | 检查通过后被切换，旧存档数据仍提交 | 同事务条件 UPDATE fence（`WriteFence.assert_current`） |
| P0-2 | 会话失效不推进任何代次 | 切换后在途 Worker 仍可写入 | `save_write_gates.generation` 单调递增；失效即递增 |
| P0-3 | transfers / squad-csv / 手动 sync / CLI 不带上下文 | 可绕过身份与会话写入 | 四个入口统一 `_require_write_fence` |
| P1-1 | 无 operation 级幂等 | 不同 scan_id 重复提交可双写 | `operation_id` + `(fm_save_id, operation_id)` 唯一 |
| P1-2 | 导入进行中不复查心跳 | 过期会话可完成写入 | 上下文解析校验心跳 + fence 校验代次/会话 |
| P1-3 | `rejected` 不存在，失败任务可被自动重试 | 旧上下文可能自动复活 | 新增 `rejected` 状态，`retryable=false` |
| P2-1 | 并发导入触发唯一约束冲突（500） | 并发采集不稳定 | `ensure_attributes` / 俱乐部创建改 savepoint + 复读 |
| P3-1 | 无代次诊断 | 无法定位“为什么被拒绝” | `GET /save-write-gate` + 身份详情 `write_gate` |

身份层保留项（未发现提权路径）：证据封顶、未解析指纹降级、多候选降级、冲突身份只能显式 verify 恢复、审计只追加。

## C. 实施结果

### C1 统一写入协议（不允许各 API 各写一套）

新增 `backend/app/services/write_safety.py`：

* `WriteContext`（frozen）：`save_id / identity_id / session_id / fingerprint / session_epoch / agent_id / capture_id / operation_id / protocol_version`。
* 统一服务：`resolve_write_context` / `acquire_write_fence` / `commit_with_fence`（由调用方在同一事务内 commit）/ `rotate_generation` / `invalidate_old_generation` / `bind_session_to_gate` / `diagnose`。
* 稳定错误码：`write_context_required`、`write_fence_stale`、`write_session_epoch_stale`、`write_gate_busy`、`write_operation_reused`。
* 协议版本：`write-safety/v1`。

### C2 Session Epoch

* `save_write_gates` 每存档一行：`generation`、`current_session_id`、`current_identity_id`、`last_switch_at/reason`。
* 代次单调递增（CAS 循环，最多 5 次），Agent 重启不推进也不回退；新会话不复用旧代次，必须由 gate 重新绑定。
* 切换在**单事务**内完成：锁/CAS → 递增 → 失效全部旧会话（`created/verified/switching`）→ 更新 gate → 写 `session_invalidated` / `save_switched` 审计 → 提交。
* 不依赖内存 bool、不依赖心跳、不依赖独立查询判定资格。
* SQLite 不假设行锁：全部通过条件 UPDATE + `rowcount` + 唯一约束实现，PG 下条件重判语义一致。

### C3 入口统一（11 个入口，矩阵见 `IMPORT-ENTRYPOINT-MATRIX.md`）

`POST /imports/scan`、`/imports/transfers`、`/imports/squad-csv`、`POST/PATCH /captures`、Agent `auto`、手动 sync、`scan --sync`、CLI、后台 Worker、重试、存档切换，全部走同一套 fence。

### C4 任务状态

`running → succeeded / partial / failed / rejected`。`rejected` 记录 `rejected_reason`（稳定错误码），`GET /imports/{id}` 的 `retryable` 排除 `rejected`；同 `operation_id` 的结果幂等复用。

### C5 客户端

* Agent：`SaveContextQuery` 增加 `OperationId`；`SyncOneAsync` 以 `op-<payload sha256 前 32 位>` 作为 `operation_id`。
* 前端：会话表新增“代次”列；采集闸门卡片展示写入代次/当前可写会话，引用类型 `SaveWriteGate`。

### C6 迁移

`e1c9a7b3d452_write_safety_gate.py`：仅新增列/索引/表，列可空或带 server_default，不回填业务数据。SQLite upgrade→downgrade→upgrade 循环成功（head `e1c9a7b3d452`）。

### C7 旧客户端兼容（明确配置 + 审计 + 禁用条件）

* 无 gate 的历史存档保留旧写入路径，每次写 `legacy_write_allowed` 审计。
* `SCOUTMIND_WRITE_SAFETY_LEGACY_ALLOWED=false` 可整体关闭旧路径（返回 409 `write_context_required`）。
* 一旦存档建立 gate，缺上下文一律 409；**不存在**“伪造默认 Session”或“自动绑定当前活跃存档”的回退。

## D. 并发安全（真实并发验证）

| 场景 | 测试 | 结果 |
|---|---|---|
| 导入窗口内发生 A→B 切换（真实第二连接） | `test_import_concurrency.py::test_switch_during_import_window_rolls_back_everything` | 导入整体回滚，`rejected`，0 条数据落库 |
| 两个并发导入（不同 scan） | `test_import_concurrency.py::test_concurrent_import_writes_two_snapshots` | 均成功，2 个快照，无唯一约束 500 |
| 同 operation 并发提交 | `test_import_concurrency.py::test_same_operation_concurrent_replay_writes_once` | 只写一次 |
| 两会话并发 start | `test_import_concurrency.py::test_concurrent_session_starts_serialize_on_single_current` | gate 上只有一个 current |
| 4 线程并发 switch | `test_session_epoch.py::test_concurrent_switches_never_lose_updates` | 代次严格 `[1,2,3,4]` |
| 切换后旧 fence 提交 | `test_write_fencing.py::test_switch_before_commit_rejects_whole_import` | 409/`rejected`，无部分数据 |

关键机制：最终校验和写入在**同一事务**内；`WriteFence.assert_current` 执行
`UPDATE save_write_gates SET generation=generation WHERE fm_save_id=? AND generation=? AND current_session_id=?`，
`rowcount != 1` 即拒绝并回滚，因此不存在“先查后写”。

## E. 导入安全

* **幂等**：`(fm_save_id, operation_id)` 唯一约束 + `IntegrityError` 兜底复读，先查后写的竞态已被消除。
* **拒绝可追溯**：`rejected_reason` 落库，审计 `write_rejected` 记录 code/message/save_id/generation。
* **无部分数据**：fence 失败先 `rollback()`，再以独立短事务标记 `rejected`，不保留业务写入。
* **阻止自动重试旧上下文**：`rejected` 不可重试；重试必须使用新 operation + 新会话/代次。
* **跨存档隔离**：会话必须属于目标存档；异存档会话 409。
* **并发补种安全**：属性字典与俱乐部创建改 savepoint 复读，不再因并发唯一约束冲突失败。

## F. 测试记录

| 项 | 命令 | 结果 |
|---|---|---|
| 后端全量 | `cd backend; python -m pytest --junitxml=pytest-v3273.xml -q` | `565 tests / 0 failures / 0 errors / 3 skipped / 382.7s` |
| 新增用例 | 4 个文件 | 23 个用例全部通过（5+5+9+4） |
| 迁移往返 | `alembic upgrade head → downgrade -1 → upgrade head` | 成功，head `e1c9a7b3d452` |
| Agent | `dotnet test tests\ScoutMind.Agent.Tests\...csproj` | 31 / 31 通过 |
| 前端 | `npm ci; npm run build` | 成功（8.70s） |
| WF-001~020 | 见 `TEST-MATRIX.md` | 20/20 有对应覆盖，无 NOT_RUN 冒充 PASS |

CI（`.github/workflows/ci.yml`）已覆盖本版本改动：backend job 跑迁移往返与全量 pytest；`postgres-migrations` job 真实 PG16 执行 `scripts/pg_migration_validation.py`（会 downgrade 到 `f3a9c57e21d8` 再 upgrade head，覆盖新迁移的上下行）与 `tests/test_pg_migrations.py`；dotnet / frontend job 覆盖客户端与类型检查。

## G. 真实 FM27（NOT_RUN）

无游戏环境，未执行，未伪造数据。人工验收步骤：

1. 启动后端与 Agent，游戏内进入存档 A，确认 `GET /save-write-gate?save_id=A` 返回 `generation=0` 或 `1`，`current_session_id` 指向当前会话。
2. 执行一次自动采集，确认 `GET /imports/{job_id}` 为 `succeeded` 且 `save_generation` 等于网关代次。
3. 游戏内切到存档 B 并触发采集：`POST /save-sessions/{A 会话}/switch`（或由 Agent 自动切换）后，A 的会话应为 `invalidated`，gate 代次 +1。
4. 在 A 的旧会话上重放一次导入：必须 409 `write_fence_stale` / `write_session_epoch_stale`，`import_jobs` 无新增 succeeded 记录。
5. 在 B 的新会话上采集：成功，数据归属 B，A 数据未被改写。
6. 检查 `GET /save-identity-audit`：存在 `save_switched`、`session_invalidated`、必要时 `write_rejected`。

可复用 v3.2.7.2 的 `scripts/manual-real-save-switch.py` 做受控切换与断言。

## H. 风险与下一步

| 风险 | 说明 | 下一步 |
|---|---|---|
| PG16 未本机验证 | 条件 UPDATE + CAS 在 READ COMMITTED 下语义需真实 PG 确认 | 依赖 PR 的 `postgres-migrations` job；若红，读日志定位，不重跑掩盖 |
| 真实 FM27 未验收 | 游戏内切换时序与心跳可能与本机模拟不同 | 按 §G 人工执行并回填结果；未执行前保持 NOT_RUN |
| 旧客户端兼容 | `legacy_allowed=true` 期间旧客户端仍可写（有审计） | 观察审计后择期置 `false`，并在 Release Notes 说明 |
| 无 cancel API | 取消语义以 `rejected` 固化，未实现真正中断 | 后续版本单独设计 worker 取消 |
| 心跳 120s 与长导入 | 长导入可能跨过心跳窗口，但资格以代次/会话为准，不因心跳在提交时被误杀 | 保持现状；如需要，后续按任务书扩展 |

结论：P0/P1 已修复并有真实并发测试固化；本地可验证项全部 PASS，无法验证项全部标记 NOT_RUN。分支已推送并创建 PR，等待评审与 CI，**未合并 main**。
