# V3.2.9 全库球员身份关联设计与实现

状态：**已实现**（服务、API、批处理、迁移、测试）。

## 1. 六步流水线（不可跳步）

1. **候选发现**：只读取 `player_instances` 的 id / player_id / uid / 姓名 / 生日元数据。
2. **字段读取**：缺失保持 NULL，不补 0、不猜生日。
3. **身份匹配**：存档内 UID 优先；同名 / 同生日只用于判定冲突，不用于合并。
4. **冲突识别**：同名、重复 UID、同名同生日不同 UID 全部进入审核。
5. **人工审核**：确认同一人 / 不同人 / 保留独立 / 暂缓。
6. **Canonical 更新**：只有第 5 步之后才写 `ConfirmedByHuman` 关联。

扫描阶段最多写到 `Candidate` / `Conflicted` / `Unverified`，**永不写 Verified**。

## 2. 有界批处理

`identity_scan_runs` 保存批次状态：

- `scan_id`（存档内唯一，幂等重放）
- `status`：Queued / Running / Paused / Completed / Failed / Cancelled
- `cursor`：已处理的最大实例 id
- `total_instances` / `processed_count` / `matched_count` / `conflict_count` / `failed_count`
- `payload_checksum`：存档 + 指纹 + 构建 + 布局 + 实例规模的作用域摘要
- `save_identity_fingerprint` / `game_build` / `layout_version`
- `started_at` / `finished_at` / `error_code` / `error_message`

每批：

1. 按 id 游标取 `batch_size` 条（上限 1000）；
2. 逐条记录 UID 观测、判定冲突、写候选关联；
3. 更新游标与计数；
4. **提交一次**，然后进入下一批。

单行失败只累加 `failed_count`，不拖垮整批。

## 3. 断点恢复

- 恢复前比较当前实例规模与创建批次时的规模：不一致 → `Failed` + `BATCH_CHECKSUM_MISMATCH`，不复用旧进度。
- 恢复时必须携带当前存档身份指纹 / 构建 / 布局：不一致 → `Failed` + `SAVE_IDENTITY_MISMATCH`。
- 旧指针（实例 id 之外的内存地址）从不持久化，因此不存在跨进程复用。

## 4. 同名冲突

| 场景 | 结果 |
| --- | --- |
| 同名 + 同生日 + 不同 UID | `Conflicted`，审核条目 `same_name_same_birth_date` |
| 同名 + 不同生日 | `Conflicted`，审核条目 `same_name_different_birth_date` |
| 同名 + 至少一方生日未知 | `Conflicted`，审核条目 `same_name_unknown_birth_date` |

同名条目按「参与者集合」生成幂等键，双方各扫一次不会产生两条。

## 5. 重复 UID

同一存档内一个 UID 对应多个球员实体时：

- 观测状态置为 `Duplicate`；
- 生成 `uid_duplicate` 审核条目，保留全部球员 id；
- 不合并、不删除任何实例。

## 6. API

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | `/identity/center/summary` | 全库统计与治理状态 |
| GET | `/identity/center/queue` | 审核队列（分页/筛选） |
| GET | `/identity/center/queue/{id}` | 条目详情与历史 |
| POST | `/identity/center/queue/{id}/resolve` | 提交决定 |
| GET | `/identity/center/players/{id}` | 球员身份详情 |
| GET | `/identity/center/uid-map` | UID 作用域映射 |
| GET | `/identity/center/cross-save` | 跨存档候选 |
| POST | `/identity/center/cross-save/{id}/review` | 跨存档人工决定 |
| GET | `/identity/center/history` | 审核历史 |
| POST/GET | `/identity/scans` | 创建/列出扫描 |
| GET | `/identity/scans/{id}` | 扫描详情 |
| POST | `/identity/scans/{id}/pause\|resume\|cancel` | 状态控制 |
| POST | `/identity/transfers/link` | 补齐转会身份关联 |

## 7. 实现位置

- `backend/app/services/identity_engine.py`
- `backend/app/services/identity_review.py`
- `backend/app/api/routes_identity_center.py`
- `backend/tests/test_v329_reconciliation.py`（8 项）
- `backend/tests/test_v329_identity_review.py`（8 项）
