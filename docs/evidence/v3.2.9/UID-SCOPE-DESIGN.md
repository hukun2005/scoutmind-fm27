# V3.2.9 UID 作用域设计与实现

状态：**已实现**（代码 + 迁移 + 测试）。真实 FM27 全库数字见 PHASE-0-DATA-AUDIT。

## 1. 核心结论

- UID 是**存档内关联键**，不是全球永久 ID。
- 缺失 UID 不默认为 0；`4294967295` / `-1` 等哨兵不是身份。
- 不同存档中的相同 UID 不自动认定为同一球员。
- 复用既有 `SaveIdentity` / `SaveSession` / `PlayerInstance`，没有第二套存档身份系统。

## 2. 数据模型

`player_uid_observations`（只追加）：

| 字段 | 说明 |
| --- | --- |
| `fm_save_id` | 存档作用域 |
| `observation_key` | 幂等键：存档 + 指纹 + 会话 + 来源 + 实例 + 采集时间 的 SHA-256 |
| `save_identity_fingerprint` | 复用 V3.2.8.1 的存档身份指纹 |
| `session_key` | 采集会话 |
| `player_instance_id` / `player_id` | 指向实例与实体（可空） |
| `uid` | 原始文本（保留前导零 / 哨兵原值） |
| `uid_status` | `valid` / `sentinel` / `missing` / `invalid` |
| `status` | `Valid` / `Missing` / `Duplicate` / `Conflicted` / `Stale` / `Unsupported` |
| `source_type` | `live_reader` / `scan` / `dump` / `import` |
| `game_build` / `layout_version` | 版本作用域 |
| `attribute_record_digest` | 姓名 + 生日 + UID 的摘要，不含地址 |
| `evidence_hash` | 观测证据摘要 |
| `conflicting_player_id` | 重复/冲突时的另一方，仅作证据 |

唯一约束是 `(fm_save_id, observation_key)`；**没有**跨存档 UID 唯一约束。

## 3. 状态判定

| 状态 | 条件 | 处理 |
| --- | --- | --- |
| Valid | 分类为 valid，且存档内只有一个球员实体使用该 UID | 可作为存档内关联键 |
| Missing | 缺失 / 哨兵 / 0 / 非法 | 不参与匹配，保留原因 |
| Duplicate | 同存档一个 UID 对应多个球员实体 | 不自动合并，写审核条目 |
| Conflicted | UID 一致但同名/生日冲突 | 写审核条目，保留双方 |
| Stale | 所属存档身份或会话变化 | 关联失效，保留历史 |
| Unsupported | 布局/构建不支持 | 停止真实读取 |

## 4. 实现位置

- `backend/app/services/uid_scope.py`：分类、幂等观测、重复分组、统计。
- `backend/app/models.py`：`PlayerUidObservation`。
- `backend/alembic/versions/a1b2c3d4e5f6_player_identity_governance.py`：建表与索引。
- 分类规则复用 `backend/app/ingestion/uid_status.py`，未重写哨兵逻辑。

## 5. 测试

`backend/tests/test_v329_uid_scope.py`（6 项，全部 PASS）：

- 有效 UID 观测幂等；
- 哨兵 / 缺失 / 0 均为 Missing，不是 0；
- 指纹或会话变化产生新观测而不是覆盖；
- 同存档重复 UID 可检出；
- 不同存档相同 UID 不合并；
- 属性摘要不含内存地址。
