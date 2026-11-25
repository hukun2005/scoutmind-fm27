# V3.2.7.5 真实 FM27 最终验收记录

- 状态：**REAL_FM27_ACCEPTANCE_PARTIAL**
- 日期：2026-11-25（Asia/Shanghai）
- 分支：`codex/v3.2.7.4-runtime-closure`
- 代码：`9d3277c`（V3.2.7.4 基线）+ `3ed41b6`（D-01 修复与 A→B→A 证据，已脱敏）+ `1572451`（C/D/E 运行期验收工具检查点）+ `d957374`（C/D/E 协议级验收与证据）+ `f74075d`、`5574443`（文档修订）；以上为历史重写前的短哈希，重写后的对应值见 `FINAL-REPORT.md` §9
- 游戏环境：FM27 build `26620374`，插件 `27.1`，布局 `FM27_1`（A/B/A 两轮实测环境，见 v3.2.7.4 记录）
- 原则：**没有真实执行与证据，不得写 PASS；自动模拟测试不得冒充真实 FM27 PASS。**

## 0. 结论摘要

| 场景 | 状态 | 执行方式 | 关键证据 |
| --- | --- | --- | --- |
| A 单存档采集 | **PASS** | 真实 FM27（2026-11-25 第 2 轮） | [runtime-rerun-20261125/A-*.json](../v3.2.7.4/runtime-rerun-20261125/A-summary.json) |
| B A→B→A 存档切换 | **PASS** | 真实 FM27（2026-11-25 第 2 轮） | [runtime-rerun-20261125/B-*.json](../v3.2.7.4/runtime-rerun-20261125/B-summary.json) |
| C 断网恢复 | **PARTIAL** | 协议级真实后端进程 + 真实 HTTP 14/14 PASS；真实 Agent + FM27 断网 **NOT_RUN** | [runtime/network-recovery-result.json](./runtime/network-recovery-result.json) |
| D 取消任务 | **PARTIAL** | 真实 Worker + 提交/取消分属两个 OS 进程 7/7 PASS；跨后端进程 Worker **NOT_RUN** | [runtime/cancel-two-process-result.json](./runtime/cancel-two-process-result.json) |
| E 重启恢复 | **PARTIAL** | 后端硬杀/重启 14/14 PASS；Agent 进程重启 + FM27 **NOT_RUN** | [runtime/backend-restart-recovery-result.json](./runtime/backend-restart-recovery-result.json) |

整体判定：**PARTIAL**。

- A / B 保持上一轮真实 FM27 的 PASS 结论，本轮未重复执行、未覆盖；
- C / D / E 的协议级部分已用真实后端进程、真实 HTTP、独立子进程执行并通过；
- C / E 的「真实 Agent + 真实 FM27」部分与 D 的「跨后端进程 Worker」部分因当前机器无法可靠构造，保持 **NOT_RUN**，操作步骤见 §9。

## 1. 状态口径

| 状态 | 含义 |
| --- | --- |
| PASS | 真实执行且全部断言通过 |
| FAIL | 真实执行且存在断言失败 |
| PARTIAL | 部分子场景真实执行通过，剩余子场景有明确原因未执行 |
| NOT_RUN | 未执行 |
| BLOCKED_BY_ENVIRONMENT | 缺少运行环境 |

`runtime/*.json` 均带 `synthetic_identity: true`、`real_fm27: false`，只证明**后端协议、进程与数据库行为**，不代表真实游戏内验收。

## 2. A / B / A 真实 FM27 结果（沿用，不覆盖）

以下结果来自 [v3.2.7.4 真实验收](../v3.2.7.4/REAL-FM27-ACCEPTANCE.md)，证据仍在原目录，本轮未修改、未删除：

| 检查 | 观测 | 判定 |
| --- | --- | --- |
| B 首采 | `save_id=1`、`identity_id=1`、`session_id=1`、任务 `#1` succeeded、`players=18,614` | PASS |
| 切到 A | 新建 `save_id=2`，B 置为非活跃；任务 `#2` 落 `save_id=2`；A `players=18,614` | PASS |
| 切回 B | 复用 `save_id=1`（未新建）；任务 `#3` 落 `save_id=1`；A 未被污染 | PASS |
| 跨存档隔离 | A / B 各自 `player_count=18,614`，互不合并 | PASS |
| 身份/会话审计 | `registered` → `session_created` → `write_accepted` → `session_invalidated` | PASS |

证据目录：[docs/evidence/v3.2.7.4/runtime-rerun-20261125](../v3.2.7.4/runtime-rerun-20261125)。

## 3. C 断网恢复

### 3.1 通信机制

- Agent → 后端：`POST /api/v1/imports/scan`（携带 `save_id` / `save_identity_id` / `save_session_id` / `operation_id`）。
- 断网识别：验收工具把连接层异常归一为 `status=0, code=transport_error`；真实 Agent 的 CLI 输出为 `无法连接后端 <url>：<原因>`（`BackendClient.cs`），并返回非 0 退出码。两者不要混用。
- 恢复连接：`POST /save-sessions/{id}/heartbeat` 携带 `reconnected=true`，写 `network_reconnected` 审计。
- 幂等键：`operation_id` 在存档内唯一；`scan_id + checksum` 防止同扫描不同内容重复写入。

### 3.2 执行结果（真实后端进程 + 真实 HTTP，14 项）

| # | 检查 | 观测 | 判定 |
| --- | --- | --- | --- |
| 1 | 正常提交 | `201`、`duplicate=false`、`job_id=1` | PASS |
| 2 | 响应丢失但服务端完成 | 任务 `succeeded`，覆盖度 `players=100/snapshots=100` | PASS |
| 3 | 原 `operation_id` 重试 | `201`、`duplicate=true`、同一 `job_id=2` | PASS |
| 4 | 重试不重复写 | 重放前后均 `100/100` | PASS |
| 5 | 处理中断开再重试 | 恰好 +50 球员/+50 快照，该 scan 只有 1 个 job | PASS |
| 6 | 后端不可达 | `status=0`、`transport_error` | PASS |
| 7 | 断网期间心跳 | `status=0` | PASS |
| 8 | 恢复后心跳 | `200` | PASS |
| 9 | 重连审计 | 含 `network_reconnected` | PASS |
| 10 | 重连后原 `operation_id` 重试 | `duplicate=true`、同一 `job_id=1` | PASS |
| 11 | 重连后不重复写 | 球员/快照不变，scan 只有 1 个 job | PASS |
| 12 | 代次推进 | `generation` 0→1 | PASS |
| 13 | 旧会话不被复活 | `409 save_session_invalidated` | PASS |
| 14 | 新会话可写 | `201` | PASS |

证据：[runtime/network-recovery-result.json](./runtime/network-recovery-result.json)（run `0e520c00`，后端启动 2 次）。

### 3.3 未执行部分

- 真实 **Desktop Agent** 进程在真实 FM27 运行中断网/恢复；
- 真实 Agent 重试「已提交未收到响应」的请求；
- 真实游戏内切换存档后旧 Session/Generation 不被恢复（与 A/B/A 已有结果部分重叠，但未在断网链路下复测）。

原因：本机当前没有可驱动的 FM27 会话与真实 Agent 交互窗口。步骤见 §9.1。

## 4. D 取消任务

### 4.1 执行方式

- Worker：后端进程内的真实导入 Worker（真实 HTTP 请求触发，非 Mock）。
- 提交方：独立子进程（`python -c`）提交 50,000 名球员的大导入。
- 取消方：本脚本进程轮询到任务 `queued/running` 后，通过真实 HTTP `POST /imports/{id}/cancel` 发起取消。
- 断言：取消/提交竞态原子、Worker 感知取消、取消后无半提交、重复取消幂等、排队任务取消幂等。

### 4.2 执行结果（7 项）

| # | 检查 | 观测 | 判定 |
| --- | --- | --- | --- |
| 1 | 任务被观察到 | `cancel_sent=true`，最终 `cancelled` | PASS |
| 2 | 取消/提交竞态原子 | 取消 `200`；提交返回 `409 import_cancelled` | PASS |
| 3 | Worker 感知取消 | 审计含 `worker_cancel_requested`、`worker_cancelled` | PASS |
| 4 | 无半提交 | 取消后 `players=0` | PASS |
| 5 | 重复取消幂等 | 再次取消 `200`、状态仍 `cancelled` | PASS |
| 6 | 排队中取消 | `200 cancelled` | PASS |
| 7 | 排队取消幂等 | 再次 `200 cancelled` | PASS |

证据：[runtime/cancel-two-process-result.json](./runtime/cancel-two-process-result.json)（run `289042f3`，players=50,000）。

### 4.3 限制（未执行）

- 取消信号实现为**后端进程内注册表**（`backend/app/ingestion/cancellation.py`）。当前验证的是「取消请求由另一个 OS 进程经 HTTP 发起、Worker 在同一后端进程内感知」；
- 「Worker 与取消 API 分属两个后端进程」的部署未验证（NOT_RUN）。SQLite 下单写者事务会阻塞跨进程取消写入，需要 PostgreSQL 才能可靠验证；
- 该限制已在 v3.2.7.4 FINAL-REPORT 记录为 PARTIAL，本轮未改变实现。

## 5. E 重启恢复

### 5.1 执行结果（后端部分 14 项）

| # | 检查 | 观测 | 判定 |
| --- | --- | --- | --- |
| 1 | 崩溃前基线导入 | `201` | PASS |
| 2 | running 中硬杀后端 | `killed_while_running=true` | PASS |
| 3 | 提交方感知中断 | `status=0` | PASS |
| 4 | 崩溃现场无业务行 | `running`、`player_count=0` | PASS |
| 5 | 启动恢复 | `running → failed` | PASS |
| 6 | 任务状态持久化 | 崩溃前 `succeeded` 保持 | PASS |
| 7 | 恢复审计 | 含 `worker_recovered` | PASS |
| 8 | 重启审计 | 含 `backend_restarted` | PASS |
| 9 | 旧 Worker 无残留写入 | `players=10`（=基线） | PASS |
| 10 | 崩溃后重试 | `201`、`duplicate=false` | PASS |
| 11 | 重试无重复写 | 恰好 +10（10→20） | PASS |
| 12 | 已完成任务重放 | `duplicate=true` | PASS |
| 13 | 代次推进 | `generation` 0→1 | PASS |
| 14 | 旧代次会话被拒 | `409 save_session_invalidated` | PASS |

证据：[runtime/backend-restart-recovery-result.json](./runtime/backend-restart-recovery-result.json)（run `144df52e`，崩溃时正在导入 12,000 人）。

### 5.2 本轮修复

`recover_interrupted_imports` 之前把 `backend_restarted` 写成 `save_id=None` 的全局事件，而审计 API 只按存档过滤，导致该事件无法被观测。现改为**每个受影响存档各写一条** `backend_restarted`，`worker_recovered` 逻辑不变。

### 5.3 未执行部分

- Agent 正常运行时关闭 Agent、重新启动、重新识别当前存档；
- 旧 Session 在 Agent 重启后是否失效、是否建立新 Session；
- 真实 FM27 环境下重启 Agent 后的重复任务写入检查。

原因：需要真实 FM27 + Agent 交互。步骤见 §9.2。

## 6. 真实 FM27 身份验证

保留既有策略，不做任何猜测：

1. **稳定文件元数据**：存档文件路径规范化 + 大小 + 修改时间 + SHA-256 派生指纹（`si:v1:file:…`）；
2. **用户确认**：多存档歧义时只使用用户已确认指纹唯一定位，不回落 `discovered`；
3. **显式切换**：每次存档切换必须执行 `save-identity --verify --save-file "<存档路径>"`；
4. **自动快照**：仅 `verified` 且 `SCOUTMIND_AUTOMATIC_SNAPSHOT` 开启时生效。

限制：本机未能从游戏内可靠取得 Save ID / World ID，因此身份仍依赖「文件元数据 + 用户确认」，不以猜测值填充。

## 7. 已知限制

| 限制 | 状态 | 说明 |
| --- | --- | --- |
| C 真实 Agent + FM27 断网 | NOT_RUN | 需人工操作，见 §9.1 |
| D 跨后端进程 Worker 取消 | NOT_RUN | 进程内取消注册表；SQLite 无法可靠跨进程验证 |
| E 真实 Agent 重启 | NOT_RUN | 需人工操作，见 §9.2 |
| 游戏内 Save ID / World ID | 未定位 | 保留用户确认机制，不猜测 |
| PostgreSQL 本地验证 | BLOCKED_BY_ENVIRONMENT | 需 Docker 或 CI |

## 8. 结论

- A / B 的真实 FM27 PASS 结论保留；
- C / D / E 的协议级真实执行全部通过，但不折算为真实 FM27 PASS；
- 整体维持 **PARTIAL**，等待 §9 的人工执行结果。

## 9. 待人工执行的操作步骤与证据采集

> 所有步骤只使用仓库现有工具，不上传完整存档，不修改游戏文件，不注入代码。

### 9.1 C：真实 Agent 断网恢复

1. 启动后端（记录 `SCOUTMIND_BACKEND_URL` 与数据库路径）；
2. 启动 Agent 并完成一次 `scan --sync`，确认任务 `succeeded`；
3. 记录当前任务 `job_id`、`operation_id`、`scan_id`；
4. 断开本机网络（禁用网卡或防火墙阻断 `127.0.0.1` 以外/后端端口）；
5. 再执行一次 `scan --sync`，确认 Agent 输出 `无法连接后端 ...` 且退出码非 0；
6. 恢复网络，确认 Agent 心跳恢复且审计出现 `network_reconnected`；
7. 用原 `operation_id` 重试同一报文，确认 `duplicate=true`、任务数不增加、球员/快照行数不变；
8. 切换存档并 `--verify`，确认旧 Session 返回 `409`、代次 `generation` 增加。

采集：

```powershell
pwsh -File tools/runtime-acceptance/collect_evidence.ps1 -EvidenceDir docs/evidence/v3.2.7.5/manual-c
```

### 9.2 E：Agent 重启恢复

1. Agent 正常运行时记录当前 `session_id`、`save_id`、正在运行的任务；
2. 关闭 Agent（正常退出），确认审计 `session_ended` 或失效记录；
3. 重新启动 Agent，执行 `save-identity --verify --save-file "<当前存档>"` 与 `scan --sync`；
4. 确认旧 Session 不可写（`409`），并建立新 `session_id`；
5. 重启后端，确认任务状态持久化、旧 Worker 无法再提交、同一 `job_id` 重试不产生重复写入。

采集：

```powershell
pwsh -File tools/runtime-acceptance/collect_evidence.ps1 -EvidenceDir docs/evidence/v3.2.7.5/manual-e
```

### 9.3 D：跨后端进程取消（可选）

需要 PostgreSQL 16 与两个后端进程共享同一数据库：

1. 以同一 `SCOUTMIND_DATABASE_URL` 启动后端 A（执行导入）与后端 B（提供取消接口）；
2. 进程 A 提交大导入，进程 B 在 `running` 时调用 `POST /imports/{id}/cancel`；
3. 确认 A 的 Worker 能感知取消（当前实现为进程内注册表，预计 **FAIL**，用于暴露限制）；
4. 若需要支持该部署，应把取消检查改为数据库状态轮询并处理 SQLite 单写者限制。

采集同上，输出到 `docs/evidence/v3.2.7.5/manual-d`。
