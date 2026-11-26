# Phase 10：性能优化记录

> 日期：2026-11-25 · 构建 26620374 · 插件 27.1
> 优化前提：Phase 9 正确性测试通过（286/286），优化不改变关联语义。
> 证据：`person-xref-optimized-2026-11-25.json`

## 1. 优化点

新增 `AttributeRecordIndex`（只读、单次调用内有效）：

- 预计算每条属性记录的姓名键（归一化）与归一化俱乐部名。
- 诊断摘要与 `xref --link-all` 在循环外构建一次索引，多个目标复用。
- 关联器仍逐条执行相同的字段比较、冲突判定和候选计数；没有跳过指针验证或身份验证。

涉及文件：

- `live-reader/ScoutMind.FMReader/Calibration/AttributeRecordIndex.cs`（新增）
- `live-reader/ScoutMind.FMReader/Calibration/AttributeRecordLinker.cs`
- `live-reader/ScoutMind.FMReader/Calibration/PersonDiagnostics.cs`
- `live-reader/tools/ScoutMind.FMReader.Diag/Program.cs`

## 2. 基准测试

命令（800 个目标 × 800 条记录，扫描与字段读取计入总时间）：

```text
ScoutMind.FMReader.Diag.exe dump --xref --located 800 --samples 800
```

| 版本 | 运行 1 | 运行 2 | 运行 3 | 中位数 |
| --- | --- | --- | --- | --- |
| 优化前 | 3.77s | 3.78s | — | 3.775s |
| 优化后 | 3.58s | 3.35s | 3.35s | 3.35s |

- 总时间下降约 **11%**（3.775s → 3.35s）。
- 总时间仍以堆扫描和字段读取为主；索引只减少重复的姓名/俱乐部归一化。
- 未做微基准隔离，以上为端到端命令时间，存在机器噪声。

## 3. 正确性验证

| 项目 | 结果 | 状态 |
| --- | --- | --- |
| 全量测试 | 286/286 PASS（新增 2 项索引测试） | PASS |
| 索引结果与逐条关联一致 | 状态、兼容候选数、冲突数、原因完全一致 | PASS |
| 索引多目标复用 | 两个目标复用同一索引，结果与逐条调用一致 | PASS |
| 关联语义 | 仍要求姓名或 UID 强匹配；生日单独命中不建立关联 | PASS |
| 冲突处理 | 仍返回 ConflictingIdentity，不自动选择 | PASS |
| 当前存档 xref 输出 | 60 抽样：唯一 59、冲突 1、成功率 0.9833 | PASS |

说明：当前存档状态与 Phase 6 不同（当时 60/60、冲突 0）；本次 1 条同名冲突是数据本身的变化，不是优化引入。

## 4. 缓存边界与失效

| 约束 | 实现 |
| --- | --- |
| 绑定 Process Identity / Build / Layout / Session | 索引不跨调用存在；每次命令重新检测闸门、重新扫描、重新读取快照 |
| 绑定 Save Identity | 不缓存存档身份；不跨存档复用任何对象 |
| 进程重启或存档切换 | 旧索引随进程退出即销毁；不存在旧指针复用 |
| 未知布局 | 布局未知时仍拒绝扫描，不进入索引构建 |
| 跳过验证换速度 | 未跳过指针验证、身份验证、冲突判定或人工门控 |

索引只保存快照中的字符串键与数值，不保存或复用内存指针；`PlayerRecordFacts.RecordPointer` 仍仅用于本机诊断输出。

## 5. 未实施的优化及原因

| 项目 | 状态 | 原因 |
| --- | --- | --- |
| 扫描结果缓存 | NOT_RUN | 跨命令缓存需要绑定进程/构建/布局/存档/会话；当前证据不足以安全失效，收益低于风险 |
| 重复 Person 读取缓存 | NOT_RUN | 稳定性检查本身要求重复读取；缓存会掩盖 Unstable |
| 字符串解码结果缓存 | NOT_RUN | 姓名槽随对象变化；单次快照内已只解码一次，跨调用缓存不满足失效要求 |
| 读取失败自动重试 | NOT_RUN | 重试会把瞬时不可读误判为稳定；当前保留失败原因，交由门控处理 |
| 候选索引桶（按姓名/UID 分桶） | NOT_RUN | 会改变 `RejectedCandidates` 的全量证据语义；需要单独设计后再评估 |

## 6. 复现

```text
dotnet run --project live-reader/tests/ScoutMind.FMReader.Tests/ScoutMind.FMReader.Tests.csproj -c Release
ScoutMind.FMReader.Diag.exe dump --xref --located 800 --samples 800
ScoutMind.FMReader.Diag.exe dump --xref --located 800 --samples 60
```
