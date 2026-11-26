# V3.2.9.2 最终验收报告

- 版本：V3.2.9.2 — LiveReader Save Switch Safety & Verified Lifecycle
- 分支：`feature/v3.2.9.2-livereader-save-switch-safety`
- 基线：`main@24beabad50083d22c5581de03480de2311fd9ad1`（PR #13 合并）
- PR：[#14](https://github.com/hukun2005/scoutmind-fm27/pull/14)
- 执行原则：不自动合并、不发布、不删除分支、不覆盖用户改动、仅只读游戏/存档。

## 1. 结论

| 编号 | 问题 | 状态 |
| --- | --- | --- |
| P0-1 | 旧确认指纹被用于选择当前存档 | 已修复 |
| P0-2 | 切档/会话变化不失效旧确认，无 generation | 已修复 |
| P0-3 | `--save-file` 可绕过身份校验 | 已修复（`CURRENT_SAVE_UNCONFIRMED`） |
| P0-4 | Verified 未绑定 generation，旧任务可覆盖 | 已修复（生命周期台账） |
| P1-1 | 审核无乐观锁，可静默覆盖 | 已修复（version + 条件 UPDATE） |
| P1-2 | 审核无幂等键 | 已修复（`request_key` + 唯一约束） |
| P1-3 | 同名候选提前返回导致集合不完整 | 已修复（全量候选） |
| P1-4 | 转会仅凭姓名确认身份 | 已修复（独立证据 + INSUFFICIENT_EVIDENCE） |
| P2-1 | 重复 UID 每批全表分组 / 关联查询无索引 | 已修复 |
| P2-2 | 诊断缺 generation / 限制码 | 已修复 |
| P2-3 | 审核队列证据分级 UI | 部分：保留 reason 码与汇总字段，未新增独立 UI 分类 |

**P0 / P1 全部解决；未发现新的 P0。**

## 2. 自动化结果

| 套件 | 结果 |
| --- | --- |
| Backend pytest | `637 passed, 3 skipped`（640 collected） |
| FMReader | `PASS 334 · FAIL 0` |
| Reader | `57 / 57` |
| Desktop Agent | `38 / 38` |
| 解决方案构建 | 成功（0 error） |
| configcheck | 退出码 0 |
| 前端构建 | 成功 |
| Migration 往返 | `b2c3d4e5f6a7`，downgrade→upgrade 通过 |

新增测试 35 项（C# 23 + Backend 12），未删除测试、未降低断言。

## 3. 真实 FM27

| 项目 | 结果 |
| --- | --- |
| 自动解析多存档 | `ambiguous=true`，退出码 3，不给当前指纹 |
| 显式 `--save-file --verify` | `candidate` + `CURRENT_SAVE_UNCONFIRMED`，`verify_applied=false` |
| 真实 A/B/A 切档 | `NOT_RUN`（需用户在游戏内切档） |

详见 `07-REAL-FM27-VALIDATION.md`。未把单元测试结果冒充真实切档验收。

## 4. 性能

| 实例数 | 耗时 | 吞吐 | 峰值内存 | 失败 |
| --- | --- | --- | --- | --- |
| 50,000 | 146.6s | 341.1/s | 60.4 MB | 0 |
| 100,000 | 295.3s | 338.6/s | 117.0 MB | 0 |
| 200,000 | 602.6s | 331.9/s | 230.6 MB | 0 |

详见 `05-PERFORMANCE.md`。

## 5. 已知限制

1. 多存档且无文件占用证据时只能返回歧义；单文件时标记已确认但仍缺游戏内
   `SAVE_ID / WORLD_ID`，最高 `CANDIDATE`，不声称进程与存档强绑定。
2. 显式 `--save-file` 永久不能独立完成 Verified（设计如此）。
3. PostgreSQL migration 与 Playwright 仅由 CI 验证，本机 `NOT_RUN_LOCAL`。
4. 真实转会数据验证 `NOT_RUN`。
5. P2-3 只提供原因码与汇总，未新增独立证据分级 UI。

## 6. 交付物

- 代码：4 个提交（基线审计、C# 安全与生命周期、审核/转会、文档与基准）。
- 证据：`docs/evidence/v3.2.9.2/00` ～ `08`。
- 基准脚本：`scripts/benchmark_v3292_identity.py`。
- 新 migration：`b2c3d4e5f6a7_identity_review_concurrency.py`。

## 7. 最终状态

PR #14 已创建，**未合并、未发布、未删除任何分支**。等待评审与 CI 结果。
