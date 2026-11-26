# ScoutMind FM27 — Design System（Phase 1）

主题：**Futuristic Football Intelligence + Premium Dark Dashboard**。
设计目标不是「把后台换成深色」，而是让每个页面都像一个足球俱乐部的 AI 指挥系统：
数据是第一层，发光与渐变只用于引导注意力。

实现位置：

- `frontend/src/styles/tokens.css` — 全部设计变量
- `frontend/src/styles/base.css` — 环境光背景、布局原语、动效与降级
- `frontend/src/styles/element.css` — Element Plus 外观映射
- `frontend/src/utils/chart.ts` — 图表主题常量与 Option 构建器

## 1. 命名策略：语义层 + 兼容层

| 层 | 示例 | 使用方 |
| --- | --- | --- |
| 语义层 | `--sm-bg-primary`、`--sm-surface-glass`、`--sm-accent-cyan`、`--sm-text-secondary`、`--sm-status-warning` | 新组件、Dashboard、外壳 |
| 兼容层 | `--sm-bg`、`--sm-surface`、`--sm-accent`、`--sm-text-2`、`--sm-warn` | 既有 17 个页面、Element Plus 覆盖 |

兼容层全部映射到语义层，因此只改 Token 就能全站换肤，不需要逐页改色。
本次新增的语义 Token 与任务书要求一一对应：

`--sm-bg-primary`、`--sm-bg-secondary`、`--sm-bg-elevated`、`--sm-surface-glass`、
`--sm-border-subtle`、`--sm-accent-cyan`、`--sm-accent-blue`、`--sm-accent-violet`、
`--sm-accent-green`、`--sm-text-primary`、`--sm-text-secondary`、
`--sm-status-success`、`--sm-status-warning`、`--sm-status-danger`。

## 2. 色彩

### 2.1 背景层级

| Token | 值 | 用途 |
| --- | --- | --- |
| `--sm-bg-primary` | `#050a13` | 画布（Deep Space Navy） |
| `--sm-bg-secondary` | `#091220` | 次级画布 / 抽屉渐变 |
| `--sm-bg-elevated` | `#0f1a2b` | 抬升面板 |
| `--sm-surface` | `#0b1524` | 卡片基准表面 |
| `--sm-surface-2` | `#101d30` | 卡片内嵌层 / 表头 |
| `--sm-surface-3` | `#16253b` | 进度轨、代码块、分隔胶囊 |
| `--sm-surface-glass` | `rgba(14,25,41,.72)` | 玻璃面板（顶栏、外壳） |
| `--sm-surface-glass-strong` | `rgba(11,21,36,.88)` | 弹窗、Popover、Toast |

### 2.2 强调色

| Token | 值 | 语义 |
| --- | --- | --- |
| `--sm-accent-cyan` | `#22d3ee` | 主识别色：眉标、焦点环、当前导航、关键数据 |
| `--sm-accent-blue` | `#4d8dff` | 链接/次级强调（兼容层 `--sm-accent`） |
| `--sm-accent-violet` | `#a78bfa` | 对比系列、理想值参考线、AI 语义 |
| `--sm-accent-green` | `#34d399` | 正向状态、精英属性 |

渐变：

```css
--sm-gradient-accent: linear-gradient(135deg, #22d3ee 0%, #4d8dff 52%, #a78bfa 100%);
--sm-gradient-text:   linear-gradient(96deg, #d9f6ff 0%, #7dd3fc 38%, #a5b4fc 72%, #c4b5fd 100%);
```

使用规则：

- 渐变只用于 **顶部 1–2px 光线、按钮、主数字、雷达填充、激活态**。
- 正文永远使用实色，禁止渐变文字承载长段落。
- 同一屏内最多两处「大面积发光」。

### 2.3 文本

| Token | 值 | 对比度（`#0b1524` 卡片 / `#050a13` 画布） |
| --- | --- | --- |
| `--sm-text-primary` | `#eef5ff` | 17.2:1 / 18.1:1 |
| `--sm-text-secondary` | `#9db0c9` | 8.3:1 / 9.0:1 |
| `--sm-text-tertiary` | `#7689a3` | 5.1:1 / 5.6:1 |

三级文本仍满足 WCAG AA 正文 4.5:1；小号提示文字不得再暗于此值。

### 2.4 状态色

| Token | 值 | 用途 |
| --- | --- | --- |
| `--sm-status-success` | `#34d399` | 已通过、正向 delta、精英属性 |
| `--sm-status-warning` | `#f5b544` | 样本不足、合同风险、演示数据 |
| `--sm-status-danger` | `#fb7185` | 冲突、失败、负向 delta |

状态永远「颜色 + 文案」双编码，禁止只靠红绿区分。
弱化底：`--sm-success-weak` / `--sm-warn-weak` / `--sm-danger-weak` 统一为 12% 透明度。

## 3. 字体

| Token | 值 |
| --- | --- |
| `--sm-font-sans` | Inter → Helvetica Neue → PingFang SC → Microsoft YaHei → system-ui |
| `--sm-font-mono` | JetBrains Mono → SFMono → Consolas |
| 字号 | 11 / 12 / 13 / 14 / 16 / 20 / 28 / 36 / 44 |
| 行高 | tight 1.2 / normal 1.55 |
| 字重 | 400 / 500 / 600 |
| 字距 | `--sm-tracking-wide: 0.14em`（全大写眉标）；`--sm-tracking-label: 0.08em`（表头） |

规则：

- 页面标题 28px（窄屏 20px）；区块标题 14px；指标数字 28px；指挥条主标题 36px。
- 数字统一 `font-variant-numeric: tabular-nums`（`.sm-num`），金额右对齐。
- 英文眉标只在 `PageHeader` 与指挥条出现，避免每个卡片都堆英文。

## 4. 间距

4px 基准：`4 / 8 / 12 / 16 / 24 / 32 / 40 / 48 / 64`。
页面：`--sm-space-5`（24px），移动端 16px/12px。
卡片内边距：16px，紧凑 12px；卡片间距：16px，移动端 12px。

## 5. 圆角

| Token | 值 | 用途 |
| --- | --- | --- |
| `--sm-radius-xs` | 6px | 小图标按钮、代码 |
| `--sm-radius-sm` | 8px | 按钮、输入、导航项 |
| `--sm-radius-md` | 10px | 内嵌面板、提示条 |
| `--sm-radius-lg` | 14px | 卡片、图表卡、表格容器 |
| `--sm-radius-xl` | 18px | 指挥条、弹窗 |
| `--sm-radius-2xl` | 24px | 保留（大面积容器） |
| `--sm-radius-pill` | 999px | 标签、状态胶囊、进度条 |

## 6. 阴影与发光

| Token | 用途 |
| --- | --- |
| `--sm-shadow-1` | 卡片静置（几乎不可见，靠边框分层） |
| `--sm-shadow-2` | 悬浮/抬升 |
| `--sm-shadow-float` | 弹窗、抽屉、Toast |
| `--sm-glow-cyan` | 当前关注卡片的悬停/激活 |
| `--sm-glow-blue` / `--sm-glow-violet` | 主按钮、AI 面板 |

规则：静置状态只用 1px 边框 + 极浅阴影；发光只在 hover / focus / active 出现。
这避免「每张卡都在发光」的廉价感。

## 7. 动效

| Token | 值 |
| --- | --- |
| `--sm-ease-out` | `cubic-bezier(.22,1,.36,1)` |
| `--sm-dur-1` | 120ms（颜色/边框） |
| `--sm-dur-2` | 220ms（悬停抬升、路由切换） |
| `--sm-dur-3` | 420ms（页面进入、图表入场） |

统一动效：

1. 页面进入：`sm-page-in`（opacity + 8px 上移），路由切换 `page` transition（out-in）。
2. 卡片悬停：`translateY(-2px)` + 边框变亮，仅 `hover: hover` 且 `pointer: fine` 生效。
3. 图表：ECharts 入场 320–420ms `cubicOut`。
4. 状态点：`sm-pulse-dot` 2.4s。
5. 骨架：`sm-shimmer` 1.6s。

**降级**：`prefers-reduced-motion: reduce` 下，Token 时长压到 1ms，页面进入动画关闭、
侧栏抽屉无过渡、状态点与旋转图标停止、ECharts 入场时长设为 0（`reducedMotion()` 读取 `matchMedia`）。

## 8. 组件规范

| 组件 | 规范 |
| --- | --- |
| 卡片 | 14px 圆角、1px `--sm-border`、顶部 1px 冷光渐变、渐变表面（168°） |
| 主按钮 | 深蓝→靛紫渐变（白字对比 5.17:1 ~ 7.10:1），hover 出现青色 1px 光环 |
| 次按钮 | 半透明深色底 + 强边框；hover 边框转青 |
| 输入 | 近黑底 + 1px 内阴影；focus 青色 1px + 3px 柔光环 |
| 表头 | 全大写 11px、0.08em 字距、粘性定位、深色不透明底 |
| 选中行 | 青色 6–7% 叠加，不使用整行高亮色块 |
| 标签 | 胶囊形；成功/警告/危险均带 30% 边框与 10% 底 |
| 弹窗 | 玻璃强底 + 18px 圆角 + 模糊 16px |
| 空状态 | 空心圆环 + 虚线边框 + 说明文案；错误/样本不足使用语义色 |
| 骨架 | 冷色三段渐变扫光，节奏 1.6s |
| Tooltip | 深色玻璃、10px 圆角、最大宽度 320px、行高 1.6 |
| 焦点 | 2px `#22d3ee` 轮廓、2px 偏移；表格行内为 `-2px` |

## 9. 图表主题

- 轴标签：`#7689a3` 11px；网格线：`rgba(122,162,220,.1)`；轴线：`rgba(122,162,220,.18)`。
- 图例：底部居中、10px 方块、11px 文本。
- Tooltip：深色玻璃 + 10px 圆角 + 1px 冷边框，`confine: true` 防溢出。
- 系列色：CA `#4d8dff`、身价/正向 `#34d399`、分钟 `#4d8dff`、出场 `#f5b544`、
  阵容雷达 `#22d3ee`、理想值 `#a78bfa`。
- 空数据由 `ChartCard` 的空状态处理，禁止渲染 0 值假序列。

## 10. 使用约束

1. 不在页面内新增十六进制颜色；确需渐变时只能使用本文档的品牌色。
2. 不新增 UI 框架、不覆盖 Element Plus 行为，只覆盖外观。
3. 不为了「看起来更满」而补数据或默认值；`null` 仍显示 `—`。
4. 新组件必须复用 `--sm-*` 半径、间距、字号与动效 Token。
