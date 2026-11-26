# V3.2.9 Canonical Player Identity 持久化设计

状态：**已实现**。复用既有 `players` 作为 Canonical 主表，没有新建第二张主表。

## 1. 模型

`players`（既有）继续承担 Canonical 球员实体：`id`、`full_name`、`normalized_name`、`birth_date`、`nationality`。

新增 `player_identity_links`：

| 字段 | 说明 |
| --- | --- |
| `canonical_player_id` | 指向 `players.id` |
| `fm_save_id` | 关联所属存档 |
| `player_instance_id` | 存档内实例 |
| `save_local_uid` / `uid_occurrence` | 存档内 UID 证据 |
| `source_record_id` | 上游记录 id |
| `verification_status` | Unverified / Candidate / ConfirmedByHuman / Stale / Conflicted / Rejected |
| `confidence` | 0–1 |
| `link_key` | 幂等键（存档 + 实例 + Canonical + 生效时间） |
| `valid_from` / `valid_to` | 关联有效期 |
| `superseded_by_id` | 后继关联行 |
| `evidence_json` | 脱敏证据 |

**没有 Verified 状态**：Verified 仍由 V3.2.8.1 的 C# 作用域门控给出；本层的上限是 `ConfirmedByHuman`。

## 2. 历史保留规则

- 关联状态变化：关闭旧行（写 `valid_to`）并追加新行，`superseded_by_id` 串联。
- 人工确认不会被后续扫描降级：`ConfirmedByHuman` 对扫描写入是只读的。
- 存档切换 / 会话失效：`mark_save_links_stale` 把当前有效关联标为 `Stale` 并写失效时间，行本身保留。
- 球员、实例、观测、审核记录在任何路径下都不删除。

## 3. 人工确认

- 审核决定 `same`：为参与者在本存档内的实例写 `ConfirmedByHuman` 关联，Canonical 指向主球员。
- 跨存档确认：对两个存档分别写关联，Canonical 指向同一 `players.id`；不移动实例、不删除记录。
- 决定 `different` / `independent` / `defer`：只改审核状态并写审计，不写关联。

## 4. 审计

`player_identity_review_actions` 只追加；模型上注册了 `before_update` / `before_delete` 事件，ORM 层直接拒绝改写或删除。

## 5. 迁移

`a1b2c3d4e5f6_player_identity_governance`：

- 只新增六张表与索引/唯一约束；
- 不改任何既有表或已发布 migration；
- SQLite upgrade → downgrade → 再 upgrade 通过；
- 迁移前后既有 `players` / `player_instances` 数据保持不变（有测试断言）。

## 6. 未覆盖

- 真实 FM27 全库 Canonical 生成：NOT_RUN（需要真实扫描数据）。
- PostgreSQL 实机迁移：NOT_RUN（未配置 `SCOUTMIND_PG_TEST_URL`）。
