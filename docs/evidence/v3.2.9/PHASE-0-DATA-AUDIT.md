# V3.2.9 全库身份数据审计（Phase 0）

日期：2026-11-26
状态：工程审计 **PASS**；真实 FM27 全库统计 **NOT_RUN**。

## 1. 审计方法

- 静态审计：`backend/app/models.py`、`backend/app/ingestion/*`、`backend/app/services/*`、`backend/alembic/versions/*`。
- 运行审计：`backend` 全量 pytest（结果见 TEST-MATRIX）、SQLite 迁移实测。
- 真实环境：只读进程检查。
- 历史数字全部标注为「历史」，不复制成当前结果。

## 2. 当前真实环境

| 项目 | 值 | 来源 |
| --- | --- | --- |
| FM27 进程 | 运行中，pid 72012 | 本机只读进程检查 |
| 游戏构建 | 26620374 | V3.2.8.1 证据（本次未重新读取） |
| 插件版本 | 27.1 | 同上 |
| 布局 | FM27_1 | 同上 |
| 当前存档身份指纹 | `si:v1:file:b887415a…`（脱敏） | V3.2.8.1 证据（本次未重新读取） |

## 3. 数量关系（必须分开统计）

| 概念 | 表 | 本次真实值 |
| --- | --- | --- |
| Person 候选 | 由 live reader 决定，不落库 | NOT_RUN |
| 属性记录 | `player_snapshots` + `player_attribute_values` | NOT_RUN |
| UID | `player_instances.save_local_uid` / `player_uid_observations` | NOT_RUN |
| Canonical Player | `players` | NOT_RUN |
| 当前存档球员 | `player_instances` | NOT_RUN |

不能假设 Person 数量 = 属性记录数量 = UID 数量。V3.2.9 的扫描统计只从数据库真实行计算，不在内存里估算。

## 4. 数据库统计口径（实现后可用）

| 指标 | 计算方式 |
| --- | --- |
| Person 总数 | `count(players)` |
| 存档内实例 | `count(player_instances where fm_save_id=?)` |
| 唯一 UID | `count(distinct save_local_uid)` |
| 重复 UID | 按 UID 分组后 `count(distinct player_id) > 1` 的组数 |
| 缺失 UID | 观测状态 `Missing` |
| 姓名读取成功 | 数据库层不单独统计；由快照/导入报告提供 |
| 出生日期成功 | `players.birth_date is not null` |
| 属性关联成功 | 扫描中 `matched_count` |
| 冲突数 | `conflict_count` + 审核条目数 |
| Verified / Stale / 未验证 | 本层不生产 Verified；Stale 由 `mark_save_links_stale` 产生 |

## 5. 模型审计结论

| 概念 | 现有实现 | 结论 |
| --- | --- | --- |
| 球员实体 | `players` | 复用为 Canonical 主表 |
| 存档内实例 | `player_instances`（`fm_save_id + save_local_uid + uid_occurrence` 唯一） | 已是存档内 UID 作用域 |
| 身份匹配审计 | `identity_matches` | 保留 |
| 身份冲突 | `identity_conflicts` + `identity_conflict_actions` | 保留；V3.2.9 新增强化队列 |
| 观测 canonical | `player_observation_canonicals` | 与 Canonical Player 不是同一概念 |
| 未解析球员 | `unresolved_player_candidates` 等 | 保留 |
| 转会候选 | `transfer_event_candidates` | 保留 |
| 存档身份 | `save_identities` / `save_sessions` | 复用 |
| UID 观测 | **新增** `player_uid_observations` | 本次实现 |
| 身份关联 | **新增** `player_identity_links` | 本次实现 |
| 审核队列 | **新增** `player_identity_review_items` / `_actions` | 本次实现 |
| 批次状态 | **新增** `identity_scan_runs` | 本次实现 |
| 跨存档候选 | **新增** `cross_save_identity_candidates` | 本次实现 |

## 6. 未解决问题

1. 真实全库 Person / 属性记录 / UID 统计：NOT_RUN。
2. 真实重复 UID 与同名冲突数量：NOT_RUN。
3. 真实跨存档 A/B/A：NOT_RUN。
4. PostgreSQL 实机迁移：NOT_RUN（未配置 `SCOUTMIND_PG_TEST_URL`）。

以上未解决问题不阻塞工程合并判断，但意味着真实数据验收只能是 PARTIAL。
