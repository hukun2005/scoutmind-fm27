# ScoutMind FM27 — UI 测试报告（Phase 8）

## 1. 环境

| 项目 | 值 |
| --- | --- |
| 日期 | 2026-11-26 |
| 分支 | `feature/scoutmind-futuristic-ui-ux`（基于 `origin/main@24beaba`） |
| Node / npm | v24.22.1 / 11.19.1 |
| 前端 | Vue 3.5 + TypeScript 5.7 + Vite 6 + Element Plus 2.9 + ECharts 5.6 |
| 后端（本地验证） | FastAPI，`127.0.0.1:8000`，独立临时 SQLite + `samples/demo` 合成数据 |
| 浏览器 | Playwright Chromium（headless） |

后端仅用于界面验证，未修改任何后端文件、迁移或数据逻辑；测试使用独立临时数据库
（`%TEMP%\sm-demo\scoutmind.db`），未触碰仓库内真实数据库。

## 2. 类型检查与生产构建

```powershell
cd frontend
npm run build   # vue-tsc --noEmit && vite build
```

结果：**PASS**（exit 0）。

主要产物（gzip）：

| 产物 | 大小 |
| --- | --- |
| `index-*.js`（外壳 + Element Plus） | 1,155.41 kB / 385.25 kB |
| `chart-*.js`（ECharts） | 1,043.51 kB / 345.98 kB |
| `TransfersView` | 37.53 kB / 12.07 kB |
| `PlayerDetailView` | 31.30 kB / 10.7 kB |
| `SquadView` | 20.10 kB / 7.6 kB |
| `DashboardView` | 18.20 kB / 7.4 kB |

构建耗时约 12s；无 TypeScript 错误、无 Vite 警告阻断。

## 3. Playwright 端到端回归

```powershell
cd frontend
npx playwright test
```

结果：**9 passed / 0 failed**（6.3s）。

覆盖：治理页队列与快照差异、自由球员候选表、空状态、加载失败、401 提示、
人工二次确认、重复确认拒绝、跨存档 404。

**过程中发现并修复的问题**：顶栏页面标题最初使用 `<h1>`，与页面内容 `PageHeader` 的 `<h1>`
形成重复一级标题，导致 `getByRole('heading')` strict mode 命中两个元素、2 个用例失败。
将顶栏标题改为 `<span>` 后 9/9 通过。该问题同时是真实的可访问性缺陷（一页两个 h1）。

## 4. 响应式与渲染审计

自建 Playwright 脚本：6 视口 × 7 页面 = 42 组合。

| 检查 | 结果 |
| --- | --- |
| 横向溢出 | 0 / 42 |
| 零高度图表 | 0 |
| Vue 运行时错误 | 0 |
| 控制台错误 | 6 条，全部为 `/transfers` 后端 500（见第 6 节） |

详细矩阵与截图见 `04-RESPONSIVE-REPORT.md`。

## 5. 浏览器冒烟（带演示数据）

| 页面 | 结果 | 观察 |
| --- | --- | --- |
| `/` 指挥中心 | PASS | 6 张 KPI、趋势图、AI 事实摘要、年龄/雷达/位置图、Top 5、覆盖度、费用分布、活动、快捷入口 |
| `/squad` 阵容智能 | PASS | 评分仪表盘 75.1、六维雷达（6 维均有值）、年龄分布、深度/工资/合同/接班 |
| `/recruitment` 智能球探 | PASS | 7 名候选、评分徽章 82.8–52.0、筛选控制台 |
| `/transfers` 转会情报 | PARTIAL | 统计与图表正常；列表接口 500 → 错误态（后端缺陷） |
| `/agent` AI 体育总监 | PASS | 会话面板、空状态、输入区、确定性模式提示 |
| `/identity-center` 球员身份中心 | PASS | 只读验证：页面正常渲染，未修改任何冻结文件 |
| `/identity`、`/data`、`/players` | PASS | 路由可加载，无运行时错误 |

## 6. 已知失败与阻断

| # | 项目 | 状态 | 证据 |
| --- | --- | --- | --- |
| T-1 | `/transfers` 列表接口 | **BLOCKED（后端缺陷，非本次引入）** | `routes_transfers.py:111` `NameError: name 'all_rows' is not defined`；该文件在 `main` 上未修改 |
| T-2 | ESLint | NOT_RUN | 仓库未配置 ESLint |
| T-3 | 前端单元测试 | NOT_RUN | 仓库无单测框架（仅 Playwright） |
| T-4 | PostgreSQL 迁移 | NOT_RUN | 本次不涉及数据库/后端 |

`T-1` 的处理：前端保留错误态与重试按钮，不吞异常、不伪造数据；
需要后端维护者在独立 PR 中修复（超出本任务「不修改后端逻辑」的边界）。

## 7. 复现命令

```powershell
# 1) 后端（使用独立临时库与演示数据，避免碰真实库）
$demo = "$env:TEMP\sm-demo"
$env:SCOUTMIND_DATABASE_URL = "sqlite:///$($demo.Replace('\','/'))/scoutmind.db"
$env:SCOUTMIND_DATA_DIR = $demo
python -m alembic upgrade head          # 在 backend/ 下
python scripts/seed_demo.py --force
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000

# 2) 前端
cd frontend
npm run dev

# 3) 回归
npx playwright test
npm run build
```
