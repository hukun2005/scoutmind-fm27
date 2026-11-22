# ScoutMind FM27 V3.2 Phase 1 — SM-061B 阶段报告

- 分支：`codex/scoutmind-v3.2-field-capture`
- 基线：`00ef014`（SM-066A 完成后）
- 日期：2026-11-22
- 范围：**SM-061B 历史快照去重与数据治理**
- 状态：**PASS**（治理机制/迁移/测试）；真实冲突仍 **PARTIAL**（36,556 组待人工确认）

## 1. 修改前审计

- `PlayerSnapshot` 只按 `(player_instance_id, observed_at)` 唯一，同一 `game_date` 可有多条；
- 已有规则引擎报告 35,468 组同日内容冲突、93,500 行重复，但没有 canonical 决策表；
- 没有删除任何历史快照，也没有“选择哪条作为成长输入”的可追溯记录。

## 2. 技术方案

新增独立 canonical 映射，**不删除、不改写原始快照**：

- 表 `player_observation_canonicals`：每个 `(save, player_instance, game_date)` 一条；
- 内容完全一致的重复扫描 → `resolved`，canonical 取最后观测；
- 内容不一致 → `needs_review`，`canonical_snapshot_id = NULL`，保留全部原始快照；
- 单条观测也记录为 `resolved`，便于后续时间轴使用；
- `POST /data-quality/canonical/scan` 默认 `dry_run=true`，显式 `false` 才写入；
- `GET /data-quality/canonical/summary` / `GET /data-quality/canonical` 只读查看。

## 3. 修改文件

| 文件 | 变更 |
| --- | --- |
| `backend/app/models.py` | 新增 `PlayerObservationCanonical` |
| `backend/alembic/versions/c8d2e5f7a013_canonical_observations.py` | 新表/唯一约束/索引 |
| `backend/app/quality/dedup.py` | canonical 评估/写入/摘要 |
| `backend/app/api/routes_quality.py` | scan/summary/list 接口 |
| `backend/tests/test_sm061b_canonical_governance.py` | 5 项测试 |
| `scripts/pg_migration_validation.py` | 新 head 与新表检查 |

## 4. 数据库变更

新增表 `player_observation_canonicals`：

- 外键：`fm_save_id → fm_saves`、`player_instance_id → player_instances`、`canonical_snapshot_id → player_snapshots`（可空）；
- 唯一：`(fm_save_id, player_instance_id, game_date)`；
- 字段：status、conflict、snapshot_count、distinct_content_count、reason、时间戳；
- 未修改/删除任何原始快照；未修改历史迁移。

SQLite 空库 `upgrade → downgrade -1 → upgrade` 成功；真实库已备份
`backend/data/backup-before-sm061b-20261122.db` 并升级到 `c8d2e5f7a013`。

## 5. 真实数据 dry-run

save 2：

| 指标 | 值 |
| --- | --- |
| groups | 54,570 |
| resolved（单条或内容一致） | 18,014 |
| needs_review（同日内容冲突） | **36,556** |
| duplicate_rows | 93,500 |
| written（dry-run） | 0 |

**未在真实库写入 canonical**：默认 dry-run，避免未经人工确认的 36,556 个冲突被自动“选中”。

## 6. 自动化测试

`backend/tests/test_sm061b_canonical_governance.py`（5 项）：

- dry-run 不写任何行；
- 内容一致 → resolved + 取最后观测；内容冲突 → needs_review + canonical NULL；
- 原始快照 4 条全部保留；
- 重跑幂等；
- 跨存档隔离；
- API dry-run/写入/摘要/列表。

本地：**5 passed**；全量后端见下。

## 7. 代码审查

- 原始快照只读：deps/服务不执行 DELETE/UPDATE snapshot；
- 冲突不自动选 canonical，避免把错误数据送入成长分析；
- 唯一约束防重复决策；重复执行更新同一行，不新增；
- API 全部走 `get_active_save`，跨存档不可见。

## 8. 未解决问题

1. 36,556 组真实冲突尚无人工 canonical 决策；`needs_review` 会阻止其进入成长时间轴（SM-061C 需明确 fallback）；
2. 未在本轮写入真实 canonical 表，避免自动决策；
3. 内容签名只覆盖 CA/PA/工资/身价/合同/俱乐部/位置/身高/脚；属性变化暂未纳入冲突判定；
4. 前端治理页面在 SM-066C。

## 9. 状态

| 项 | 状态 |
| --- | --- |
| SM-061B 模型/迁移/服务/API | **PASS** |
| 真实冲突治理 | **PARTIAL**（36,556 组待人工） |
| 原始快照删除 | **0 条** |
| 下一阶段 SM-061C | **NOT_STARTED**（等待审查） |

## 10. CI

- run **45013051855**，提交 `4bf9241`，**success**；
- Backend、PostgreSQL 16、AI isolation、.NET、Frontend 全部 success。

完成后停止，不进入 SM-061C。
