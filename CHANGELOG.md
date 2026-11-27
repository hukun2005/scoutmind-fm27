# Changelog

本文件记录 ScoutMind 的重要变更。编号对应 `docs/evidence/` 下的验收证据。

## [V3.3.2-05] - 2026-11-27

AI 转会总监（AI Transfer Director，Release Candidate）：合同/条款读取、确定性买卖报价、真实谈判记录与复盘。

### 新增

- **AI 转会总监工作台** `/transfer-director`：转会情报、AI 买入报价、AI 出售报价、合同与条款、谈判记录五个页签；球员详情页新增「AI 交易分析」入口。
- **确定性报价引擎** `app/services/transfer_director.py`：买入（保守/竞争/快速）与出售（快速/合理/价值最大化）各三套方案，因子包含合同剩余、年龄、CA、挂牌状态；预算不足只标记不编造；估值样本不足时明确拒绝区间。
- **真实谈判记录**：`transfer_negotiations` + `negotiation_events`（migration `c1a4e7f92b30`），状态机、终态保护、事件幂等与复盘；只写本地数据库，不提交游戏内报价。
- **交易状态历史** `transfer_status_history`：pending/agreed → completed 等变化只追加，重复导入不新增。
- **条款来源与计划**：`transfer_fee_components` 新增 `source/confidence/payment_schedule`；`loan_records` 新增租借费、工资承担、买断费用与条款状态（全部 nullable）。
- **AI 工具 10 个**：合同、转会历史、俱乐部汇总、条款、预算（明确不可用）、估值、买入/出售报价、记录谈判事件、复盘；工具层拒绝模型传入存档 ID。

### 数据能力（真实存档 62,229 人）

- 合同：周薪 81.2%、到期日 82.8% 可自动读取；挂牌 1,558 条、可租 6,491 条。
- 历史转会、成交费用、租借/买断条款：真实存档 0 条，来源不提供，状态 `BLOCKED_BY_SOURCE`，不伪装可用。

### 测试

- 后端新增 14 个用例（报价确定性、预算、条款来源、状态历史、谈判状态机/幂等/复盘、存档隔离）；
- 前端 `vue-tsc --noEmit && vite build` 通过；Playwright 新增 6 个用例；
- 迁移 `c1a4e7f92b30` 在临时库完成升级/降级/再升级往返，真实库副本升级通过。

## [V3.3.2] - 2026-11-27

查询性能深度优化 + 全局搜索升级 + AI 足球总监（Release Candidate）。PR [#25](https://github.com/hukun2005/scoutmind-fm27/pull/25)。

### 新增

- **AI 足球总监** `/director`：阵容补强、球员培养、出售/外租、引援计划、关注名单、年龄结构六类结构化分析；结论、规则计算、推断与缺失数据分开展示；推荐卡片可跳转球员、加入关注、加入对比，不自动改动游戏或数据库状态。
- **全局搜索升级**：新增「关注」分类（名单/状态/备注），球员支持位置代码与当前俱乐部名，俱乐部支持国家/联赛，转会支持类型/状态/日期；命中片段高亮、最近访问（本地按存档隔离）、Ctrl+K 与键盘导航。
- **查询缓存** `app/services/query_cache.py`：覆盖度、阵容统计、引援评分按 `存档 + 数据版本` 缓存 60 秒，导入或战术模板变化立即失效。
- **最新快照引用** `player_instances.latest_snapshot_id`（migration `b8f3d2a6c1e9`）：导入时维护，历史回补不覆盖新数据；读取端对空引用保留聚合回退。

### 修复

- **引援推荐在 6 万人存档报 `too many SQL variables`**：国籍查询改为按需分批；俱乐部改用候选自带 `club_id`。
- **引援推荐 O(N²)**：每名候选重复构建评分上下文改为只构建一次。
- **引援推荐属性加载过多**：先过滤再按 500 个快照一批加载命中球员属性。
- **俱乐部首次创建丢失联赛/国家/声望**：新建时写入扫描提供的字段，搜索和阵容展示不再永远为空。

### 性能（真实存档 62,229 人 / 195,593 快照）

- 球员列表 474 → 188 ms（冷）/ 118 ms（热）；搜索 476 → 201 / 127 ms；覆盖度 220 → 68 / 0.2 ms。
- 引援推荐从不可用 → 可用；按位置过滤首次约 4.0 秒，缓存命中 0.5 ms。

### 测试

- 新增 V3.3.2 后端用例：最新快照、搜索分类、AI 总监、缓存失效、migration 回填/降级；
- 前端 `vue-tsc --noEmit && vite build` 通过；Playwright 新增 2 个用例，完整 32 个用例通过；
- 真实存档只读验收 13/13 PASS（搜索、总监 6 类问题、存档隔离），详见 `docs/reports/V3.3.2_RELEASE_CANDIDATE_REPORT.md`。

## [V3.3.0] - 2026-11-26

一键数据体验 + 自动数据修复（One-Click Data Experience + Automatic Data Repair）。

### 新增

- **统一导入引擎** `app/datahub`：识别 → 解析 → 校验 → 匹配 → 修复 → 去重 → 事务导入 → 导入后验证 → 审计。
- **自动识别**：扫描 JSON、NDJSON、FMSuperScout 导出自动分流；阵容名单 CSV 明确引导到对应入口；UTF-8 / GB18030 编码回退，不静默替换字符。
- **三级修复**：
  - Level 1 确定性标准化（空白、空值、日期、数字字符串、枚举大小写、旧字段名、完全重复行）；
  - Level 2 有依据补全（稳定 UID 复用、同存档唯一俱乐部名 → uid），歧义不猜；
  - Level 3 隔离（缺姓名、非法枚举、未知状态等），不写入正式数据。
- **修复审计表** `data_repair_audits`（migration `c3f5a1b7d9e2`）：保留前后值、规则与规则版本、批次、来源、结果；只追加、不可覆盖。
- **数据中心 API**：`GET /data-hub/status`、`POST /data-hub/import`、`GET /data-hub/repairs`、`GET /data-hub/capabilities`。
- **数据中心 UI**：游戏连接 / 文件导入 / 数据状态三块；6 阶段进度；统一结果页；技术信息折叠到“开发者诊断”。
- **全站普通人视角**：中文导航分组；新增系统设置页（常用信息优先，内部凭据折叠）；首页/球员中心区分“没有数据”与“筛选无结果”，并提供同步或清除入口。

### 保障

- 复用既有 `ScanImporter` 的事务、幂等（`save_id + scan_id` / `operation_id`）、取消状态机与写栅栏；
- 修复审计与业务写入同一事务，失败一起回滚；重复导入不重复写审计；
- Level 2 查询全部按 `fm_save_id` 过滤，禁止跨存档；导入后校验批次快照与转会归属；
- 旧接口 `/imports/scan`、`/imports/fmscout`、`/imports/squad-csv`、`/imports/transfers` 行为不变。

### 测试

- 新增 data-hub 用例 34 个（识别、修复、引擎、API），全部通过；
- 针对性回归覆盖导入、并发、事务安全、FMSuperScout 适配、未解析球员、canonical 治理、质量规则，全部通过；
- 前端 `vue-tsc --noEmit && vite build` 通过，Playwright 16 / 16 通过（含 3 档分辨率无横向溢出）；
- SQLite 迁移升级 → 回滚 → 再升级通过，`scripts/check_migration_safety.py` 通过；
- 临时数据库全链路冒烟通过（自动修复 15 条、去重 1 条、隔离 1 条、二次导入幂等、验证 PASS、数据中心页面渲染 PASS）。
- 真实 FM27 一键导入验收：`NOT_RUN`（验收时游戏未运行）。

## [V3.2.9.2] - 2026-11-26

首版公开发布前稳定性收口（First Public Preview）。PR #14 + 本分支发布工程修复。

### 修复

- **存档切换后旧确认仍可写入（High）**：切换存档立即失效旧确认，确认绑定 generation，跨代写入被拒绝；真实 FM27 A/B/A（generation 1→2→3）验收通过。
- **`GET /api/v1/transfers` 500（High）**：列表接口引用未定义的 `all_rows`，每次请求都抛 `NameError`；改为在全量筛选集上计算覆盖率。
- **`/transfers` 的 `sort` 被静默忽略（Medium）**：支持 `transfer_date` / `effective_fee` 双向排序，非法字段返回 `400 invalid_sort`；`effective_fee` 空值排末尾，分页稳定。
- **审核并发写入（Medium）**：审核操作加入乐观锁与幂等键，重复提交不产生双重写入。
- **同名候选被截断（Medium）**：同名球员候选完整返回。
- **发布包端口误判（Medium）**：启动脚本先检查端口占用，避免健康检查连到其它实例并误报成功。
- **停止脚本找不到进程（Medium）**：按实际监听端口记录 PID，并按命令行中的发布包路径校验归属。

### 新增

- Verified 生命周期账本：确认、撤销、冲突全程可追溯。
- 转会证据关联与审核审计落库。
- 高频查询索引（转会、候选、采集、身份）。
- `GET /api/v1/transfers` 13 个回归测试：分页、筛选、排序、非法排序、空结果、缺失费用、附加条款、多存档隔离、列表与统计一致性、覆盖率跨页稳定。
- Windows 发布工程：`scripts/build-release.ps1`、`Start-ScoutMind.ps1`、`Stop-ScoutMind.ps1`、`Check-Environment.ps1`、`Backup-Database.ps1`、`backup_sqlite.py`。
- 后端可选托管生产前端（`SCOUTMIND_FRONTEND_DIST`）：单端口提供 API 与界面，刷新深链不 404，`/api/*` 未知路径仍返回 404。
- `config/app.example.json`、`docs/release/v3.2.9.2/` 发布文档。

### 迁移

- `b2c3d4e5f6a7`：身份审核并发与审计（PR #14）。
- 本分支未新增 migration；升级路径、重复升级与回滚均验证通过。

### 测试

- 后端 658 个用例 0 失败；FMReader 334、Reader 57、Agent 38；前端构建 + Playwright 9/9。
- 真实 FM27：`status` / `probe` / `scan`（44,144 名球员）/ 导入 / 重复上传去重全部通过。

## [V3.2.7.4] - 2026-11-25

真实运行闭环与 PR #8 最终审核。

### 修复

- **身份切换后新会话不可写（High）**：`rotate_generation` 未保留新会话，已传 `next_session_id` 并加回归测试。
- **采集入口缺少 Write Fence（Medium）**：`POST /captures`、`PATCH /captures/{id}` 现在与导入一致，提交前 `assert_current`。
- **operation 幂等未绑定 payload（Medium）**：同 operation 不同内容返回 `409 operation_conflict`；同 scan 不同内容返回 `409 scan_payload_mismatch`；被拒绝 operation 重放返回 `409 operation_rejected`。
- **Agent 启动恢复无上下文上传（Medium）**：新增 `.context.json` 固定任务上下文；缺失/损坏或指纹不一致直接隔离。

### 新增

- Worker 取消状态机：`queued → cancelled`（原子）、`running → cancel_requested → cancelled`；新增 `POST /imports/{id}/cancel`、`attempt_count`、`cancel_requested_at`、`cancelled_at`、`cancellable`。
- 启动恢复审计：`worker_recovered`、`backend_restarted`。
- 审计事件：`identity_verified`、`identity_conflict`、`session_created`、`write_accepted`、`network_reconnected`。
- Desktop Agent：`diagnostics`、`jobs list|inspect <scan_id>`、`network status`；连接失败单次 500ms 退避。
- 前端：`SaveIdentityView` 增加 Worker/网络只读诊断（任务状态、尝试次数、心跳、重连与重启计数）。
- `tools/runtime-acceptance/`：一键运行期验收（环境检查、存档隔离、Worker 栅栏、operation 幂等、断网模拟、证据脱敏汇总）。

### 迁移

- `b5d9c2e7f4a1`：`import_jobs.status` 加宽至 32，新增 `attempt_count`、`cancel_requested_at`、`cancelled_at` 与 `ix_import_jobs_status`；downgrade 先收敛状态再收窄。

### 文档

- `docs/evidence/v3.2.7.4/`：Phase 0 审计、PR #8 审核、CI/数据库/写入栅栏/取消/网络/真实 FM27 验收、RT 矩阵、最终报告。

### 已知限制

- `/imports/fmscout`、`/imports/transfers/history` 仍走 legacy 允许策略（PARTIAL，计划 V3.2.7.5 收紧）。
- 取消信号为进程内事件，单写进程部署假设。
- 真实 FM27 A/B、断网、重启验收：2026-11-25 真实执行，`REAL_FM27_ACCEPTANCE_FAIL`——A 通过，B 出现跨存档污染（D-01：扫描报文无存档标识 + Agent 不传目标存档，B 写入 A 的 `save_id`）；C/D/E 未执行。
