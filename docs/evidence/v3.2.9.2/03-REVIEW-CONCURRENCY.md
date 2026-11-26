# V3.2.9.2 阶段 3 — 审核并发、版本冲突与同名候选完整性

## 1. 修改范围

| 文件 | 变更 |
| --- | --- |
| `backend/app/models.py` | 审核条目新增 `version`；审核动作新增 `previous_version`/`new_version`/`request_key`，并加唯一约束 `uq_identity_review_action_request` |
| `backend/alembic/versions/b2c3d4e5f6a7_identity_review_concurrency.py` | 新 migration（`down_revision=a1b2c3d4e5f6`），只加列/约束，可 downgrade |
| `backend/app/services/identity_review.py` | 乐观锁 + 条件 UPDATE + 幂等键 + 版本历史 |
| `backend/app/api/routes_identity_center.py` | 透传 `expected_version` / `request_key`，返回 `version` |
| `backend/app/schemas.py` | 请求新增 `expected_version`、`request_key` |
| `backend/app/services/identity_engine.py` | `_same_name_review` 纳入全部同名参与者；重复 UID 分组只算一次 |
| `frontend/src/{api,types,views}` | 提交时携带版本；冲突后强制重新读取最新状态 |

## 2. 并发保护语义

1. 客户端读取条目时拿到 `version`，提交时必须回传 `expected_version`；
2. 服务端先 `refresh` 读取最新行，再用 **条件 UPDATE** 抢占：

```sql
UPDATE player_identity_review_items
   SET status = :target, version = :version + 1
 WHERE id = :id AND version = :version AND status NOT IN (...)
```

3. 只有一个审核者能拿到 `rowcount == 1`；后到者：
   - 已被处理 → `REVIEW_ALREADY_RESOLVED`；
   - 版本已变但未解决 → `REVIEW_VERSION_CONFLICT`（HTTP 409）。
4. 历史以追加方式记录 `previous_status/new_status/previous_version/new_version`；
   ORM 事件继续禁止 update/delete 审核动作。
5. `request_key` 幂等：同一 key 重复提交返回既有条目，不追加历史；
   并发下由数据库唯一约束兜底。
6. 失败路径（如确认同一人时写入关联失败）回滚，条目保持原版本、无历史残留。

## 3. 同名候选完整性

`_same_name_review` 不再按 `same_birth` 提前返回：

- 候选集合 = **全部同名球员**（同生日 / 不同生日 / 生日未知）；
- 原因码按整个集合的生日分布确定性计算：
  - 全部已知且相同 → `same_name_same_birth_date`
  - 全部已知且不同 → `same_name_different_birth_date`
  - 全部未知 → `same_name_unknown_birth_date`
  - 部分未知 → `same_name_mixed_evidence`
- 同一参与者集合在不同实例上产生同一条审核项（按集合去重）。

## 4. 新增测试（12 项）

`backend/tests/test_v3292_identity_review_concurrency.py`

- 并发审核只有一个写入者；
- 版本冲突返回 409 / `REVIEW_VERSION_CONFLICT`；
- 已解决条目不能被覆盖；
- 历史追加且不可改写；
- 管理员纠正产生新历史（版本 1→2→3）；
- 事务失败回滚（状态与版本不变、无历史）；
- 同一 `request_key` 幂等；
- 批量审核不得覆盖并发修改；
- 同名候选集合完整（同生日 3 人、不同生日 3 人、不同生日 2 人）；
- 证据不足进入人工审核；
- API 版本冲突返回 409。

## 5. 实际结果

```text
python -m pytest tests/test_v3292_identity_review_concurrency.py \
  tests/test_v329_identity_review.py tests/test_v329_reconciliation.py \
  tests/test_v329_transfer_identity.py tests/test_v329_migration.py -q
40 passed
```

migration 测试已更新为新的 head `b2c3d4e5f6a7`，并校验新增列存在；downgrade→upgrade 仍可往返。
