# ScoutMind FM27 V3.2 Phase 1 — SM-066A 阶段报告

- 分支：`codex/scoutmind-v3.2-field-capture`
- 基线：`fc28e92`（SM-061A 完成后）
- 日期：2026-11-22
- 范围：**SM-066A 数据质量规则引擎**
- 状态：**PASS**（规则、只读报告、API、测试、真实数据验证）

## 1. 修改前审计（摘要）

- 已有 `quality_summary` + `GET /data-quality/summary`，只提供计数字段，没有规则、严重级别、命中明细；
- 没有规则目录、不可解释“为什么这条数据不合格”；
- 真实存档 save 2 已有同日重复/冲突，但现有摘要只报 `duplicate_game_date_rows`，不区分冲突类型。

## 2. 技术方案

新增独立、确定性的只读规则引擎：

- `backend/app/quality/rules.py`：规则目录 + `run_quality_rules`；
- `backend/app/api/routes_quality.py`：
  - `GET /data-quality/rules` 规则目录；
  - `GET /data-quality/report` 执行报告（可按 import_job 过滤，校验存档归属）；
- 不修改原始 `PlayerSnapshot` / `ImportJob`；不填充缺失值；不删除任何记录；
- 复用现有快照/导入批次模型，无数据库变更、无迁移。

## 3. 规则清单

| rule_id | severity | 说明 |
| --- | --- | --- |
| missing_ca / missing_pa | warning | CA/PA 缺失 |
| missing_contract | warning | 合同到期缺失 |
| missing_market_value / missing_wage | info | 身价/工资缺失 |
| same_day_conflict | error | 同球员同 game_date 的 CA/PA/工资/身价/合同不一致 |
| duplicate_same_day | warning | 同日多快照（重复扫描） |
| negative_value | error | CA/PA/身价/工资负值 |
| stale_observation | warning | 观测日期比 game_date 晚 >30 天 |
| import_count_mismatch | warning | ImportJob.player_count 与实际实例数不一致 |
| unknown_source | info | 没有可追溯 ImportJob/source |
| empty_save | info | 没有快照 |

每条 finding 含 `rule_id`、severity、category、count、affected_player_count、message、sample_snapshot_ids、remediation。

## 4. 真实数据结果（save 2，只读）

| 指标 | 值 |
| --- | --- |
| checked_snapshot_count | 148,070 |
| severity_counts | error 1 / warning 3 / info 2 |
| same_day_conflict | **35,468 组**（CA/PA/工资/身价/合同任一不同） |
| duplicate_same_day | 93,500 行，48,089 个球员-日期组 |
| missing_contract | 21,305 |
| missing_market_value | 28,684 |
| missing_wage | 21,396 |
| stale_observation | 148,070（真实扫描日期比 game_date 晚 >30 天） |

结论：真实存档存在系统性同日冲突与时间偏差，SM-061B 治理必须先定义 canonical 规则，不能删除原始快照。

## 5. 自动化测试

`backend/tests/test_sm066a_quality_rules.py`（9 项）：

- clean save 无 finding；
- 缺失字段/负值；
- 同日重复 + 冲突区分；
- stale observation；
- import count mismatch + unknown source；
- 跨存档隔离；
- 规则执行前后行数不变（只读）；
- 规则目录/API；
- 外来 import_job 404。

本地结果：**9 passed**。

## 6. 代码审查

- 所有查询按 `PlayerInstance.fm_save_id` 过滤；`import_job_id` 必须属于当前存档；
- 报告为只读（`read_only: true`），无 INSERT/UPDATE/DELETE；
- 规则阈值集中常量（`STALE_DAYS=30`），同日常量可测试；
- 缺失与 0 分开：缺失计 missing，0 不会被当成缺失；
- 冲突判断只比较字段值，不修改/删除快照。

## 7. 未解决问题

1. `same_day_conflict` 只给组数与样本 ID，尚未定义 canonical 选择策略（SM-061B）；
2. 真实数据全部满足 `stale_observation`，需产品确认阈值（30 天）是否合理；
3. 规则阈值暂为代码常量，未做用户可配置；
4. 前端质量中心页面在 SM-066C，未开始。

## 8. 状态

| 项 | 状态 |
| --- | --- |
| SM-066A 规则引擎/API/测试 | **PASS** |
| 真实数据只读报告 | **PASS** |
| 数据库变更 | 无 |
| 下一阶段 SM-061B | **NOT_STARTED**（等待本阶段审查） |

完成后停止，不进入 SM-061B。
