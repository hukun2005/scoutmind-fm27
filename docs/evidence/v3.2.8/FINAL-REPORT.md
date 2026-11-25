# 最终报告（FINAL-REPORT）

- 运行日期：2026-11-25
- 游戏版本：FM27 27.1
- Steam Build：26620374
- DLL 版本：game_plugin.dll 27.1
- 进程：fm.exe pid 72012
- 分支：`codex/v3.2.8-person-calibration`
- Git HEAD：`5720c88`（报告提交前）
- 基线：`5e90f65`；`origin/main`：`89fe8fa`
- 说明：未 push、未建 PR、未发 Release。

## 1. 阶段状态

| Phase | 内容 | 状态 |
| --- | --- | --- |
| 0 | 仓库与安全基线审计 | PASS |
| 1 | Person 布局候选调查 | PASS |
| 2 | 定位器设计与实现 | PASS |
| 3 | 真实校准与采样偏差修复 | PASS |
| 4 | 属性记录关联（xref） | PASS |
| 5 | Verified 门控与审计 | PASS |
| 6 | 只读诊断命令 | PASS |
| 7 | 真实 FM27 人工核对 | PASS（3 名球员） |
| 8 | UID 索引可行性调查 | PASS（结论：暂不需要索引） |
| 9 | 测试体系 | PASS（含 PARTIAL/UNKNOWN 缺口） |
| 10 | 性能优化 | PASS（端到端约 -11%） |
| 11 | 报告与证据 | PASS |

## 2. 测试摘要

| 套件 | 结果 |
| --- | --- |
| ScoutMind.FMReader.Tests | 286 / 286 PASS |
| ScoutMind.Reader.Tests | 57 / 57 PASS |

真实 FM27 测试单独统计：进程连接、定位、姓名 48/60、生日 60/60、关联 60/60（Phase 4/6）、3 人人工核验、Verified 门控均 PASS；校准、全库覆盖、跨存档与真实进程退出为 PARTIAL / UNKNOWN / NOT_RUN。

## 3. 真实结果摘要

- 3 名球员完成人工核对并 Verified：Erick Pulgar、Georginio Wijnaldum、Wang Junyang。
- 审计日志：1 条历史 Pending + 3 条 Verified，无内存地址。
- 当前存档 xref：60 抽样、59 唯一、1 条同名冲突；冲突未自动裁定。
- UID：1500 条记录唯一、0 重复、快照内稳定；跨存档与生命周期 UNKNOWN。
- 性能：800×800 关联从 3.775s 降至 3.35s（约 -11%）。

## 4. 失败与事故

- 按序号验证时发生定位漂移，3 次验证指向了非人工确认的球员；相关错误 Verified 已撤回，未保留错误记录。
- 修复 `7f56e67`：改为 `--name + --dob` 唯一选人，匹配不唯一即拒绝。
- 同一 pid 内游戏状态变化，Phase 7 的球员在后续扫描中无法重新定位；旧证据仅对当时存档有效。
- 姓名读取率 0.80，原因是姓名槽为空（`zero_pointer`），不是解码错误。

## 5. 未完成项

- Phase 12–16 未执行（CI、发布准备等）。
- 真实进程退出、句柄失效、读取中断的真实注入未执行（模拟测试 PASS）。
- 双存档对照、存档切换后 Verified 失效未验证（UNKNOWN）。
- 全库 800/800 逐条关联与冲突审计未执行（仅抽样 60）。
- 转会/退役/自由球员生命周期未观察（UNKNOWN）。
- CLI `dump`/`verify` JSON 缺进程级自动化断言（PARTIAL）。
- 仓库 CI 最近 8 次失败为既有问题，尚未处理。

## 6. 合规声明

- 全程只读：未写存档、未修改保护属性、未注入 DLL、未上传存档或内存转储。
- 未跳过指针验证或身份验证；未建立跨存档缓存。
- 仅 3 名人工核对球员被 Mark(Verified)；其余保持 Pending/未验证。
- 文档未包含绝对路径、完整内存地址或敏感信息。

## 7. 证据清单

`PHASE-0-AUDIT.md`、`PERSON-LAYOUT-CANDIDATES.md`、`PERSON-LOCATOR-DESIGN.md`、`CALIBRATION-RESULTS.md`、`PLAYER-XREF-RESULTS.md`、`VERIFIED-GATE-REPORT.md`、`UID-INDEX-FEASIBILITY.md`、`TEST-RESULTS.md`、`REAL-FM27-ACCEPTANCE.md`、`FINAL-REPORT.md`，以及对应的 JSON/JSONL 原始结果。
