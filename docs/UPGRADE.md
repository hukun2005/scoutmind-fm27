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

## V2 升级（2026-11）

- 新增迁移 `ba679f76cb1b`：`tactical_profiles`、`player_statistics`、`scouting_reports`、
  `recruitment_shortlists`、`recruitment_shortlist_items`、`ai_reports`。只新增表与索引，不改写既有数据。
- 协议 `1.0` 兼容扩展：`player.statistics[]`（赛季统计块）、`transfer_type=loan_with_option`、
  `fee_components[].type=buy_option`、`player.age`（数据源直接给年龄时使用）、`source=fmsuperscout`。
  旧报文不写这些字段时行为不变，缺失即标记为不可用。
- 新增 FMSuperScout 适配层（`app/ingestion/adapters`），导入入口 `/imports/fmscout`，`/imports/scan` 同时支持自动识别。
- 旧演示数据库可直接迁移；重新生成演示数据用 `python scripts/seed_demo.py --force`。

## 回滚

```powershell
cd backend
python -m alembic downgrade -1     # 回退一步
python -m alembic current          # 查看当前版本
```

回滚不会恢复被删除的业务数据，只能恢复结构；数据恢复依赖第 1 步的备份。
- 迁移 `fd65d0d5f75d`：新增 `player_availability`、`loan_records`、`transfer_candidates`，并给 `player_snapshots`
  增加 `height_cm`、`foot`、`world_reputation`。只新增表与列。
- 协议 `1.0` 再扩展：`player.availability` / `player.ownership` / `player.agreed_transfer` 三个可选块，
  `status` 增加 `agreed`、`bid_rejected`，`transfer_type` 增加 `loan_buyout`。
- 新增 `POST /imports/transfers`（历史交易独立通道）与 `GET /players/{id}/status`、`/transfers/candidates*`。
- 演示数据重建：`python scripts/seed_demo.py --force`（现在包含挂牌、伤病倾向、一笔租借与一笔已达成未生效转会）。
