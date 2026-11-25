# 数据库与迁移验证报告（V3.2.7.4）

- 数据库：SQLite（本地）/ PostgreSQL 16（CI）
- 迁移基线：`e1c9a7b3d452`（V3.2.7.3）
- 新增迁移：`b5d9c2e7f4a1_v3274_worker_cancellation.py`

## 1. 结论

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| SQLite `upgrade head` | **PASS** | 临时库从空库升级成功 |
| SQLite 往返（head → base → head） | **PASS** | downgrade/upgrade 对称 |
| 迁移安全检查 | **PASS** | `scripts/check_migration_safety.py` |
| PostgreSQL 16 迁移 | **PASS（CI）** | CI `postgres-migrations` job |
| PostgreSQL 16 本地执行 | **BLOCKED_BY_ENVIRONMENT** | Docker 引擎未启动、无 `psql` |
| PostgreSQL 行锁并发（本地） | **NOT_RUN** | 同上；由 CI 覆盖迁移兼容，行锁并发由 SQLite 线程测试近似验证 |

## 2. 迁移内容

`b5d9c2e7f4a1`（`down_revision = "e1c9a7b3d452"`）：

- `import_jobs.status`：`VARCHAR(16)` → `VARCHAR(32)`
  原因：新增 `cancel_requested`（16 字符恰好占满）与 `cancelled`，留出余量。
- 新增 `attempt_count INTEGER NOT NULL DEFAULT 0`；
- 新增 `cancel_requested_at DATETIME/TIMESTAMP NULL`；
- 新增 `cancelled_at DATETIME/TIMESTAMP NULL`；
- 新增索引 `ix_import_jobs_status`。

### downgrade 安全性

SQLite 无法直接收窄枚举，downgrade 先做数据迁移再收窄：

- `cancel_requested` / `cancelled` → `failed`（保留任务与审计，不删除行）；
- `queued` → `running`（旧版本没有 queued 语义）。

这保证 downgrade 不丢任务本身，也不产生非法状态值。

## 3. 执行命令

```powershell
cd backend
$env:SCOUTMIND_DATABASE_URL = "sqlite:///<临时目录>/acceptance.db"
python -m alembic upgrade head
python -m alembic downgrade base
python -m alembic upgrade head
python ..\scripts\check_migration_safety.py
```

`tools/runtime-acceptance/run_acceptance.ps1` 每次运行都会在全新临时 SQLite 上重复 `upgrade head`，
因此迁移失败会直接让一键验收失败。

## 4. 并发与事务边界

- SQLite：`tests/test_worker_cancellation.py` 使用多线程 + 独立连接：
  - 提交前取消 → 事务回滚，无半提交数据；
  - 提交后取消 → 409；
  - 领取前取消 → 直接 `cancelled`。
- PostgreSQL：行级 `UPDATE ... WHERE status = 'queued'` 的原子性由 CI 迁移与现有 PG 测试覆盖；
  本地未执行真实 PG 并发，因此**不标记 PASS**。

## 5. 未覆盖项

| 项目 | 状态 | 需要 |
| --- | --- | --- |
| 本地 PostgreSQL 并发压测 | BLOCKED_BY_ENVIRONMENT | Docker Desktop 或本机 PG 16 + psycopg |
| 生产数据规模迁移耗时 | NOT_RUN | 真实存档数据库副本（脱敏） |
