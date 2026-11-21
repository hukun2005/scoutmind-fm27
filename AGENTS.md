# AGENTS.md — ScoutMind 工程守则

本文件约束所有在本仓库工作的 agent / 开发者。与任务书冲突时，以当前任务书的明确限制为准。

## 修改前检查

1. `git fetch --all --prune`，确认当前分支、工作区干净、最新远程 SHA；不得在未知分支上直接提交。
2. 阅读涉及的 Model、Schema、Migration、API、调用方与该模块测试；不凭字段名猜测数据库结构。
3. 数据库字段以 `backend/app/models.py` + 实际 migration 为准；两者不一致时先修 migration（新增迁移），不改历史迁移。
4. 先写测试设计/失败测试，再改实现；不删除测试、不降低断言、不跳过失败检查。
5. 不覆盖用户或其他 agent 的未提交修改；不 `reset --hard`、不 `checkout --` 丢弃他人改动。

## 数据库与迁移

- 所有 schema 变更必须有 Alembic migration；禁止修改已发布的历史 migration。
- 所有数据库变更分别验证 SQLite 与 PostgreSQL 16；本地无 PG 时必须通过 CI 的真实 PG service 验证。
- 迁移前跑 `scripts/check_migration_safety.py`；`downgrade base` 在生产/真实数据上禁止。
- 默认保留历史 `scan_id`；有损清理必须业务批准。

## AI / 工具安全

- 服务端注入 `save_id`；模型参数中的 `save_id`/`fm_save_id`/`user_id`/`session_id` 一律拒绝。
- 每个需要存档实体的工具在调用前验证 `instance_id`/`transfer_id`/`club_id`/候选等属于当前存档；越权统一返回安全错误。
- 不把 Mock/Fake Provider 说成真实联调；没有 Key 时标记 NOT_RUN。
- 工具参数必须做类型/有限性/范围/长度/枚举/未知键校验；bool 不得冒充 integer。

## 测试与 CI

- 后端：`cd backend; python -m pytest`。
- 前端：`cd frontend; npm ci; npm run build`。
- .NET：`dotnet build ScoutMind.sln -c Release`；FMReader 单测与 Reader 集成测试。
- PostgreSQL 16 migration job 必须绿；SQLite migration 往返必须绿。
- CI 失败必须读日志定位根因，不得重跑掩盖；不得跳过 required checks。
- 状态口径：`PASS` / `PARTIAL` / `FAIL` / `NOT_RUN` / `BLOCKED`；没有真实证据不得写 PASS。

## Git

- 工作分支隔离，不直接改 main；合并 main 需用户明确指令。
- 提交信息说明任务编号、改动与测试；推送后记录 CI run 链接。

## 自动检查评估

| 检查 | 状态 | 说明 |
| --- | --- | --- |
| PostgreSQL 16 migration CI | 已实现 | `.github/workflows/ci.yml` 的 `postgres-migrations` job |
| SQLite migration 往返 | 已实现 | Backend job 的 `Migration round-trip on a fresh database` |
| AI Tool Save Isolation tests | 已实现 | `backend/tests/test_sm050_ai_tool_isolation.py` |
| LLM Tool Schema tests | 已实现 | `backend/tests/test_sm051_tool_schema_validation.py` |
| ORM Schema Contract tests | 部分 | 由 PG/SQLite 迁移断言与关键列检查覆盖，尚未独立成通用契约套件 |
| GitHub Required Checks | 需管理员 | workflow 已定义 job；设为 required 必须在仓库 Settings → Branches 配置，代码无法自动完成 |

## 禁止

- 猜测字段、删除测试、降低断言、跳过 CI。
- 用 Mock 冒充真实 Provider、把 NOT_RUN 写成 PASS。
- 修改历史 migration 解决业务问题、未验证直接改 main。
