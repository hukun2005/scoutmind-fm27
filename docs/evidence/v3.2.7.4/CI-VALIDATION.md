# CI 验证报告（V3.2.7.4）

- 仓库：`hukun2005/scoutmind-fm27`
- 审计时间：2026-11-25
- 基线：`main` @ `9a6145f`（PR #8 合并提交，head `7628c3c`）
- 本分支：`codex/v3.2.7.4-runtime-closure`

## 1. 结论

| 项目 | 状态 | 证据 |
| --- | --- | --- |
| PR #8 CI（head `7628c3c`） | **PASS** | GitHub Actions run `45546259776`，6/6 job 成功 |
| `main` 合并后 CI（`9a6145f`） | **PASS** | GitHub Actions run `45546286541`，6/6 job 成功 |
| 本地后端全量 pytest | **PASS** | 576 tests / 0 failed / 3 skipped，见 [runtime/pytest-summary.txt](./runtime/pytest-summary.txt) |
| 本地 Desktop Agent `dotnet test` | **PASS** | 见 §4 |
| 本地前端 `npm run build` | **PASS** | 见 §5 |
| 本地迁移往返（SQLite） | **PASS** | 见 [DATABASE-VALIDATION.md](./DATABASE-VALIDATION.md) |
| PostgreSQL 16（CI） | **PASS** | CI `PostgreSQL migration compatibility` job |
| PostgreSQL 16（本地） | **BLOCKED_BY_ENVIRONMENT** | 本机 Docker 引擎未启动、未安装 `psql` |
| Playwright E2E（CI） | **PASS** | CI `Playwright (governance)` job |
| Playwright E2E（本地） | **NOT_RUN** | 本机未安装 Playwright 浏览器二进制 |

> 状态口径：PASS / FAIL / PARTIAL / NOT_RUN / BLOCKED_BY_ENVIRONMENT。
> 未执行的项目不会写成 PASS。

## 2. CI 工作流覆盖

仓库 CI（`.github/workflows/ci.yml`）包含 6 个 job：

1. `backend` — Backend (pytest + migrations)：迁移往返 + pytest；
2. `security` — Upload / identity / agent isolation regressions；
3. `dotnet` — .NET readers and agent：解决方案构建、Agent 测试、Reader 单测与集成测试、兼容清单一致性；
4. `frontend` — Frontend (typecheck + build)；
5. `postgres-migrations` — PostgreSQL migration compatibility；
6. `playwright` — Playwright (governance)。

两次 run（`45546259776`、`45546286541`）的 6 个 job 均为 `success`，无跳过、无重跑成功掩盖失败。
本分支复用同一工作流；PR 创建后由 CI 重新执行，结果以 PR 页面为准。

## 3. 本地后端全量测试

执行：

```powershell
cd backend
python -m pytest -q --junitxml=..\pytest-v3274-final.xml
```

结果以 `runtime/pytest-summary.txt` 为准（本分支最终 HEAD）：

- tests = 576
- failures = 0
- errors = 0
- skipped = 3（全部为 PostgreSQL 用例：本机无 PG，以 CI job 为准）
- time = 513.75s

改动前基线（`main` @ `9a6145f`）：565 passed，3 skipped，0 failed。
改动后新增测试：

| 文件 | 用例数 | 覆盖 |
| --- | --- | --- |
| `tests/test_worker_cancellation.py` | 5 | 运行中取消回滚、领取前取消、cancelled 后新 operation 重试、重启恢复审计、HTTP 取消权限与幂等 |
| `tests/test_operation_conflicts.py` | 4 | 同 op 同内容重放、同 op 不同内容、同 scan 不同内容、rejected 重放 |
| `tests/test_identity_switch_regression.py` | 2 | F-01 身份切换回归、capture 代次栅栏 |
| 原有 `test_save_identity_api.py` 等 | — | 审计事件名对齐（`identity_verified` / `identity_conflict` / `session_created`） |

最终通过数见 `runtime/pytest-summary.txt`（XML 原始报告因体积未入库）。

## 4. Desktop Agent

```powershell
dotnet build ScoutMind.sln -c Release
dotnet test desktop-agent/tests/ScoutMind.Agent.Tests/ScoutMind.Agent.Tests.csproj
live-reader/tests/ScoutMind.Reader.Tests/bin/Release/net10.0/ScoutMind.Reader.Tests.exe
live-reader/tests/ScoutMind.FMReader.Tests/bin/Release/net10.0/ScoutMind.FMReader.Tests.exe
```

- 解决方案构建：0 错误（60 个第三方 nullability 警告，均为既有代码）；
- `ScoutMind.Agent.Tests`：38 passed / 0 failed；
- `ScoutMind.Reader.Tests`（自包含 runner）：57/57 通过；
- `ScoutMind.FMReader.Tests`（自包含 runner）：PASS 214 / FAIL 0。

本分支新增测试（`V3274AgentTests.cs`）：

- `DiagnosticsAndJobsCommandsParse`：`diagnostics` / `jobs list` / `jobs inspect` / `network status` 解析与错误分支；
- `ScanTaskContextRoundTripsAndDetectsFingerprint`：任务上下文边车往返、指纹归属、重启换会话保持 operation_id；
- `ScanTaskContextMissingOrCorruptReturnsNull`：缺失/损坏上下文必须识别为不可恢复；
- `QueueMovesContextSidecarWithTask`：claim → pending → quarantine 全程携带 `.context.json`，且上下文不被当作信封；
- `RecentJobsParseAttemptsAndRejection`：`attempt_count` / `rejected_reason` / 终态判定；
- `ProbeReportsStatusCodeWithoutBody`：后端探测路径与令牌头。

## 5. 前端

```powershell
cd frontend
npm ci
npm run build
```

`vue-tsc` 类型检查与 `vite build` 均通过。

## 6. 未覆盖项与原因

| 项目 | 原因 | 需要谁执行 |
| --- | --- | --- |
| PostgreSQL 本地行锁并发 | 本机无 Docker/psql | 具备 Docker 的机器，或直接使用 CI PostgreSQL job |
| Playwright E2E | 本机未安装浏览器二进制 | `npx playwright install chromium` 后执行 |
| 真实 FM27 A/B | 需要真实游戏与存档 | 人工执行，见 [REAL-FM27-ACCEPTANCE.md](./REAL-FM27-ACCEPTANCE.md) |

这些项目不会被标记为 PASS，也不会用模拟结果替代。
