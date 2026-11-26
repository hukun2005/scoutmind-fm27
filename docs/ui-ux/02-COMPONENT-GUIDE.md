# ScoutMind FM27 — 组件规范（Phase 2）

本文件覆盖外壳与公共组件。所有组件只改外观，不改 API、props 语义与业务流程。
新增可选 props 均向后兼容，既有页面无需修改即可获得新主题。

## 1. 应用外壳（`App.vue`）

结构：

```
shell
├── skip-link（跳到主内容）
├── sidebar（品牌 / 主导航 / 状态脚注）
├── scrim（移动遮罩）
└── main
    ├── topbar（模块眉标、页面标题、同步状态、存档、刷新、提醒、设置、分析员）
    └── content → content__inner → alerts + DemoBanner + <router-view transition>
```

| 断点 | 行为 |
| --- | --- |
| ≥ 1200px | 248px 完整侧栏，分组标签可见 |
| 900–1199px | 76px 图标轨，隐藏文字，保留 tooltip 与 `aria-label` |
| ≤ 900px | 固定抽屉 + 遮罩，顶栏出现汉堡；`Escape` 关闭，路由切换自动关闭 |

导航分组：`Command`（指挥中心）、`Intelligence`（阵容/球员/球探/转会/发展/表现/AI）、
`Identity & Data`（数据中心、治理、身份复核、身份中心、存档身份、自由球员）、`Tools`（角色球探、关注名单）。

可访问性：

- 侧栏 `aria-label="主导航栏"`，当前项 `aria-current="page"`。
- 汉堡按钮 `aria-expanded` + `aria-controls`。
- 图标按钮全部带 `aria-label` 与 `title`。
- 顶栏为玻璃层（`backdrop-filter`），滚动时内容从其下方穿过，不遮挡焦点。

## 2. `PageHeader`

| Prop | 类型 | 说明 |
| --- | --- | --- |
| `title` | `string` | 页面标题（中文，保持原页面文案） |
| `description` | `string` | 一句话说明该页回答的问题 |
| `eyebrow` | `string` | **新增**：英文模块眉标，全大写 + 渐变短线 |
| `backTo` / `backLabel` | `string` | 返回链接 |

```vue
<PageHeader eyebrow="SQUAD INTELLIGENCE" title="阵容智能" description="六维评分与位置深度" />
```

规则：一个页面最多一个 `h1`；眉标不重复标题内容；窄屏标题降到 20px，操作区换行到下一行。

## 3. `KpiCard`

| Prop | 类型 | 说明 |
| --- | --- | --- |
| `label` | `string` | 指标名 |
| `value` | `string` | 已格式化的值，缺失为 `—` |
| `hint` | `string` | 口径说明（始终标注来源/时间） |
| `tone` | `default / accent / warn / danger` | 顶部光线与数字渐变 |
| `loading` | `boolean` | 骨架 |
| `to` | `string` | 整卡可点击，匿名锚点铺满 |
| `unit` | `string` | **新增**：单位后缀（€、%、岁） |

实现要点：顶部 2px 强调光线；`accent` 时数字使用渐变文字；悬停抬升 2px + 青色光环；
链接态保留 `kpi__stretch` 覆盖整卡，焦点环落在锚点上。

## 4. `SectionCard`

| Prop | 类型 | 说明 |
| --- | --- | --- |
| `title` / `subtitle` | `string` | 标题与口径 |
| `flush` | `boolean` | 去掉 body 内边距（表格/图表） |
| `dense` | `boolean` | 紧凑 |
| `accent` | `boolean` | **新增**：顶部改为完整品牌渐变（用于当前关注区块） |

槽位：默认、`actions`、`footer`。页脚用于样本量、算法版本、排除项等口径说明。

## 5. `ChartCard`

在 `SectionCard` 基础上增加：`loading`、`loadingRows`、`empty`、`emptyTitle`、
`emptyDescription`、`emptyVariant`（`empty / insufficient / error`）、`footnote`。

- 标题前的 3px 渐变竖条是统一视觉锚点。
- `empty` 为真时渲染 `EmptyState`，绝不渲染 0 值假曲线。
- 空状态的说明必须写清「哪个筛选/数据条件导致为空」。

## 6. `EmptyState`

| Prop | 说明 |
| --- | --- |
| `title` | 主信息 |
| `description` | 为什么为空、下一步做什么 |
| `variant` | `empty`（中性）/ `insufficient`（样本不足，琥珀）/ `error`（失败，珊瑚红） |
| `compact` | 表格/图表内使用 |

视觉：空心圆环 + 中心点，虚线边框 + 左上角径向冷光；语义色只加在圆环与中心点。

## 7. `LoadingBlock` / `ErrorState` / `DemoBanner`

- `LoadingBlock`：Element Plus 骨架 + 冷色扫光；`role="status"` + `aria-label`。
- `ErrorState`：保留原组件的重试与网络错误区分，仅跟随 Token 换色。
- `DemoBanner`：合成演示数据横幅，**不得为了截图而隐藏**；关闭仅对当前标签页生效。

## 8. `DataTable`

原生 `<table>` 实现（非 `el-table`），保留列宽、粘性表头、排序与键盘激活。

本次视觉变化：

- 表头：`rgba(16,29,48,.96)` 不透明底、11px 全大写、0.08em 字距。
- 行分隔：`rgba(122,162,220,.09)`；悬停：`rgba(34,211,238,.06)`。
- 排序激活箭头：青色。
- 行焦点：2px 青色内轮廓。
- 展开按钮：8px 圆角 + 青色悬停。

## 9. 徽标与数据单元

| 组件 | 规则 |
| --- | --- |
| `ScoreBadge` | 胶囊 + 语义边框；≥80 绿、≥65 蓝、≥50 琥珀、其余中性；覆盖率不足显示「覆盖 x%」 |
| `ConfidenceTag` | 沿用 Element Tag，高/中/低 + 文案，不只靠颜色 |
| `AttributeBar` | 20 段；精英绿、良好蓝、平均琥珀、弱珊瑚；渐变填充 + 圆角段 |
| `CoverageBar` | 胶囊轨道；≥90% 绿、≥60% 琥珀、其余红；`role="progressbar"` 与 `aria-valuenow` |
| `StatHeader` | 左侧分隔线网格；数值 20px 右对齐；窄屏两列 |

## 10. `EChart`

- 单实例初始化，`ResizeObserver` 跟随容器；`notMerge: true` 防止旧系列残留。
- `role="img"` + `aria-label`；ECharts `aria.enabled` 生成数据描述。
- 高度由调用方传入（216–268px）；容器 `width: 100%`，不设固定宽度。

## 11. 图表构建器（`utils/chart.ts`）

| 函数 | 数据来源 | 说明 |
| --- | --- | --- |
| `buildTrendChart` | `/analytics/overview.trend` | 总身价 + CA 均值双轴 |
| `buildFeeHistogram` | `/transfers/stats.distribution` | 成交费用直方图 |
| `buildGrowthChart` | `/players/{id}/history` | CA/PA/身价 |
| `buildAppearanceChart` | `/players/{id}/history` | 分钟 + 次数 |
| `buildRadarChart` | 球探/招募对比 | 任意维度 0–100 |
| `buildSquadRadar` | `/squad/overview.components` | **新增**：六维雷达，仅绘制有值维度 |
| `buildAgeDistribution` | `/squad/overview.age_structure.buckets` | **新增**：实际 vs 理想占比 |
| `buildPositionDistribution` | `/squad/overview.depth` | **新增**：位置现有 vs 需求 |

所有构建器共用一个 `baseFrame()`：统一网格、图例、Tooltip、动效与 reduced-motion 降级。

## 12. 禁止

- 不使用 `!important` 覆盖 Element Plus 的布局行为。
- 不在组件内写死颜色（除图表必需的渐变字面量）。
- 不新增全局副作用选择器（例如给 `body` 加状态类）。
- 不为了视觉效果隐藏错误态、空状态、演示横幅或「未配置 LLM」提示。
