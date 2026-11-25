# V3.2.7.5 上传前审计（PRE-UPLOAD-AUDIT）

- 审计时间：2026-11-25（Asia/Shanghai）
- 审计对象：分支 `codex/v3.2.7.4-runtime-closure`，工作树 `<repo>`
- 审计方式：**只读**。未执行 `reset --hard`、`clean -fd`、`push --force`、未删除任何文件、未合并 main
- 文件用途：远程同步前的差异与证据核对；本文件为新增未跟踪文件，尚未提交

## 0. 前提校正（与任务描述不一致处）

任务描述中的三处状态已过时，以下为本次实测结果：

| 任务描述 | 实测 | 说明 |
| --- | --- | --- |
| 远程仓库仍然是 V3.2.7.4 | **成立（就 `main` 内容而言）** | `origin/main = 89ac157`，是重写后的 V3.2.7.4 合并提交；V3.2.7.5 成果只在分支上 |
| C 断网恢复 NOT_RUN | **已执行（协议级 PASS）** | run `0e520c00`，14/14 检查通过；真实 Agent 子场景仍 NOT_RUN |
| D 取消 NOT_RUN | **已执行（单后端真实双进程 PASS）** | run `289042f3`，7/7；跨后端进程取消仍 NOT_RUN |
| E 重启恢复 NOT_RUN | **已执行（后端重启 PASS）** | run `144df52e`，14/14；Agent 重启子场景仍 NOT_RUN |

上述 C/D/E 均为**真实 uvicorn 进程 + 真实 HTTP + 真实 SQLite**，证据 JSON 标注 `synthetic_identity=true`、`real_fm27=false`，**未冒充真实 FM27 结果**。

## 1. 工作区与分支

| 项 | 值 |
| --- | --- |
| 工作树根 | `<repo>` |
| 当前分支 | `codex/v3.2.7.4-runtime-closure` |
| HEAD | `906868d`（docs: record full history rewrite and old-to-new commit mapping） |
| `git status --short --branch` | 无输出（工作区干净，与 `origin` 同名分支一致） |
| 未提交修改 | **0 个**（审计开始时；本文件写入后新增 1 个未跟踪文件） |
| 未推送提交 | **0 个** |

Worktree 清单（同一仓库的 5 个检出）：

| 路径 | HEAD | 分支 |
| --- | --- | --- |
| `<repo>` | `776a9a5` | `codex/v3.2.6.1-date-verification` |
| `<repo-v327>` | `187f4ad` | `codex/v3.2.7-save-identity` |
| `<repo-v3272>` | `31b7f1a` | `codex/v3.2.7.2-save-identity-e2e` |
| `<repo-v3273>` | `7628c3c` | `codex/v3.2.7.3-write-safety` |
| `<repo-v3274>` | `906868d` | `codex/v3.2.7.4-runtime-closure` |

最近 10 个提交：

```
906868d docs(v3.2.7.5): record full history rewrite and old-to-new commit mapping
86521e6 docs(v3.2.7.5): update hashes after full evidence sanitization
ae62a38 docs(v3.2.7.5): record A/B/A evidence sanitization
f3661d7 docs(v3.2.7.5): correct Agent transport error wording
18b6f72 docs(v3.2.7.5): record acceptance commit hash
ecc6317 feat(v3.2.7.5): complete protocol-level C/D/E acceptance and evidence
8c6fb4b checkpoint(v3.2.7.5): preserve D-01 fix tests and C/D/E runtime acceptance tools
91e9329 wip: preserve D-01 fix + round-2 A/B/A real acceptance evidence before C/D/E completion
f8e69f5 docs(v3.2.7.4): record PR #9 link in final report
0306433 feat(v3.2.7.4): runtime closure, worker cancellation and operation idempotency
```

## 2. 与 GitHub 远程对比（已重新 fetch）

| 项 | 值 |
| --- | --- |
| `origin/main` 真实 SHA | `89ac15758ca91b72e4091981c326d29db2d83b5f` |
| `origin/codex/v3.2.7.4-runtime-closure` | `906868d`（与本地一致） |
| ahead / behind（`origin/main...HEAD`） | **8 ahead / 1 behind** |
| 未推送提交 | 0 |
| 其它开发分支 | 远端共 26 个分支（`git branch -r` 另含 `origin/HEAD`） |
| V3.2.7.5 PR | **不存在**（PR #9 已 closed，针对 V3.2.7.4） |
| 本地 `main` | `187f4ad`（陈旧，仅本地；`origin/main` 已更新为 `89ac157`） |

> behind 的 1 个提交就是 main 上的合并提交 `89ac157 Merge pull request #9`，不是新内容；分支本身已包含其全部代码树。

## 3. 已完成代码（相对 `origin/main`：59 个文件，+4339 / −165）

非文档类变更：

| 分组 | 文件 |
| --- | --- |
| 后端 D-01 | `backend/app/api/routes_core.py`、`backend/app/schemas.py`、`backend/tests/test_saves_resolve.py` |
| 后端 C/D/E | `backend/app/ingestion/importer.py`（按存档写 `backend_restarted`） |
| Agent D-01 | `desktop-agent/ScoutMind.Agent/{AgentApplication,BackendClient,ReaderRunner,SaveIdentityGate,SaveIdentitySync}.cs`、`SaveIdentitySyncTests.cs` |
| Reader D-01 | `live-reader/ScoutMind.FMReader/Discovery/SaveIdentityModels.cs`、`Engine/FmSaveIdentityDiagnostics.cs`、`SaveIdentityTests.cs` |
| 验收工具 | `tools/runtime-acceptance/{backend_harness,verify_network_recovery,verify_cancel_two_process,verify_backend_restart_recovery}.py`、`collect_evidence.ps1` |

## 4. D-01 修复证据

问题：真实切换存档时污染同一 `fm_save`（第 1 轮真实验收 FAIL）。

| # | 位置 | 修复 |
| --- | --- | --- |
| 1 | `SaveIdentityModels.cs` | 自动快照开关改读 `SCOUTMIND_AUTOMATIC_SNAPSHOT`；`SnapshotEligible` 仅 `verified` 为真；歧义时用用户已确认指纹定位 |
| 2 | `FmSaveIdentityDiagnostics.cs` | `--verify` 允许从 `candidate`/`conflict` 显式切换确认 |
| 3 | `routes_core.py` | 新增 `POST /saves/resolve`，按指纹 find-or-create 并激活 `fm_save` |
| 4 | `SaveIdentitySync.cs` | 先解析 `save_id`，注册身份/会话、上传全部携带 `save_id` |
| 5 | `AgentApplication.cs` | `scan --sync` 走同一身份链路，携带 `save_id` + `operation_id` |

回归测试：`backend/tests/test_saves_resolve.py`、`desktop-agent/tests/ScoutMind.Agent.Tests/SaveIdentitySyncTests.cs`、`live-reader/tests/ScoutMind.FMReader.Tests/SaveIdentityTests.cs`。

## 5. A/B/A 真实 FM27 验收证据

证据目录：`docs/evidence/v3.2.7.4/runtime-rerun-20261125/`（第 2 轮，修复后）与 `runtime-manual/`（第 1 轮）。

| 检查 | 观测 |
| --- | --- |
| 执行时间/环境 | `environment.json` 含 `executed_at`、`operator`、`repo_branch`、`base_commit`、`game`、`backend`、`saves`、`commands` |
| 存档 A | `<save-A>.fm`，指纹 `si:v1:file:ab0bd795…`，游戏内日期 `2026-08-21` |
| 存档 B | `<save-B>.fm`，指纹 `si:v1:file:b887415a…`，游戏内日期 `2026-02-03` |
| 显式 `--verify` | 每次切换均执行 `save-identity --verify --save-file`，结果 `verified` / `kind=user_confirmed` |
| 身份消歧 | 无 `--save-file` 的 `--diagnostics` 返回 `verified`、`ambiguous=false` |
| 隔离 | B → `save_id=1`，A → 新建 `save_id=2` 且 B 置 `is_active=false`；各自 `identity_id`、`session_id` 独立 |
| 数据量 | B：`player_count=18,614`、快照 37,228；A：18,614 / 18,614（A→B→A 后无跨存档累加） |
| 审计链 | `registered` → `session_created` → `worker_started` → `write_accepted` |

真伪区分：A/B/A 为**真实 FM27 人工验收**；C/D/E 为**协议级真实进程验收**（`real_fm27=false`），两者在文档中已分开标注。

## 6. C / D / E 状态

| 场景 | 脚本 | run_id | 检查 | 结果 | 真实 FM27 子场景 |
| --- | --- | --- | --- | --- | --- |
| C 断网恢复 | `verify_network_recovery.py` | `0e520c00` | 14 | PASS | NOT_RUN（真实 Agent 断网） |
| D 取消任务 | `verify_cancel_two_process.py` | `289042f3` | 7 | PASS（单后端 + 独立客户端进程） | NOT_RUN（跨后端进程） |
| E 重启恢复 | `verify_backend_restart_recovery.py` | `144df52e` | 14 | PASS（硬杀后端进程） | NOT_RUN（Agent 重启） |

整体验收：**PARTIAL**（A/B/A PASS；C/D/E 协议级 PASS，真实 Agent 子场景 NOT_RUN）。

## 7. 多进程 Worker 安全审计

审计文件：`backend/app/ingestion/cancellation.py`、`backend/app/ingestion/importer.py`、`backend/app/api/routes_core.py`、`backend/app/models.py`、`alembic/versions/b5d9c2e7f4a1_v3274_worker_cancellation.py`。

| 问题 | 结论 | 依据 |
| --- | --- | --- |
| 1. 进程 A 的 Worker 能否感知进程 B 的取消？ | **运行中不能** | `_check_cancel()` / 提交前检查只调用 `cancellation.is_requested()`，其底层是**进程内** `threading.Event` 字典；跨进程只写 DB。仅在任务仍为 `queued`（取消先于认领，`_claim_job` 的条件更新会失败并读回 `cancelled`）时可生效 |
| 2. 取消状态是否持久化？ | **是** | `ImportJob.status`（`cancel_requested`/`cancelled`）、`cancel_requested_at`、`cancelled_at`，并写 `worker_cancel_requested` / `worker_cancelled` 审计 |
| 3. Worker 重启后能否恢复？ | **是** | `recover_interrupted_imports()`：`running`/`queued` → `failed`，`cancel_requested` → `cancelled`，写 `worker_recovered`，并按存档写 `backend_restarted` |
| 4. 取消与最终提交是否跨进程竞态保护？ | **不完整** | 认领阶段有条件更新（`WHERE status='queued'`）；但最终提交是 ORM 赋值 `job.status = outcome.status`（`_apply` 末尾）后直接 `commit()`，**没有** `WHERE status='running'` 守卫。另一进程写入的 `cancel_requested` 可能被覆盖为 `succeeded` |
| 5. 是否存在旧 Worker 延迟提交？ | **部分防护** | `WriteFence`（存档 `generation`）能拒绝旧代次写入；但同一代次内、取消已落库的旧 Worker 不会被拦截。文档已声明单进程部署假设（`cancellation.py` 文件头与 `uploads.import_slot` 进程内限流一致） |

**审计结论（基线 `906868d`）：多进程取消不得标记 PASS。** 当前实现是「单后端进程内取消 + 数据库状态可见」，跨进程取消仅能保证：排队阶段可取消、运行阶段由重启恢复兜底；运行中的跨进程取消不会被 Worker 及时响应。本轮已做最小加固，见 §11。

## 8. 与远程 main 的差异

- `origin/main` = `89ac157`（V3.2.7.4 内容）；分支 = `906868d`。
- 差异规模：59 个文件，+4339 / −165；其中 40 个为 `docs/evidence/**` 文档与证据，19 个为代码/测试/工具。
- 差异性质：D-01 修复 + A/B/A 证据 + C/D/E 工具与协议级证据 + 文档；**未修改数据库迁移**（无新增迁移文件）。
- 未触碰：`main` 不含 V3.2.7.5 任何内容，分支未合并回 main。

## 9. 下一步最小修改范围

按优先级，均为**可选**，且本轮未执行：

1. **保持现状即可发布分支**：分支已推送、工作区干净、证据齐全；只需决定是否创建 V3.2.7.5 PR（未创建）。
2. **补真实子场景（不改代码）**：按 `REAL-FM27-ACCEPTANCE.md` §9 执行 C/E 的真实 Agent 步骤与 D 的跨后端进程步骤，回填结果后把 PARTIAL 收敛。
3. **若要真正支持多进程取消（改代码，建议单独立项）**：
   - `_check_cancel()` 增加按存档读取 `ImportJob.status` 的检查（限频，避免每 200 行打一次库）；
   - 最终提交改为条件更新：`UPDATE import_jobs SET status=:final WHERE id=:id AND status='running'`，`rowcount=0` 时回滚业务写入并落 `cancelled`；
   - 新增跨进程测试（两个独立后端进程共享同一 SQLite/PostgreSQL）。
   - **状态：已按此实现（本地未提交），见 §11。**
4. **提交本审计文件前**：确认不含本机路径（本文件已使用 `<repo>` / `<save-A>` 等占位符）。

## 10. 本次审计执行的命令与未做的事

已执行（只读）：`git rev-parse`、`git status --short --branch`、`git log -10 --oneline`、`git worktree list`、`git branch -vv`、`git fetch origin --prune`、`git rev-list --left-right --count`、`git diff --stat/--name-only origin/main...HEAD`、GitHub PR API 查询、源码与证据 JSON 阅读。

未执行：`git push`、`git push --force`、`git reset --hard`、`git clean -fd`、创建 PR、合并 main、发布 Release、删除分支、覆盖工作区。

## 11. 本轮最小代码加固（本地未提交）

针对 §7 的两个缺口做了最小改动，未改变既有 C/D/E 证据与验收结论：

| 文件 | 变更 |
| --- | --- |
| `backend/app/ingestion/importer.py` | ① 检查点（每 200 行）除进程内事件外，额外用**独立连接**读取已提交的任务状态；② 新增 `_cancel_requested_in_db()`（读取失败按“未取消”处理，由终态守卫兜底）；③ 终态写入改为 `UPDATE ... WHERE id=? AND status='running'`，`rowcount != 1` 时回滚全部业务写入并落 `cancelled`（reason `cancel_requested_cross_process`）；④ `_apply()` 不再直接赋值 `job.status`，避免绕过守卫 |
| `backend/app/ingestion/cancellation.py` | 更新模块说明：进程内事件仍是快速路径，跨进程由数据库状态 + 终态守卫兜底 |
| `backend/tests/test_worker_cancellation.py` | 新增 2 个用例：另一会话写入 `cancel_requested` 后终态守卫必须回滚；安全检查点必须读到数据库中的取消状态 |

验证：

| 命令 | 结果 |
| --- | --- |
| `pytest tests/test_worker_cancellation.py -q` | 7 passed |
| `pytest tests/test_import_jobs_api.py tests/test_import_transaction_safety.py tests/test_import_concurrency.py tests/test_unified_import_identity.py tests/test_saves_resolve.py -q` | 27 passed |
| `pytest -q`（全量） | 581 项通过、0 failed（排除 1 项，见下） |
| `git diff --check` | 退出码 0 |

- 排除项：`tests/test_fmscout_real_data.py::test_real_sample_converts_cleanly[real_sample_01.json]`。原因是**本地未被 Git 跟踪**的数据文件与 manifest 记录的 sha256 不一致（`8c7915…` vs `5dc926…`），与本次改动无关。
- 仍未验证（保持 NOT_RUN）：两个独立后端进程共享同一数据库的端到端取消；SQLite 单写者模型下取消写请求会与导入写事务串行，需在 PostgreSQL 或 WAL 模式下单独验证。

结论：多进程取消从“运行中不可感知”提升为“检查点可感知 + 终态不可被覆盖”，但**仍不足以标记多进程取消 PASS**；整体验收维持 **PARTIAL**。
