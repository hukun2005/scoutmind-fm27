# 升级与数据迁移

ScoutMind 的表结构由 Alembic 管理，升级步骤必须可重复执行且不破坏已有数据。

## 版本升级流程

1. 备份：复制 `backend/data/scoutmind.db`（SQLite）或 `pg_dump`（PostgreSQL）。
2. 拉取代码后安装依赖：`pip install -r backend/requirements.txt`。
3. 执行迁移：`cd backend && python -m alembic upgrade head`。
4. 启动后端，检查 `GET /api/v1/health`。
5. 打开「数据与诊断」页面，确认导入历史与覆盖率正常。

## 破坏性变更

删除列、修改类型、重命名表一律需要：

- 新迁移中先加新结构、回填数据、再删除旧结构；
- 在本文档记录迁移脚本与回滚方式；
- 保留至少一个版本的读取兼容（旧扫描报文仍可导入）。

## 扫描协议升级

协议版本采用 `major.minor`：

- `minor` 升级：新增字段，后端忽略未知字段并记录 warning；
- `major` 升级：后端拒绝旧报文，读取器与后端必须同步升级。

## 回滚

```powershell
cd backend
python -m alembic downgrade -1     # 回退一步
python -m alembic current          # 查看当前版本
```

回滚不会恢复被删除的业务数据，只能恢复结构；数据恢复依赖第 1 步的备份。
