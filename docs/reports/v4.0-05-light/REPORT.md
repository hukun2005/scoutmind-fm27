# ScoutMind FM27 · V4.0-05 Premium Light 全应用浅色主题统一改造报告

- 分支：`feature/v4.0-05-premium-light`（基于 `feature/v4.0-04-brand-tag-system`，基线 `e3eb12d`）
- 代码提交：`5d0c34d`
- Pull Request：https://github.com/hukun2005/scoutmind-fm27/pull/37
- 验收环境：Windows / Chromium / FastAPI 本地同端口托管构建产物；真实只读数据库副本（存档 2，54,570 名球员）

---

## 1. 全局主题架构修改说明

本次改造没有逐页“刷白”，而是先把主题收敛到全局设计系统，再由 Token 驱动所有页面与组件。

| 层级 | 文件 | 修改内容 |
|---|---|---|
| 设计 Token | `frontend/src/styles/tokens.css` | 原有深色语义 Token 全部改写为 Premium Light 取值；保持变量名不变（`--sm-*`），实现“一处换肤、全站生效”。移除 `html.dark` 主题块，改为在 `:root` 直接覆盖 Element Plus 浅色变量。 |
| 全局基础层 | `frontend/src/styles/base.css` | 画布改为 `#F5F7FA`，移除深色环境光；滚动条、选区、焦点环、折叠面板、代码块改为浅色。 |
| 组件库覆盖 | `frontend/src/styles/element.css` | 卡片、弹窗、抽屉、Popper/Dropdown、按钮、输入框、标签、表格、折叠、Tabs、Alert、Message、Notification、MessageBox、Skeleton、Loading、Pagination、Switch、Radio 全部改为浅色表面。 |
| 主题入口 | `frontend/src/main.ts` | 删除 `element-plus/theme-chalk/dark/css-vars.css` 引入与 `document.documentElement.classList.add('dark')`。 |
| HTML 元信息 | `frontend/index.html` | `color-scheme` 改为 `light`，`theme-color` 改为 `#F5F7FA`。 |
| 应用外壳 | `frontend/src/App.vue` | 侧栏、顶栏、导航分组、选中/悬停态、存档选择、同步状态、通知、头像菜单、底部状态区全部浅色化；移除霓虹渐变与发光。 |
| 图表 | `frontend/src/utils/chart.ts` | 文本、坐标轴、网格线、Tooltip、系列色、雷达底色统一为浅色规范。 |

改造后应用不再存在深色/浅色双主题切换，产品默认且唯一主题为 Premium Light。

## 2. 全局设计 Token 清单

```css
:root {
  color-scheme: light;

  --sm-bg-primary: #f5f7fa;      /* 应用主背景 */
  --sm-bg-secondary: #ffffff;    /* 主内容背景 */
  --sm-bg-elevated: #ffffff;     /* 浮层 / 卡片 */

  --sm-surface: #ffffff;
  --sm-surface-2: #f8fafc;
  --sm-surface-3: #eef2f7;

  --sm-text-primary: #172033;
  --sm-text-secondary: #475569;
  --sm-text-tertiary: #94a3b8;

  --sm-border-subtle: #e7ecf2;
  --sm-border-strong-2: #d8e1ec;

  --sm-accent-blue: #356ae6;
  --sm-accent-hover: #2a5bd0;
  --sm-accent-weak: rgba(53, 106, 230, 0.10);

  --sm-status-success: #16a36a;
  --sm-status-warning: #d99124;
  --sm-status-danger: #dc5b5b;
}
```

Element Plus 同步覆盖：`--el-color-primary`、`--el-bg-color`、`--el-bg-color-page`、`--el-bg-color-overlay`、`--el-fill-color*`、`--el-border-color*`、`--el-text-color*`、`--el-mask-color`、`--el-disabled-*`。
阴影改为低透明度冷灰阴影：`0 1px 2px rgba(23,32,51,.06)` / `0 10px 30px -18px rgba(23,32,51,.18)`。

## 3. 已修改的页面清单

全部 21 个真实路由已逐一打开并截图。

| 路由 | 页面 | 结果 |
|---|---|---|
| `/` | 首页 | PASS |
| `/players` | 球员探索 | PASS |
| `/players/:id` | 球员详情 | PASS |
| `/compare` | 球员对比 | PASS |
| `/watchlist` | 关注名单 | PASS |
| `/squad` | 阵容分析 | PASS |
| `/scouting` | 角色球探 | PASS |
| `/recruitment` | 引援机会 | PASS |
| `/development` | 球员发展 | 主题 PASS；数据加载 BLOCKED_BY_REAL_DATA（见第 9 节） |
| `/performance` | 表现分析 | PASS（真实数据无赛季统计，空态正确） |
| `/transfers` | 转会情报 | PASS |
| `/agent` | AI 球探助手 | PASS |
| `/director` | AI 足球总监 | PASS |
| `/transfer-director` | AI 转会总监 | PASS |
| `/identity` | 身份复核 | PASS |
| `/identity-center` | 身份中心 | PASS |
| `/save-identity` | 存档管理 | PASS |
| `/unresolved` | 待确认球员 | PASS |
| `/data` | 游戏数据 | PASS |
| `/governance` | 数据治理 | 主题 PASS；顶部偶发网络错误提示（见第 9 节） |
| `/settings` | 系统设置 | PASS（外观文案已改为 Premium Light） |

页面级改动集中在：`DashboardView`、`SquadView`、`PlayerDetailView`、`PlayersView`、`CompareView`、`RecruitmentView`、`TransfersView`、`AgentView`、`DirectorView`、`PlayerIdentityCenterView`、`DevelopmentView`、`SettingsView`。

## 4. 已修改的通用组件清单

| 组件 | 修改 |
|---|---|
| `AppTag` | 默认表面由 dark 改为 light；删除未使用的深色表面样式。 |
| `PlayerDetailDrawer` | `--pd-*` 映射到全局 Token，抽屉、遮罩、按钮统一浅色。 |
| `GlobalSearch` | 搜索弹层由深色渐变改为白色浮层；分组、标签页、命中高亮、图标底色浅色化。 |
| `DataTable` | 表头、悬停行、展开单元格、展开按钮浅色化。 |
| `EmptyState` / `InsightPanel` / `SectionCard` / `ChartCard` / `FilterPanel` / `KpiCard` | 移除深色渐变表面，统一白色卡片 + 浅色强调线。 |
| `AttributeBar` / `CoverageBar` | 轨道改为浅灰，能力/覆盖率色阶改为低饱和语义色。 |
| `PositionHeatmapCard` | 位置卡与缺员/薄弱状态改为浅色语义底色。 |
| `OnboardingPanel` | 摘要块改为浅色次级表面。 |

Element Plus 的 Modal、Drawer、Dropdown、Select、Tooltip、Popover、Toast/Message、Notification、Tabs、Table、Pagination、Input、Checkbox、Radio、Switch、Loading、Empty、Skeleton 均由 `element.css` 统一接管，不存在局部深色弹层。

## 5. 仍然存在的“深色”样式及保留原因

| 位置 | 内容 | 保留原因 |
|---|---|---|
| `AppLogo.vue` / 品牌 PNG/ICO | 应用图标采用深海军蓝圆角底板 + 白色 S | 这是品牌标识本身的配色，不是主题背景；在白色侧栏上对比清晰，符合 V4.0-04 品牌资源规范。 |
| `public/brand/scoutmind-mark-dark.svg` | 深色背景专用反白标识 | 品牌资源变体，供安装包/外部物料使用，运行界面未使用。 |
| `--sm-text-inverse: #ffffff` | 品牌蓝按钮、头像、主按钮白字 | 前景色，用于保证彩色底上的对比度。 |
| 状态色（成功/警告/错误） | `#16a36a` / `#d99124` / `#dc5b5b` 及其 7%–10% 浅色底 | 低饱和语义色，符合浅色规范，非旧深色主题残留。 |

运行界面中已不存在深色主背景、深色侧栏、深色顶栏、深色弹窗、深色下拉或深色表格。

## 6. 全路由截图

目录：`docs/reports/v4.0-05-light/`

- 1920×1080：21 个路由全量截图 + 全局搜索弹窗、球员详情抽屉、用户下拉菜单。
- 1600×900 / 1366×768：首页、球员探索、阵容分析、转会情报、AI 球探助手、游戏数据、系统设置 7 个关键页面截图。
- 机器可读结果：`screenshots.json`（含 `bodyBg`、侧栏/顶栏背景、`scrollWidth` vs `clientWidth`）。

## 7. 三档分辨率视觉验收

| 分辨率 | 结果 | 说明 |
|---|---|---|
| 1920×1080 | PASS | 无横向溢出；侧栏/顶栏/内容区均浅色。 |
| 1600×900 | PASS | `scrollWidth == clientWidth`；关键页面布局正常。 |
| 1366×768 | PASS | `scrollWidth == clientWidth`；侧栏为完整导航（≥1200px），表格无横向溢出。 |

逐路由计算的 `body` 背景均为 `rgb(245, 247, 250)`，侧栏为 `rgb(255, 255, 255)`，顶栏为 `rgba(255, 255, 255, 0.86)`。

## 8. 构建与测试结果

| 项目 | 命令 | 结果 |
|---|---|---|
| 前端类型检查 + 构建 | `npm run build`（含 `vue-tsc --noEmit`） | PASS，构建成功 |
| Playwright 全量回归 | `npx playwright test --workers=1` | PASS，102/102 |
| 全路由真实打开与截图 | Playwright + 真实只读 DB 副本 | PASS（主题维度） |
| 后端测试 | 本次未改动后端代码，未执行 | NOT_RUN（与主题改造无关） |

## 9. 未完成事项与阻塞原因

| 事项 | 状态 | 原因 |
|---|---|---|
| 球员发展页真实榜单加载 | BLOCKED_BY_REAL_DATA | `GET /api/v1/development/board` 在 54,570 人规模的真实只读副本上单次耗时超过 60 秒，页面展示浅色错误态。属既有后端查询性能问题，不是主题问题，本次未修改业务查询。 |
| 数据治理页顶部偶发“无法连接后端”红色提示 | BLOCKED_BY_ENVIRONMENT | 真实数据下部分重查询耗时长，浏览器/请求取消后全局会话错误提示被触发；页面主体与组件仍为浅色。属既有网络错误聚合逻辑，未在主题任务中改动。 |
| 后端 pytest | NOT_RUN | 本次仅修改前端样式与文案，未触碰后端。 |
| 1600×900 / 1366×768 全 21 路由截图 | PARTIAL | 三档均覆盖 7 个关键页面；全量 21 路由截图在 1920×1080 完成。 |

## 10. Git 信息

- 分支：`feature/v4.0-05-premium-light`
- 基线：`e3eb12d`（`feature/v4.0-04-brand-tag-system`）
- 提交 SHA：`5d0c34d`（实现）；报告回填为后续文档提交
- PR：https://github.com/hukun2005/scoutmind-fm27/pull/37

未执行：合并 main、发布应用、构建 Windows 安装包、安装/卸载/签名测试。
本次完成后暂停，等待用户审核。
