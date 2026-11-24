# ScoutMind FM27 V3.2.6 实施报告

- 分支：`codex/v3.2.6-release-candidate`（基于 `f8c740e`）
- 环境：FM27 27.1.0 / build 26620374 / 插件 27.1（本轮开始时游戏已退出）

## 1. 实际完成

| Phase | 内容 | 状态 |
| --- | --- | --- |
| 0 | 仓库审计（`SCOUTMIND-V3.2.6-PRE-RELEASE-AUDIT.md`） | PASS |
| 1 | 启发式日期解析 `world-date` + 5 例测试 | PASS |
| 2 | 真实日期验收（11-07/08、再次跨重启） | NOT_RUN（游戏已退出） |
| 3 | 多存档 | 自动化 PASS / 真实 NOT_RUN |
| 4 | Worker / 自动快照 | NOT_RUN / BLOCKED |
| 5 | Playwright | NOT_RUN（前端未改） |
| 6 | Windows 安装包 | NOT_RUN |
| 7 | 全量测试 | 部分（见 §3） |
| 8 | RC 文档 | 已生成 |

## 2. 代码变更

| 文件 | 变更 |
| --- | --- |
| `live-reader/ScoutMind.FMReader/Discovery/WorldDateResolver.cs` | 新增：签名 + 最新日期 + 参考间隔 + 三重复读 + 歧义 |
| `live-reader/ScoutMind.FMReader/Engine/FmWorldDate.cs` | 新增：进程/闸门封装 |
| `live-reader/ScoutMind.FMReader/Discovery/WorldDateLocator.cs` | 命中上限 32 → 4096 |
| `live-reader/ScoutMind.Reader/CliCommandParser.cs` · `Cli.cs` | 新增 `world-date` |
| `live-reader/tests/ScoutMind.FMReader.Tests/WorldDateResolverTests.cs` | 新增 5 例 |

未改动：后端、前端、数据库、Migration、Agent、第三方代码。

## 3. 测试（真实执行）

```text
dotnet build ScoutMind.sln -c Release                     → 成功
dotnet run -c Release --project ...FMReader.Tests         → 156/156
dotnet run -c Release --project ...Reader.Tests           → 53/53
ScoutMind.LiveReader.exe world-date --json                → game_not_running（退出码 2）
```

后端/前端/Playwright 未在本轮执行（零改动）。

## 4. 真实 FM27 验收

| 项 | 结果 |
| --- | --- |
| 日期读取（历史） | PASS：10-26 / 10-31 / 11-06 |
| 跨重启（11-06） | PASS（结构同、日期同；启发式定位） |
| 11-07 / 11-08 | NOT_RUN |
| 多存档切换 | NOT_RUN |
| 自动快照 | BLOCKED |

## 5. 未完成

1. 日期可信度状态机（session_verified / build_verified）未落库；
2. Worker、进度、取消/重试；
3. 安装器与升级/卸载；
4. Playwright 新页面；
5. 真实多存档。

## 6. 风险

| 风险 | 缓解 |
| --- | --- |
| 启发式误选日期 | `confidence=heuristic` 明确标注；自动快照关闭 |
| 无 Worker | 手动导入 + 409 幂等 + 启动恢复 |
| 无安装器 | 仅源码部署，文档写明 |
| 多存档未验证 | 数据按 save_id 隔离 + 文档声明 |

## 7. 结论

**READY_FOR_BETA_WITH_LIMITATIONS**（不是 READY_FOR_RC）。
