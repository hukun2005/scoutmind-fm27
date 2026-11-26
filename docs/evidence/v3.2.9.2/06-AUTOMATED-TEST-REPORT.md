# V3.2.9.2 阶段 6 — 自动化测试与构建报告

执行时间：2026-11-26（Asia/Shanghai）
分支：`feature/v3.2.9.2-livereader-save-switch-safety`（基线 `main@24beaba`）

## 1. 汇总

| 套件 | 命令 | 结果 |
| --- | --- | --- |
| Backend pytest | `cd backend; python -m pytest -q` | `637 passed, 3 skipped`（共 640） |
| FMReader（含阶段 1/2 新增） | `dotnet run --project live-reader/tests/ScoutMind.FMReader.Tests -c Release` | `PASS 333 · FAIL 0` |
| Reader 集成 | `dotnet run --project live-reader/tests/ScoutMind.Reader.Tests -c Release` | `57 / 57 通过` |
| Desktop Agent | `dotnet test -c Release --no-build` | `38 passed, 0 failed` |
| 解决方案构建 | `dotnet build ScoutMind.sln -c Release` | 成功（0 error；仅 third_party 既有 warning） |
| 兼容性清单 | `... Diag ... -- configcheck` | 退出码 0 |
| 前端类型检查 + 构建 | `cd frontend; npm run build` | 成功（`✓ built in 9.34s`） |
| Migration 往返 | `pytest tests/test_v329_migration.py` | 2 passed（head `b2c3d4e5f6a7`，downgrade→upgrade 可往返） |

## 2. 新增测试清单

### C#（22 项）

`live-reader/tests/ScoutMind.FMReader.Tests/LiveReaderSaveSwitchSafetyTests.cs`（12）
与 `VerifiedLifecycleTests.cs`（10），见 01/02 文档。

### Backend（12 项）

`backend/tests/test_v3292_identity_review_concurrency.py`：

- 并发审核单写者、版本冲突 409、已解决不可覆盖；
- 历史追加不可改写、管理员纠正、事务回滚；
- 幂等请求、批量不覆盖并发修改；
- 同名候选集合完整（3 类场景）、证据不足进入审核、API 409。

`backend/tests/test_v329_transfer_identity.py` 新增 3 项（仅姓名不足、年龄冲突、俱乐部证据）。

### 更新（加强）

- `SaveIdentityTests` 中“多存档用旧确认消歧”改为安全语义断言；
- `test_v329_migration` 更新为新 head 并校验新增列；
- 转会原有用例补充年龄证据后才允许关联（规则收紧）。

## 3. 与基线的差异

| 项目 | 基线 24beaba | 本分支 |
| --- | --- | --- |
| Backend 测试 | 628 collected | 640 collected |
| FMReader | 311 PASS | 333 PASS |
| Reader | 57 PASS | 57 PASS |
| Agent | 38 PASS | 38 PASS |
| 前端构建 | PASS | PASS |

未删除任何测试、未降低任何断言；3 个 skip 为基线既有跳过项。

## 4. 未执行

- PostgreSQL migration 兼容性：CI 专用（本机无 PostgreSQL），状态 `NOT_RUN_LOCAL`，以 CI 结果为准。
- Playwright governance：本机不启动浏览器验收，状态 `NOT_RUN_LOCAL`，以 CI 结果为准。
