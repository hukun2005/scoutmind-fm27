# ScoutMind FM27 V3.1.5 实施报告

- 仓库：`hukun2005/scoutmind-fm27`
- 分支：`codex/scoutmind-v3.1.5-field-evidence`
- 基线：`94ccfc9`（开始前 fetch 确认，main 未改动）
- 范围：**SM-055 ～ SM-060**
- 日期：2026-11-21
- 状态口径：`PASS` / `PARTIAL` / `FAIL` / `NOT_RUN` / `BLOCKED`

## 总览

| 编号 | 任务 | 状态 |
| --- | --- | --- |
| SM-055 | Field Evidence 异常判定机制 | PASS |
| SM-056 | FieldSpec 独立验证策略 | PASS |
| SM-057 | FM27 真实字段采样工具 | PASS（工具结构）；真实采集 NOT_RUN |
| SM-058 | Player Longitudinal Intelligence | PASS（复用现有模型，无新迁移） |
| SM-059 | 成长回测与质量报告 | NOT_RUN（真实存档只有 1 个 game_date） |
| SM-060 | 自动化数据质量监控 | PASS |

---

## SM-055 Field Evidence 异常判定机制 — PASS

### 修改文件

- `live-reader/ScoutMind.FMReader/Evidence/FieldEvidence.cs`
- `live-reader/tests/ScoutMind.FMReader.Tests/StabilityTests.cs`

### 规则

1. 单次/少量异常不再直接 Rejected：异常比例在字段 `AllowedMismatchRate` 内 → **Candidate + NeedsReview**；
2. 超过允许比例，或同一异常在 ≥3 个独立观测重复出现（系统性）→ **Rejected**；
3. 记录 `MatchCount`、`MismatchCount`、`ObservedMatchRate`、`MissingSampleCount`；
4. `Anomalies` 保留每条异常的 raw/expected/observed/object/simulated；
5. 缺失样本与不匹配样本分开计数；
6. `EvidenceClass` 区分 `real` / `simulated` / `missing-only` / `none`；
7. 未达门槛最高 Candidate；`Rejected` 不再仅由单个 mismatch 触发。

### 测试

100 全一致、100 中 1 异常、100 中 5 异常、系统性重复异常、不同对象独立异常、日期跨时区、
数值容差边界、0/0 与空值/缺失、样本不足、独立对象不足、模拟/真实区分。
FMReader 单测 **114 passed**。

---

## SM-056 FieldSpec 独立验证策略 — PASS

### 修改文件

- `live-reader/ScoutMind.FMReader/Probes/FieldValidationStrategy.cs`（新增）
- `live-reader/ScoutMind.FMReader/Probes/FieldSpecs.cs`

### 实现

`FieldSpec` 增加 `Validation`（`FieldValidationStrategy`），`FieldSpecs.Build` 为 **每个字段** 解析策略：

| 字段 | DataType | 比较 | 容差 | 最小样本/对象/观测 | 允许异常率 | Null/Sentinel |
| --- | --- | --- | --- | --- | --- | --- |
| CA / PA | Integer | numeric | 0 | 3/3/2 | 0% | 空值不计数；UI 不可见 |
| Wage | Integer | numeric | 0 | 3/2/2 | 2% | 0 需界面确认 |
| Contract Expiry | Date | date | 0 | 2/2/2 | 5% | 全 0/全 1 未设置 |
| Player DOB | Date | date | 0 | 2/2/1 | 0% | 0 未设置 |
| Name / Club / Nation | String | exact | 0 | 2/2/1 | 2% | 空字符串不计数 |
| Team type / contract status | Enum | exact | 0 | 3/2/2 | 2% | 0xFF 未定义 |
| 其他 u/int | Integer | numeric | 0 | 3/2/2 | 2% | 0 需确认 |

CA/PA 因游戏界面不可见，策略明确“最多 Candidate”；阈值写死在策略对象中并有测试断言，
不是全局共享一套容差。

---

## SM-057 FM27 真实字段采样工具 — PASS（结构）；真实采集 NOT_RUN

### 修改文件

- `live-reader/ScoutMind.FMReader/Evidence/FieldValidationCapture.cs`（新增）
- `live-reader/tools/ScoutMind.FMReader.Diag/Program.cs`（`capture` 命令）
- `live-reader/tests/ScoutMind.FMReader.Tests/StabilityTests.cs`

### 实现

1. `FieldValidationCapture` 包含 FieldId、PlayerInstanceUid、ObjectType、RawMemoryValue、
   ExpectedGameValue、GameBuild、PluginVersion、LayoutVersion、GameDate、ObservedAt、
   EvidenceSource、ValidationStatus、Simulated；
2. `FieldValidationCaptureStore` 按 `(FieldId, PlayerInstanceUid, ObservedAt)` 去重，
   同一球员同一观测时间不会重复计样；
3. 支持 JSON 与 CSV 导出，保留原始值，允许离线复核；
4. `Diag capture <dir>` 导出 `captures.json` / `captures.csv`，当前样本标记 `simulated`；
5. 不修改 Reader 扫描路径、不修改内存偏移。

### 真实 FM27 采集

本轮 FM27 未运行：真实采集 **NOT_RUN**；`capture` 输出明确 `real_fm27_capture: NOT_RUN`。
结构测试：去重、CSV 表头/字段、JSON 保留 `Simulated`。

CON_EXPIRY 仍 Candidate；采样工具已能记录原始值与界面日期，等待真实运行。

---

## SM-058 Player Longitudinal Intelligence — PASS

### 修改文件

- `backend/app/analytics/longitudinal.py`（新增）
- `backend/tests/test_sm058_longitudinal.py`（新增）

### 数据模型

复用现有 `PlayerSnapshot` / `PlayerAttributeValue` / `ImportJob`，**无新迁移**：

- `game_date` 与 `observed_at` 已分开；
- 同一 `game_date` 的重复扫描折叠为 1 个独立成长观测（最后一次观测胜出），
  同时保留 `raw_snapshot_count` / `unique_observed_dates`；
- 来源、ReaderVersion、GameBuild 从 `ImportJob` 关联，不把不同来源 CA/PA 直接拼接；
- 缺失字段保持 `None`，不填 0；
- 所有查询强制 `PlayerInstance.fm_save_id == save_id`，跨存档隔离。

### 测试

同日两次扫描只算 1 个独立点、缺失工资保持 None、跨存档拒绝、5 个 game_date 序列。

---

## SM-059 成长回测与质量报告 — NOT_RUN（真实数据）

### 实现

`growth_report`：CA growth/year、attribute growth、potential realization、stagnation、
coverage/missing rate；`growth_backtest`：按 unique game_date 排序，前 70% 日期训练、
其后验证，训练只用 cutoff 之前的数据（无未来泄漏），返回 MAE/RMSE、raw/unique 计数；
样本不足返回 `available=False`，不伪造区间覆盖率。

### 真实结果

真实存档 `save_id=2`：`raw_snapshot_count=148070`，`unique_game_dates=1`，
`unique_observed_dates=54,570` → **只有 1 个独立 game_date，无法做时间切分回测**；
返回 `available=False`。因此 SM-059 真实回测 **NOT_RUN**。

合成序列测试通过（5 个 game_date，MAE/RMSE 可计算），仅用于验证实现，**不冒充真实 FM27 结果**。

---

## SM-060 自动化数据质量监控 — PASS

### 修改文件

- `backend/app/analytics/longitudinal.py`（`quality_summary`）
- `backend/app/api/routes_core.py`（`GET /data-quality/summary`）
- `backend/tests/test_sm058_longitudinal.py`

### 内容

每次导入/存档的质量摘要：球员数、有效快照数、独立 game_date/observed date、CA/PA/合同/身价/工资覆盖率、
字段异常数、重复 game-date 行数、来源分布、game builds、ImportJob 状态；可按 `import_job_id` 追溯，
跨存档校验批次归属。

真实存档结果：54,570 名球员、148,070 快照、**1 个 game_date**、93,500 行同日重复、
CA/PA 覆盖率 100%、合同 85.6%、身价 80.6%、工资 85.6%，来源
`fmsuperscout=1,500` / `fm27_live_reader=146,570`。

---

## 质量门禁

| 项目 | 结果 |
| --- | --- |
| 后端 pytest | **361 passed, 3 skipped** |
| FMReader 单测 | **114 passed** |
| Reader 集成测试 | 全部通过 |
| .NET Release build | 0 error |
| 前端 build | PASS |
| SQLite migration | 无新迁移；现有 round-trip 保持 |
| PostgreSQL 16 | CI job（见下） |
| GitHub Actions | 见下 |

## 数据模型 / Migration

- 无新增表、无新增列、无历史迁移修改；
- 复用 `player_snapshots`、`player_attribute_values`、`import_jobs`；
- 因此本轮不需要新的 SQLite/PostgreSQL schema migration；CI 仍会跑既有迁移验证。

## CI

推送后验证：run **44916529554**，提交 4aa8d60，**success**（5 job 全绿：Backend、PostgreSQL 16、AI isolation、.NET、Frontend）。

## 未解决问题

1. 真实 FM27 字段采集 NOT_RUN（游戏未运行），`CON_EXPIRY` 仍 Candidate；
2. 真实存档只有 1 个 game_date，SM-059 无法真实回测；
3. 质量摘要显示 93,500 行同日重复，需要后续采集多 game_date 存档；
4. 属性成长测试只覆盖结构，未做真实界面核对；
5. GitHub Required Checks 仍需管理员配置。

## 下一阶段建议

1. 用至少 3 个不同 game_date 的真实存档跑通采样与回测；
2. 为 CON_EXPIRY 采集原始值 + 界面日期配对，按合同类型分层；
3. 把 `capture` 接入 Reader 扫描后的可选输出，保持扫描主路径不变；
4. 对同日重复扫描建立独立数据质量告警（当前已统计，未阻断导入）。
