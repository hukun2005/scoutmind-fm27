# V4.0-03 球员探索页面全量 UI/UX 重构报告（Premium Light）

- 分支：`feature/v4.0-03-player-explorer`
- 基线：`origin/main` @ `5edc1ba`（已包含 PR #32 / V4.0-02）
- 范围：球员探索页面、球员详情抽屉、真实筛选 API 扩展、回归测试与真实数据只读验收
- 状态口径：`PASS` / `PARTIAL` / `FAIL` / `NOT_RUN` / `BLOCKED_BY_ENVIRONMENT` / `BLOCKED_BY_REAL_DATA` / `BLOCKED_BY_INFRASTRUCTURE`

---

## 1. 原页面问题分析

对基线页面的审计结论（来自实现与既有 E2E 契约）：

| 问题 | 具体表现 | 影响 |
| --- | --- | --- |
| 概览区过重 | 页面顶部有整块「球探概览」叙述与规则生成内容 | 用户进入页面先读解释，而不是先看球员 |
| 指标独立成排 | 四项统计以 `stat-strip` 独立横排 | 占据首屏高度，信息价值低 |
| 搜索/筛选分散 | 搜索、位置、年龄、能力、身价分布在不同卡片与折叠区 | 操作路径长，筛选状态难理解 |
| 容器层层包裹 | 结果区被多个 `SectionCard` 包裹 | 有效内容宽度被压缩，列表密度低 |
| 数据主次不清 | 姓名、能力、身价与辅助字段权重接近 | 难以快速识别和比较球员 |
| 纵向浪费 | 行高、卡片间距与空状态偏大 | 首屏可浏览球员数量少 |
| 旧空状态 | 大面积空状态区域 | 无数据时页面显得空洞 |
| 视觉气质 | 深色后台风格 | 更像通用后台，而非专业球探工作台 |

本次不是换肤：页面的信息架构、搜索入口、筛选方式、列表/卡片结构、详情交互、状态页和响应式策略全部重写。

---

## 2. 新版页面信息架构（IA）

1. **紧凑页头**：标题「球员探索」+ 一句话说明；右侧「球员对比（n/4）」与「刷新」。
2. **核心搜索工作区**：宽搜索框（姓名）+ 位置组胶囊 + 年龄 / CA / 身价上限 + 「高级筛选」。
3. **筛选条件摘要**：仅在存在筛选时出现；每个条件可单独清除，另有「清空全部」。
4. **数据状态栏**：存档球员总数 / 当前结果 / 已关注；附页码与每页数量。
5. **球员结果主体**：结果数量 + 排序 + 列表/卡片切换；服务端分页；密度化列表。
6. **详情抽屉**：右侧浅色抽屉，按基本资料、能力结构、合同与市场、状态与风险、适配与档案分组。
7. **空 / 无结果 / 加载 / 错误状态**：与结果区同构，保持页面结构稳定。

---

## 3. 新版浅色设计规范（Premium Light）

| 用途 | Token | 值 |
| --- | --- | --- |
| 页面画布 | `--pl-bg` | `#F5F7FA` |
| 主内容 | `--pl-surface` | `#FFFFFF` |
| 次级区域 | `--pl-surface-2` | `#F0F3F7` |
| 主文字 | `--pl-text` | `#172334` |
| 次级文字 | `--pl-text-2` | `#68778A` |
| 辅助文字 | `--pl-text-3` | `#94A1B1` |
| 主品牌 | `--pl-primary` | `#2563EB` |
| 品牌弱底 | `--pl-primary-weak` | `#EFF4FF` |
| 边框 | `--pl-border` | `#E4EAF1` |
| 警告 | `--pl-warn` | `#B45309` |
| 风险 | `--pl-danger` | `#B91C1C` |

实现方式：

- 浅色主题**作用域限定**在 `.player-workspace`（含筛选抽屉与详情抽屉的独立 token），不改变其它页面的全局深色主题。
- 全部控件使用原生 input / select / button 并统一 token，避免 Element Plus 深色变量泄漏到浅色页面。
- 阴影仅用于结果容器与抽屉，边框为 1px 低对比灰；无大面积渐变、发光或装饰图标。
- 字号层级：页标题 24 / 球员姓名 13 / 数值 12.5–15 / 辅助 11；行高 48px，卡片间距 10px。

---

## 4. 新旧数据分布对比

| 区域 | 旧版 | 新版 |
| --- | --- | --- |
| 身份 | 姓名、国籍、位置分散在表格列 | 头像缩写 + 姓名 + 国籍同列；位置单独紧凑徽标（多位置取首个位置，避免撑破列） |
| 所属 | 俱乐部单列，联赛缺失 | 俱乐部 + 真实联赛副标题（无联赛数据时留空，不显示“联赛未知”噪音） |
| 能力 | CA / PA 与其他数值同权 | CA / PA 独立右对齐数值列，CA 加粗为主指标 |
| 市场 | 身价、合同、工资并列 | 身价为主列；合同在 ≥1400px 显示到期年份并按 12 个月预警着色；工资移入详情抽屉 |
| 操作 | 关注/详情入口较弱 | 星标关注、对比按钮、查看档案三连，固定在行尾 |
| 密度 | 行高偏大、容器嵌套 | 48px 行高、9 列（宽屏）→ 按断点隐藏合同/俱乐部/年龄/PA 等低优先级列 |
| 卡片 | 复制列表字段 | 只保留姓名、位置、年龄、国籍、俱乐部、CA/PA/身价、关注/对比/查看 |

所有数值均来自 `/players` 与 `/players/{id}`；缺失值显示 `—`，不写 0、不做推算。

---

## 5. 新旧布局对比

| 维度 | 旧版 | 新版 |
| --- | --- | --- |
| 首屏 | 概览卡 + 统计条 + 筛选卡 | 页头 + 搜索工作区 + 状态栏 + 结果区 |
| 搜索 | 表单卡片内 | 页面最显眼的主入口，即时查询 |
| 筛选 | 大型表单 + 折叠 | 4 个常用条件常驻；其余进右侧高级抽屉，条件实时摘要 |
| 结果容器 | 多层卡片嵌套 | 单一结果容器 + 共享网格列模板 |
| 详情 | 跳转页面 | 右侧抽屉（浅色），支持上一位/下一位与完整档案跳转 |
| 状态 | 大块空状态 | 与结果区同构的紧凑引导/骨架/错误块 |

---

## 6. 修改文件清单

**后端**

- `backend/app/analytics/players.py`：新增真实筛选字段（国籍、联赛、惯用脚、身高区间、合同截止、PA 上限）与 `player_facets()`。
- `backend/app/api/routes_players.py`：新增查询参数与 `GET /players/facets`。
- `backend/tests/test_api.py`：新增高级筛选 + facets 回归测试。

**前端**

- `frontend/src/views/PlayersView.vue`：整页重写（IA、Premium Light、列表/卡片、高级筛选、状态、响应式、关注/对比）。
- `frontend/src/components/PlayerDetailDrawer.vue`：新增浅色详情抽屉（按需加载、上一/下一位、关注/对比、完整档案）。
- `frontend/src/types/players.ts`：筛选字段、facets 类型与列表可选字段。
- `frontend/src/api/players.ts`：`getPlayerFacets()`。
- `frontend/tests/e2e/v4.0-03-players.spec.ts`：新增 23 条回归用例（覆盖 21 项要求 + 2 条卡片/断点补充）。
- `frontend/tests/e2e/v4.0-02-ui.spec.ts`、`frontend/tests/e2e/ui-v3.3.0.spec.ts`：按新 IA 更新页面契约断言（未删除、未降低覆盖）。

**文档**

- `docs/reports/v4.0-03/`：本报告与截图。

无数据库模型/迁移改动。

---

## 7. 组件与能力复用清单

- 复用 `stores/players.ts` 的分页、排序、筛选状态与过期响应序号保护。
- 复用 `stores/compare.ts` 的对比上限、持久化与提示；复用 `MAX_COMPARE`。
- 复用 `stores/session.ts` 的当前存档与 `dataRevision` 失效机制。
- 复用 `api/watchlist.ts` 的添加/删除/列表接口；未新增关注后端。
- 复用 `api/clubs.ts` 的俱乐部（含联赛）数据。
- 复用 `utils/format.ts`、`utils/labels.ts` 的货币/百分比/位置/属性/来源文案。
- 复用既有关注名单、对比引擎、角色适配与完整档案页（`/players/:id`），未重复实现。

---

## 8. API 改动说明（向后兼容）

`GET /api/v1/players` 新增可选参数：

| 参数 | 说明 | 数据来源 |
| --- | --- | --- |
| `nationality` | 精确国籍 | `players.nationality` |
| `league` | 联赛名 | `clubs.league`（子查询） |
| `foot` | `left/right/both` | 最新 `player_snapshots.foot` |
| `min_height` / `max_height` | 身高区间（cm） | 最新快照 `height_cm` |
| `contract_end_before` | 合同在该日期前到期 | 最新快照 `contract_end` |
| `max_pa` | 潜力上限（原前端已发送但后端未接收，本次补齐） | 最新快照 `pa` |

新增 `GET /api/v1/players/facets?save_id=`：

```json
{
  "total_players": 54570,
  "nationalities": [{ "value": "意大利", "count": 1234 }],
  "leagues": []
}
```

- 只返回真实存在的值；字段缺失返回空数组，前端隐藏或提示，不伪造选项。
- 无破坏性变更、无迁移；旧客户端不传新参数时行为不变。
- `/players?watchlist_only=true&limit=1` 仍用于关注总数（仅取 total）。

---

## 9. 功能测试结果

| # | 场景 | 结果 | 证据 |
| --- | --- | --- | --- |
| 1 | 页面加载 | PASS | E2E `默认加载…` |
| 2 | 姓名搜索 | PASS | E2E `姓名搜索…`（query 参数） |
| 3 | 位置筛选 | PASS | E2E `位置筛选…`（position_group） |
| 4 | 年龄筛选 | PASS | E2E `年龄筛选…`（min_age） |
| 5 | 能力筛选 | PASS | E2E `能力筛选…`（min_ca） |
| 6 | 身价筛选 | PASS | E2E `身价筛选…`（万→基础单位） |
| 7 | 高级筛选 | PASS | E2E `高级筛选…`（国籍/联赛/俱乐部/脚型/身高/合同/工资） |
| 8 | 多条件组合 | PASS | E2E `多条件组合…` |
| 9 | 排序 | PASS | E2E `排序…` |
| 10 | 分页 | PASS | E2E `分页…`（offset/limit） |
| 11 | 清空筛选 | PASS | E2E `清空筛选…` |
| 12 | 添加关注 | PASS | E2E `关注…`（POST + 星标反馈） |
| 13 | 取消关注 | PASS | E2E `取消关注…`（GET 记录 + DELETE） |
| 14 | 球员对比 | PASS | E2E `球员对比…` |
| 15 | 打开详情 | PASS | E2E `详情抽屉…` |
| 16 | 关闭详情 | PASS | E2E `详情抽屉：关闭…` |
| 17 | 切换详情球员 | PASS | 同上（下一位 → Luca Verdi） |
| 18 | 无数据状态 | PASS | E2E `空数据…` |
| 19 | 无搜索结果 | PASS | E2E `清空筛选…` |
| 20 | 加载状态 | PASS | E2E `加载状态…`（骨架 aria-busy） |
| 21 | 错误状态 | PASS | E2E `错误状态…`（重试/检查同步） |

后端：

- `python -m pytest`：853 条收集，850 passed / 3 skipped / 0 failed（`.pytest_cache/v/cache/lastfailed` 为空对象，进度 100% 无 F/E）。
- 新增 `test_players_advanced_filters_and_facets`：国籍/联赛/脚型/身高/合同过滤与 facets 计数 PASS；`tests/test_api.py` 复跑 11 passed。

---

## 10. UI/UX 测试结果

- Chromium E2E：21 项功能 + 卡片视图 + 1366/1600/1920 三档断点，全部通过；`document.scrollWidth - innerWidth ≤ 1`。
- 视觉截图（真实数据只读副本，54,570 名球员）：

| 状态 | 截图 |
| --- | --- |
| 默认页面 1600×900 | [01-default-1600x900.png](./screenshots/01-default-1600x900.png) |
| 高级筛选抽屉 | [02-advanced-filter-1600x900.png](./screenshots/02-advanced-filter-1600x900.png) |
| 球员详情抽屉 | [03-player-detail-1600x900.png](./screenshots/03-player-detail-1600x900.png) |
| 卡片视图 | [04-card-view-1600x900.png](./screenshots/04-card-view-1600x900.png) |
| 1366×768 | [05-responsive-1366x768.png](./screenshots/05-responsive-1366x768.png) |
| 1920×1080 | [05-responsive-1920x1080.png](./screenshots/05-responsive-1920x1080.png) |
| 空数据状态 | [06-empty-state-1600x900.png](./screenshots/06-empty-state-1600x900.png) |

验收说明：

- 空数据截图使用同一前端 + 空列表路由（真实存档均有数据）；其余截图连接真实 FM27 数据库的**只读副本**（`%TEMP%\sm-perf\real-opt.db`），原库未被写入。
- 真实数据中 `clubs.league` 全为 `NULL`，因此联赛下拉显示「存档未提供联赛数据」；代码与后端测试支持联赛过滤，但**真实数据下无可选联赛**（`BLOCKED_BY_REAL_DATA`，非前端缺陷）。
- 真实数据存在大量缺失的市场/合同字段，页面统一显示 `—`，未用 0 或估值填充。

---

## 11. 性能测试结果

环境：Windows，真实库只读副本（1.08 GB，54,570 名球员 / 106,106 player 行），后端 `127.0.0.1:8010`，SQLite。

| 请求 | 5 次中位耗时 |
| --- | --- |
| `/players?limit=50` | 232 ms（首次冷启动 1211 ms） |
| `/players?limit=50&min_ca=150` | 183 ms |
| `/players?limit=50&position_group=FW&max_value=5000000` | 169 ms |
| `/players/facets` | 71 ms |

- 列表始终服务端 `limit/offset` 分页，筛选在 SQL 层完成，未全量加载球员。
- 搜索 200 ms 防抖；`players` store 使用请求序号丢弃过期响应。
- 前端构建：`PlayersView` 42.34 kB（gzip 13.27 kB）；`npm run build` PASS，`vue-tsc --noEmit` PASS。
- 未做 PostgreSQL 下的大存档压测：`NOT_RUN`（本环境仅 SQLite 副本；CI 负责 PG 迁移）。

---

## 12. 后端与前端最终测试统计

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 后端全量 `pytest` | PASS | 853 collected / 850 passed / 3 skipped / 0 failed；lastfailed `{}` |
| 后端 API 子集 | PASS | `tests/test_api.py` 11 passed |
| Playwright 全量 | PASS | 88 passed（43.3s） |
| `vue-tsc --noEmit` | PASS | 无输出 |
| `npm run build` | PASS | 9.03s，PlayersView 42.34 kB / gzip 13.27 kB |
| SQLite 迁移 | PASS（无变更） | 本任务无迁移 |
| PostgreSQL 16 CI | NOT_RUN（本地） | 由 PR CI 的 `postgres-migrations` 执行 |

---

## 13. 未解决问题与限制

1. **联赛真实值缺失**：真实存档 `clubs.league` 为 `NULL`。筛选能力已完成并通过合成数据测试，真实 UI 无法选择联赛；状态 `BLOCKED_BY_REAL_DATA`。
2. **属性/角色筛选未开放**：现有 API 未提供按技术/心理/身体属性或角色模板筛选的查询，本次不伪造该能力（`NOT_RUN`，需后端新查询能力）。
3. **完整档案页**：`/players/:id` 仍为既有页面；本次按任务「优先右侧抽屉」完成详情重设计，抽屉内提供完整档案入口。完整档案页的浅色重做不在本任务范围（`PARTIAL`）。
4. **全局外壳**：侧边栏/顶栏为应用级深色外壳；本次浅色工作台限定在球员探索页面（符合页面级重构范围）。
5. **空状态截图**：真实存档均有数据，空状态以同前端空响应截图呈现；未伪造球员数据。
6. **性能**：仅验证 SQLite 只读副本；PostgreSQL 大存档压测 `NOT_RUN`。

---

## 14. Git / 提交 / PR

- 分支：`feature/v4.0-03-player-explorer`
- 基线：`origin/main` @ `5edc1ba`
- Worktree：`C:\Users\hukun\Desktop\FM27-v4-03`
- 提交 SHA：见本分支最新提交
- PR：由 `gh pr create` 创建后回填

完成后停止：不合并 main、不发布、不修改安装包。
