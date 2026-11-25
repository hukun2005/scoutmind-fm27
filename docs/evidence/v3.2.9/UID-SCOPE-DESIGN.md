# V3.2.9 UID 作用域设计（只设计，不实现）

## 1. 原则

- UID 是**存档内关联键**，不是全球永久 ID。
- 缺失 UID 不得默认为 0；哨兵值不得当作身份。
- 不同存档中的相同 UID 不自动认定为同一球员。
- 优先复用 `SaveIdentity` / `SaveSession` / `PlayerInstance`，不建第二套存档身份系统。

## 2. 现有基础

`PlayerInstance` 已有唯一约束 `(fm_save_id, save_local_uid, uid_occurrence)`，已经表达
“同一存档内 UID 可重复出现（occurrence）”。这比“UID 全局唯一”更接近真实数据。

## 3. 建议新增（合并 V3.2.8.1 后）

`PlayerUidObservation`（观测表，只追加）：

- `id`
- `fm_save_id`（外键）
- `save_identity_fingerprint`（与 V3.2.8.1 作用域同口径）
- `person_instance_id`（外键，可空）
- `attribute_record_digest`（姓名/生日/UID 的 SHA-256，不含地址）
- `uid`（字符串保存，保留前导零与原始表示）
- `source_type`（live_reader / dump / import）
- `game_build` / `layout_version`
- `session_key`
- `observed_at`
- `confidence`
- `status`（Valid / Missing / Duplicate / Conflicted / Stale / Unsupported）
- `evidence_hash`

唯一性建议：`(fm_save_id, uid, source_type, session_key, observed_at)` 或按采集批次去重；
**不建立跨存档 UID 唯一约束**。

## 4. 状态与判定

| 状态 | 条件 | 处理 |
| --- | --- | --- |
| Valid | 存档内唯一、非 0、非哨兵 | 可作为存档内关联键 |
| Missing | 读不到/为 0 | 不得参与匹配，保留缺失原因 |
| Duplicate | 同存档多条记录同 UID | 不自动合并；全部保留，进入人工审核 |
| Conflicted | UID 一致但生日/姓名冲突 | `IdentityConflict`，不自动合并 |
| Stale | 所属 Save Identity 或会话已变化 | 禁止继续使用，保留历史 |
| Unsupported | 布局/构建不支持 | 停止真实读取 |

## 5. 测试方案

- 同存档唯一 UID / 重复 UID。
- 不同存档相同 UID（必须不合并）。
- 缺失 UID、Sentinel UID。
- UID 变化、版本变化、布局变化。
- 重复导入幂等、断点恢复。
- 并发扫描不产生重复观测。

实现前这些用例全部为 `NOT_RUN`；本阶段不创建表、不写迁移。
