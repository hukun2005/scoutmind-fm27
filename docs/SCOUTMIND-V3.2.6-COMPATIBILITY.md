# ScoutMind FM27 V3.2.6 兼容性矩阵

| 项 | 已验证 | 说明 |
| --- | --- | --- |
| Windows | Windows 11（本机） | 其他版本未测 |
| .NET | 10（SDK 10.0.404） | Reader/Agent 自包含发布 |
| FM27 版本 | 27.1.0 | — |
| Steam Build | **26620374** | 布局 `FM27_1` |
| game_plugin | 27.1 / 27.1.0+2505117 | 兼容清单已登记 |
| Reader | 0.1.0（本分支） | 新增 world-date / date-read 等 |
| Agent | 0.1.0 | 未改动 |
| 数据库 | SQLite（WAL）/ PostgreSQL 16 | CI 覆盖 PG16 迁移 |
| Alembic 头 | `b7e2c9d4a105` | 本轮无新迁移 |
| 前端 | Vue 3 + Element Plus | 构建通过 |

## 未验证

- 其他 FM27 Build（含未来补丁）；
- 其他 Windows 区域设置（日期/时间格式）；
- 多存档真实切换；
- 安装包安装/升级/卸载。

**不得把未验证的 Build 写成兼容。**
