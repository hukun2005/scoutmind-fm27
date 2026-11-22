# ScoutMind FM27 V3.2.1 Phase A — SM-061C / SM-061D 报告

- 分支：`codex/scoutmind-v3.2-field-capture`
- 起始 HEAD：`6f4c469`
- 日期：2026-11-22
- 范围：**SM-061C Canonical 接入成长时间轴；SM-061D 完整属性签名**
- 状态：**SM-061C PASS（代码/测试）**；真实 canonical 尚未写入，真实时间轴 **PARTIAL**
- **SM-061D PASS**（属性签名/冲突分类）；真实统计见第 5 节

## 1. 修改前审计

- `build_series` 仍按 `observed_at` last-wins，不读取 `PlayerObservationCanonical`；
- `growth_report`、`development`、`forecast` 都直接读取原始快照；
- `_signature()` 不含 `PlayerAttributeValue`，也不区分 source/reader/build；
- 真实库 canonical 表为空（SM-061B 只 dry-run），因此真实成长仍不可用。

## 2. SM-061C 实现

### 2.1 Canonical-aware series

`build_series` 现在：

- 读取 `PlayerObservationCanonical`（save + instance）；
- 允许状态：`resolved` / `resolved_auto` / `resolved_manual`；
- 必须满足：canonical_snapshot_id 非空、快照属于当前存档和实例、快照 game_date 与 canonical 组一致；
- `needs_review` / `excluded` / `review_required` / 空 canonical 一律不进入时间轴；
- 无 canonical 时默认返回 `canonicalization_pending`，不使用 last-wins；
- `legacy=True` 是显式模式，结果标记 `legacy_mode=True` + `canonicalization_pending=True`。

### 2.2 SeriesBuild 新字段

`raw_snapshot_count`、`unique_game_dates`、`unique_observed_dates`、
`canonical_point_count`、`excluded_conflict_count`、`excluded_snapshot_count`、
`pending_canonical_count`、`legacy_mode`、`canonicalization_pending`。

### 2.3 下游

- `growth_report`：返回 canonical 计数与 pending/excluded；无可用 canonical 时明确 `available=False`；
- `growth_profile`（Player Development）：使用 canonical 快照；冲突组不进入；结果带 `canonicalization`；
- `forecast_player`：使用 canonical 快照；全部冲突时报 `no CA observations`；
- `backtest`：使用 canonical 快照；legacy 实例计数写入 `legacy_instances`；
- AI 工具通过上述 analytics 调用，无需单独改协议；
- `quality_summary` 保持原始快照计数（质量统计不应被 canonical 过滤）。

### 2.4 测试

`backend/tests/test_sm061c_canonical_timeline.py`（7 项）：

resolved 进入、resolved_manual 进入且重扫描不覆盖、needs_review/excluded 排除、
NULL/跨存档 canonical 快照拒绝、无 canonical 时 pending、显式 legacy、
development/forecast 排除冲突且标记 legacy。

## 3. SM-061D 实现

### 3.1 属性签名

- 批量读取 `PlayerAttributeValue` + `PlayerAttribute.key`（每 400 个快照一批，按 key 排序）；
- 每个快照的指纹是 `tuple(sorted((key, value)))`；
- 缺失属性不出现；属性值 0 仍作为真实值出现，二者不同；
- 字典输入顺序不影响签名。

### 3.2 冲突分类

`ability_changed`、`contract_changed`、`valuation_changed`、`club_changed`、
`position_changed`、`physical_data_changed`、`missing_vs_present`、`source_changed`、
`mixed_changes`。

`build_canonicals` 返回 `conflict_type_counts`、`changed_field_counts`、`sample_conflicts`（最多 20 组）。

### 3.3 人工保护

再次运行 `build_canonicals` 时，`resolved_manual` / `excluded` 不被覆盖；
若快照组发生变化，状态改为 `review_required`，保留原 canonical 与审计线索（完整审计表在 SM-061E）。

### 3.4 测试

`backend/tests/test_sm061d_content_signature.py`（6 项）：

仅 CA / 仅 PA / 单个属性 / 多属性 / 缺失 vs 0 / 属性顺序 / 合同 / 身价 / 俱乐部 / 位置 /
来源 / Reader 版本 / 重复导入幂等。

## 4. 真实数据 canonical（dry-run，save 2）

| 指标 | 值 |
| --- | --- |
| groups | 54,570 |
| resolved | 10,669 |
| needs_review | **43,901** |
| duplicate_rows | 93,500 |
| conflict_type_counts | ability 43,771 / mixed 33,684 / valuation 28,554 / contract 8,771 / physical 8,944 / position 1,987 / source 1,500 / missing 1,062 |
| 耗时 | 18.6 s（含属性批量读取） |

**未写入真实 canonical 表。**

## 5. 冲突统计统一（SM-061D 要求）

| 来源/口径 | 冲突组 | 说明 |
| --- | --- | --- |
| SM-066A 规则引擎 | 35,468 | 只比较 CA/PA/工资/身价/合同；不含属性、来源、位置/俱乐部/身高/脚 |
| SM-061B 旧签名 | 36,556 | 增加 club/position/height/foot；仍不含属性和 source/reader/build |
| **本轮统一签名** | **43,901** | 增加 **PlayerAttributeValue**、source/reader_version/game_build、missing-vs-present |

差异解释：

1. **+7,345** 主要来自属性变化（43,731 组 `attributes` 变化）；旧签名把“属性变了但 CA/合同没变”误判为一致；
2. +1,500 来源差异（fmsuperscout vs live_reader）在旧签名中不可见；
3. 新增 `missing_vs_present` 1,062 组，来自 NULL 与 0/有值混用；
4. 三个数字不是同一口径，不能强行对齐；最终报告采用统一签名 **43,901**，并保留旧数字作为历史口径。

## 6. 质量门禁

| 项目 | 结果 |
| --- | --- |
| 后端全量 | **396 passed, 3 skipped** |
| FMReader 单测 | 114 passed |
| .NET Release | 0 error |
| 前端 build | PASS |
| 数据库变更 | Phase A 无新迁移（复用 B 的 canonical 表） |
| PostgreSQL 16 | 既有 CI job（无新迁移） |
| GitHub Actions | **success**（run 45027305367，5 job 全绿） |

## 7. CI 与性能

- 首轮 Phase A CI 在 500k 行价格统计上超时（6.16s > 5s），根因为 ORM Row 构造；9ea39a7 改为 literal-bound SQL + 驱动游标，语义不变；
- 修复后 run **45027305367** **success**。

## 8. 未解决问题

1. 真实 canonical 表仍为空，真实成长时间轴返回 `canonicalization_pending`；只能在 SM-061F 安全写入后恢复；
2. 43,901 组真实冲突尚无人工审核（SM-061E）；
3. `source_changed` 目前也进入 needs_review；是否应自动忽略来源差异需产品确认（本轮未放宽）；
4. 属性批量读取在真实数据约 18.6 s，后续写入需要评估事务/分批；
5. `review_required` 状态尚未进入前端/审计表。

## 9. 状态

| 任务 | 状态 |
| --- | --- |
| SM-061C 代码/测试 | **PASS** |
| SM-061C 真实时间轴 | **PARTIAL**（canonical 未写入） |
| SM-061D 属性签名/分类 | **PASS** |
| 真实冲突统计 | **PASS（只读）** |
| SM-061E / SM-061F | **NOT_STARTED**（等待 Phase A 审查） |

完成后停止，不进入 Phase B。
