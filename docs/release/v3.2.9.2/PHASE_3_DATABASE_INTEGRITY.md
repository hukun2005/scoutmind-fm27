# Phase 3：数据库与数据完整性检查（V3.2.9.2）

- 数据库：SQLite（默认）/ PostgreSQL（仅 CI 验证）
- 本轮未新增或修改任何 migration
- 验证方式：真实命令执行 + 既有测试套件

## 1. 数据库初始化

| 检查项 | 结果 | 证据 |
| --- | --- | --- |
| 默认数据库路径 | `backend/data/scoutmind.db`（`config.py:32`，`sqlite:///...`） | `config.py:32` |
| 数据目录自动创建 | 是，`data_dir.mkdir(parents=True, exist_ok=True)`，同时创建 `raw/` | `config.py:102-107` |
| 首次运行初始化 | `alembic upgrade head` 可从空库建出完整 schema | 见 §2 |
| 数据库版本表 | `alembic_version = b2c3d4e5f6a7 (head)` | 实查 |
| 数据库锁 | `PRAGMA busy_timeout=30000` | `db.py:34` |
| 并发读写 | `PRAGMA journal_mode=WAL`（仅在未启用时切换，避免独占锁） | `db.py:28-32` |
| 连接关闭 | FastAPI `get_db` 依赖负责 `close()` | 既有测试 |
| 异常恢复 | 解析失败/中断导入不破坏已有数据 | 见 §5 |

## 2. Migration

- migration 文件共 24 个，线性升级到 head `b2c3d4e5f6a7`。
- 空库初始化为 head：

```
python -m alembic upgrade head
INFO  Running upgrade a1b2c3d4e5f6 -> b2c3d4e5f6a7, V3.2.9.2 identity review concurrency and audit
```

- 重复启动（再次执行 `upgrade head`）：无任何迁移执行，退出 0（幂等）。
- 回滚再升级：

```
python -m alembic downgrade -1   # b2c3d4e5f6a7 -> a1b2c3d4e5f6
python -m alembic upgrade head   # a1b2c3d4e5f6 -> b2c3d4e5f6a7
python -m alembic current        # b2c3d4e5f6a7 (head)
```

- 结果：升级 → 重复升级 → 回滚 → 再升级，全部成功；旧库升级路径由 CI 的 `Migration round-trip on a fresh database` 与本地同等命令覆盖。
- 未修改任何已发布 migration（`git diff origin/main -- backend/alembic` 为空）。

## 3. 索引与约束

- 空库升级后：**60 张表、195 个索引**（其中 155 个显式 `ix_*` 命名索引）。
- 关键索引抽样（与性能核心相关）：
  - `ix_transfer_save_date`（`fm_save_id`, `transfer_date`）
  - `ix_candidate_save_status`
  - `ix_capture_save_date`、`ix_capture_save_status`
  - `ix_canonical_save_status`、`ix_canonical_action_save_canonical`
  - `ix_cross_save_save_status`、`ix_assignment_save_club`
  - `ix_conflict_actions_conflict`、`ix_alerts_fm_save_id`、`ix_alerts_player_instance_id`
- 唯一约束（由既有测试覆盖）：导入任务按存档唯一（`c3f0f7a92b14`）、存档身份、候选人确认、审核操作幂等键。

## 4. 存档隔离与身份治理

| 验证点 | 结果 |
| --- | --- |
| 不同存档数据隔离 | PASS（含本轮新增 `test_transfers_are_isolated_per_save`） |
| Save Identity Binding | PASS（既有 `test_sm_phase1.py` 等） |
| Player/Club Identity | PASS（既有用例） |
| Verified 生命周期与 generation | PASS（PR #14 证据 `docs/evidence/v3.2.9.2/`） |
| Conflict / Ambiguous 状态 | PASS（既有用例） |
| 审核并发保护（乐观锁） | PASS（`e8b62eb` 用例） |
| 历史转会关联 | PASS（`test_p2_data_quality.py`） |

## 5. 数据导入可靠性

| 场景 | 结果 |
| --- | --- |
| 重复导入同一份扫描 | PASS，返回 `duplicate=true`，不产生重复业务数据 |
| 重复扫描 / 同存档多次扫描 | PASS（快照维度幂等） |
| 中断恢复 | PASS（导入任务状态与 stale running 处理由既有用例覆盖） |
| 不同存档切换 | PASS（PR #14 A/B/A + 本轮隔离用例） |
| 部分导入失败 | PASS（既有用例，失败不写入半成品） |
| 导入后一致性 | PASS（`scripts/data_coverage_report.py` 三层对账，历史真实数据 0 未解释偏差） |

## 6. 本轮执行的测试

```
python -m pytest -q -k "duplicate or idempotent or isolation or save_switch or cross_save"
83 passed
```

## 7. 未执行项与限制

| 项 | 状态 | 原因 |
| --- | --- | --- |
| 本地 PostgreSQL 迁移 | NOT_RUN | 本机无 PostgreSQL 实例 |
| CI PostgreSQL 迁移 | PASS | `PostgreSQL migration compatibility` 作业（main run `45813033668`、PR #15 run `45814296148`）绿 |
| 真实存档升级（44k 球员） | NOT_RUN（本轮） | 使用干净库验证 schema；真实库升级在 PR #14 证据中已记录 |

状态：**PASS（本地 PG 标记 NOT_RUN）**
