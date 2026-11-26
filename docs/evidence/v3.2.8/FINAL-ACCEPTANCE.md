# 最终验收结论（Phase 14）

- 验收日期：2026-11-26
- 游戏版本：FM27 27.1
- Steam Build：26620374
- DLL 版本：game_plugin.dll 27.1
- 分支：`codex/v3.2.8-person-calibration`
- Git HEAD：`90cdb2b`；`origin/main`：`89fe8fa`
- 工作区：干净（0 个未提交修改）
- PR：未创建（按约束不自动开 PR、不合并、不发布）

## 1. 等级 A：代码完成

| 要求 | 证据 | 状态 |
| --- | --- | --- |
| Person Locator 已实现 | `PersonCandidateLocator` + 11 项定位器测试 | PASS |
| 候选布局配置已实现 | `PersonLayoutCandidate.Fm27_1_20261125` + 12 项候选字段测试 | PASS |
| 只读校准命令可运行 | `calibrate` / `dump --calibration` 真实运行 | PASS |
| xref 能输出关联结果 | `xref --link-all` / `dump --xref` 真实运行 | PASS |
| Verified 门控已实现 | `PersonVerificationGate` + 19 项门控测试 + 3 条真实审计 | PASS |
| 自动化测试通过 | FMReader 286/286、Reader 57/57、Agent 38/38、后端 582 项 0 失败（3 跳过） | PASS |

**等级 A：PASS**

## 2. 等级 B：真实内存验证

| 要求 | 真实结果 | 状态 |
| --- | --- | --- |
| 正确连接 FM27 真实进程 | fm.exe pid 72012，构建 26620374，插件 27.1，闸门 Verified | PASS |
| 正确读取 Person 候选对象 | 800 / 1500 条候选（不同运行） | PASS |
| 正确读取姓名 | 48/60（0.80）；空姓名保持 null | PASS |
| 正确读取出生日期 | 60/60（1.00） | PASS |
| 重复读取稳定 | 校准 3 次读取不稳定 0；UID 快照内变化 0/60 | PASS |
| 诊断报告完整 | summary / xref / calibration / uid 四种模式与证据文件齐全 | PASS |

**等级 B：PASS**

说明：验收时游戏进程仍在，但当前未加载存档，`probe` 返回未通过；等级 B 的数据来自同进程、同构建的已记录真实运行。

## 3. 等级 C：真实球员人工验证

| 要求 | 结果 | 状态 |
| --- | --- | --- |
| 至少 2～3 名球员 | 3 名 | PASS |
| 姓名正确 | 3/3 经用户在 FM27 界面确认 | PASS |
| 出生日期正确 | 3/3 经用户在 FM27 界面确认 | PASS |
| 俱乐部正确 | 3/3 经用户在 FM27 界面确认 | PASS |
| 属性记录关联唯一 | 3/3 为 SingleCandidate，冲突 0 | PASS |
| CA 在有可靠数据源时核对 | 游戏界面不可见，无可靠数据源；CA 仅记录，不纳入验证 | PASS（不适用） |
| 人工确认成功 | 确认人 user，来源 fm27-ui，证据 HUMAN-VERIFICATION-SHEET.md | PASS |
| Mark(Verified) 门控正常 | 3 名 Verified；其余保持 Pending/未验证 | PASS |

三名球员：Erick Pulgar（1994-01-15）、Georginio Wijnaldum（1990-11-11）、Wang Junyang（2007-10-02）。

**等级 C：PASS**

## 4. 最终结论

**V3.2.8 最终验收：PASS**

- A、B、C 三个等级均通过。
- 单元测试通过未被单独当作完成依据；B、C 使用真实 FM27 运行与人工核对结果。

## 5. 已知限制（不属于 A/B/C 失败）

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| 全库逐条审计 | PARTIAL | 仅抽样 60/800 |
| 跨存档与生命周期 | UNKNOWN | 未做双存档对照，未观察转会/退役 |
| 真实进程退出/句柄失效 | NOT_RUN | 仅模拟测试覆盖 |
| 历史 CI 失败 | UNKNOWN | 最近 8 次均 failure，明细未取得 |
| 本分支 CI | NOT_RUN | 未 push，无法触发 |
| 当前存档同名冲突 | PARTIAL | 1 条 ConflictingIdentity，未人工裁定，未 Verified |

Phase 11 的 `REAL-FM27-ACCEPTANCE` 标记为 PARTIAL，指的是上述更广的真实环境覆盖；不影响本阶段 A/B/C 的判定。

## 6. 复现与证据

```text
dotnet build ScoutMind.sln -c Release
dotnet run --project live-reader/tests/ScoutMind.FMReader.Tests/ScoutMind.FMReader.Tests.csproj -c Release
dotnet run --project live-reader/tests/ScoutMind.Reader.Tests/ScoutMind.Reader.Tests.csproj -c Release
dotnet test desktop-agent/tests/ScoutMind.Agent.Tests/ScoutMind.Agent.Tests.csproj -c Release --no-build
cd backend && python -m pytest -q
```

证据：`REAL-FM27-ACCEPTANCE.md`、`TEST-RESULTS.md`、`VERIFIED-GATE-REPORT.md`、`CALIBRATION-RESULTS.md`、`PLAYER-XREF-RESULTS.md`、`FAILURE-HANDLING.md`。
