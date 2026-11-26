# Phase 6：完整回归测试与安全检查（V3.2.9.2）

- 分支：`release/v3.2.9.2-stabilization`
- 所有命令在本机真实执行，结果如下

## 1. 后端

| 项目 | 命令 | 结果 |
| --- | --- | --- |
| 全量测试 | `python -m pytest -q` | **658 收集，0 失败**（退出码 0，`lastfailed` 为空） |
| 新增转会回归 | `python -m pytest -q tests/test_transfers_list_api.py` | 13 passed |
| 相关旧测试 | `tests/test_api.py`、`test_analytics.py`、`test_p2_data_quality.py`、`test_sm005_transfer_perf.py`、`test_sm_phase1.py` | 59 passed |
| 幂等/隔离 | `pytest -q -k "duplicate or idempotent or isolation or save_switch or cross_save"` | 83 passed |
| 迁移往返 | `alembic upgrade head` → 再来一次 → `downgrade -1` → `upgrade head` | PASS（幂等、可回滚） |

## 2. Native Reader / Agent

| 项目 | 命令 | 结果 |
| --- | --- | --- |
| 解决方案构建 | `dotnet build ScoutMind.sln -c Release` | PASS，0 错误 |
| FMReader 测试 | `dotnet run --project live-reader/tests/ScoutMind.FMReader.Tests -c Release` | **334 PASS** |
| Reader 集成测试 | `dotnet run --project live-reader/tests/ScoutMind.Reader.Tests -c Release` | **57 PASS** |
| Agent 测试 | `dotnet test desktop-agent/tests/ScoutMind.Agent.Tests -c Release` | **38 PASS** |
| 兼容清单一致性 | `Diag ... -- configcheck` | 退出码 0 |

## 3. 前端

| 项目 | 命令 | 结果 |
| --- | --- | --- |
| 类型检查 + 生产构建 | `npm run build`（`vue-tsc --noEmit` + `vite build`） | **PASS** |
| Playwright | `npm run test:e2e` | **9/9 PASS**（governance 2 + unresolved 7） |
| PR #15 分支构建 | `npm ci && npm run build`（独立 worktree） | PASS |
| PR #15 Playwright | `npm run test:e2e` | 9/9 PASS |

## 4. API 与数据

| 项目 | 结果 |
| --- | --- |
| `/transfers` 列表 | 200，分页/筛选/排序/覆盖率正确（13 个新用例） |
| `/transfers` 非法排序 | 400 `invalid_sort` |
| `/transfers/stats` | 与列表口径一致（样本 2、中位数 20,000,000） |
| 必填参数缺失 | 既有用例覆盖，返回 422/400 错误信封 |
| 未知 API 路径（发布包） | 404 JSON，不被 SPA 兜底吞掉 |
| 空数据 | `{items: [], total: 0, coverage: 全 0}` |
| 重复导入 | `duplicate=true`，不重复写入 |
| 多存档隔离 | PASS（含新增真实双存档用例） |
| 备份/恢复 | PASS（备份 → 停止 → 替换 → 启动 → 数据仍在） |

## 5. 安全检查

详见 `SECURITY_REPORT.md`。要点：

- 仓库无真实密钥，`.env` 未跟踪；
- 默认只监听 `127.0.0.1`，CORS 仅本机；
- 新增静态托管做了路径穿越防护与 `/api/` 404 隔离；
- 停止脚本校验进程归属，避免误杀；
- `pip-audit` / `npm audit` 本轮 **NOT_RUN**。

## 6. CI

| Run | 分支 | 结果 |
| --- | --- | --- |
| `45813033668` | `main` | SUCCESS 6/6 |
| `45814296148` | PR #15 | SUCCESS 6/6 |

本分支的 CI 将在推送 PR 后触发，结果记录在 Phase 9 与 PR 页面。

## 7. 未执行项

| 项 | 原因 |
| --- | --- |
| 本地 PostgreSQL 全量测试 | 无本机 PG，CI 作业已通过 |
| 前端 axe 自动化无障碍扫描 | 仓库无 axe 依赖 |
| 依赖漏洞扫描 | 未纳入门禁 |

状态：**PASS**
