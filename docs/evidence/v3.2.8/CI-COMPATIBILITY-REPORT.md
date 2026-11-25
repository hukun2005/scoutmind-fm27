# CI 与兼容性验证（Phase 12）

- 运行日期：2026-11-25
- 游戏版本：FM27 27.1（Build 26620374）
- DLL 版本：game_plugin.dll 27.1
- Git SHA：`1fe822f`（本次验证时 HEAD）
- 分支：`codex/v3.2.8-person-calibration`（未 push）

## 1. 检查项

| # | 检查项 | 命令 / 方式 | 结果 | 状态 |
| --- | --- | --- | --- | --- |
| 1 | Native Reader 单元测试 | `ScoutMind.FMReader.Tests` | 286/286 PASS | PASS |
| 2 | Native Reader 集成测试 | `ScoutMind.Reader.Tests` | 57/57 PASS | PASS |
| 3 | 全量后端测试 | `python -m pytest -q` | 582 项：581 PASS、1 FAIL、3 skipped | FAIL |
| 4 | Frontend 构建 | `npm run build` | 构建成功（8.60s） | PASS |
| 5 | Agent 构建与测试 | `dotnet build ScoutMind.sln` / Agent tests | 解决方案构建成功；38/38 PASS | PASS |
| 6 | `git diff --check` | 工作区检查 | 退出码 0，无空白错误 | PASS |
| 7 | 现有 CI | `gh run list --limit 8` | 最近 8 次全部 failure；本分支未触发 | FAIL / NOT_RUN |
| 8 | FM27.1.0 版本检查 | `status` + `configcheck` | Build 26620374、插件 27.1、闸门 Verified、配置一致 | PASS |

### 后端失败详情

```text
FAILED tests/test_fmscout_real_data.py::test_real_sample_converts_cleanly[real_sample_01.json]
AssertionError: real_sample_01.json 与 manifest 记录的 sha256 不一致
expected 5dc9263c65c0...d9a98d0a1fa55
actual   8c79158972ca...dd0ad34a218b8
```

- 已排除换行符影响：原始文件与 LF 归一化后的哈希相同，仍与 manifest 不一致。
- 本分支相对基线 `5e90f65` 未修改 `backend/`、`frontend/`、`desktop-agent/`（diff 为空），因此这是既有数据/清单不一致，不是 V3.2.8 引入。
- 没有修改测试逻辑或清单来绕过失败。

## 2. 附加检查

| 检查 | 结果 | 状态 |
| --- | --- | --- |
| V3.2.7.5 行为回归 | 后端 581/582、Agent 38/38、前端构建通过；唯一失败为既有 fixture 哈希不一致 | PARTIAL |
| 旧诊断命令兼容 | `status` / `probe` / `configcheck` / `calibrate --dry-run` / `dump <index>` 均退出码 0 且输出合法 JSON | PASS |
| 未支持版本安全拒绝 | VersionGate 8 项测试通过（未知构建、无构建号、插件不一致、candidate 构建均拒绝） | PASS |
| Verified 被旧布局继承 | 27.0 整体 Candidate、27.1 整体 Pending；两份布局独立，修改 27.1 不影响 27.0 | PASS |

补充：`probe` 当前返回 `passed=false`，原因是游戏未加载存档/布局探测失败；这是环境状态，不是命令回归。

## 3. CI 说明

- 历史 CI 最近 8 次运行全部 failure（2026-11-25），与既有问题一致。
- 本分支未 push，因此没有本分支的 CI 运行记录；按约束不 push、不建 PR、不修改测试绕过 CI。
- 尝试读取单次运行明细时 GitHub API 返回 EOF（网络/接口问题），明细日志未取得。

## 4. 未完成项

- 本分支 CI 未触发（NOT_RUN，需 push 后才能运行）。
- CI 失败明细日志未取得（网络 API 失败）。
- Playwright 治理测试、PostgreSQL 迁移测试未在本地运行（NOT_RUN；CI 中需服务/浏览器）。
- 后端 fixture 哈希不一致未修复（留给 Phase 13 分类处理；禁止用改测试/改清单绕过）。

## 5. 失败分类（供 Phase 13）

| 现象 | 分类 | 说明 |
| --- | --- | --- |
| fixture sha256 与 manifest 不一致 | DATA / FIXTURE | 样本或清单漂移；需确认哪份是权威数据后重新生成，不是读取器代码错误 |
| 历史 CI 全失败 | UNKNOWN（既有） | 本次未取得失败明细；需在 Phase 13 用 CI 日志定位 |

## 6. 复现

```text
dotnet build ScoutMind.sln -c Release
dotnet test desktop-agent/tests/ScoutMind.Agent.Tests/ScoutMind.Agent.Tests.csproj -c Release --no-build
dotnet run --project live-reader/tests/ScoutMind.FMReader.Tests/ScoutMind.FMReader.Tests.csproj -c Release
dotnet run --project live-reader/tests/ScoutMind.Reader.Tests/ScoutMind.Reader.Tests.csproj -c Release
cd backend && python -m pytest -q
cd frontend && npm run build
git diff --check
gh run list --limit 8
```
