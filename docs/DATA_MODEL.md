# 数据模型：V2 规格表与实现映射

产品规格（V2）列出了一组建议表名。本文件说明 ScoutMind 实际如何落地这些能力，避免出现「表建了但没人写」的空壳。

原则：**能被推导的字段不新建表**。球员合同、身价、能力都来自追加式快照，任何时刻都能重放出历史；
新建表只用于快照无法表达的数据（赛季统计、生成物、用户配置）。

## 1. 规格表 → 实际实现

| V2 规格表 | 实际实现 | 说明 |
| --- | --- | --- |
| `players` | `players` | 跨存档的稳定身份 |
| — | `player_instances` | 球员在某个存档里的实例（规格未列，但身份与存档必须分离） |
| `player_attributes` | `player_attributes` + `player_attribute_values` | 属性字典与每次快照的读数 |
| `player_snapshots` | `player_snapshots` | 追加式快照，`(instance, observed_at)` 唯一 |
| `player_contracts` | `player_snapshots.contract_end` + `wage` | 合同是随时间变化的观测值，独立表会与快照冲突 |
| `clubs` | `clubs` | 含 `is_user_club`，阵容模块据此确定「我的球队」 |
| `competitions` | `clubs.league` | 目前只需要联赛名与级别比较，独立赛事表尚无写入方 |
| `squads` | 派生：`player_instances.club_id` | 阵容 = 本队球员的最新快照集合，不另存快照副本 |
| `player_statistics` | `player_statistics` | 新增：赛季统计块（可选，缺失即标记为不可用） |
| `matches` | 未实现 | 逐场数据需要读取器支持；表现模块把逐场窗口标记为不可用 |
| `transfers` | `transfer_history` | 已完成、金额口径与去重键见 `TRANSFER_INTELLIGENCE.md` |
| `transfer_installments` | `transfer_fee_components`（`type=installment`） | 分期是费用组件，带 `status` 与 `due_date` |
| `transfer_clauses` | `transfer_fee_components`（`type=addon/sell_on/buy_option`） | 条款同样带触发状态与条件文本 |
| `loans` | `transfer_history`（`transfer_type=loan/loan_with_option`）+ `player_statistics` | 租借是交易类型，租借费是费用组件 |
| `player_development` | 派生：`player_snapshots` | 成长速率由快照差分计算，不落重复表 |
| `scouting_reports` | `scouting_reports` | 新增：生成物的可重放副本 |
| `recruitment_shortlists` | `recruitment_shortlists` + `recruitment_shortlist_items` | 新增：候选名单与排名明细 |
| `tactical_profiles` | `tactical_profiles` | 新增：阵容评分六维权重模板 |
| `ai_reports` | `ai_reports` | 新增：AI 回答、可靠性分类与引用 |
| `data_import_jobs` | `import_jobs` + `import_rows` | 导入任务与行级拒绝记录 |
| — | `watchlists` / `watchlist_items` / `watch_rules` / `alerts` | 关注名单与提醒 |
| — | `player_valuations` / `player_scores` / `score_template_versions` | 估值与角色评分的可审计副本 |
| — | `algorithm_versions` / `reader_compatibility` / `data_sources` / `identity_matches` | 版本、兼容性与身份匹配审计 |

## 2. V2 新增表

### `player_statistics`

一行 = 一名球员一个统计周期（`scope=season`，`period` 如 `2026/27`）的赛季聚合。

- 唯一键 `(player_instance_id, scope, period)`；新观测时间更晚时覆盖计数，否则跳过（幂等）。
- 全部指标可空：数据源没有预期进球时 `xg` 为 `NULL`，不是 0。
- 指标：出场、首发、分钟、进球、助攻、射门、射正、xG、关键传球、传球尝试/成功、过人、
  抢断、拦截、解围、争顶成功、扑救、失球、零封。

### `tactical_profiles`

一行 = 一个存档的一套阵容评分权重（六列浮点 + `is_default`）。权重在读取时归一化到 1，负数按 0 处理。

### `recruitment_shortlists` / `recruitment_shortlist_items`

名单保存筛选条件与预算；明细保存名次、评分和生成时的完整 JSON，因此历史名单不会随算法变化而改变。

### `scouting_reports`

保存任意生成物的完整 JSON、方法名、算法版本与可靠性分类，用于复盘「当时为什么这么判断」。

### `ai_reports`

保存问题、结论、可靠性四分类与工具引用。AI 回答的每个数字都必须能在 `citations` 里找到对应工具结果。

## 3. 迁移

- `alembic/versions/a65960362a18_*.py`：V1 初始 schema。
- `alembic/versions/ba679f76cb1b_*.py`：V2 新增六张表（本文件第 2 节），不修改既有表。
- 迁移只新增表与索引，不改写既有数据；SQLite 下通过 `render_as_batch` 执行。

## 4. P0-2/P0-4 新增表

| 表 | 一行代表 | 关键规则 |
| --- | --- | --- |
| `player_availability` | 某个球员在某个观测时刻的挂牌/伤病/注册状态 | 与快照同频追加；全部字段三态（`NULL` = 数据源未提供）；`(instance, observed_at)` 唯一 |
| `loan_records` | 一段租借关系 | 原属俱乐部与租借俱乐部都记录；`has_option`/`has_obligation` 缺失即 `NULL`；`(save, source_record_id)` 唯一 |
| `transfer_candidates` | 一次快照对比发现的俱乐部变化 | 只是候选：`status=candidate`，确认后生成/关联交易，误报标记 `dismissed` |

补充说明：

- `player_snapshots` 新增 `height_cm`、`foot`、`world_reputation`：来源直接给出画像字段时落库，缺失保持 `NULL`。
- `transfer_history` 的 `status` 增加 `agreed`（已达成未生效）与 `bid_rejected`（报价被拒绝）；`transfer_type` 增加
  `loan_buyout`（租借买断）。`agreed`、`bid_rejected` 既不进价格统计也不计支出。
- 迁移 `fd65d0d5f75d` 只新增表与列，不改写既有数据；SQLite 下仍以 batch 模式执行。

## 5. 俱乐部解析相关表（2026-11 新增）

`clubs` 增列：

| 列 | 含义 |
| --- | --- |
| `normalized_name` | 归一化名称（去大小写/重音/标点），用于合并"只有名字"和"带 ID"的记录 |
| `source` | `payload_clubs` / `player_club_field` / `squad_csv` / `manual` |
| `confidence` | 渠道固定可信度（1.0 / 0.6 / 0.9 / 1.0） |
| `external_ids_json` | 上游 ID（如 FMSuperScout 的 uid），用于后续升级匹配 |

`fm_saves` 增列：

| 列 | 含义 |
| --- | --- |
| `user_club_id` | 主执教俱乐部。**故意不加外键**：与 `clubs.fm_save_id` 形成环，SQLite 无法建表；归属由解析器校验 |
| `user_club_source` | `manual` / `payload`，记录本队是怎么定下来的 |

新表 `squad_assignments`（阵容归属，来自 CSV 或手动）：

| 列 | 含义 |
| --- | --- |
| `fm_save_id` / `player_instance_id` | 归属对象；`UNIQUE(fm_save_id, player_instance_id, source)` 保证重复导入幂等 |
| `club_id` / `club_name_raw` | 解析到的俱乐部与 CSV 原文 |
| `squad_type` | `senior` / `reserve` / `youth` / `unknown` |
| `loan_status` | `none` / `loaned_out` / `loaned_in` / `unknown` |
| `source` / `confidence` | 来源与匹配置信度 |
| `observed_at` / `raw_json` | 观测时间与原始行，便于回溯 |
