# CI 结果（V3.2.8.1 Phase 7）

## 1. 远程 GitHub Actions（PR #11，审计时）

| 检查 | 结论 | 备注 |
| --- | --- | --- |
| Backend (pytest + migrations) | SUCCESS | run 45655257130 / 45655076166 |
| Upload / identity / agent isolation regressions | SUCCESS | 同上 |
| .NET readers and agent | SUCCESS | 同上 |
| Frontend (typecheck + build) | SUCCESS | 同上 |
| PostgreSQL migration compatibility | SUCCESS | 同上 |
| Playwright (governance) | SUCCESS | 同上 |

本阶段会推送新的加固提交；推送后的 CI 结果需在 PR 页面复核，若基础设施不可用则标记
`BLOCKED_BY_INFRASTRUCTURE`，不得写成代码失败或通过。

## 2. 本地执行（本次真实结果）

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| FMReader 单元/自测 | `dotnet run -p live-reader/tests/ScoutMind.FMReader.Tests` | PASS 308 / FAIL 0 |
| Reader 集成测试 | `dotnet run -p live-reader/tests/ScoutMind.Reader.Tests` | 57 / 57 通过 |
| Agent 测试 | `dotnet test desktop-agent/tests/ScoutMind.Agent.Tests` | 38 通过 / 0 失败 |
| Backend pytest | `python -m pytest -q`（backend） | 见 `TEST-MATRIX.md` |
| 前端生产构建 | `npm run build`（frontend） | `vue-tsc --noEmit && vite build` 成功，built in 8.48s |
| 空白错误 | `git diff --check` | 退出码 0 |
| 数据库迁移 | 本阶段未新增迁移 | N/A（现有迁移由 CI 与 pytest 覆盖） |
| PostgreSQL 兼容 | 仅 CI（本地无 PostgreSQL 实例） | NOT_RUN（本地）/ SUCCESS（CI） |
| Playwright | 仅 CI | NOT_RUN（本地）/ SUCCESS（CI） |

## 3. 限制说明

- CI 的 Playwright 与 PostgreSQL 检查依赖 GitHub Actions 环境，本地未重复执行。
- 真实 FM27 验收不通过 CI 执行，见 `CROSS-SAVE-ACCEPTANCE.md`。
