# Phase 0：GitHub 仓库安全审计（V3.2.9.2）

- 审计时间：2026-11-26（Asia/Shanghai）
- 执行方式：实时访问 GitHub（`gh` CLI + `git fetch origin`），未使用历史会话 SHA 作为基线
- 审计分支：`release/v3.2.9.2-stabilization`（从 `origin/main` 新建）
- 本地 worktree：`C:\Users\hukun\Documents\Trae-CN\temp_20261124_02\scoutmind-v3281`

## 1. 仓库基线

| 项目 | 值 |
| --- | --- |
| Remote | `https://github.com/hukun2005/scoutmind-fm27.git` |
| 最新 `origin/main` SHA | `33882bc4e4c93775619b930e8994dbac7a21d030` |
| main 最近一次合并 | PR #14 `feature/v3.2.9.2-livereader-save-switch-safety`（2026-11-26 11:42Z） |
| 本地工作区状态 | 干净（`git status --porcelain` 输出为空） |
| 本地分支 | `release/v3.2.9.2-stabilization`（本轮新建，跟踪 `origin/main`） |
| 旧功能分支 | `feature/v3.2.9.2-livereader-save-switch-safety` 已完全合入 main（`origin/main..HEAD` 为空，`git diff main..feature` 为空），保留未删除 |

最近提交（main）：

```
33882bc Merge pull request #14 from hukun2005/feature/v3.2.9.2-livereader-save-switch-safety
b6fc223 docs(v3292): record real FM27 A/B/A save switch acceptance
c3d0eaa docs(v3292): record CI results for 6/6 jobs
e8b62eb fix(v3292): serialize verified ledger writes and cover concurrent commits
8768bd9 docs(v3292): add final acceptance report
2bd6c73 docs(v3292): add acceptance evidence and identity scan benchmark
b6b33dc feat(v3292): add review optimistic locking, complete same-name candidates and evidence-based transfer links
acedcfd feat(v3292): make save switching safe and bind verified lifecycle to generation
```

## 2. 远程分支

远程分支共 37 个，其中 `main` 为唯一发布分支；历史 `codex/*` 与 `feature/*` 分支均保留（本轮不删除）。

本轮新增/相关：

- `origin/main` — 发布基线
- `origin/feature/scoutmind-futuristic-ui-ux` — PR #15 head（本轮 fetch 首次发现）
- `origin/feature/v3.2.9.2-livereader-save-switch-safety` — PR #14 head（已合入，保留）

## 3. 开放 PR

| PR | 标题 | head → base | 状态 | 可合并 | CI |
| --- | --- | --- | --- | --- | --- |
| #15 | ScoutMind FM27 — Futuristic UI/UX Design System & Dashboard Upgrade | `feature/scoutmind-futuristic-ui-ux` → `main` | OPEN，非 Draft | MERGEABLE / CLEAN | 6/6 成功 |
| #6 | feat(v3.2.6): heuristic world-date resolution + RC documentation | `codex/v3.2.6-release-candidate` → `codex/v3.2.5.1-memscan-module-resolution` | OPEN | MERGEABLE | 旧栈，未纳入本次发布 |
| #5 | fix(reader): module bounds + static-root date tooling (V3.2.5.1) | `codex/v3.2.5.1-...` → `codex/v3.2.5-native-intelligence-release` | OPEN | MERGEABLE | 旧栈 |
| #4 | feat(v3.2.5): read-only date candidate discovery (phase 1) | `codex/v3.2.5-...` → `codex/v3.2.4-release-hardening` | OPEN | MERGEABLE | 旧栈 |
| #3 | feat(v3.2.4): unresolved real chain, contract calibration and date root cause | `codex/v3.2.4-...` → `codex/v3.2.3-nightly` | OPEN | MERGEABLE | 旧栈 |
| #2 | feat(v3.2.3): reader diagnostics, queue integrity and import recovery | `codex/v3.2.3-nightly` → `codex/v3.2.2.8-unresolved-identity` | OPEN | MERGEABLE | 旧栈 |

说明：#2–#6 是历史 `codex/*` 链式分支之间的 PR，目标分支都不是 `main`，不影响本次发布；本轮不合并、不关闭、不删除。

## 4. PR #15 状态详查

| 检查项 | 结果 |
| --- | --- |
| 是否仍开放 | 是（OPEN，非 Draft） |
| Head SHA | `6b622b2eea6079b619c2de5bff7ca90db9e99f77` |
| Base 分支 | `main`（正确） |
| CI | run `45814296148`，6/6 全部 SUCCESS：Backend、.NET readers and agent、Frontend、Playwright (governance)、PostgreSQL migration compatibility、Upload/identity/agent isolation regressions |
| 新增 Review | 0 条（`pulls/15/reviews` 返回空数组） |
| 未解决 Review Thread | 0 条（`pulls/15/comments` 为空） |
| 合并冲突 | 无（`mergeable=MERGEABLE`，`mergeStateStatus=CLEAN`） |
| 是否有未完成修改 | 无；head 分支工作已完成并已推送 |
| 与 main 兼容性 | 分支已合入 `origin/main`（commit `ebf8035` 合并 main），无落后提交 |
| 是否引入新 API/业务回归 | 未改动 `backend/**`、migration、LiveReader、Desktop Agent；`api/identityCenter.ts` 与 `types/identityCenter.ts` 未改动（PR #14 边界保持）；新增 Dashboard 查询为只读 |

改动范围（共 42 个文件，全部为前端 + 文档）：

- 前端（`frontend/src/**`）：`App.vue`、`router/index.ts`、`styles/{tokens,base,element}.css`、`utils/chart.ts`、11 个共享组件、14 个页面视图
- 文档（`docs/ui-ux/**`）：8 份设计与测试报告 + 9 张截图
- `frontend/index.html`

结论：PR #15 可以进入 Phase 1 代码级审查；**不合并**，等待用户授权。

## 5. CI 状态

| 分支/来源 | Run | 结论 |
| --- | --- | --- |
| `main` @ `33882bc` | `45813033668` | SUCCESS（6/6） |
| PR #15 @ `6b622b2` | `45814296148` | SUCCESS（6/6） |
| `main` @ PR #13 合并 | `45787728897` | SUCCESS |
| `main` @ 更早 | `45783067077` / `45770160842` / `45760515122` | SUCCESS |
| `main` @ `45781583030` | — | CANCELLED（同一分支后续 run 取代，非失败） |

无失败中的 main CI，无运行中的关键流水线。

## 6. Releases 与 Tags

- GitHub Releases：无（`gh release list` 为空）
- Git Tags：无（`git tag --list` 为空）

即当前仓库从未正式发布过任何版本，本次 V3.2.9.2 将是首个 Release。

## 7. 工作区与未提交修改

- `git status --porcelain`：空
- `git diff` / `git diff --cached`：空
- 无其它 Agent 的未提交改动需要保留

## 8. 已知问题（进入各 Phase 的输入）

1. **转会接口 `all_rows` 作用域**（Phase 2 复核）：任务书指出 `backend/app/api/routes_transfers.py` 中列表/统计接口可能存在变量作用域错误，需以 main 最新实现为准复核。
2. **缺少 Windows 一键发布工程**（Phase 4）：现有 `scripts/publish-windows.ps1` 只发布 Reader + Agent 两个 exe，没有整包目录、启动/停止/诊断/备份脚本、生产前端静态资源和后端启动封装。
3. **无 `docs/release/` 目录**（Phase 7）：发布文档需从零建立。
4. **README 版本信息滞后**：README 头部仍写 V3.2.7.4 状态，需在 Phase 7 统一到 V3.2.9.2。
5. **本机无 PostgreSQL**：PG migration 兼容性只能依赖 CI 作业验证（已绿）。
6. **本机无 `backend/.env`、无本地 `backend/data/scoutmind.db`**：干净环境验证需要用新建数据库完成。
7. **多存档自动解析返回 `AMBIGUOUS_SAVE_FILES`**：属既有预期行为，真实 A/B/A 已通过显式指定存档完成。

## 9. 发布阻塞项

| 阻塞项 | 级别 | 处理阶段 |
| --- | --- | --- |
| PR #15 合并需用户授权 | 硬阻塞（流程） | Phase 9 等待授权 |
| 转会接口作用域问题未复核 | 待定（可能 P0） | Phase 2 |
| Windows 发布包不存在 | 硬阻塞（交付） | Phase 4 / Phase 8 |
| 发布文档缺失 | 硬阻塞（交付） | Phase 7 |
| 正式 Release/Tag 未创建 | 硬阻塞（流程，需授权） | Phase 9 之后 |

## 10. 发布分支计划

- 基线：`origin/main` @ `33882bc`
- 工作分支：`release/v3.2.9.2-stabilization`（本轮创建）
- 规则：
  - 所有修复在本分支提交，按 Phase 分次 commit；
  - 每阶段结束跑相关测试并记录真实输出；
  - 阶段完成后推送分支并创建 PR（目标 `main`），**不自动合并**；
  - PR #15 单独审查，合并时机由用户决定；
  - 不修改已发布 migration，不删除测试、不降低断言。

## 11. 风险列表

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| PR #15 为大规模前端改动（App.vue +642/−132，SquadView +729/−249） | 视觉回归、页面白屏风险 | Phase 1 逐个组件/页面审查 + 生产构建 + Playwright 现有用例 |
| 无 Releases/Tags，首次发布流程未经演练 | 发布步骤出错 | Phase 8 先产出 RC ZIP + SHA256，Phase 9 只做 Release 草稿 |
| 本机无 PostgreSQL | 无法本地验证 PG migration | 以 CI `PostgreSQL migration compatibility` 为证据，标注 NOT_RUN(本地) |
| 真实 FM27 仅单机单版本（build 26620374） | 兼容性覆盖有限 | Phase 5 明确标注已验证/未验证边界，不伪造结论 |
| 前端依赖 `npm install` 体积大 | 发布包过大 | 发布包只带 `dist/` 静态产物，不带 `node_modules` |
| Python 运行时需外部安装 | 用户环境差异 | Phase 4 提供 `Check-Environment.ps1` 明确依赖与提示 |

## 12. Phase 0 结论

- 基线明确：`main` @ `33882bc`，工作区干净，CI 全绿，无 Releases/Tags。
- PR #15 处于可审查、可合并状态（CI 绿、无冲突、无未解决 Review），但**按任务书要求等待用户授权后合并**。
- 无阻塞 Phase 1 的问题，允许进入 Phase 1。

状态：**PASS**
