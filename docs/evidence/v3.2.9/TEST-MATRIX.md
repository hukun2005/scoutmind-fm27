# V3.2.9 测试矩阵（同一批次真实执行结果）

执行时间：2026-11-26
执行环境：Windows / Python 3.13 / Node（前端构建）/ .NET 10

## 1. 总表

| 套件 | 采集/总数 | 通过 | 失败 | 跳过 | 未运行 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| Backend pytest | 628 | 625 | 0 | 3 | 0 | PASS |
| ├ V3.2.9 新增 | 37 | 37 | 0 | 0 | 0 | PASS |
| ScoutMind.FMReader.Tests | 308 | 308 | 0 | 0 | 0 | PASS |
| ScoutMind.Reader.Tests | 57 | 57 | 0 | 0 | 0 | PASS |
| ScoutMind.Agent.Tests | 38 | 38 | 0 | 0 | 0 | PASS |
| 前端 `npm run build` | — | 1 | 0 | 0 | 0 | PASS |
| GitHub Actions | 6 类 | 6 | 0 | 0 | 0 | PASS（run 45749190883） |

Backend 口径说明：

- 全量 `python -m pytest -q` 退出码 0，进度 100%，输出中出现 3 个 `s`；
- 采集总数 628 = 改造前 591 + 本阶段新增 37；
- 3 个跳过原因见下；
- 没有使用历史报告的 582 / 581 / 286 / 57 / 38 等数字代替本次执行结果。

## 2. 跳过原因

| 测试 | 原因 |
| --- | --- |
| `test_pg_migrations.py`（1 项） | 未配置 `SCOUTMIND_PG_TEST_URL`，跳过 PostgreSQL 实机迁移 |
| `test_fmscout_real_data.py`（2 项） | 仓库内没有脱敏后的 FMSuperScout 真实样本 |

跳过不是通过；这 3 项在报告中单独计数。

## 3. V3.2.9 新增测试明细

| 文件 | 数量 | 覆盖 |
| --- | --- | --- |
| `test_v329_uid_scope.py` | 6 | 观测幂等、哨兵/缺失、作用域变化、重复 UID、跨存档 UID、摘要脱敏 |
| `test_v329_reconciliation.py` | 8 | 扫描完成、批处理、恢复、校验和不一致、存档身份不一致、同名冲突、重复 UID、状态机 |
| `test_v329_identity_review.py` | 8 | 四种决定、审计追加、不可覆盖、Verified 拒绝、队列 API、存档隔离、重扫不覆盖 |
| `test_v329_cross_save_api.py` | 7 | 候选生成、UID 非身份、Stale 隔离、跨存档确认、扫描 API、汇总/详情/UID 映射 |
| `test_v329_transfer_identity.py` | 6 | 唯一/多/零匹配、俱乐部变化、租借自由状态、幂等 |
| `test_v329_migration.py` | 2 | upgrade/downgrade/upgrade 数据保留、唯一约束存在 |

## 4. 未运行项

| 项目 | 状态 | 原因 |
| --- | --- | --- |
| 真实 FM27 全库扫描（Save A） | **PASS** | 44,886 实例，0 失败 |
| 真实 FM27 A/B/A（数据层） | **PASS** | B 18,614 实例；A 摘要前后一致；共有 UID 13,977 未合并 |
| 真实 FM27 生命周期（转会/退役/自由球员） | NOT_RUN | 需要人工在游戏中制造事件 |
| Verified 级别真实 A/B/A | **FAIL（P1）** | 旧存档指纹可为他档球员生成 Verified |
| PostgreSQL 迁移 | NOT_RUN（本地 skip） | 未配置测试库；CI 作业已通过 |
| 浏览器 E2E | NOT_RUN | 本阶段未执行 |

## 5. 真实 Save A 扫描（2026-11-26）

| 指标 | 值 |
| --- | --- |
| 导入球员 / 实例 | 44,803 / 44,869 |
| 身份扫描 | 44,869 处理 / 42,195 匹配 / 2,674 冲突 / 0 失败 |
| 唯一 UID | 44,869（重复 0） |
| 审核条目 | 813 |
| Verified | 0 |
| 耗时 | 导入 2,174.81 s；扫描 870.13 s |

详见 `REAL-FM27-ACCEPTANCE.md`。A/B/A 复跑基线为 44,886 实例（A）、18,614（B）；A 摘要未变。

## 6. 稳定性

- 新增测试 37 项连续两次单独执行均通过（开发中按文件执行）。
- 全量 Backend 一次通过，无 flaky 重跑。
- dotnet 测试为既有套件，未修改任何 C# 代码，数量与 V3.2.8.1 一致（308 / 57 / 38）。
