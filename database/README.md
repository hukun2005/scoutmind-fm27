# 数据库

Schema 的唯一来源是 `backend/app/models.py`，迁移由 `backend/alembic` 管理。本目录只放部署说明，不放第二份 DDL，
避免两处定义漂移。

## 本地 SQLite（默认）

无需任何操作：后端启动或执行 `alembic upgrade head` 时会在 `backend/data/scoutmind.db` 建库。

```powershell
cd backend
.\.venv\Scripts\python.exe -m alembic upgrade head
```

## PostgreSQL

```powershell
docker compose up -d postgres
$env:SCOUTMIND_DATABASE_URL = 'postgresql+psycopg://scoutmind:scoutmind@127.0.0.1:5432/scoutmind'
cd backend
.\.venv\Scripts\python.exe -m pip install "psycopg[binary]"
.\.venv\Scripts\python.exe -m alembic upgrade head
```

`psycopg` 不在默认依赖里，只有使用 PostgreSQL 时才安装，避免 SQLite 用户多装一个二进制依赖。

## 迁移规范

- 每次改模型都要生成迁移：`alembic revision --autogenerate -m "..."`，人工复核生成结果。
- 迁移必须可回滚（`downgrade` 不能是空实现）。
- 破坏性变更（删列、改类型）需要先在 `docs/UPGRADE.md` 记录数据迁移步骤。
- 生产环境先备份：`backend/data/` 下的 SQLite 文件或 `pg_dump` 输出。

## 表分组

| 领域 | 表 |
| --- | --- |
| 用户与存档 | `users`、`fm_saves`、`data_sources` |
| 身份 | `players`、`player_instances`、`identity_matches` |
| 快照 | `player_snapshots`、`player_attributes`、`player_attribute_values` |
| 导入 | `import_jobs`、`import_rows` |
| 转会 | `transfer_history`、`transfer_fee_components` |
| 关注与提醒 | `watchlists`、`watchlist_items`、`watch_rules`、`alerts` |
| 评分与估值 | `score_template_versions`、`player_scores`、`player_valuations` |
| AI | `agent_conversations`、`agent_messages` |
| 版本与审计 | `algorithm_versions`、`reader_compatibility` |
