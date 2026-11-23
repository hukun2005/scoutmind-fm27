# ScoutMind FM27 V3.2.2.4 — 实施报告

- 分支：`codex/v3.2.2.3-date-discovery`
- 真实 FM27：pid 105040，build 26620374，plugin 27.1
- 日期：2026-11-23

## 1. 状态

| 任务 | 状态 | 说明 |
| --- | --- | --- |
| SM-086 OBJ_DUNI 诊断 | **PARTIAL** | 统计拆分完成；真实 probe 仍因 14 个哨兵 UID 失败 |
| SM-087 DateDiscovery 采集器 | **NOT_RUN** | 未实现 |
| SM-088 A/B/C 关联 | **BLOCKED** | 无内存样本 |
| SM-089 候选时钟验证 | **NOT_RUN** | 无候选 |
| SM-090 轻量日期集成 | **BLOCKED** | 无 Verified 来源 |
| SM-091 自动采集验收 | **NOT_RUN** | 完整扫描仍被 probe 拒绝 |

## 2. OBJ_DUNI

修复：

- 按对象地址去重；
- 分离 DB 不可读、UID 不可读、零 UID、哨兵 UID、重复 UID；
- 唯一性只基于合法 UID；
- 新增 `ObjectIdDiagnostics` / `ObjectIdSample`；
- 未降低 95% 阈值。

真实结果：

```text
UID 合法比例（0=0，哨兵=14）：57/71（80%，阈值 95%）
```

- 去重对象 71，重复对象地址 0；
- 合法 UID 57，全部唯一，重复 UID=0；
- 14 个 `0xFFFFFFFF` 哨兵导致覆盖不足；
- 未识别哨兵对象类型，不能静默过滤。

Reader 测试：**116 passed**（新增 2 项）。

## 3. 日期/自动采集

- `date --json`：`DateUnavailable`；
- 真实 probe：FAIL，完整扫描未执行；
- 没有新快照、没有写数据库；
- 没有把 next_match 当 game_date。

## 4. 测试/Git

- Reader 单元：116 passed；
- .NET build：PASS；
- 后端/前端/Playwright 未因本轮修改重跑（无相关改动）；
- 未合并 main，未发布。

## 5. 结论

OBJ_DUNI 统计逻辑已修正并得到真实诊断；但 14 个哨兵对象仍未解释，probe 仍失败，精确日期和自动采集核心目标 **BLOCKED**。不能标记 V3.2.2.4 完成。
