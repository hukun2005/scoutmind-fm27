# 测试结果（TEST-RESULTS）

- 运行日期：2026-11-25
- 游戏版本：FM27 27.1
- Steam Build：26620374
- DLL 版本：game_plugin.dll 27.1
- Git SHA：`5720c88`（测试与报告同版本；Phase 10 优化后）
- 完整矩阵：`TEST-MATRIX.md`

## 1. 命令与输出摘要

```text
dotnet run --project live-reader/tests/ScoutMind.FMReader.Tests/ScoutMind.FMReader.Tests.csproj -c Release
```

结果：`PASS 286 · FAIL 0`

```text
dotnet run --project live-reader/tests/ScoutMind.Reader.Tests/ScoutMind.Reader.Tests.csproj -c Release
```

结果：`通过：57 · 失败：0 · 全部通过`

## 2. 覆盖摘要

| 层次 | 结果 | 状态 |
| --- | --- | --- |
| §11.1 单元测试（13 类） | 指针、姓名、Unicode、日期、范围、Person、关联、同名、缺失 UID、无效对象、门控、版本、稳定性 | PASS |
| §11.2 集成测试（7 项） | xref、calibrate、审计 PASS；Locator+真实内存、dump CLI、失败回滚 PARTIAL | PARTIAL |
| §11.3 安全测试（14 项） | 12 项 PASS；进程句柄失效 UNKNOWN；进程退出为模拟 PASS | PARTIAL |
| §11.4 真实 FM27（7 项） | 连接、定位、姓名、生日、关联、人工核对、门控均 PASS | PASS |

## 3. 本轮新增测试

| 测试 | 目的 |
| --- | --- |
| 重复人工确认结果一致且不改变状态 | 防止重复确认绕过门控 |
| 旧版本候选重新验证被拒绝 | 旧构建候选不得升级 |
| 读取中断后不得 Verified | 中断必须失败或异常 |
| 候选索引与逐条关联结果一致 | 优化不改变语义 |
| 候选索引可多目标复用 | 优化复用安全 |

## 4. 真实测试（单独统计）

- 真实进程连接、Person 定位、姓名读取 48/60、生日 60/60、属性关联 60/60、3 人人工核验、Verified 门控均已在真实 FM27 上执行。
- 真实姓名读取率 0.80，失败原因是姓名槽为空，不是解码失败。
- 模拟测试通过不代替真实 FM27 结果；上表真实项已单独运行。

## 5. 已知缺口

- 进程句柄失效：无专门注入测试，与不可读内存共用失败路径（UNKNOWN）。
- CLI `dump` / `verify` 的 JSON 结构缺自动化断言（PARTIAL）。
- 真实进程退出/重启仅由模拟测试覆盖（真实 NOT_RUN）。
- 未做全库逐条关联测试，仅抽样 60。
