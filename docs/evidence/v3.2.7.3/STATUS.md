# V3.2.7.3 执行状态（真实命令与输出）

执行时间：2026-11-25（Asia/Shanghai）
分支：`codex/v3.2.7.3-write-safety`（worktree `scoutmind-v3273`，基点 `origin/main` = `6aaaa31`）
合并状态：**未合并 main，未创建 Release，未删除分支。**

## 1. 环境

| 项 | 值 |
|---|---|
| OS | Windows |
| Python | 3.13（系统解释器，`backend/.venv` 不存在） |
| 数据库（自动化） | SQLite 文件库（pytest 用 `tmp_path`） |
| PostgreSQL 16 | NOT_RUN（本机无实例）；由 `.github/workflows/ci.yml` 的 `postgres-migrations` job 覆盖 |
| 真实 FM27 游戏 | NOT_RUN（无游戏环境） |
| .NET | 10.0.x |
| Node | 22（`npm ci` + `npm run build`） |

## 2. 后端测试

```powershell
cd backend
python -m pytest --junitxml=pytest-v3273.xml -q
```

结果（JUnit XML 解析，`-q` 不打印汇总行）：

```text
tests=565  failures=0  errors=0  skipped=3  time=382.728s
```

其中 3 个 skipped 为既有 PG/环境依赖用例（无 `SCOUTMIND_PG_TEST_URL` 等），不是本版本新增跳过。

本版本新增 23 个用例（均通过）：

| 文件 | 用例数 | 覆盖 |
|---|---|---|
| `tests/test_write_fencing.py` | 5 | 当前代次提交、切换后 stale fence 回滚、会话被取代、operation 重放、身份切换 |
| `tests/test_session_epoch.py` | 5 | start 绑定代次、switch 递增/失效/心跳 409、心跳不复活、4 线程并发 switch、404 |
| `tests/test_unified_import_identity.py` | 9 | legacy 路径与审计、legacy 可关闭、gated 缺上下文 409、有效上下文写入、多入口、跨存档、切换后旧上下文、新会话代次 |
| `tests/test_import_concurrency.py` | 4 | 导入窗口内切换（真实第二连接）、并发导入、同 operation 并发、并发 start |

```powershell
python -m pytest --collect-only -q tests/test_write_fencing.py tests/test_session_epoch.py tests/test_unified_import_identity.py tests/test_import_concurrency.py
# tests/test_import_concurrency.py: 4
# tests/test_session_epoch.py: 5
# tests/test_unified_import_identity.py: 9
# tests/test_write_fencing.py: 5
```

## 3. 迁移（SQLite 往返）

```powershell
cd backend
$env:SCOUTMIND_DATABASE_URL="sqlite:///./mig-check.db"
python -m alembic upgrade head
python -m alembic downgrade -1
python -m alembic upgrade head
python -m alembic current
```

输出：`e1c9a7b3d452 (head)`；三次命令全部成功，无异常。临时库已删除。

## 4. Agent

```powershell
cd desktop-agent
dotnet test tests\ScoutMind.Agent.Tests\ScoutMind.Agent.Tests.csproj
```

结果：**31 / 31 通过，0 失败**。

## 5. 前端

```powershell
cd frontend
npm ci
npm run build
```

结果：`✓ built in 8.70s`（`vue-tsc` 类型检查 + vite 构建均通过）。

## 6. NOT_RUN（不得写 PASS）

| 项 | 原因 | 后续 |
|---|---|---|
| PostgreSQL 16 迁移与行级并发语义 | 本机无 PG16 实例 | CI `postgres-migrations` job（`scripts/pg_migration_validation.py` + `tests/test_pg_migrations.py`）在 PR 上验证 |
| 真实 FM27 游戏内 A→B 切换 + 游戏内采集 | 无游戏环境 | 需人工按 `docs/evidence/v3.2.7.3/FINAL-REPORT.md` §G 步骤验收 |
| 网络层真实断线重连 | 无法在本机自动化复现 | 服务端语义已由 operation 幂等测试覆盖；UI/网络层 NOT_RUN |

## 7. 本次改动文件

新增：

```text
backend/alembic/versions/e1c9a7b3d452_write_safety_gate.py
backend/app/services/write_safety.py
backend/tests/write_safety_support.py
backend/tests/test_write_fencing.py
backend/tests/test_session_epoch.py
backend/tests/test_unified_import_identity.py
backend/tests/test_import_concurrency.py
docs/evidence/v3.2.7.3/{PHASE-0-AUDIT,PR7-SECURITY-AUDIT,IMPORT-ENTRYPOINT-MATRIX,TEST-MATRIX,STATUS,FINAL-REPORT}.md
```

修改：`backend/app/{models,schemas,config}.py`、`backend/app/services/save_identity.py`、
`backend/app/ingestion/{importer,attributes}.py`、`backend/app/clubs/resolver.py`、
`backend/app/api/{routes_core,routes_capture,routes_save_identity}.py`、
`backend/tests/test_save_identity_api.py`、`desktop-agent/ScoutMind.Agent/{AgentApplication,BackendClient}.cs`、
`frontend/src/types/saveIdentity.ts`、`frontend/src/views/SaveIdentityView.vue`。

未改历史 migration；`d4b7c1e2f9a3` 及之前的迁移文件保持原样。
