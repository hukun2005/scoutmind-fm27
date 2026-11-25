# V3.2.9 全库身份关联与 Canonical 持久化设计（只设计）

## 1. 现状

- 已有 `Player`（实体）、`PlayerInstance`（存档内实例）、`IdentityMatch`（匹配审计）、
  `IdentityConflict`/`IdentityConflictAction`（冲突与人工操作）、`UnresolvedPlayerCandidate`（未解析候选）。
- 没有跨存档 Canonical Player 的持久化与审核队列。
- V3.2.8.1 已把 Verified 绑定到 Save Identity / 会话 / 构建 / 布局。

## 2. 流水线（六步，禁止跳步）

1. 候选发现（只定位，不写 Verified）。
2. 字段读取（缺失保持 null）。
3. 身份匹配（UID + 生日 + 姓名 + 其他字段）。
4. 冲突识别（多候选/同名/生日冲突）。
5. 人工审核（确认/拒绝/保留独立/待调查）。
6. Canonical 更新（仅在第 5 步之后）。

## 3. 匹配策略

优先级：存档内 UID → 出生日期 → 规范化姓名 → 其他稳定字段 → 俱乐部（仅辅助）。
禁止：只用姓名/生日/CA-PA 自动合并；字符串相似度直接合并；多候选取第一条。

状态：`NoMatch`、`SingleCandidate`、`MultipleCandidates`、`VerifiedMatch`、`Conflicted`、`Rejected`、
`PendingHumanReview`、`Stale`。`VerifiedMatch` 仍不等于 V3.2.8.1 的 Verified。

## 4. 持久化建议（合并后实现）

- 优先扩展 `Player` 作为 canonical 实体，不新建第二张主表。
- 新增 `PlayerIdentityLink`（设计稿）：
  `canonical_player_id`、`fm_save_id`、`save_local_uid`、`source_record_id`、
  `verification_status`、`confidence`、`linked_at`、`valid_from`、`valid_to`、`evidence_json`。
- 历史不覆盖：姓名/俱乐部/UID 变化、审核记录、失效原因全部追加。
- 迁移要求：新增 migration、不改已发布 migration、SQLite upgrade/downgrade/再 upgrade、PostgreSQL 兼容、
  历史数据不丢失。

## 5. 批处理与恢复

- 有界批次、每批进度与结果、可恢复、可重试、幂等。
- 保存 `scan_id`、`save_id`、`batch_id`、`cursor`、计数、`payload_checksum`、时间戳。
- 恢复前校验 Save Identity、进程、构建、布局、数据指纹；不匹配禁止复用旧指针。
- 禁止一次性扫描无限内存、禁止超长事务。

## 6. 同名冲突

同名不同生日 → `Conflicted`；同名同生日不同 UID → `PendingHumanReview`（不自动合并）；
UID 一致但其他字段冲突 → `Conflicted`。所有冲突保留原始记录与证据，追加审计。

## 7. 跨存档

使用姓名 + 生日 + 已验证历史映射 + 其他稳定字段生成候选；仅生成 `CrossSaveCandidate`，
不得直接合并 Canonical。存档隔离：A 不得覆盖 B，A 的 UID 不得成为 B 的 UID。

## 8. 历史转会关联

复用 `TransferEventCandidate` 与 `Transfer`；球员身份关联使用 `PlayerIdentityLink`。
俱乐部变化、自由球员、退役都不改变身份；租借必须区分母俱乐部/租借俱乐部/时间/类型；
附加条款不得混入基础转会费；身份不确定的交易保留待审核。

## 9. 明确未实现

本阶段未创建任何表、迁移、API、前端页面或批处理代码；全部等待 V3.2.8.1 合并后执行。
