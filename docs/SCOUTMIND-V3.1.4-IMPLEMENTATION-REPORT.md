# ScoutMind FM27 V3.1.4 实施报告

- 仓库：`hukun2005/scoutmind-fm27`
- 分支：`codex/scoutmind-v3.1.3-pg-validation`
- 基线：`8f08392`（开始前 fetch 确认）
- 范围：**SM-050 ～ SM-054**
- 日期：2026-11-21
- 状态口径：`PASS` / `PARTIAL` / `FAIL` / `NOT_RUN` / `BLOCKED`

## 总览

| 编号 | 任务 | 状态 |
| --- | --- | --- |
| SM-050 | AI 工具存档权限隔离 | PASS |
| SM-051 | LLM JSON Schema 参数验证 | PASS |
| SM-052 | Field Evidence 可信度升级 | PASS（代码/测试）；真实界面样本 NOT_RUN |
| SM-053 | 文档状态统一 | PASS |
| SM-054 | AI Agent Engineering Guardrails | PASS（AGENTS.md + 自动检查评估） |

---

## SM-050 AI 工具存档权限隔离 — PASS

### 修改文件

- `backend/app/agents/llm_planner.py`
- `backend/tests/test_sm050_ai_tool_isolation.py`（新增）

### 问题

TOOL_SPECS 的 `player_profile`/`player_growth`/`player_forecast`/`transfer_roi`/`simulate_transfer`/
`career_timeline`/`club_transfer_intelligence`/`recruitment_recommend` 等只把 `instance_id`/`transfer_id`
直接传给 analytics；只要拿到其他存档的 ID，工具就会读取/计算，未校验 `save_id` 归属。

### 修复

1. `execute_plan` 在调用任何工具前统一执行 `_assert_tool_scope(session, save_id, arguments)`；
2. 校验 `instance_id`、`transfer_id`、`club_id`、`shortlist_id`、`candidate_id` 对应实体的
   `fm_save_id == save_id`；
3. 越权统一抛 `PlannerError("工具参数引用了当前存档之外的记录")`，不区分"不存在/属于别人"；
4. 作用域错误直接抛出，不被“工具执行失败”兜底成通用错误；
5. 服务端注入的 `save_id` 仍是唯一来源，模型参数中的 `save_id`/`fm_save_id`/`user_id`/`session_id` 被拒绝；
6. 失败发生在工具执行前，不产生写操作。

### 测试（5 项）

- 当前存档正常访问；
- 同一用户第二个存档正常访问；
- 其他用户实例被拒绝，且实例数不变；
- 其他存档交易被拒绝；
- LLM 伪造 `save_id` / 伪造计划在解析或执行前被拒绝。

---

## SM-051 LLM JSON Schema 参数验证 — PASS

### 修改文件

- `backend/app/agents/llm_planner.py`
- `backend/tests/test_sm051_tool_schema_validation.py`（新增）

### 实现

未引入新依赖，按现有 schema 实现严格子集校验：

- integer/number/string/boolean 类型；
- `bool` 不得冒充 integer/number；
- `NaN` / `Infinity` / `-Infinity` 拒绝；
- `enum`、`minimum`、`maximum`、`minLength`、`maxLength`、`required`、
  `additionalProperties: false`、未知参数；
- `save_id` / `fm_save_id` / `user_id` / `session_id` 一律拒绝。

### 测试（7 项）

`contract_years` 上限 8、`season` 长度 7、`page_size` 上限 20、bool 冒充、NaN/Inf、未知/受限参数、
required/enum/长度与合法参数原样返回。

---

## SM-052 Field Evidence 可信度升级 — PASS（代码/测试）

### 修改文件

- `live-reader/ScoutMind.FMReader/Evidence/FieldEvidence.cs`
- `live-reader/tests/ScoutMind.FMReader.Tests/StabilityTests.cs`

### 实现

1. `confidence` 与 `validation_status` 分离：`Confidence` 改为 `double?`，只有显式校准值才填写，
   默认 `null`；notes 明确“不是概率”；
2. 删除 `0.6 + 0.1 * sampleCount` 启发式公式；
3. 按字段类型选择比较器：数值（可配置 `NumericTolerance`）、日期（标准化到日）、字符串（trim 精确）；
4. 记录 `SampleCount`、`UniqueObjectCount`、`UniqueObservationCount`、`MismatchCount`；
5. 字段级门槛 `MinimumSamples` / `MinimumUniqueObjects` / `MinimumUniqueObservations`，
   未达门槛最高 Candidate；
6. 无真实界面证据的字段保持 Pending/Candidate；CON_EXPIRY 保留独立规则（仍 Candidate）；
7. 未修改任何内存偏移。

### 测试

- 独立对象/观测计数与门槛；
- 数值容差（默认严格、容差 1 内一致）；
- 0/0 配对仍是有效观测；
- 无样本不得 Verified；未校准 confidence 必须为 null。
- FMReader 单测总计 **109 passed**。

真实界面样本本轮 **NOT_RUN**（游戏未运行），因此没有新增 Verified。

---

## SM-053 文档状态统一 — PASS

### 修改文件

- `README.md`（读取器已验证可扫描；测试数 355）
- `docs/PRODUCT_SPEC.md`（14 个工具；真实 LLM NOT_RUN）
- `docs/ARCHITECTURE.md`（14 个工具）
- `docs/MIGRATION-COMPATIBILITY.md`（PostgreSQL 16 CI PASS，head `f0a2c6d81b47`）
- `docs/ROADMAP.md`（追加 V3.1.4 当前状态，不覆盖历史）

### 内容

- 读取器：build 26620374 + plugin 27.1.0+2505117 Verified；其他版本拒绝，不再声称“不可用”；
- PostgreSQL：CI 真实 16.16 验证 PASS；
- SM-013 BLOCKED、SM-018 真实 Provider NOT_RUN、SM-019 真实回测 NOT_RUN 均保留；
- AI 工具数量与 `TOOL_SPECS` 一致（14）；
- 版本兼容与字段可信度分开；历史报告保留，用当前状态说明引用。

---

## SM-054 AI Agent Engineering Guardrails — PASS

### 交付

- `AGENTS.md`（根目录）

### 内容

修改前检查、数据库字段确认、Model/Migration/Schema 对照、测试先行、SQLite/PostgreSQL 双引擎验证、
禁止弱化测试/跳过 CI/覆盖修改、Git 分支隔离、CI 失败读日志、PASS/PARTIAL/FAIL/NOT_RUN/BLOCKED 口径。

### 自动检查评估

| 检查 | 状态 |
| --- | --- |
| PostgreSQL 16 migration CI | 已实现 |
| SQLite migration 往返 | 已实现 |
| AI Tool Save Isolation tests | 已实现 |
| LLM Tool Schema tests | 已实现 |
| ORM Schema Contract tests | 部分（由迁移断言/关键列检查覆盖） |
| GitHub Required Checks | 需管理员在 Settings → Branches 配置；代码无法自动完成，未声称已完成 |

---

## 质量门禁

| 项目 | 结果 |
| --- | --- |
| 后端 pytest | **355 passed, 3 skipped** |
| FMReader 单测 | **109 passed** |
| Reader 集成测试 | 全部通过 |
| .NET Release build | 0 error |
| 前端 build | PASS |
| PostgreSQL 16 | CI job（见下） |
| GitHub Actions | **success**（run 44908508254，5 job 全绿，含 PostgreSQL 16 / AI 隔离 / .NET / 前端 / 后端） |

## CI

- 运行：https://github.com/hukun2005/scoutmind-fm27/actions/runs/44908508254
- 提交：`2fb06d5`
- 结论：**success**
  - Backend (pytest + migrations)：success
  - PostgreSQL migration compatibility：success
  - Upload / identity / agent isolation regressions：success
  - .NET readers and agent：success
  - Frontend (typecheck + build)：success

## 未解决问题

1. SM-052 真实界面样本未采集，无新增 Verified；
2. `CON_EXPIRY` 仍 Candidate，根因报告待真实样本；
3. GitHub Required Checks 需管理员配置；
4. SM-013 BLOCKED、SM-018 真实 Provider NOT_RUN、SM-019 真实回测 NOT_RUN 维持；
5. `downgrade base` 仍不可用（历史迁移 + 真实重复 scan_id）。
