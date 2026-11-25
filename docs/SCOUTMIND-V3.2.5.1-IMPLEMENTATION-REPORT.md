# ScoutMind V3.2.5.1 实施报告

- 分支：`codex/v3.2.5.1-memscan-module-resolution`（基于 `d114dee`）
- 环境：FM27 27.1.0 / build 26620374 / 插件 27.1，真实进程 pid 60012
- 结论：**PARTIAL / BLOCKED**（模块边界已修复，世界时钟静态根未找到）

## 1. 原始问题

日期字段在进程内可识别，但游戏重启后无法重新定位；此前 `StaticDateScan` 报“没有模块内区域”。

## 2. 根因

`MemScan.ScanRegions` 只含堆区域（`MEM_PRIVATE` 可写），不含模块镜像；旧代码用“扫描区域里 `InModule` 的区域”当模块区域，必然为空。模块边界本身由 `FindModules()` 正常解析。

## 3. 修改文件

| 文件 | 变更 |
| --- | --- |
| `live-reader/ScoutMind.FMReader/Probes/IMemorySource.cs` | 新增 `ModuleBounds` 记录 |
| `live-reader/ScoutMind.FMReader/Engine/WinMemorySource.cs` | 新增 `Bounds`（Gp/Ga/区域数/插件路径） |
| `live-reader/ScoutMind.FMReader/Discovery/StaticDateScan.cs` | 新增：模块区域由调用方传入，1–2 跳静态根扫描 |
| `live-reader/ScoutMind.FMReader/Engine/FmStaticDateScan.cs` | 新增：进程/闸门 + 模块区域构建 |
| `live-reader/ScoutMind.Reader/CliCommandParser.cs` · `Cli.cs` | 新增 `module-info`、`static-date-scan`、`date-read` |
| `live-reader/ScoutMind.FMReader/Discovery/WorldDateLocator.cs` | 命中上限 32 → 4096（避免提前截断） |
| `live-reader/tests/ScoutMind.FMReader.Tests/StaticDateScanTests.cs` | 新增 5 例 |
| `docs/SCOUTMIND-V3.2.5.1-*.md` | 审计、指针分析、本报告 |

## 4. 模块定位

`module-info` 实测：

```text
game_plugin   0x7FFD55290000  size 411,533,312
GameAssembly  0x7FFD987A0000  .. 0x7FFD9C36F000
scan regions  1617
```

ASLR/重启后基址会变，但 RVA 稳定，`date-read` 用“基址 + RVA”定位。

## 5. 静态根结果

- 命中 1 条：`game_plugin + 0x5CE040` → 堆对象，日期字段 +0x1E4。
- 目标对象是**日历/赛程结构**（同对象内含 10-17 / 10-24 / 10-25 / 10-26 及成组赛季固定日期）。
- 交叉验证失败：游戏日期 10-26 时，该字段仍读 10-25；签名搜索 127 处也没有 10-26。
- 因此世界时钟静态根 **未找到**。

## 6. 状态

| 项 | 状态 |
| --- | --- |
| 模块边界获取 | **PASS** |
| MemScan 扫描范围 | **PASS**（仅堆；模块通过 Bounds 单独提供） |
| 静态根扫描工具 | **PASS**（工具可用，能定位静态引用） |
| 世界时钟静态根 | **FAIL**（只找到日历对象） |
| 日期跨日期验证 | **FAIL**（字段读昨日） |
| 跨进程重定位验证 | **NOT_RUN** |
| 多存档真实验收 | **BLOCKED**（仅一个存档） |
| 自动快照 | **BLOCKED**（日期未验证） |
| 自动化测试 | **PASS**（FMReader 151/151） |

## 7. 测试

```text
dotnet run -c Release --project live-reader\tests\ScoutMind.FMReader.Tests   → 151/151
dotnet build ScoutMind.sln -c Release                                        → 成功
module-info / static-date-scan / date-read                                   → 真实进程可用
```

新增用例：一跳命中、模块内自引用不算堆引用、无模块安全失败、两跳命中、日期不匹配不命中。

## 8. 未完成与风险

1. 世界时钟的静态根（真实阻塞项）；
2. 跨重启复测（需先有正确字段）；
3. 多存档真实验收（缺第二个存档）；
4. 当前 RVA 0x5CE040 是 build 26620374 的实测值，不能外推到其他 build。

## 9. 下一步建议

差分定位：在“静态根可达对象”集合中，对比两个游戏日期的快照，找值按日序 +1 的字段，
再用 `date-read` 在其 RVA 上跨日期、跨重启复测。不得用日历/赛程条目替代当前日期。
