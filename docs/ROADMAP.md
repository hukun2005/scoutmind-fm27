# 路线图与当前完成度

阶段划分来自产品基线文档（V2 的 P0-P3）。状态以代码和测试为准，不以计划为准。

| V2 阶段 | 目标 | 状态 | 说明 |
| --- | --- | --- | --- |
| Phase 0 环境确认 | 机器、Steam、版本诊断 | 部分完成 | `status` 可输出诊断 JSON；真实 FM27 未在本机运行验证 |
| Phase 1 Live Reader PoC | 检测、版本校验、probe、扫描 | 完成（本机真实验收） | 读取器与 46 项自检通过；build 26620374 / 插件 27.1.0+2505117 已验证，10 次真实扫描一致 |
| Phase 1b FMSuperScout 接入 | 第三方导出 → 适配层 → 导入 | 代码完成，待真实 dump 验证 | 适配器 + 三类导入方式 + 字段映射报告；真实导出的字段核对需要你提供样本 |
| Phase 2 数据协议与导入 | 标准化管道与幂等导入 | 完成 | 赛季统计块、状态块、租借块；行级拒绝与 `scan_id` 幂等 |
| Phase 3 数据库与快照 | 核心表、迁移、快照追加 | 完成 | 34 张表、三次迁移；快照与状态均只追加 |
| Phase 4 历史交易采集 | 费用拆分、状态、去重 | 完成（依赖数据源） | 三条通道：FMSuperScout / 交易独立导入 / 快照差异候选 |
| Phase 5 Transfer Intelligence | 分位数、相似交易、俱乐部画像、估值 | 完成 | 版本化算法 + 样本门槛 + 覆盖率 |
| Phase 6 转会决策与复盘 | 总成本模型、投资效率、交易复盘 | 完成 | 成本项区分观测/假设/缺失 |
| Phase 7 阵容智能（P1） | 六维评分、位置深度、短板、接班 | 完成 | 权重模板可切换与覆盖 |
| Phase 8 智能球探引擎（P1） | 位置模板、六维评分、隐藏价值、名单 | 完成 | 隐藏价值规则逐条标注可评估性 |
| Phase 9 球员发展（P1） | 成长速率、建议、潜力区间 | 完成 | 潜力以等级与区间呈现 |
| Phase 10 表现分析（P1） | 分位置产出、趋势、能力对比 | 完成（依赖统计字段） | 逐场窗口需要逐场统计 |
| Phase 11 AI 体育总监（P2） | LLM + 工具调用 + RAG | 工具层完成，真实 LLM 未联调（PARTIAL） | 14 个业务工具、四类可靠性、工具级引用；真实模型联调待 API Key |
| Phase 12 自动化（P3） | Desktop Agent、自动同步、PostgreSQL 多存档 | 部分完成 | 桌面同步链路已实现；自动同步待补 |

### P0 六个阶段（按规格顺序）

| 阶段 | 状态 | 交付物 | 还缺什么 |
| --- | --- | --- | --- |
| P0-1 真实导出验证 | 工具就绪，待真实文件 | `-Validate` 报告（5 节 + verdict）、`POST /imports/fmscout/validate` | 你提供一份真实 dump |
| P0-2 适配器与模型升级 | 完成 | 状态/租借/待生效转会字段与三张新表、未知字段与版本兼容检测 | 真实 dump 的字段核对 |
| P0-3 真实数据回归 | 框架完成，待真实样本 | `tests/fixtures/fmsuperscout/` + 8 条用例（构造数据全绿） | 把脱敏真实导出放进 fixtures |
| P0-4 历史交易采集 | 完成 | 三条采集通道、`agreed`/`bid_rejected`/`loan_buyout`、候选择确认/驳回 | 真实转会历史数据 |
| P0-5 自研读取器验证 | 待在你机器上执行 | `scripts/acceptance-live-reader.ps1` + 验收记录 | 需要 FM27 运行 + 兼容的构建/插件 |
| P0-6 端到端验收 | 脚本可跑（9 PASS / 1 WARN / 0 FAIL） | `scripts/acceptance-e2e.ps1` | 真实数据导入后重跑一次并留存记录 |
## 下一步（建议顺序）

1. 在本机跑通 `status → probe → scan`，保存一份真实导出。
2. 用 `scripts/import-scan.ps1` 导入真实数据，核对球员、合同、身价、CA/PA 与历史交易字段是否齐全。
3. 若数据源能提供逐场统计，补 `matches` 与逐场窗口趋势；否则保持「不可用」的明确标记。
4. 在真实数据上校准位置属性模板与六维权重（`docs/MODELS.md` 记录了当前初始值）。
5. 接入 LLM 规划器：让模型只负责选择工具与组织语言，数字仍由工具返回。

## 已知缺口

- 真实 FM27 构建未验证；`docs/VERSION_COMPATIBILITY.md` 中的组合是候选值。
- `transfer_listed`（挂牌）与租借状态字段数据源未提供，两条隐藏价值规则只能标注为无法评估。
- 伤病风险、逐场趋势、现金流预算未实现。
- 多用户与云同步未实现（表结构已按 `user_id` / `fm_save_id` 预留）。
- 货币换算与通胀调整未实现。


## 当前状态补充（V3.1.4，2026-11-21）

- PostgreSQL 16 迁移已通过 CI 真实验证；
- SM-013 历史转会来源仍 **BLOCKED**；
- SM-018 真实 LLM 联调 **NOT_RUN**（无 API Key），运行时重试/用量/成本已实现；
- SM-019 真实回测 **NOT_RUN**（真实存档无多时间点，演示数据不计入）；
- AI 工具数量为 14，工具参数已做存档隔离与严格 Schema 校验。

## V3.2.7.2 完成情况（2026-11-25）

- 存档身份 `save-identity/v1` 协议、后端 API、会话心跳与不可变审计：完成；
- Agent 采集前注册身份/开会话、扫描后复核、切换即失败：完成（协议级）；
- 采集与导入携带身份/会话上下文并校验归属：完成；
- 导入事务回滚/重试/幂等真实测试：完成；
- 前端 `/save-identity` 诊断页：完成；
- 已知未完成：真实 FM27 游戏内 A→B 切换（NOT_RUN）、本机 PG16（NOT_RUN，以 CI 为准）。
- 详情：`docs/SCOUTMIND-V3.2.7.2-IMPLEMENTATION-REPORT.md`、`docs/evidence/v3.2.7.2/STATUS.md`。

## V3.2.7.4 完成情况（2026-11-25）

- PR #8 已合并（`9a6145f`），本版本做事后安全审核并修复 3 项缺陷（身份切换新会话失效、采集缺 fence、operation 未绑定 payload）；
- Worker 取消：`queued → cancelled`（原子）、`running → cancel_requested → cancelled`，新增取消 API、`attempt_count` 与审计；
- operation 幂等：同 op 不同内容 / 同 scan 不同内容 / rejected 重放均 409；重放递增 `attempt_count`；
- Agent：固定 `.context.json`、重启重识别、`diagnostics` / `jobs list|inspect` / `network status`；
- 一键运行期验收 `tools/runtime-acceptance/`：33 项真实 HTTP 检查通过；
- 前端 `SaveIdentityView`：Worker / 网络 / 审计只读诊断；
- 状态口径：工程闭环 PASS；真实 FM27 A/B、断网、重启 = **REAL_FM27_ACCEPTANCE_PENDING**；
- 已知限制：`/imports/fmscout` 与 `/imports/transfers/history` 仍走 legacy 允许策略（计划 V3.2.7.5 收紧）；取消信号为进程内事件；
- 详情：`docs/evidence/v3.2.7.4/FINAL-REPORT.md`。
