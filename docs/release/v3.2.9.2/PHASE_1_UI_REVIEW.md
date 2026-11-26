# Phase 1：PR #15 UI/UX 审查与整合（V3.2.9.2）

- 审查对象：PR #15 `ScoutMind FM27 — Futuristic UI/UX Design System & Dashboard Upgrade`
- Head：`feature/scoutmind-futuristic-ui-ux` @ `6b622b2eea6079b619c2de5bff7ca90db9e99f77`
- Base：`main` @ `33882bc`
- 审查方式：独立 worktree `temp_20261124_02/pr15-review` 只读代码审查 + 本地构建 + 本地 Playwright
- 结论：**可以准备合并，但本轮不合并，等待用户授权**

## 1. 变更范围核验

PR #15 共 42 个文件，全部为前端与文档：

| 类别 | 文件 |
| --- | --- |
| 前端入口 | `frontend/index.html`、`frontend/src/App.vue`、`frontend/src/router/index.ts` |
| 样式 | `frontend/src/styles/tokens.css`、`base.css`、`element.css` |
| 共享组件（11） | `AttributeBar`、`ChartCard`、`CoverageBar`、`DataTable`、`EmptyState`、`KpiCard`、`PageHeader`、`ScoreBadge`、`SectionCard`、`StatHeader`、`utils/chart.ts` |
| 页面（14） | `DashboardView`、`SquadView`、`PlayerDetailView`、`PlayersView`、`RecruitmentView`、`TransfersView`、`ScoutingView`、`DevelopmentView`、`PerformanceView`、`AgentView`、`PlayerIdentityCenterView` |
| 文档 | `docs/ui-ux/` 8 份报告 + 9 张截图 |

确认未触碰：`backend/**`、`alembic` migration、`live-reader/**`、`desktop-agent/**`、`frontend/src/api/identityCenter.ts`、`frontend/src/types/identityCenter.ts`。Dashboard 新增查询全部为只读 GET。

## 2. API 契约核验（前端 ↔ 后端）

| 前端调用 | 路径 | 后端实现 | 结果 |
| --- | --- | --- | --- |
| `analytics.ts` `getOverview` | `GET /analytics/overview` | `routes_ops.py:28` | 一致 |
| `imports.ts` `listImports` | `GET /imports` | `routes_core.py:380` | 一致 |
| `transfers.ts` `getTransferStats` | `GET /transfers/stats` | `routes_transfers.py:129` | 一致 |
| `squad.ts` `getSquadOverview` | `GET /squad/overview` | `routes_squad.py:31` | 一致 |
| `players.ts` `listPlayers` | `GET /players` | `routes_players.py:32` | 一致 |
| `agent.ts` 四个调用 | `/agent/conversations*` | `routes_agent.py:42/79/98/130` | 一致 |
| `captures.ts` | `GET /captures/summary` | `routes_capture.py:134` | 一致 |
| `identityCenter.ts` | `GET /identity/center/summary` | `routes_identity_center.py` | 未改动 |
| `deals.ts` | `GET /transfers/investment` | `routes_transfers.py:270` | 一致 |
| `saves.ts` | `GET /saves/{id}/summary` | `routes_core.py:230` | 一致 |
| `watchlist.ts` | `GET /alerts` | `routes_players.py` | 一致 |

所有路由都已在 `backend/app/main.py:142-169` 以 `/api/v1` 前缀注册。未发现前端调用不存在的接口。

## 3. 页面健壮性

- 所有 view 的加载函数使用 `try/catch`，失败时写入 `error` 并清空数据，模板有 `ErrorState` / `LoadingBlock` / `EmptyState` 三个分支（抽查 Dashboard、Squad、Agent、Transfers、Data、Governance、PlayerIdentityCenter）。
- `client.ts:136-186` 将所有传输异常归一化为 `ApiError`，401 通过 `unauthorizedListeners` 统一处理。
- 深层字段访问点已逐一对照后端结构：
  - `DashboardView.vue` 的 `contracts` / `succession` / `weakness` 与 `SquadView.vue` 的 `profile` 均来自 `backend/app/analytics/squad.py:307-373`，空数据分支也返回完整键（`contracts`、`weakness: []`、`succession: []`、`profile.weights`），不会因缺字段崩溃。
  - `DashboardView.vue` 的 `row.warnings.length` 对应 `routes_core.py:723-740` `_job_payload`，恒返回 `warnings` 数组。
- 未发现 `any` / `as any` 类型绕过；Pinia 使用一致（各页统一 `useSessionStore()`，球员/转会走各自 store）。

## 4. 导航

`router/index.ts` 17 条路由（含 `/:pathMatch(.*)*` 回退 `/`）与 `App.vue` NAV_GROUPS 16 个菜单项一一对应；`player-detail` 通过 `activeKey` 映射回 `/players`；Dashboard 快捷入口链接均存在。无死链。

## 5. 无障碍

| 项 | 结果 |
| --- | --- |
| skip-link | 有（`App.vue:213`） |
| 移动抽屉 Escape 关闭 | 有（`App.vue:174-177`） |
| 路由切换关闭抽屉 | 有（`App.vue:194-199`） |
| 图标按钮可访问名 | 有（汉堡、刷新、关闭等均带 `aria-label`） |
| `aria-current` 导航态 | 有（`App.vue:237`） |
| 表格横向滚动 | 有（`DataTable.vue:312`、`GovernanceView.vue:469`、`AgentView.vue:831`） |
| 表格标题 | 有（`DataTable.vue:222` `sm-sr-only` caption） |
| 进度条语义 | 有（`CoverageBar.vue:38-40` `role="progressbar"`） |
| 对话流播报 | 有（`AgentView.vue:292` `role="log" aria-live="polite"`） |
| 减少动效 | 有（`base.css:373`、`tokens.css:204` `prefers-reduced-motion`） |
| 移动抽屉 Focus Trap | **未实现**（仅 Escape + scrim 关闭） |
| 自动化 axe 扫描 | **NOT_RUN**（仓库无 axe 依赖/用例） |

判断：Focus Trap 缺失属 MINOR。抽屉为侧边导航而非模态对话框，Escape 可关闭、页面主体仍可用；Element Plus `el-dialog` 自带焦点管理。按任务书"不为了零告警大规模改动无关组件"，本轮不修改。

## 6. 响应式

- 全站断点：`1180px`（侧栏收窄）、`1100px`、`768px`、`640px`、`480px`、`420px`，覆盖要求的 1024 / 768 / 390。
- 主内容区 `overflow-x: hidden`（`App.vue:799-801`），装饰光晕 `width: 420px` 位于 `overflow: hidden` 容器内（`DashboardView.vue:633/646`），不产生页面级横向溢出。
- PR 自带截图覆盖：1920（Dashboard）、1440（Squad / Identity Center）、1366（Recruitment）、1024（Dashboard）、768（Agent）、390（Dashboard / Squad / Identity Center）。缺口：并非每个页面在每个宽度都有截图。

## 7. 本地验证结果

| 项目 | 命令 | 结果 |
| --- | --- | --- |
| 依赖安装 | `npm ci`（pr15-review/frontend） | PASS（110 包） |
| 类型检查 + 生产构建 | `npm run build` | **PASS**（`vue-tsc --noEmit` + `vite build`，8.52s） |
| Playwright 端到端 | `npm run test:e2e` | **PASS 9/9**（governance 2 + unresolved 7，5.9s） |
| CI（GitHub Actions） | run `45814296148` | **SUCCESS 6/6** |

## 8. 问题清单

| 级别 | 位置 | 问题 | 影响 | 发布前必修 |
| --- | --- | --- | --- | --- |
| MINOR | `App.vue` 移动抽屉 | 无 Focus Trap | 键盘用户 Tab 可能离开抽屉 | 否 |
| MINOR | `DashboardView.vue` / `SquadView.vue` 深层字段 | 依赖后端恒返回固定键，未全部可选链 | 当前后端契约下安全；未来字段变更才可能报错 | 否 |
| INFO | 全站 | 无 axe 自动化无障碍用例 | 无障碍只能人工/代码审查 | 否（标记 NOT_RUN） |

**无 BLOCKER，无 MAJOR。**

## 9. PR #15 合并门禁

| 条件 | 状态 |
| --- | --- |
| 代码审查通过 | PASS |
| 最新 CI 全部通过 | PASS（6/6） |
| 无严重未解决 Review | PASS（0 条 review / 0 thread） |
| 无合并冲突 | PASS（MERGEABLE / CLEAN） |
| 关键页面测试通过 | PASS（构建 + 9 条 e2e） |
| 无关键 API 回归 | PASS（未改后端，契约逐条核对） |
| 身份治理测试通过 | PASS（CI `Upload / identity / agent isolation regressions`） |
| 用户授权 | **待授权** |

结论：PR #15 已具备合并条件，按任务书要求**不自动合并**，等待用户明确授权后执行合并。

状态：**PASS（等待合并授权）**
