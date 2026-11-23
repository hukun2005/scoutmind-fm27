# ScoutMind FM27 V3.2.2.6 — 实施报告

- 分支：`codex/v3.2.2.3-date-discovery`（V3.2.2.6 工作分支）
- 真实 FM27：pid 105040，build 26620374，plugin 27.1
- 日期：2026-11-23

## 1. 状态

| 任务 | 状态 | 说明 |
| --- | --- | --- |
| SM-098 完整诊断 JSON | **PASS** | `probe --json` 输出 `report.probes[].ObjectIds.Samples` |
| SM-099 扩展 ObjectIdSample | **PASS（基础）** | 增加 UID 地址、CA/PA、出生、合同/球队/俱乐部 |
| SM-100 哨兵对象采集 | **PASS** | 71 条摘要 + 全部 14 条哨兵明细 |
| SM-101 合同/球队诊断 | **PASS（只读）** | 14 个哨兵全部合同指针 0、球队/俱乐部不可达 |
| SM-102 对象分类 | **PARTIAL** | 14 个为真实球员属性、无合同、无 UID → FreeAgentPlayerCandidate / Medium |
| SM-103 本地诊断安全 | **PARTIAL** | 诊断在 `artifacts/diagnostics/`，未提交完整文件；脱敏流程未实现 |
| SM-104 真实回归 | **PARTIAL** | 真实 probe 仍 FAIL；完整扫描未执行 |

## 2. 诊断输出

`ScoutMind.FMReader.Diag probe --json` 现在包含完整 `report`；`--summary` 只返回汇总。

真实结果：

```text
CandidateCount=71
UniqueObjectCount=71
ValidUidCount=57
SentinelUidCount=14
DuplicateUidCount=0
Samples=71
```

14 条哨兵对象全部在 `Samples` 中，包含姓名、CA/PA、出生日期、合同/球队/俱乐部地址。

## 3. 根因结论

14 个哨兵对象共同特征：

- 姓名和 CA/PA 正常，是真实球员；
- 出生日期可解码；
- 合同指针为 0；
- 球队/俱乐部关系不可达；
- UID 稳定为 `0xFFFFFFFF`。

分类：**FreeAgentPlayerCandidate / Unattached Player**，置信 Medium。不能因此降低 95% 阈值，也不能静默删除。

## 4. 安全门禁

- 95% 阈值未改变；
- 14 个哨兵未当合法 UID；
- 未修改 OBJ_DUNI 偏移；
- 完整扫描仍被 probe 阻止；
- 未写正式快照。

## 5. 测试

- Reader 单元测试：116 passed（上一轮）
- 真实完整 JSON：71 samples / 14 sentinels 可解析
- .NET Release build：PASS
- 其他 CI 组件未因本轮 CLI/诊断改动重跑

## 6. 未完成

- 需要用游戏界面确认 14 人是否自由球员；
- 需要设计“无 UID 自由球员候选”的 Unresolved 身份策略；
- 脱敏导出未实现；
- 完整扫描仍 BLOCKED；
- 未合并 main，未发布。

## 7. 结论

完整诊断和 14 个哨兵取证已完成；分类为自由球员候选，但门禁仍失败。**PARTIAL / BLOCKED**，不能宣称 V3.2.2.6 完成。
