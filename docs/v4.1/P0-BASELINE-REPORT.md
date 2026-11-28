# V4.1 P0 基线审计报告

> 分支：`feature/v4.1-premium-light-ui`（基于 `feature/v4.0-05-premium-light` @ `56738c2`）
> 范围：ScoutMind FM27 前端（Vue 3 + TypeScript + Vite + Pinia + Element Plus + ECharts）
> 结论：V4.0-05 已完成「全应用浅色」基础改造；V4.1 在此基础上做设计规范收敛与全局一致性加固。

## 1. 架构与主题入口

| 层 | 位置 | 现状 |
| --- | --- | --- |
| 设计令牌 | `frontend/src/styles/tokens.css` | 单一 `:root` CSS Variables；同时覆盖 Element Plus 变量；无 `html.dark`、无 dark 样式表 |
| 基础层 | `frontend/src/styles/base.css` | 重置、排版、布局原语、动效、减少动效降级 |
| 组件库覆盖 | `frontend/src/styles/element.css` | Dialog / Drawer / Popper / Dropdown / Select / Table / Tag / Alert / Message / Skeleton / Pagination 等浅色覆盖 |
| 图表主题 | `frontend/src/utils/chart.ts` | 统一 tooltip / 坐标轴 / 图例 / 调色板 |
| 应用外壳 | `frontend/src/App.vue` | 侧栏 + 顶栏 + 路由视图，导航按任务分组，高级工具默认折叠 |
| 路由 | `frontend/src/router/index.ts` | 21 条业务路由 + 兜底重定向 |

## 2. 路由清单（21）

`/`、`/players`、`/players/:id`、`/compare`、`/watchlist`、`/squad`、`/scouting`、`/recruitment`、
`/development`、`/performance`、`/transfers`、`/agent`、`/director`、`/transfer-director`、
`/identity`、`/identity-center`、`/save-identity`、`/unresolved`、`/data`、`/governance`、`/settings`。

## 3. 页面与组件规模

- 业务视图 21 个（`frontend/src/views/*.vue`）。
- 通用组件 29 个（`frontend/src/components/*.vue`），其中主题相关重点：
  `AppLogo`、`AppTag`、`AttributeBar`、`CoverageBar`、`ScoreBadge`、`DataTable`、
  `GlobalSearch`、`PlayerDetailDrawer`、`SectionCard`、`ChartCard`、`InsightPanel`、
  `EmptyState`、`ErrorState`、`LoadingBlock`、`KpiCard`、`PageHeader`。

## 4. 基线问题（本次修复目标）

1. **品牌色不统一**：`#356AE6`（旧品牌蓝）与 `#1D4ED8` / `#2563EB` / `#3B82F6` / `#33548A` 等零散旧蓝并存。
2. **紫色与荧光色残留**：`#6D5BD0`、`#7C6BD6`、`#A78BFA`、`#22D3EE` 出现在图表、进度条、雷达环与 Logo 节点。
3. **对比度缺陷**：`ScoreBadge` 使用深色主题时代的亮色（`#6EE7B7` / `#93C5FD` / `#FCD34D`），在浅色底上几乎不可读。
4. **语义色三套并存**：Element Plus 默认色阶、`AppTag` 硬编码色阶、`--sm-status-*` 三套不一致。
5. **导航分组与产品结构不一致**：`AI 转会总监` 未归入「转会中心」；`身份中心` 被特判。
6. **玻璃拟态**：顶栏使用 `backdrop-filter` 毛玻璃。
7. **列表悬停色/描边色**：`#F5F8FF`、`#E7ECF2`、`#E2E8F0` 等散落在多个文件。

## 5. 基线验收结论

- 基线 `npm run build`：PASS。
- 基线 Playwright：102/102 PASS（V4.0-05 基线）。
- 基线主题：全应用已为浅色，但未达到 V4.1「单品牌蓝 + 低饱和语义色 + 无紫色/荧光色」规范。

## 6. 真实数据可用性（基线既有问题，非本次主题问题）

- `/api/v1/development/board` 在 54k 球员真实副本上响应超过 60s → 真实数据页面验收标记 `NOT_RUN`。
- `/api/v1/data-quality/*` 重查询偶发超时取消，会触发全局「无法连接后端」提示 → `BLOCKED_BY_REAL_DATA`。

以上两项不写 PASS，也不伪造数据。
