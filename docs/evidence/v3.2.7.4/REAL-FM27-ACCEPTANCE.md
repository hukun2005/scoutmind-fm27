# 真实 FM27 A/B 验收（人工执行）

- 状态：**REAL_FM27_ACCEPTANCE_PARTIAL**
- 第 1 轮执行：2026-11-25 13:58–14:10（Asia/Shanghai）→ 场景 B 命中跨存档污染 **D-01（FAIL）**
- 第 2 轮执行：2026-11-25 14:25–14:35（Asia/Shanghai）→ 修复 D-01 后重跑 **A / B 均通过**
- 未执行：C 断网恢复、D 取消、E 重启恢复（仅协议级自动化验证，仍为 NOT_RUN）
- 原则：**没有人工执行与证据，不得写 PASS**。

## 0. 结论摘要

| 场景 | 第 1 轮 | 第 2 轮（修复后） | 关键证据 |
| --- | --- | --- | --- |
| A 单存档采集 | PASS（含两项偏差） | **PASS** | `runtime-rerun-20261125/A-*.json` |
| B A→B→A 切换 | **FAIL（D-01 污染）** | **PASS** | `runtime-rerun-20261125/B-*.json`、`saves.json` |
| C 断网恢复 | NOT_RUN | NOT_RUN | 协议级 `verify_operation_idempotency.py` |
| D 取消 | NOT_RUN | NOT_RUN | 协议级 `verify_worker_fencing.py` |
| E 重启恢复 | NOT_RUN | NOT_RUN | 协议级 + `recover_interrupted_imports` 测试 |

整体判定：**PARTIAL**。跨存档污染已修复并由真实环境复验；C/D/E 仍缺人工执行，不折算成 PASS。

## 1. 环境记录（第 2 轮）

| 项目 | 值 |
| --- | --- |
| 日期 | 2026-11-25 14:25–14:35（Asia/Shanghai） |
| 执行人 | 用户（游戏内载入/切换存档）+ 自动化（Reader / Agent / 后端） |
| 代码 | 分支 `codex/v3.2.7.4-runtime-closure`，基线 `9d3277c` + 未提交的 D-01 修复 |
| FM27 | 构建 `26620374`，插件 `27.1`，布局 `FM27_1`；`fm.exe` PID 66972 |
| 会话键 | `66972:2026-11-24T15:57:31.1218361Z:26620374` |
| 后端 | 仓库代码另起 `127.0.0.1:8010`，SQLite `backend/data/acceptance-v3274-r3.db`，迁移到 `b5d9c2e7f4a1` |
| 存档 A | `<save-A>.fm`，指纹 `si:v1:file:ab0bd795…f58e8672665`，游戏内日期 `2026-08-21` |
| 存档 B | `<save-B>.fm`，指纹 `si:v1:file:b887415a…3a8c67418083`，游戏内日期 `2026-02-03` |

> 验收没有使用本机 `127.0.0.1:8000`（`<repo-v323>` 的旧后端），也未写入用户原库。

## 2. D-01 修复内容

| # | 位置 | 修复 |
| --- | --- | --- |
| 1 | [SaveIdentityModels.cs](file:///<repo>/live-reader/ScoutMind.FMReader/Discovery/SaveIdentityModels.cs) | `AutomaticSnapshotEnabled` 改为读取 `SCOUTMIND_AUTOMATIC_SNAPSHOT`；`SnapshotEligible` 只对 `verified` 为真；多存档歧义时用**用户已确认指纹**唯一定位，不再盲目回落 `discovered` |
| 2 | [FmSaveIdentityDiagnostics.cs](file:///<repo>/live-reader/ScoutMind.FMReader/Engine/FmSaveIdentityDiagnostics.cs) | `--verify` 允许 `candidate` / `conflict` 显式切换确认到新存档 |
| 3 | [routes_core.py](file:///<repo>/backend/app/api/routes_core.py) | 新增 `POST /saves/resolve`：按指纹 find-or-create `fm_save` 并激活，返回 `save_id` |
| 4 | [SaveIdentitySync.cs](file:///<repo>/desktop-agent/ScoutMind.Agent/SaveIdentitySync.cs) | 先解析 `save_id`，注册身份、启动会话、上传全部携带 `save_id`；会话键按指纹稳定化并附加时间戳 |
| 5 | [AgentApplication.cs](file:///<repo>/desktop-agent/ScoutMind.Agent/AgentApplication.cs) | `scan --sync` 也走身份/会话链路，`SyncOneAsync` 携带 `save_id` + `operation_id` |

## 3. 第 2 轮实测：B（先执行，游戏已载入 B）

1. `save-identity --verify --save-file "…\<save-B>.fm"` → `verified`、`kind=user_confirmed`、`snapshot_eligible=true`；
2. 无 `--save-file` 的 `save-identity --diagnostics` → `verified`、`ambiguous=false`（确认指纹消歧生效）；
3. `scan --sync`（`SCOUTMIND_BACKEND_URL=http://127.0.0.1:8010/api/v1`）。

| 检查项 | 观测值 | 判定 |
| --- | --- | --- |
| 存档解析 | `POST /saves/resolve` 新建 `save_id=1`（`FM27 存档 b887415a`） | PASS |
| 身份登记 | `identity_id=1`，`identity_status=verified`，`kind=user_confirmed`，审计 `registered` | PASS |
| 会话 | `session_id=1`，审计 `session_created`（`session_key=…26620374#ile:b887#…`） | PASS |
| 导入落点 | 任务 `#1` `succeeded`，`save_id=1`，`save_identity_id=1`，`save_session_id=1`，`operation_id=op-9b1495…` | PASS |
| 写入审计 | `worker_started` → `write_accepted` | PASS |
| 隔离 | 存档列表只有 B 的一个存档；`player_count=18,614` | PASS |

## 4. 第 2 轮实测：A（游戏切到 A，进程不重启）

1. `save-identity --verify --save-file "…\<save-A>.fm"` → `verified`，诊断提示「用户确认了与上次不同的存档文件，已将确认切换至当前存档」；
2. `save-identity --diagnostics`（无 `--save-file`）→ 指纹 `ab0bd795…`、`verified`、`ambiguous=false`；
3. `scan --sync`。

| 检查项 | 观测值 | 判定 |
| --- | --- | --- |
| 存档解析 | 新建 `save_id=2`（`FM27 存档 ab0bd795`），B 的 `save_id=1` 变为 `is_active=false` | PASS |
| 身份/会话 | `identity_id=2`、`session_id=2`，审计 `registered` + `session_created` | PASS |
| 导入落点 | 任务 `#2` `succeeded`，`save_id=2`，`save_identity_id=2`，`save_session_id=2`，`operation_id=op-a0cfec…` | PASS |
| A 覆盖度 | `players=18,614`、`snapshots=18,614`、`clubs=25` | PASS |
| B 未被污染 | `save_id=1` 仍为 `player_count=18,614`、`snapshot_count=18,614` | PASS |

## 5. 第 2 轮实测：切回 B（A→B→A 的第三段）

1. `save-identity --verify --save-file "…\<save-B>.fm"` → 确认切回 B；
2. `scan --sync` → 解析到已存在的 `save_id=1`（未新建存档）。

| 检查项 | 观测值 | 判定 |
| --- | --- | --- |
| 存档复用 | 任务 `#3` `succeeded`，`save_id=1`，`save_identity_id=1`，`save_session_id=3` | PASS |
| A 未被污染 | `save_id=2` 仍为 `players=18,614`、`snapshots=18,614` | PASS |
| B 自身 | `player_count=18,614` 未累加；`snapshot_count` 18,614 → 37,228 | PASS（同存档两次采集按次追加快照，属设计行为，非跨存档合并） |
| 会话收尾 | 审计 `session_created` → `write_accepted` → `session_invalidated`；失效当前可写会话时代次 0→1（V3.2.7.3 写门设计） | PASS |

## 6. 第 1 轮记录（保留原始 FAIL 证据）

第 1 轮（`runtime-manual/`）中 B 的导入落到 **`save_id=1`**（A 的存档），`player_count` 18,614→18,616、`snapshot_count` 18,614→37,228，且扫描报文无 `save` 段、Agent 不传身份/会话、后端回落 `get_active_save`、`AutomaticSnapshotEnabled=false` 使 `auto` 永不执行。根因链与证据见 `runtime-manual/B-save-identity.json`、`B-import-job.json`、`B-payload-header.json`、`saves-after-B.json`、`A-save-summary-after-B.json`。

该轮的偏差已在第 2 轮消除：

| 第 1 轮偏差 | 第 2 轮状态 |
| --- | --- |
| `auto` 被常量 `false` 永久拒绝 | 已改为环境变量开关 + 仅 `verified` 放行 |
| `scan --sync` 无身份/会话/`save_id` | 已携带 `save_identity_id` / `save_session_id` / `operation_id` / `save_id` |

## 7. 测试与回归

| 项目 | 结果 |
| --- | --- |
| FMReader 单测 | 215 PASS / 0 FAIL（含新增「多存档歧义时用户确认指纹可唯一消歧」） |
| Reader 集成测试 | 57 PASS / 0 FAIL |
| Agent 测试 | 通过（exit 0） |
| 后端全量 pytest | 通过（0 failed，3 skipped） |
| `test_saves_resolve.py` | 4 用例通过（新建/复用/绑定身份/非法指纹 422） |

## 8. 证据清单

`docs/evidence/v3.2.7.4/runtime-rerun-20261125/`：

- `environment.json`（进程、构建、库、指纹、命令）
- `saves.json`（A/B 两个独立存档）
- A：`A-identity.json`、`A-audit.json`、`A-summary.json`、`A-imports.json`
- B：`B-identity.json`、`B-audit.json`、`B-summary.json`、`B-imports.json`

第 1 轮历史证据保留在 `runtime-manual/`，不删除。

## 9. 剩余工作

- C 断网恢复、D 取消、E 重启恢复仍为 **NOT_RUN**（需人工断网/取消/重启游戏），不得写 PASS。
- 真实环境未定位游戏内 Save ID / World ID，身份仍依赖「稳定文件元数据 + 用户确认」；每次切换存档需显式 `--verify`。

## 10. 结论口径

| 结果 | 含义 |
| --- | --- |
| PASS | 五个场景全部人工执行且符合预期 |
| PARTIAL | 至少一个场景因环境原因未执行 |
| FAIL | 任一场景出现跨存档污染、旧会话写入成功、半提交或重复写入 |

**本文件结论：PARTIAL。** D-01 已修复并在真实 A→B→A 中复验通过；C/D/E 未执行。
