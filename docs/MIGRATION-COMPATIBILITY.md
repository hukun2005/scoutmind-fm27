# 数据库迁移兼容性调查（SM-034）

- 日期：2026-11-21
- 当前 head：`f0a2c6d81b47`
- 数据库：SQLite（真实存档副本，`backend/data/scoutmind.db`，约 1 GB）

## 1. 调查结论

| 场景 | 结果 | 说明 |
| --- | --- | --- |
| 旧库（`f3a9c57e21d8`）升级到 head | **PASS** | 升级 3 个迁移，球员/实例/快照/交易行数不变 |
| 当前 head 降一个版本再升级 | **PASS** | `d2f7 → b6e2 → d2f7` 往返成功 |
| 从 head `downgrade base` | **BLOCKED** | 在 `992f85fb22b8` 失败：`UNIQUE constraint failed: _alembic_tmp_import_jobs.scan_id` |
| PostgreSQL 16 | **PASS** | CI PostgreSQL 16.16：空库升级、旧 schema 升级、约束/外键、回滚、耗时（见 V3.1.3 报告）；本地 Docker 仍不可用 |

## 2. 旧数据库升级（真实副本）

使用 `backend/data/backup-before-identity-repair-20261120-191904.db`（版本 `f3a9c57e21d8`）的副本：

```text
Running upgrade f3a9c57e21d8 -> a4d8e1f63c09
Running upgrade a4d8e1f63c09 -> b6e2f4a70d15
Running upgrade b6e2f4a70d15 -> d2f7a91b64e0
```

升级后：

| 表 | 行数 |
| --- | --- |
| players | 106,106 |
| player_instances | 106,112 |
| player_snapshots | 198,711 |
| transfer_history | 151 |
| transfer_sources | 0 |
| transfer_import_runs | 0 |
| identity_conflict_actions | 0 |

新列 `fee_raw` / `currency_original` 存在；新表已创建，旧数据未丢失。

## 3. `downgrade base` 失败原因

`992f85fb22b8`（scope import job idempotency to `(fm_save_id, scan_id)`）的 downgrade 会把
`import_jobs.scan_id` 的唯一约束改回**全局唯一**：

```sql
INSERT INTO _alembic_tmp_import_jobs (...) SELECT ... FROM import_jobs
-- UNIQUE constraint failed: _alembic_tmp_import_jobs.scan_id
```

真实库中同一 `scan_id` 可以出现在不同存档（唯一约束是 `(fm_save_id, scan_id)`），因此该 downgrade 必然失败。

**不修改旧迁移的原因**：

- 该迁移已发布，用户可能已经执行；
- 修改它会让已有数据库的 alembic 历史与代码不一致；
- 要让 downgrade 成功，必须删除或改写重复的 `scan_id`，这会破坏历史导入记录的可追溯性。

**新增修复迁移也无法解决**：downgrade 按版本倒序执行，新迁移只能影响 head 之后的数据，无法改变
`992f85fb22b8` 自身重建表时的约束检查。

## 4. 升级前的强制检查

```powershell
cd backend
python ..\scripts\check_migration_safety.py data\scoutmind.db
```

脚本只读，输出重复 `scan_id` 组数与 `downgrade_below_992_safe`：

- `true`：仍建议先备份再 downgrade；
- `false`：禁止 downgrade 到 `992f85fb22b8` 之前，保持当前版本。

本次真实库结果：9 条导入记录、1 组跨存档重复 `scan_id` → **不安全**。

## 5. 备份与回滚方案

1. 停止后端进程，确认没有写入；
2. 备份（SQLite 在线备份 API，避免直接复制正在写入的文件）：

   ```powershell
   cd backend
   python -c "import sqlite3; src=sqlite3.connect('data/scoutmind.db'); dst=sqlite3.connect('data/backups/scoutmind-YYYYMMDD-HHMM.db'); src.backup(dst); dst.close(); src.close()"
   ```

3. 升级：`python -m alembic upgrade head`；
4. 验证：`alembic current`、`/api/v1/meta/bootstrap`、关键表行数；
5. 回滚：**只能降级到 `992f85fb22b8` 之后的版本**；如需回到更早结构，使用备份文件恢复，不要依赖 `downgrade base`。

## 6. PostgreSQL

PostgreSQL 迁移兼容性已由 CI 的真实 PostgreSQL 16 service 验证（run 44901354992）；本地 Docker daemon 不可用，无法本地复跑。
已知风险：

- 迁移大量使用 `op.batch_alter_table`（SQLite 兼容写法），在 PostgreSQL 上会直接 `ALTER TABLE`，通常可用；
- `server_default=sa.true()` 与 `Text` 类型在 PostgreSQL 上可用；
- 但 `ALTER TABLE ... ADD COLUMN ... DEFAULT` 在旧版本 PG 上可能锁表，需要在测试环境验证。

在 PG 上执行前必须先跑 `alembic upgrade head` 于空库和一份真实数据副本，并记录锁表时间。
