# V3.2.7.3 Phase 0 — 仓库审计

审计时间：2026-11-25（Asia/Shanghai）
审计对象：`hukun2005/ScoutMind`，`origin/main` = `6aaaa31`（PR #7 合并提交）

## 1. Git 状态（执行前）

```text
git branch --show-current        codex/v3.2.7.3-write-safety
git log -1 origin/main           6aaaa31ca4d1b0c362eb34a0099529b903cf17df
                                 6aaaa31 Merge pull request #7 from hukun2005/codex/v3.2.7.2-save-identity-e2e
git worktree list
  temp_20261124_02/repo            776a9a5 [codex/v3.2.6.1-date-verification]
  temp_20261124_02/scoutmind-v3.2.7   187f4ad [codex/v3.2.7-save-identity]
  temp_20261124_02/scoutmind-v3.2.7.2 31b7f1a [codex/v3.2.7.2-save-identity-e2e]
  temp_20261124_02/scoutmind-v3273    6aaaa31 [codex/v3.2.7.3-write-safety]
```

* 新分支/worktree 从 `origin/main` 建立：`git worktree add ../scoutmind-v3273 -b codex/v3.2.7.3-write-safety origin/main`。
* 未直接修改 `main`；未删除任何分支；未创建 Release。
* PR #7 已于 2026-11-24T17:06Z 合并（`6aaaa31`），这是用户显式指令「合并到 main 分支」的结果，非本任务自动合并。

## 2. 现有写入链路（审计结论）

| 层级 | 文件 | 现状 |
|---|---|---|
| 身份注册/验证 | `backend/app/services/save_identity.py` | 证据封顶、幂等注册、verified 判定、审计（只追加） |
| 会话 | 同上 | `start_session` / `heartbeat` / `invalidate`；心跳 120s 超时 |
| 导入事务 | `backend/app/ingestion/importer.py` | `_begin_job` 单独提交 running；`_apply` 写数据；`final_guard` 独立连接复核；最后 commit |
| HTTP 入口 | `backend/app/api/routes_core.py` | `/imports/scan`、`/imports/transfers`、`/imports/squad-csv` |
| 采集入口 | `backend/app/api/routes_capture.py` | `POST/PATCH /captures` |
| Agent | `desktop-agent/ScoutMind.Agent/*` | auto 走 `EnsureAsync`；手动 sync 只传文件 |

## 3. 审计发现（摘要，详见 PR7-SECURITY-AUDIT.md）

* **P0**：`final_guard` 与业务提交不是同一个事务，存在“检查通过 → 切换 → 提交”的竞态。
* **P0**：会话失效没有推进任何代次，切换后在途 Worker 仍可提交。
* **P0**：`/imports/transfers`、`/imports/squad-csv`、手动 sync/CLI 完全不带身份上下文。
* **P1**：没有 operation 级幂等；并发重复提交可能双写。
* **P1**：心跳过期只在写请求入口判定，导入进行中不再检查。
* **P2**：`ensure_attributes` / 俱乐部创建在真实并发下触发唯一约束冲突（新并发测试实测复现）。
* **P3**：诊断接口不暴露当前写入代次。

## 4. 环境与限制

| 项 | 结果 |
|---|---|
| Python | 3.13（本机） |
| SQLite | 支持，用于全部本地自动化测试 |
| PostgreSQL 16 | NOT_RUN（本机无 PG16 实例）；由 CI workflow 覆盖 |
| 真实 FM27 游戏 | NOT_RUN（无游戏环境） |

本文件中的结论全部来自真实代码与真实执行输出；无环境项一律标注 NOT_RUN，不写 PASS。
