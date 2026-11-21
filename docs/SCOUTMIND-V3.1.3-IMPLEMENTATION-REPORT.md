# ScoutMind FM27 V3.1.3 实施报告

- 仓库：`hukun2005/scoutmind-fm27`
- 分支：`codex/scoutmind-v3.1.3-pg-validation`
- 基线：`30c745a`（开始前 fetch 确认）
- 范围：**SM-040 ～ SM-047**
- 日期：2026-11-21
- 状态口径：`PASS` / `PARTIAL` / `FAIL` / `NOT_RUN` / `BLOCKED`

## 总览

| 编号 | 任务 | 状态 |
| --- | --- | --- |
| SM-040 | PostgreSQL 迁移兼容性验证 | PASS（CI PostgreSQL 16） |
| SM-041 | 迁移回滚策略 | PASS（策略）；`downgrade base` 仍 BLOCKED |
| SM-042 | Field Evidence Validation System | PASS |
| SM-043 | CON_EXPIRY 根因调查 | PARTIAL（真实样本 NOT_RUN） |
| SM-044 | 32 个 Pending 字段验证计划 | PASS（计划）；真实证据 NOT_RUN |
| SM-045 | SM-013 历史转会来源 | BLOCKED |
| SM-046 | SM-018 真实 LLM 联调 | PARTIAL（运行时能力 PASS；真实 API NOT_RUN） |
| SM-047 | SM-019 真实回测 | NOT_RUN（真实存档无多时间点） |

### 先检查 CI #21

`https://github.com/hukun2005/scoutmind-fm27/actions/runs/44875093122`：**success**，5 个 job 全部通过
（含 PostgreSQL migration compatibility）。无需修复。

---

## SM-040 PostgreSQL 迁移兼容性验证

### 修改文件

- `scripts/pg_migration_validation.py`（新增）
- `backend/tests/test_pg_migrations.py`（新增，PG 环境专用）
- `.github/workflows/ci.yml`（PG job 改为完整验证）

### 实现

1. 真实 PostgreSQL 16 上执行 `upgrade head`，记录耗时与 `alembic current`；
2. 校验表/列/索引/唯一约束/外键：
   - 表数量、关键表存在；
   - `transfer_history` 的 `fee_raw`/`addons_raw`/`loan_fee_raw`/`currency_original`/`source_id`；
   - `ix_transfer_history_source_id`；
   - `import_jobs` 唯一约束是 `(fm_save_id, scan_id)`；
   - `transfer_history.source_id → transfer_sources.id` 外键；
3. `downgrade f3a9c57e21d8` 后用旧 schema 插入 users/fm_saves/players/player_instances/import_jobs；
4. 再 `upgrade head`，对比 players/import_jobs 行数；
5. 验证同一 `scan_id` 在不同存档可共存（隔离语义）；
6. 验证非法外键事务回滚（行数不变）；
7. 输出每一步耗时 JSON；
8. PG 专项 pytest（`SCOUTMIND_PG_TEST_URL` 未配置时 skip）。

### 真实 PostgreSQL 16 结果

CI run **44901354992**（提交 `596532c`）的 PostgreSQL job **success**，脚本输出：

| 检查 | 结果 |
| --- | --- |
| 表数量 | 40 |
| 缺表 / 缺列 / 缺索引 | `[]` / `[]` / `[]` |
| `import_jobs` 唯一约束 `(fm_save_id, scan_id)` | true |
| `transfer_history.source_id` 外键 | true |
| 跨存档同 `scan_id` 允许 | 2 条并存 |
| 事务失败回滚 | true |
| 升级 head 耗时 | 1.21 s |
| 降级到旧版本耗时 | 0.82 s |
| 旧 schema 升级 head 耗时 | 0.83 s |

发现并修复：`b6e2f4a70d15` 添加了 `transfer_history.source_id` 却没有外键；新增迁移
`f0a2c6d81b47` 补上 `fk_transfer_history_source_id`（ON DELETE SET NULL），SQLite 真实副本
upgrade/downgrade/upgrade 通过；本地头版本同步升级。

本机 Docker daemon 不可用，所以本地不跑 PG；以上数字来自 CI 的真实 PostgreSQL 16.16 容器。

---

## SM-041 迁移回滚策略 — PASS（策略）

### 交付

- `docs/MIGRATION-ROLLBACK-STRATEGY.md`
- 复用 `scripts/check_migration_safety.py`（fail-closed）

### 内容

1. 完整 revision 链与支持边界：只允许降级到 `992f85fb22b8` 之后；`downgrade base` 禁止；
2. forward-only：新增迁移、双写/回填/切换，不改历史 ID；
3. 备份/恢复：SQLite 在线备份、升级前后 `alembic current` 与行数记录；
4. 恢复后完整性检查：外键检查、行数、scan_id 隔离、接口冒烟、测试回归；
5. 只有业务批准才能提出改写历史 `scan_id` 的方案，本轮不实施。

---

## SM-042 Field Evidence Validation System — PASS

### 修改文件

- `live-reader/ScoutMind.FMReader/Evidence/FieldEvidence.cs`（新增）
- `live-reader/tools/ScoutMind.FMReader.Diag/Program.cs`（`evidence` 命令）
- `live-reader/tests/ScoutMind.FMReader.Tests/StabilityTests.cs`

### 实现

1. `FieldEvidence` 含 14 个字段：field_id/name、object_type、offset、data_type、raw/expected、
   observed_at、sample_count、mismatch_count、validation_status、evidence_source、confidence、notes；
2. `FieldEvidenceCatalog.Build` 生成 50 条；没有配对样本时最高 **Candidate**，绝不自动 Verified；
3. mismatch>0 → Rejected；0 与 0 的界面配对算有效样本（不把 0 当缺失）；
4. `Diag evidence [out.json]` 输出 JSON，可归档为验证报告；
5. 测试：无样本最高 Candidate、一致样本 + 注册表才 Verified、Candidate 不因样本升级、Rejected、0 值样本。

### 真实结果

`Diag evidence`：50 字段，**Verified 0 / Candidate 18 / Pending 32 / Rejected 0**（本轮无新界面样本）。

---

## SM-043 CON_EXPIRY 根因调查 — PARTIAL

### 修改文件

- `live-reader/ScoutMind.FMReader/Probes/ContractDateDiagnostics.cs`
- `live-reader/ScoutMind.FMReader/Probes/ObjectProbes.cs`
- `docs/CON-EXPIRY-ROOT-CAUSE-REPORT.md`

### 实现

1. 诊断输出原始值转换样本（最多 8 条：`0x... -> y/d [类别]`）；
2. 新增 `contract_flags_mix`：按 `CON_STATUS_FLAGS` 统计对象分布（仅线索，不判定类型）；
3. 报告中列出根因假设：同一指针指向多类对象、偏移语义不同、混合对象池；
4. 未修改偏移、未把异常年份映射为当前年份、未用默认日期填补。

### 真实样本

本轮 FM27 未运行，无法采集 24 个异常对象的原始字节；真实界面核对 **NOT_RUN**。`CON_EXPIRY` 保持 Candidate。

---

## SM-044 32 个 Pending 字段验证计划 — PASS（计划）

### 交付

- `docs/FM27-PENDING-FIELDS-VALIDATION-PLAN.md`（由 `Diag evidence` 生成）

### 内容

1. 32 个 Pending 字段逐一列出对象类型、偏移、数据类型、界面核对内容、验证步骤、风险、预期门槛；
2. 规则：原始值 + 界面期望值配对才算样本；无界面证据不得 Verified；0/缺失/默认不算证据；
3. 18 个 Candidate 仍缺独立界面证据，未升级；
4. 本轮不产生新的 Verified。

---

## SM-045 历史转会来源调查 — BLOCKED

### 交付

- `docs/TRANSFER-SOURCE-MATRIX.md`

### 结论

1. FMSuperScout 1.7.3 只有 `ScanAgreedTransfers`（agreed），没有历史数组；
2. Native Reader 未定位历史转会结构；
3. FM 存档文件解析未实现、无公开格式/授权，本轮只做可行性判断；
4. CSV/JSON 导入保留，字段覆盖率最高；
5. 设计了独立 Transfer Source Adapter 接口与能力矩阵；
6. 无可靠来源，SM-013 继续 **BLOCKED**，下一步需要带来源/记录号的历史 CSV/JSON。

---

## SM-046 真实 LLM 联调 — PARTIAL

### 修改文件

- `backend/app/config.py`（超时、重试、价格配置）
- `backend/app/agents/llm_planner.py`（重试、超时、usage、成本）
- `backend/app/agents/service.py`（回答中返回 usage/cost）
- `backend/tests/test_sm046_llm_runtime.py`（新增）

### 实现

1. `chat_completion` 使用可配置超时，429/5xx/网络错误重试，耗尽后抛 `LlmUnavailable`；
2. 解析 `usage`，按输入/输出单价计算成本；
3. `PlanResult` 携带 usage/cost，回答中返回 `llm_usage` / `llm_cost_estimate`；
4. 日志记录 usage 与成本；
5. 测试：usage/成本、计划携带、重试成功、重试耗尽、无 Key 明确不可用。

### 真实联调

没有真实 API Key，**真实 Provider 调用 NOT_RUN**；测试使用假响应，仅验证运行时行为，不声称真实联调通过。

---

## SM-047 真实回测 — NOT_RUN

### 检查结果

- 真实存档 `save_id=2`（真实 FM27 数据）：有 148,070 条快照、54,570 个独立观测日，
  但没有任何球员拥有 ≥2 个带 CA 的不同观测日；
- `save_id=1`（演示/导入数据）有 92 个多观测日实例，但不是真实 FM27 存档，不能用于真实回测；
- 因此真实回测 **NOT_RUN**，没有用合成数据/演示数据冒充。

现有 backtest 已按独立观测日、同日去重、训练只用历史点实现（SM-028），等真实多时点存档后可运行。

---

## 质量门禁

| 项目 | 结果 |
| --- | --- |
| 后端 pytest | **343 passed, 3 skipped** |
| FMReader 单测 | **107 passed** |
| Reader 集成测试 | 全部通过 |
| .NET Release build | 0 error |
| 前端 build | PASS |
| SQLite 迁移 | 旧库升级 PASS；head 往返 PASS；base downgrade BLOCKED（已记录） |
| PostgreSQL 16 | CI job 执行（本地 Docker 不可用） |
| GitHub Actions | **success**（run 44901354992，5 job 全绿，含 PostgreSQL 16） |

## 未解决问题

1. `downgrade base` 仍不可用（历史迁移 + 真实重复 scan_id），需要业务批准才能设计有损修复；
2. PostgreSQL 本地无法验证，依赖 CI PG 16；
3. CON_EXPIRY 真实样本未采集（游戏未运行），保持 Candidate；
4. 32 个 Pending 字段仍无界面证据，不能升级；
5. SM-013 来源 BLOCKED，需要真实历史转会文件；
6. SM-018 无真实 API Key，真实联调 NOT_RUN；
7. SM-019 真实存档无多时点，回测 NOT_RUN。

## 状态汇总

| 任务 | 状态 | 说明 |
| --- | --- | --- |
| SM-040 | 见 CI | PG 16 完整验证脚本 + 专项测试 |
| SM-041 | PASS | forward-only + 备份恢复 + 边界 |
| SM-042 | PASS | 50 字段证据 JSON + 状态规则 + 测试 |
| SM-043 | PARTIAL | 诊断增强；真实样本 NOT_RUN |
| SM-044 | PASS（计划） | 32 Pending 字段逐一计划 |
| SM-045 | BLOCKED | 无可靠历史转会来源 |
| SM-046 | PARTIAL | 运行时能力 PASS；真实 API NOT_RUN |
| SM-047 | NOT_RUN | 真实存档缺多时点 |
