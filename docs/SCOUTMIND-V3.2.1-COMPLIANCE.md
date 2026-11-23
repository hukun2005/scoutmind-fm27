# V3.2.1 任务书复核与补齐记录

- 分支：`codex/scoutmind-v3.2-field-capture`
- 复核日期：2026-11-23
- 说明：V3.2.1 主体已在 `25fd471`/`43c7e9d` 交付，并经用户明确指令合入 `main`（`eae1991`）。本记录只处理任务书逐条复核后发现的差额，不回退已合并历史，不删除原始快照。

## 1. 主体交付状态

| 任务 | 状态 | 证据 |
| --- | --- | --- |
| SM-061C Canonical 时间轴 | PASS | 10,669 resolved canonical；43,901 冲突排除 |
| SM-061D 完整属性签名 | PASS | `PlayerAttributeValue` + source/reader/build |
| SM-061E 人工审核/审计 | PASS | `player_observation_canonical_actions` 追加表 + API |
| SM-061F 真实写入 | PASS | 54,570 组；快照 198,711 / 属性 8,734,392 不变 |
| SM-066C 前端 | PASS | `/governance` + 截图 |
| SM-066D 治理操作 | PARTIAL | 导出/历史/进度/冲突统计；未开放批量自动裁决 |
| 43,901 组人工审核 | PARTIAL | 机制完成，业务审核未完成 |
| PostgreSQL 16 CI | PASS | run 45108778416 / 45112035237 |

## 2. 本轮复核发现的差额与修复

### 2.1 `reader_version_changed` 独立分类

原实现把 source/reader/build 合并为 `source_changed`。任务书要求单独返回
`reader_version_changed`，本轮已拆分：

- source 不同 → `source_changed`（changed_fields: `source`）
- reader_version 不同 → `reader_version_changed`（`reader_version`）
- game_build 不同 → `source_changed`（`game_build`）
- 同时变化 → `mixed_changes`

真实 canonical 表未重新写入；现有 43,901 组的 `conflict_types_json` 仍是旧分类。
这是**派生元数据未重算**，不是快照或决策变化；重新扫描时会按新规则生成。未自动改写
现有 needs_review 记录，避免在未审核时改变审核依据。

### 2.2 未来日期/回测与 AI 一致性测试

新增：

- `test_growth_backtest_cutoff_does_not_train_on_future`：回测 cutoff 之前训练，不把未来日期泄漏进训练；
- `test_development_matches_canonical_series`：Player Development 时间轴与 canonical series 一致。

### 2.3 分批 flush

`build_canonicals(..., batch_size=1000)` 每 1000 组 `session.flush()`，仍保持单一事务，
避免 54k 组一次性积累 ORM 对象；不改变原子性与冲突策略。

### 2.4 关键查询 EXPLAIN

SQLite `EXPLAIN QUERY PLAN`：

- review queue：`SEARCH c USING INDEX ix_canonical_save_status (fm_save_id=? AND status=?)`，排序使用 temp B-tree（limit 50，实测 0.3s）；
- canonical detail：`SEARCH s USING INDEX ix_snapshot_instance_observed (player_instance_id=?)`；
- attributes：`SEARCH v USING INDEX ix_player_attribute_values_player_snapshot_id`。

没有全表扫描进入审核队列主路径。

## 3. 测试

| 项目 | 结果 |
| --- | --- |
| 后端全量 | **406 passed, 3 skipped**（565s） |
| SM-061C/D 定向 | 15 passed |
| 前端 build（含 vue-tsc） | PASS |
| .NET Release | PASS |
| PostgreSQL 16 | 既有 main CI 已通过；本分支提交需再跑 CI |

## 4. 未解决/边界

1. 43,901 组人工审核仍未完成，状态仍是 PARTIAL；
2. 真实 canonical 表的 `conflict_types_json` 未按新 reader 分类重算（避免未审核即改变依据）；如需重算，应另做一次仅更新派生字段的受控操作；
3. 前端自动化审核 workflow 测试仍 NOT_RUN（项目无前端测试运行器）；
4. 本分支差额未合并 main；用户此前已明确合并主体，是否合并本轮差额需再次明确指令。
