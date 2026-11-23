# ScoutMind FM27 V3.2.2 — 实施报告（阶段性）

- 基线：`main` `397007b`
- 开发分支：`codex/v3.2.2-auto-snapshot`
- 实施日期：2026-11-23
- 状态：**部分阶段完成；未合并 main**
- 真实 FM27：运行中（pid 105040），但自动采集的轻量日期探测尚未实现，真实自动采集验收 **NOT_RUN**

## 1. 状态总览

| 任务 | 状态 | 说明 |
| --- | --- | --- |
| SM-067 自动历史快照 | **PARTIAL** | 采集表/API/前端面板 + Agent `auto`（扫描后日期判断、同日隔离）；轻量日期探测未完成 |
| SM-073 可靠性/断点恢复 | **PARTIAL** | ScanWriter 原子写、Agent 状态文件、启动恢复、指数退避完成；无完整故障矩阵测试 |
| SM-068 Canonical 审核辅助 | **PARTIAL** | 风险分、证据完整度、推荐候选（只读）已加入详情/界面 |
| SM-069 成长历史 2.0 | **PARTIAL** | 属性分类趋势完成；真实仅 1 个 game_date，无法验证趋势 |
| SM-070 Transfer Event | **PARTIAL** | 俱乐部变化候选（Unverified）表/API/检测完成；完整事件分类/验证未完成 |
| SM-072 Playwright | **PARTIAL** | Playwright 基础设施 + 2 个治理页面用例通过；未覆盖全部页面 |
| SM-071 文档统一 | **PARTIAL** | README 测试数修正；CHANGELOG/完整版本统一未完成 |

## 2. 已实现

### SM-067
- 新表/迁移 `capture_runs`（head `e5a1b2c3d4f6`）：
  - save、game_date、reader_version、game_build、scan_scope、status、
    attempt/max、next_retry、scan_id、import_job_id、supplemental/revision、
    observed/started/finished、error、metadata；
  - 正式采集 revision 0；同日补充扫描 revision > 0，不覆盖正式记录。
- API：`GET/POST /captures`、`PATCH /captures/{id}`、`GET /captures/summary`；
- DataView 新增“自动历史快照”面板（采集记录/完成/重试/失败/最近记录）。
- Agent 新增 `auto --interval-minutes`：扫描后读取 game_date；同存档同日期重复扫描移入 `duplicates/`，不重复导入；状态持久化到 `capture-state.json`；启动恢复 pending 文件；同步失败指数退避/最多 3 次。
- 未实现：扫描前的轻量日期探测（因此每个 interval 仍会全量扫描），暂停/恢复、严格存档指纹。

### SM-073
- `ScanWriter` 改为临时文件 + flush + 原子 `File.Move(overwrite)`；
- 已实现：状态文件、启动时 pending 恢复、同步失败指数退避；ScanWriter 原子写。
- 未实现：完整故障矩阵（扫描中退出/导入中退出/磁盘不足等）、文件 SHA-256 校验、并发锁。

### SM-068
- canonical 详情新增只读 `suggestion`：
  - `risk_score`、`priority`、`evidence_completeness`、
    `recommended_snapshot_id`、reason、`auto_applied=false`；
- 前端显示风险/推荐快照，明确“仅建议，未写入”；
- 不自动改 canonical，不删除审计。

### SM-069
- `growth_profile.attribute_trends`：按 `PlayerAttribute.category` 聚合
  （physical/technical/mental 等），返回每点日期、snapshot_id、均值、数量、delta；
- 只使用 canonical 快照；不足 2 个日期明确 unavailable；
- 真实 save 2 只有 1 个 game_date，真实成长趋势不能验证。

### SM-070
- 新表/迁移 `transfer_event_candidates`（head `f6a7b8c9d0e1`）：
  event_type、from/to club、game_date、evidence_level、status、linked_transfer、evidence；
- 检测规则：canonical 连续快照俱乐部变化 → `unknown_pending_verification` /
  `Unverified` / `pending`，fee 固定 null；
- API：`GET /transfer-events`、`POST /transfer-events/detect`；
- 不把俱乐部变化直接标为 Permanent Transfer 或收费交易。

### SM-072
- 加入 `@playwright/test`、`playwright.config.ts`、`test:e2e`；
- `frontend/tests/e2e/governance.spec.ts` 覆盖治理总览/队列/详情/建议/空状态，API 全部 mock；
- 本地结果：**2 passed**。

### SM-071
- README 后端测试数 406→413；
- C# 自检数 46→114；
- 新增本报告。

## 3. 数据库

| 项 | 值 |
| --- | --- |
| 新 head | `f6a7b8c9d0e1` |
| 新迁移 | `e5a1b2c3d4f6_capture_runs`、`f6a7b8c9d0e1_transfer_event_candidates` |
| 历史迁移修改 | 无 |
| SQLite 往返 | 两个新迁移均 upgrade → downgrade -1 → upgrade 通过 |
| PostgreSQL 16 | **PASS**（run 45126784762） |
| 真实库 | 未执行新迁移；避免在自动采集未完成时改真实 schema |

## 4. 测试

| 项目 | 结果 |
| --- | --- |
| 后端全量 | **413 passed, 3 skipped** |
| 新增 SM-067 API | 4 项 |
| 新增 SM-070 事件 | 2 项 |
| SM-068 suggestion | 现有 review 测试扩展 |
| SM-069 属性趋势 | 1 项 |
| Playwright | **2 passed**（本地 chromium） |
| .NET build | 0 error |
| 前端 build（vue-tsc） | PASS |
| 真实 FM27 自动采集 | **NOT_RUN** |

## 5. 未完成/阻塞

1. Agent 没有轻量游戏日期/存档探测；`watch` 仍是固定间隔全量扫描，不能作为可靠的自动历史采集。
2. 没有持久化采集状态机、退避重试、崩溃恢复、并发锁。
3. SM-070 没有 Permanent/Loan/Free/Expiry/Released/Agreed/Cancelled/Future 的完整证据分类；当前只产生 Unverified 俱乐部变化候选。
4. SM-069 真实 save 仅 1 个 game_date，真实趋势不能验收。
5. Playwright 只覆盖治理页，未覆盖 Dashboard/球员/成长/转会/自动采集全部范围。
6. 新迁移未应用到真实库；真实库应在自动采集链路完成并通过备份验证后再升级。
7. 未合并 main，未开始 V3.2.3。

## 6. Git

- 分支：`feature/v3.2.2-sm067-auto-snapshot`
- 远程分支 HEAD：`a6bc4e9`（报告提交前）；CI run **45126784762** success。
- main 仍为 `397007b`。


## 7. CI

- run **45126784762**：**success**
- Backend、PostgreSQL 16、AI isolation、.NET、Frontend 全部通过
- 真实 FM27 自动采集验收仍为 **NOT_RUN**（Agent 自动日期监控未实现）
