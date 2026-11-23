# ScoutMind FM27 V3.2.2 — 架构审计报告

- 审计日期：2026-11-23
- 基线：`main` / `397007b`（远程 `origin/main` 同步）
- 工作区：干净，无未提交修改
- 开发分支：`codex/scoutmind-v3.2-field-capture` @ `824274d`（V3.2.1 验证修复）
- 任务书中的 `6f4c469` / `3c01093` 已过时，未作为基线。
- 本阶段只做审计，**未修改代码、Schema 或真实数据**。

## 1. 仓库与 CI 事实

| 项 | 实际值 |
| --- | --- |
| main HEAD | `397007b` |
| origin/main | `397007b` |
| 开发分支 HEAD | `824274d` |
| 开放 PR | 0 |
| 标签 | 无 |
| 最近 CI | run 45120185768 **success**（Backend / PostgreSQL 16 / AI isolation / .NET / Frontend） |
| 后端测试 | 406 passed, 3 skipped |
| FMReader 单测 | 114 passed |
| 前端测试运行器 | **不存在**（package.json 只有 dev/build/preview） |
| 当前 FM27 进程 | 未运行（真实验收只能 NOT_RUN/BLOCKED） |

## 2. 现有架构

```text
FM27（只读）
  └─ FMSuperScout 原生内核（ReadProcessMemory；不写进程）
      └─ ScoutMind.FMReader
          ├─ FmProcessLocator / GameBuildDetector / VersionGate / LayoutResolver
          ├─ ReaderPipeline.Detect()：进程 + Steam 清单 + 插件版本 + 兼容闸门
          ├─ FMSuperScoutMemoryEngine.ScanAsync()：完整 dump → UpstreamDumpMapper
          └─ ScanWriter：scan-<id>.json + scan-<id>.meta.json
              └─ ScoutMind.Agent
                  ├─ watch：固定间隔执行 scan --sync
                  ├─ ScanQueue：scans / pending / sent 文件目录
                  ├─ BackendClient：POST /api/v1/imports/scan
                  └─ ReaderRunner：子进程 + 超时
                      └─ FastAPI
                          ├─ ScanImporter：scan_id 幂等、身份解析、快照追加、ImportJob/ImportRow
                          ├─ Canonical / Quality / Review
                          └─ Analytics：longitudinal / development / forecast / transfers
                              └─ Vue 3 前端（DataView / Development / Governance 等）
```

### 2.1 可复用组件（不得重复实现）

| 能力 | 现有实现 |
| --- | --- |
| FM27 进程定位 | `live-reader/ScoutMind.FMReader/Engine/FmProcessLocator.cs` |
| 构建/插件检测 | `GameBuildDetector.cs`、`VersionGate.cs`、`ReaderPipeline.Detect()` |
| 只读内存扫描 | `FMSuperScoutMemoryEngine`、`IUpstreamDumpProvider` |
| 扫描文件写出 | `ScanWriter`（信封 + meta 边车） |
| 本地文件队列 | `desktop-agent/ScoutMind.Agent/ScanQueue.cs` |
| 代理扫描/同步 | `AgentApplication.RunScanAsync`、`ReaderRunner`、`BackendClient` |
| 导入幂等 | `ImportJob (fm_save_id, scan_id)` 唯一约束；`ScanImporter.import_payload` |
| 快照追加 | `PlayerSnapshot`，`(player_instance_id, observed_at)` 唯一 |
| Canonical | `PlayerObservationCanonical`、`build_canonicals`、review API |
| 成长基础 | `analytics/longitudinal.py`、`analytics/development.py` |
| 真实数据状态 | `session.hasRealScanData`、`DataView` 导入历史 |

## 3. 缺失能力（按任务）

### 3.1 SM-067 自动历史快照

现状：

- `watch` 只按 `--interval-minutes` 无条件重复扫描；没有游戏日期变化检测。
- `ReaderStatus` **不包含游戏日期**；游戏日期只在完整 `scan` 后的 dump `meta.gameDate` 里出现。
- `ScanResult` 也不含 game_date。
- 没有“同一存档、同一游戏日期只生成一个正式快照”的采集任务模型；幂等只在 `scan_id` 级别。
- 存档身份没有由 Reader 自动识别：Agent 配置里的 `SaveName` 只是模板/日志；后端使用当前 active save。
- 没有采集任务状态持久化、进度、暂停/恢复、失败原因 API。
- 前端没有自动采集管理界面。

结论：SM-067 的核心依赖（轻量日期探测 + 采集任务状态）**尚不存在**。

### 3.2 SM-073 可靠性/断点恢复

现状：

- `ScanQueue` 只有文件目录，不是持久化任务状态机；没有 attempt、next_retry、timeout、last_error。
- `watch` 没有重试/指数退避；失败后只能人工 `sync`。
- `ScanWriter` 直接 `File.WriteAllTextAsync` 信封与 meta，不是临时文件 + 原子 rename；meta 无 SHA-256/大小校验。
- Agent 只在同步成功后归档；进程崩溃留下的半文件没有启动时清理/校验流程。
- 没有并发采集任务锁。
- 没有故障恢复测试（扫描中退出、导入中退出、文件占用等）。

### 3.3 SM-068 Canonical 智能审核辅助

现状：

- 已有 canonical 表、review queue、history、decision、冲突分类、真实 43,901 待审核。
- 没有风险评分、证据完整度、来源可信度、推荐候选、冲突模式聚合、审核优先级。
- `review_queue` 只按 conflict/snapshot_count 排序，不是风险评分。
- 安全约束（建议只读、不自动改 canonical）已有基础，但没有“建议 API”与批量建议的可撤销审计。

### 3.4 SM-069 成长历史 2.0

现状：

- `longitudinal.build_series` 已 canonical-aware；`growth_report` / `development` / `forecast` 接入 canonical。
- 只有 CA/PA、工资/身价/合同和整体属性差值；没有按位置/身体/技术/精神分组的趋势，没有年龄-成长关系、停滞区间和逐点证据链。
- 真实 save 2 只有 **1 个 game_date**（198,711 快照、8,734,392 属性值），真实成长趋势 **无法验证**，只能显示数据不足。
- 时间切分回测有基本测试，但属性级/分位置时间顺序仍需扩展。

### 3.5 SM-070 Transfer Event

现状：

- 只有 `transfer_history` 外部导入通道；真实 save 2 的 `transfer_history` 为 **0 条**。
- 没有从快照俱乐部变化自动生成转会事件；没有事件候选、证据等级、事件类型（loan/free/expiry/released/agreed/cancelled/future）。
- `transfer_history` 有 `status`/`transfer_type`/费用组件，但它仍是被导入的历史交易，不是自动识别事件。
- 没有“俱乐部变化 ≠ 有偿转会”的事件模型；没有本队买卖/租借事件视图。

### 3.6 SM-072 Playwright

现状：

- `frontend/package.json` 没有 Playwright、test、lint 脚本。
- 没有 `playwright.config.*`、E2E 测试目录、浏览器安装步骤。
- CI 只有 frontend typecheck/build，没有 E2E job。

### 3.7 SM-071 文档一致性

已知不一致：

- README 写“C# 读取器（46 个自检用例）”，实际 FMReader 单测为 **114 passed**。
- README 的“当前状态”仍以 V2 分析层为主，未完整反映 V3.2.1 canonical 治理与 `/governance`。
- 没有 `CHANGELOG.md`。
- 多个历史报告仍是当时状态，不能当作 V3.2.2 当前状态。
- 任务书要求最终报告名 `SCOUTMIND-V3.2.2-SM067-IMPLEMENTATION-REPORT.md`，尚未创建。

## 4. 数据库与迁移现状

- Alembic head：`d9e3f6a8b124`
- 迁移文件：17 个
- 关键表：`fm_saves`、`player_snapshots`、`player_attribute_values`、`import_jobs`、`import_rows`、`transfer_history`、`player_observation_canonicals`、`player_observation_canonical_actions`
- 真实 save 2：
  - snapshots 198,711
  - attributes 8,734,392
  - canonical 54,570（resolved 10,669 / needs_review 43,901）
  - game_date 只有 1 个
  - transfer_history 0
- SQLite 与 PostgreSQL 16 迁移均已在 V3.2.1 CI 验证；V3.2.2 新迁移尚未创建。

## 5. 建议的目标设计（待各阶段实现）

### 5.1 SM-067

- Reader 新增轻量 `date`/`session` 探测（复用内存读取与 `FmDate`，不启动完整 dump）；在未验证前不得把推测值当真实日期。
- 存档身份：优先使用真实、可验证的存档指纹；`meta.manager`/`myClub` 目前不足以单独证明存档身份，必须验证后才可启用。未验证时继续由用户/后端 active save 绑定，并明确 provenance。
- 后端新增采集任务表（建议 `capture_runs`）：
  - `fm_save_id`、`game_date`、`reader_version`、`game_build`、`scan_scope`
  - `state`、`attempt_count`、`max_attempts`、`next_retry_at`
  - `scan_id`、`import_job_id`、`supplemental`、`revision`
  - `observed_at`、`started_at`、`finished_at`、`error_code`、`error_message`
  - `metadata_json`
  - 唯一键至少覆盖 `(fm_save_id, game_date, reader_version, scan_scope, revision)`；同一天补充扫描写 `supplemental=true`，不覆盖正式记录。
- Agent 状态机与本地持久化：`Idle → Monitoring → DateDetected → ScanQueued → Scanning → Importing → Completed`；异常 `RetryPending/Failed/Cancelled/Paused`。
- 前端优先嵌入 DataView/Dashboard 的采集卡片，不新建独立大型系统。

### 5.2 SM-073

- `ScanWriter`：写 `.tmp` → fsync/close → 原子 rename；meta 记录 SHA-256 与字节数。
- Agent：启动时清理/隔离不完整 `.tmp`；导入前校验 meta 校验和与 JSON 完整性；持久化 queue manifest（attempt/next_retry/error）；指数退避、最大重试、超时、取消、暂停。
- 后端：保持 `scan_id` 幂等；采集任务状态机持久化；并发采集互斥。
- 测试覆盖：扫描中/导入中进程退出、数据库短暂不可用、Reader 不可用、文件占用、磁盘不足、重复提交、双任务并发。

### 5.3 SM-068

- 只读建议层：风险分、证据完整度、来源可信度、推荐候选、解释、优先级、冲突模式聚合。
- 建议只写审计（用户确认后才改 canonical）；不开放 AI 自动确认高风险。
- 复用现有 `canonical/review-queue`，增加建议字段/独立建议 endpoint。

### 5.4 SM-069

- 扩展 canonical-only 成长：属性按 category 分组（技术/身体/精神/位置）、年龄-成长、停滞区间、逐点 snapshot_id/source/game_date。
- 不足日期时明确“历史数据不足”，不制造曲线。
- 预测/回测按 game_date 隔离，禁止未来泄漏；补属性级测试。

### 5.5 SM-070

- 新事件候选表（建议 `transfer_event_candidates`）：
  - player_instance、event_type、from/to club、observed game_date range
  - evidence_level（Verified/High/Medium/Low/Unverified）、status、evidence_json
  - linked_transfer_id（可空）、fee 仅在真实来源提供时填写，未知保持 NULL
- 规则：
  - 明确的 transfer/agreed/loan 源数据 → 可到 High/Verified；
  - 仅俱乐部变化 → Unknown/Pending Verification，不推断费用/性质；
  - 合同到期/释放需合同与状态证据；
  - 同事件去重；本队视图区分买/卖/租入/租出/自由/条款/未完成/取消。

### 5.6 SM-072

- 引入 `@playwright/test`、config、`tests/e2e`；优先用 API fixture/演示存档，真实 FM27 单独标记。
- 覆盖 Dashboard、球员列表/详情、成长、转会事件、Canonical 审核、自动采集管理；正常/空/加载/错误/分页/搜索/筛选/详情/权限。
- CI 增加 Chromium 安装与 Playwright job；真实游戏 E2E 不进入 CI。

### 5.7 SM-071

- 最后统一 README/CHANGELOG/ARCHITECTURE/DATA_MODEL/API/测试说明/实施报告；修正 46→114 等过时数字；区分已实现与计划。

## 6. 预期修改文件（初步）

| 阶段 | 文件/模块 |
| --- | --- |
| SM-067 | `live-reader/.../Engine/FMSuperScoutMemoryEngine.cs`、Reader contracts、`desktop-agent/.../AgentApplication.cs`、`ScanQueue.cs`、后端 models/migration/routes、DataView/Dashboard |
| SM-073 | `live-reader/.../ScanWriter.cs`、`desktop-agent/.../ScanFileReader.cs`/`ScanQueue.cs`/`AgentApplication.cs`、后端 capture 状态表 |
| SM-068 | `backend/app/quality/review.py`、`routes_quality.py`、schemas、tests；前端 GovernanceView |
| SM-069 | `backend/app/analytics/longitudinal.py`、`development.py`、`routes_development.py`、tests；前端 DevelopmentView |
| SM-070 | models/migration、`analytics/transfers.py` 或新 `transfer_events.py`、routes、tests；前端 TransfersView |
| SM-072 | `frontend/package.json`、`playwright.config.ts`、`tests/e2e/`、`.github/workflows/ci.yml` |
| SM-071 | `README.md`、`CHANGELOG.md`、docs、最终报告 |

## 7. 测试策略

- 每个阶段先在独立分支写失败测试，再实现；不删除/降低现有 406 + 114 断言。
- Backend：pytest（业务/API/DB/幂等/故障恢复/跨存档）。
- .NET：`dotnet build ScoutMind.sln -c Release`、FMReader.Tests、Reader.Tests；新增 Agent 状态机/队列测试（当前无 Agent 测试项目）。
- 前端：`npm run build`；新增 Playwright（SM-072）。
- DB：SQLite `upgrade → downgrade -1 → upgrade`；PostgreSQL 16 CI service；真实数据备份验证；真实写入只对备份后的真实库执行，禁止 downgrade base。
- 真实 FM27：当前进程未运行，V3.2.2 真实采集验收标记 **NOT_RUN/BLOCKED**；不得用 Mock 冒充。

## 8. 实施顺序与分支

1. `feature/v3.2.2-sm067-auto-snapshot`：日期/存档探测 + 采集任务/状态机 + API/前端。
2. `feature/v3.2.2-sm073-recovery`：原子文件、校验、持久队列、重试/恢复 + 故障测试。
3. `feature/v3.2.2-sm068-canonical-review`：风险/建议/优先级（只读建议）。
4. `feature/v3.2.2-sm069-player-growth`：属性分组/停滞/证据链。
5. `feature/v3.2.2-sm070-transfer-events`：事件候选与证据等级。
6. `feature/v3.2.2-sm072-playwright`：E2E 基础设施与用例。
7. `docs/v3.2.2-documentation`：文档/版本一致性 + 最终报告。

每阶段独立提交，完成后暂停等待审查；不自动合并 main。

## 9. 风险与阻塞

1. **游戏日期探测**：Reader 目前只有完整 dump 才有 `meta.gameDate`；轻量读取需要真实 FM27 验证偏移，当前游戏未运行，必须先实现可测试接口并标记真实验收 NOT_RUN。
2. **存档身份**：`meta.manager`/`myClub` 语义未验证，不能直接作为可靠存档指纹；需要真实多存档验证。
3. **真实历史不足**：save 2 仅 1 个 game_date，SM-069 真实趋势无法验收；只能验证“正确显示不足”。
4. **真实转会数据不足**：save 2 transfer_history=0，SM-070 真实识别只能 Mark NOT_RUN；候选规则可用合成/历史 fixture 测试。
5. **Playwright**：需新增依赖与浏览器；CI 时间会增加。
6. **Agent 测试空白**：Desktop Agent 无测试项目，需要新增。
7. **CI**：当前公开仓库 CI 正常；新增 Playwright job 后需观察时长/缓存。

## 10. Phase 0 结论

- 现有 Reader、Agent、导入、Canonical、成长基础设施可以复用；
- V3.2.2 的主要缺口是 **日期/存档探测、采集任务状态机、可靠文件/队列、转会事件模型、Playwright**，不是重写现有扫描链路；
- 真实 FM27 当前未运行，涉及真实游戏验收的任务必须保持 NOT_RUN/BLOCKED，不得用模拟代替；
- 下一步应先实现 SM-067 的**只读日期/存档探测契约与测试**，再进行状态机和自动采集；在 Phase 0 审查通过前不修改业务代码。

**Phase 0 状态：PASS（审计完成；未修改代码/数据库）**
