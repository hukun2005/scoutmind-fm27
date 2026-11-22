# ScoutMind FM27 V3.2.1 Phase B — SM-061E / SM-061F 报告

- 分支：`codex/scoutmind-v3.2-field-capture`
- 起始 HEAD：`30bf755`
- 日期：2026-11-22
- 范围：**SM-061E 人工 canonical 决策与审计；SM-061F 真实数据库安全写入**
- 状态：**SM-061E PASS**；**SM-061F PASS（真实写入完成，原始数据未变）**

## 1. 修改前审计

- canonical 表只有 status/canonical_snapshot_id，没有人工审核记录；
- 没有 review queue/history/decision API；
- 真实库 canonical 表为空（仅 Phase A dry-run）；
- 43,901 组冲突全部 needs_review，无法人工处置。

## 2. SM-061E 实现

### 2.1 数据模型

新增 `player_observation_canonical_actions`（追加写审计）：

- canonical_id、fm_save_id、player_instance_id、game_date
- reviewer_user_id
- action：`select_snapshot` / `exclude_game_date` / `keep_pending`
- selected_snapshot_id、previous_status、new_status
- reason、evidence_json、created_at/updated_at

canonical 表新增：`conflict_types_json`、`changed_fields_json`、`reviewed_by_user_id`、`reviewed_at`。

Migration：`d9e3f6a8b124_canonical_review_audit`（新增表/列/索引，历史迁移未改）。

### 2.2 审核规则

- `select_snapshot`：所选快照必须属于同一 PlayerInstance、同一 game_date，否则 404；
- `exclude_game_date`：整个日期组排除；
- `keep_pending`：保持 `needs_review`；
- 理由必填；相同动作/相同快照/相同理由重复提交返回 409；
- 人工 `resolved_manual` / `excluded` 不会被 `build_canonicals` 覆盖；组变化标记 `review_required`。

### 2.3 API

- `GET /data-quality/canonical/review-queue`
  - 姓名/UID 搜索、game_date、冲突类型、状态、分页；
  - 不返回全部 43,901 组；真实库 50 条查询约 0.305 s。
- `GET /data-quality/canonical/{id}/history`
- `POST /data-quality/canonical/{id}/decision`

全部接口使用 `get_active_save`；canonical/快照必须属于当前存档，跨存档 404。

### 2.4 测试

`backend/tests/test_sm061e_review.py`（7 项）：

queue 字段、选择快照、审计历史、重扫描不覆盖、重复提交 409、跨日期快照拒绝、
exclude/keep_pending、跨存档 404、API 全流程。

## 3. SM-061F 真实写入

### 3.1 写入前

- 真实库：`backend/data/scoutmind.db`
- 新备份：`backend/data/backup-before-sm061f-20261122.db`
- 备份与主库均可打开，迁移前均为 `c8d2e5f7a013`，快照 198,711 / 属性 8,734,392；
- 升级到 `d9e3f6a8b124`；
- 写入前 dry-run 与 Phase A 完全一致：groups 54,570 / resolved 10,669 / needs_review 43,901 / duplicate 93,500。

### 3.2 写入

- `build_canonicals(save_id=2, dry_run=False)`，单事务写入；
- 单条观测与内容一致重复观测自动写 resolved；
- 43,901 组冲突写 `needs_review`，`canonical_snapshot_id=NULL`；
- **没有自动选中任何冲突快照**。

### 3.3 写入后

| 指标 | 写入前 | 写入后 |
| --- | --- | --- |
| PlayerSnapshot | 198,711 | **198,711** |
| PlayerAttributeValue | 8,734,392 | **8,734,392** |
| canonical rows | 0 | **54,570** |
| resolved | 0 | **10,669** |
| needs_review | 0 | **43,901** |
| resolved_manual | 0 | 0 |
| excluded | 0 | 0 |
| audit actions | 0 | 0 |

- 重跑 `dry_run=False`：仍为 54,570 rows，无重复，原始快照/属性数不变（幂等）；
- 真实 resolved 球员（如 UID 29233529）可进入时间轴；冲突球员（UID 109160、29125842）被排除；
- 未跨存档：所有 canonical 行属于 save 2；审计 0 条。

### 3.4 备份与迁移

- SQLite 空库 `upgrade → downgrade -1 → upgrade` 通过；
- 真实库只执行 upgrade，未执行 downgrade base；
- PostgreSQL 16 迁移由 CI `postgres-migrations` job 验证；
- `check_migration_safety.py` 发现既有重复 scan_id 1 条，属于历史数据，未删除/未 downgrade。

## 4. 当前真实数据

- 43,901 组冲突仍在 `needs_review`，需要人工逐组审核；
- 真实成长分析现在可以读取 10,669 个 resolved canonical；
- 43,901 冲突组被明确排除，不会 fallback 到最后一次扫描。

## 5. 质量门禁

| 项目 | 结果 |
| --- | --- |
| 后端全量 | **403 passed, 3 skipped** |
| SM-061E 测试 | 7 passed |
| FMReader | 114 passed |
| .NET Release | 0 error |
| 前端 build | PASS |
| SQLite migration 往返 | PASS |
| PostgreSQL 16 | CI job（见提交后链接） |
| 真实写入 | PASS（备份 + 前后计数 + 幂等） |

## 6. 未解决问题

1. 43,901 组冲突尚未人工审核，不能写成“全部治理完成”；
2. 前端 Data Governance Center 未开始（SM-066C/D）；
3. `source_changed` 目前也进入 needs_review；
4. 真实写入为单事务，后续更大规模需分批；
5. `check_migration_safety.py` 报告历史重复 scan_id 1 条（非本轮产生）。

## 7. 状态

| 任务 | 状态 |
| --- | --- |
| SM-061E 人工审核/审计 | **PASS** |
| SM-061F 真实 canonical 写入 | **PASS** |
| 真实冲突人工治理 | **PARTIAL**（43,901 待审核） |
| SM-066C/D 前端 | **NOT_STARTED** |

完成后停止，不进入 Phase C。
