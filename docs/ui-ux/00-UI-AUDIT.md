# ScoutMind FM27 — 前端 UI/UX 审计（Phase 0）

- 审计时间：2026-11-26
- 基线提交：`origin/main@24beaba`（Merge pull request #13）
- 工作分支：`feature/scoutmind-futuristic-ui-ux`
- 工作目录：独立 worktree（基于 `origin/main` 新建，未合并 main、未触碰其它 agent 分支）
- 审计方式：静态阅读 + 本地运行（后端 `127.0.0.1:8000`，前端 `127.0.0.1:5173`）

## 1. Git 与协作边界

| 项目 | 审计结果 |
| --- | --- |
| 本地/远程分支 | 24 个远程分支；本次仅新增 `feature/scoutmind-futuristic-ui-ux` |
| `git status`（main worktree） | 干净，无未提交修改 |
| 其它 agent worktree | 6 个（v3.2.2.8 / v3.2.3 / v3.2.4 / v3.2.5 / v3.2.5.1 / v3.2.6），本次未触碰 |
| PR #14 | `#14 V3.2.9.2 — LiveReader Save Switch Safety & Verified Lifecycle`，状态 OPEN，目标 `main`，`mergeable=MERGEABLE` |
| PR #14 与 main 的关系 | `merge-base(origin/main, PR14) == origin/main == 24beaba`，PR #14 不含 main 之外的提交 |
| PR #14 前端改动 | `frontend/src/api/identityCenter.ts`、`frontend/src/types/identityCenter.ts`、`frontend/src/views/PlayerIdentityCenterView.vue`（3 个文件，共 21 行） |

**结论（已随 PR #14 合并更新）**：PR #14 已于 2026-11-26 合并进 `main`（`33882bc`），
本分支已同步 `main`，原先冻结的三个文件不再受限。
冻结期间未产生任何改动，因此没有与 PR #14 的文本冲突；合并后新增 Phase 7，
对 `PlayerIdentityCenterView.vue` 做纯视觉升级，`Verified / Conflict / Ambiguous` 等
业务状态含义、审核接口与决策流程均未改变。`api/identityCenter.ts` 与
`types/identityCenter.ts` 仍未改动。

兼容性修复：升级 `PageHeader` / `EmptyState` 时新增了 `eyebrow` / `description` 等属性，
审计中发现 3 个未改版页面仍在用旧的 `subtitle` / `hint`，已保留同名兼容属性，
避免说明文案丢失（详见 `07-FINAL-REPORT.md`）。

## 2. 技术栈（保持不动）

| 层 | 现状 |
| --- | --- |
| 框架 | Vue 3.5（`<script setup lang="ts">`，Composition API） |
| 构建 | Vite 6 + `vue-tsc --noEmit` |
| 路由 | Vue Router 4，`createWebHistory`，17 条路由，全部懒加载 |
| 状态 | Pinia 2（`session` / `players` / `transfers`） |
| UI 组件 | Element Plus 2.9（深色变量覆盖） |
| 图表 | ECharts 5.6，自封装 `EChart.vue`（canvas + ResizeObserver + aria） |
| 样式 | 原生 CSS + CSS 变量（`tokens.css` / `base.css` / `element.css` + 组件 scoped） |
| 质量工具 | Playwright（2 个 e2e spec）；无 ESLint / 单测框架 |

本次不引入任何新 UI 框架、图表库或 CSS 预处理器。

## 3. 路由与页面清单

| 路由 | 视图 | 视图体积 | 本次处理 |
| --- | --- | --- | --- |
| `/` | `DashboardView` | 15.9 KB | Phase 3 重构为指挥中心 |
| `/squad` | `SquadView` | 29.2 KB | Phase 4 视觉升级 |
| `/recruitment` | `RecruitmentView` | 18.8 KB | Phase 5 视觉升级 |
| `/transfers` | `TransfersView` | 59.0 KB | Phase 5 视觉升级（不改数据语义） |
| `/development` | `DevelopmentView` | 11.9 KB | Phase 4 统一视觉 |
| `/performance` | `PerformanceView` | 13.9 KB | Phase 4 统一视觉 |
| `/agent` | `AgentView` | 28.8 KB | Phase 6 视觉升级 |
| `/players` | `PlayersView` | 14.9 KB | Phase 4 统一视觉 |
| `/players/:id` | `PlayerDetailView` | 55.9 KB | Phase 4 视觉升级 |
| `/scouting` | `ScoutingView` | 22.9 KB | Phase 5 统一视觉 |
| `/watchlist` | `WatchlistView` | 18.8 KB | 统一视觉（不改业务） |
| `/data` | `DataView` | 46.9 KB | 统一视觉（不改业务） |
| `/governance` | `GovernanceView` | 23.1 KB | 统一视觉（不改业务） |
| `/identity` | `IdentityResolutionView` | 10.0 KB | 统一视觉（不改业务） |
| `/identity-center` | `PlayerIdentityCenterView` | 14.4 KB | **冻结**（PR #14） |
| `/save-identity` | `SaveIdentityView` | 23.1 KB | 统一视觉（不改业务） |
| `/unresolved` | `UnresolvedPlayerView` | 19.5 KB | 统一视觉（不改业务） |

## 4. 现有设计系统盘点

### 4.1 已有资产

- `styles/tokens.css`：8px 间距网格、深色单一强调色（`#4d8dff`）、字号/圆角/阴影/布局变量，
  并在 `html.dark` 上覆盖 Element Plus 的 CSS 变量。
- `styles/base.css`：reset、滚动条、聚焦环、`.sm-page` / `.sm-grid` / `.sm-row` 等布局原语、
  排版工具类、`.sm-sr-only`。
- `styles/element.css`：卡片、按钮、输入、表格、弹窗的密度与边框覆盖。
- 18 个公共组件，覆盖 KPI、区块、图表容器、表格、空状态、错误态、徽标、加载、图标。

### 4.2 主要问题

| # | 问题 | 影响 |
| --- | --- | --- |
| D-1 | 只有单一蓝色强调色，无渐变、无辅助色语义，缺少「足球情报 / AI 指挥中心」识别度 | 所有页面观感偏通用后台 |
| D-2 | 表面层级只有 4 档纯色，缺少玻璃层、发光边框、环境光 | 缺少未来感与空间感 |
| D-3 | 阴影只有 2 档且偏黑，无悬浮/聚焦光晕 | 卡片层级弱 |
| D-4 | 无动效 Token，无 `prefers-reduced-motion` 支持 | 无法安全地做微交互 |
| D-5 | 圆角仅 4/6/10，卡片在 1440 以上显得生硬 | 高级 SaaS 质感不足 |
| D-6 | 图表颜色硬编码在 `utils/chart.ts` 与部分视图（如 `DevelopmentView`） | 换色无法一处生效 |
| D-7 | `index.html` 的 `meta color-scheme` 写成 `light`，与深色主题矛盾 | 原生控件/滚动条在部分浏览器不协调 |
| D-8 | 导航固定 216px、1100px 以下直接变图标条，平板/手机没有抽屉式导航 | 768 / 390 宽度下体验差 |
| D-9 | 无统一页面过渡、无悬停反馈规范、无骨架屏统一外观 | 交互缺乏连续感 |
| D-10 | 图表容器高度固定像素（216–268px），窄屏下比例失衡 | 移动端图表过扁或溢出 |

### 4.3 数据真实性约束（必须保持）

- 所有数值来自 API；`null` 显示 `—`，`0` 显示 `0`（`utils/format.ts` 的既定规则）。
- 空数据必须显示解释性 EmptyState（已有 `EmptyState` 的 `empty / insufficient / error` 三态）。
- 演示数据（`source=synthetic_fixture`）必须保留顶部 DemoBanner，禁止为了截图隐藏。
- AI 体育总监的答案与可靠性分类来自后端；前端不得生成或补写分析结论。

## 5. 图表现状

| 构建器 | 用途 | 主题方式 |
| --- | --- | --- |
| `buildTrendChart` | 概览：总身价 + CA 均值 | 硬编码 `TEXT_2/TEXT_3/BORDER` 常量 |
| `buildFeeHistogram` | 概览/转会：费用分布 | 同上 |
| `buildGrowthChart` | 球员详情：CA/PA/身价 | 同上 |
| `buildAppearanceChart` | 球员详情：出场 | 同上 |
| `buildRadarChart` | 球探/招募对比 | 同上 |

已有基础：深色轴标签、tooltip `confine`、图例统一、`animationDuration`、雷达图 0–100 归一。
缺口：无 Squad 六维雷达、无年龄分布图、无位置分布图、无图表入场动画、无 `prefers-reduced-motion` 降级。

## 6. 响应式与可访问性现状

- 断点只有 `1180px`（栅格降列）与 `1100px`（侧栏变图标条）。
- `sm-page` 使用 `max-width: 1680px` + 自动外边距，1920 下内容居中但两侧留白偏大。
- 表格在窄屏依赖横向滚动（Element Plus 默认），未做列优先级裁剪。
- 已有：全局 `:focus-visible` 2px 轮廓、表格行 `focus-visible`、图表 `role="img"` + `aria-label`、
  覆盖率 `role="progressbar"`、DemoBanner 文案。
- 缺口：导航抽屉无 `aria-expanded`/`Escape` 关闭；状态色（成功/警告/危险）在部分徽标里只靠颜色区分；
  无 `prefers-reduced-motion`；移动端无安全区适配。

## 7. 测试与构建基线

| 检查 | 基线 |
| --- | --- |
| `npm run build`（`vue-tsc --noEmit && vite build`） | 通过（改造前本地复跑） |
| Playwright | 2 个 spec：`governance.spec.ts`、`unresolved.spec.ts`（需要运行中的后端） |
| ESLint | 仓库未配置，仅做 `vue-tsc` 与人工规范检查 |
| 后端 | 本次不修改后端；回归以「页面 API 调用参数不变」为准 |

## 8. 本次改造策略

1. **优先改 Token 与公共层**：一处换肤，全部 17 个页面立即获得统一的新配色、圆角、字体与控件外观。
2. **外壳重做主视觉**：侧栏、顶栏、导航状态、移动抽屉，这是「指挥中心」第一印象。
3. **Dashboard 结构化重构**：信息层级从「若干卡片」变成「任务控制台」。
4. **分析页渐进增强**：只增加真实数据驱动的图表与视觉分区，不改查询参数、不改计算逻辑、不改字段含义。
5. **冻结身份中心**：只读研究，不做任何代码修改。
6. 每个阶段执行 `vue-tsc` + `vite build`，最后统一做响应式与可访问性回归。

## 9. 明确不做

- 不重写前端、不替换 Element Plus、不新增 UI 框架。
- 不修改后端、数据库迁移、LiveReader、身份验证算法。
- 不删除页面、不删除业务功能、不改 API 请求参数与返回字段解释。
- 不伪造数据、不在无数据时生成占位统计、不隐藏错误态。
- 不修改 `PlayerIdentityCenterView.vue` / `api/identityCenter.ts` / `types/identityCenter.ts`。
