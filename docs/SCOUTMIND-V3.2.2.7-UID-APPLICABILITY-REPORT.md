# ScoutMind FM27 V3.2.2.7 — UID 适用性与自由球员身份报告

- 分支：`codex/v3.2.2.3-date-discovery`
- 真实 FM27：pid 105040，build 26620374，plugin 27.1
- 日期：2026-11-23

## 1. 状态

| 任务 | 状态 | 说明 |
| --- | --- | --- |
| SM-105 样本统计 | **PASS** | 71 条 Samples + 全部哨兵 SentinelSamples |
| SM-106 合同状态 | **PASS（基础）** | 明确区分合同读取成功/失败；自由球员需成功读到 0 |
| SM-107 UID Applicability | **PARTIAL** | 类型感知分母已实现；未建独立枚举/Unknown 完整矩阵 |
| SM-108 自由球员身份 | **PARTIAL** | FreeAgentCandidate 保留；Unresolved 持久化未实现 |
| SM-109 上游映射 | **NOT_RUN** | 未处理上游 4294967295 |
| SM-110 安全门禁 | **PARTIAL** | 95% 阈值保持，但 Probe 已在类型感知下通过 |
| SM-111 真实回归 | **PARTIAL** | 真实 probe PASS；完整正式扫描未执行 |
| SM-112 脱敏 | **PARTIAL** | 本地 artifacts 已 ignore；脱敏未实现 |

## 2. 真实结果

- 候选 / 去重：71 / 71
- 合法 UID：57
- 哨兵 UID：14
- 重复合法 UID：0
- 自由球员候选：14
- SentinelSamples：14

真实 probe：**PASS**（类型感知后 UID 适用分母为 57，合法率 100%）。

## 3. 分类规则

自由球员候选必须同时满足：

- UID 可读且为 `0xFFFFFFFF`；
- 合同指针**成功读取**且明确为 0（读取失败不算）；
- CA/PA 在 1..200；
- 姓名可读。

这避免把“合同读取失败”误判成自由球员。未知对象仍留在分母，不能静默排除。

## 4. 未完成

- FreeAgent/Unresolved 的数据库/API 持久化未实现；
- 上游 dump `id=4294967295` 的映射未处理；
- 完整正式扫描未执行，未验证自由球员不会进入错误 Canonical；
- 多存档/重载/重启未验收；
- 脱敏导出未实现。

## 5. 安全

- 95% 阈值未降低；
- 没有伪造 UID；
- 14 个自由球员保留在诊断中；
- 未合并 main，未发布。

## 6. 结论

类型感知 UID 统计与自由球员分类已完成；真实 probe 通过，但**正式导入仍应等待 Unresolved 策略**。状态：**PARTIAL**。
