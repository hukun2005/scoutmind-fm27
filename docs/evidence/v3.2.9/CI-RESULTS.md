# V3.2.9 CI 结果

## 1. 运行

| 项目 | 值 |
| --- | --- |
| 工作流 | CI |
| 分支 | `codex/v3.2.9-player-identity` |
| 提交 | `80a1edd`（docs(v3.2.9): record identity governance evidence） |
| Run ID | 45749190883 |
| 触发 | push |
| 总状态 | **success** |

## 2. 作业

| 作业 | 结果 | 耗时 |
| --- | --- | --- |
| Backend (pytest + migrations) | success | 约 13 分钟 |
| PostgreSQL migration compatibility | success | 50 s |
| Upload / identity / agent isolation regressions | success | 2 m 20 s |
| Playwright (governance) | success | 1 m 11 s |
| .NET readers and agent | success | 1 m 12 s |
| Frontend (typecheck + build) | success | 49 s |

六类作业全部通过，包括：

- 新迁移在 PostgreSQL 上的兼容性（`a1b2c3d4e5f6`）；
- Backend 全量 pytest 与迁移 round-trip；
- 上传 / 身份 / Agent 隔离回归；
- Playwright 治理用例；
- .NET readers + agent（308 / 57 / 38）；
- 前端 typecheck + production build。

## 3. 告警（非失败）

GitHub Actions 提示 `actions/checkout@v4`、`actions/setup-python@v5`、`actions/setup-node@v4`、`actions/setup-dotnet@v4` 使用的 Node.js 20 已被弃用并强制运行在 Node.js 24。属于平台公告，不影响本次结果。

.NET 侧存在既有 nullable 警告（如 `MemScan.Win.cs` 的 `SnapshotError` / `ImageNote`），与 V3.2.9 改动无关。

## 4. 说明

- 本阶段没有跳过 CI、没有把未启动的 CI 写成通过。
- Playwright 治理用例为既有套件；V3.2.9 新增页面未单独增加 Playwright 用例（浏览器 E2E 标记 NOT_RUN，见 TEST-MATRIX）。
- 最终文档提交会触发一次新的 CI；若结果不同，以最新 run 为准并在 FINAL-REPORT 更新。
