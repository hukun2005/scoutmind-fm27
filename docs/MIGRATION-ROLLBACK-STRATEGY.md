# 迁移回滚策略（SM-041）

- 日期：2026-11-21
- 当前 head：`d2f7a91b64e0`
- 原则：**forward-only**。已发布的历史迁移不修改；默认保留历史 `scan_id`；不做有损自动清理。

## 1. Alembic revision 链（从旧到新）

| revision | 说明 |
| --- | --- |
| `992f85fb22b8` | import job 幂等范围改为 `(fm_save_id, scan_id)`（旧版 downgrade 会恢复全局唯一） |
| `c3f0f7a92b14` | identity_conflicts |
| `d5a1c7e04f22` | identity conflict lifecycle columns |
| `e7b2d91c4a35` | transfer statistics indexes |
| `f3a9c57e21d8` | identity conflict review audit |
| `a4d8e1f63c09` | identity conflict actions |
| `b6e2f4a70d15` | historical transfer pipeline |
| `d2f7a91b64e0` | transfer fee raw amounts |

## 2. 支持的 downgrade 边界

| 起点 → 目标 | 支持 | 说明 |
| --- | --- | --- |
| head → `a4d8e1f63c09` / `b6e2f4a70d15` / `d2f7...` | 是 | 本轮迁移可逆 |
| head → `f3a9c57e21d8` | 是 | 只删除新增表/列 |
| head → `992f85fb22b8` **之前** | **否（BLOCKED）** | 旧迁移会恢复全局唯一 `scan_id`，与真实数据冲突 |
| `downgrade base` | **否** | 同上；生产禁止尝试 |

`scripts/check_migration_safety.py` 必须先跑；任何缺表/缺列/版本异常/重复 `scan_id` 都返回**不安全**（fail-closed）。

## 3. Forward-only 数据迁移策略

1. 新需求只新增迁移，不修改已发布迁移；
2. 不删除历史 `scan_id`，不改写历史导入记录；
3. 需要改变唯一性或字段语义时：
   - 新增列/表并双写；
   - 回填后切换读取路径；
   - 旧列保留至少一个发布周期；
4. 任何需要改写历史 ID 的方案必须先获得业务批准（本轮不实施）。

## 4. 备份与恢复流程

1. 停止后端，确认无写入；
2. 用 SQLite 在线备份 API 备份（不要直接复制正在写入的库）；
3. 记录 `alembic current`、关键表行数；
4. 升级并运行 `check_migration_safety.py`；
5. 恢复：优先用备份文件替换（数据库结构回到备份时点）；
   `alembic downgrade` 只允许降级到 `992f85fb22b8` 之后。

## 5. 恢复后完整性检查

1. `alembic current` 与备份记录一致；
2. `PRAGMA foreign_key_check` 为空；
3. 关键表行数不少于备份记录（允许新增，不允许无解释减少）；
4. `import_jobs.scan_id` 非空且跨存档隔离语义仍成立；
5. `/api/v1/meta/bootstrap`、`/api/v1/transfers/coverage` 可正常返回；
6. 重新运行后端测试与权限回归。

## 6. 风险

- `downgrade base` 在有真实数据的库上必然失败，不是可选项；
- 修改历史迁移会让已有数据库的迁移历史与代码不一致；
- 自动去重 `scan_id` 会破坏导入可追溯性，默认禁止；
- PostgreSQL 上的锁表风险尚未实测（SM-040 用 CI PG 16 验证）。
