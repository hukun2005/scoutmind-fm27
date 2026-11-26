# ScoutMind FM27 V3.2.9.2 — 测试报告

- 执行时间：2026-11-26
- 分支：`release/v3.2.9.2-stabilization`
- 环境：Windows 11 x64、PowerShell 7、Python 3.13、Node 22/24、.NET 10
- 真实游戏：FM27 27.1.0，build `26620374`，插件 `27.1.0+2505117`

## 1. 汇总

| 套件 | 结果 | 备注 |
| --- | --- | --- |
| 后端 pytest | **658 收集，0 失败** | 退出码 0，`lastfailed` 为空 |
| FMReader | **334 PASS** | |
| Reader 集成 | **57 PASS** | |
| Agent | **38 PASS** | |
| .NET 解决方案构建 | **PASS** | 0 错误 |
| 前端类型检查 + 构建 | **PASS** | `vue-tsc --noEmit` + `vite build` |
| Playwright | **9/9 PASS** | governance 2 + unresolved 7 |
| 兼容清单一致性 | **PASS** | `configcheck` 退出码 0 |
| 数据库迁移往返 | **PASS** | upgrade / 重复 upgrade / downgrade / upgrade |
| 真实 FM27 端到端 | **PASS** | status / probe / scan / import / dedupe |
| 发布包干净目录验收 | **PASS** | 15 步（启动、停止、重启、持久化、备份、恢复） |

## 2. 后端新增回归（`tests/test_transfers_list_api.py`）

| 用例 | 覆盖点 |
| --- | --- |
| `test_list_returns_rows_total_and_coverage` | 正常列表、总数、覆盖率 |
| `test_empty_list_is_not_an_error` | 空结果 |
| `test_limit_one_pages_through_every_row` | limit=1 多页无重复 |
| `test_offset_beyond_total_is_an_empty_page` | offset 越界 |
| `test_status_filter_keeps_pending_out_of_default_list` | 状态筛选 |
| `test_transfer_type_filter_does_not_merge_loans` | 租借/永久不混淆 |
| `test_missing_fee_is_reported_not_zeroed` | 缺失费用不当作 0 |
| `test_addon_components_are_potential_not_paid` | 附加条款不计入已付 |
| `test_transfers_are_isolated_per_save` | 多存档隔离 |
| `test_list_and_stats_agree_on_completed_permanent_sample` | 列表与统计一致 |
| `test_coverage_is_stable_across_pages` | 覆盖率跨页稳定 |
| `test_invalid_sort_is_rejected` | 非法排序 400 |
| `test_sort_by_effective_fee_both_directions` | 排序双向、空值末尾 |

## 3. 真实 FM27

| 步骤 | 结果 |
| --- | --- |
| `status --json` | `Compatible`，pid 72012，build 26620374 |
| `probe --json` | `passed=true`，22,647 ms，布局 `FM27_1` |
| `scan --sync` | 44,144 球员 / 32,796 职员；dump 87,854,283 字节 |
| 导入 | 任务 succeeded，`player_count=44144`，`GET /players` total=44144 |
| 重复上传 | `duplicate=true`，未重复写入 |
| 未验证构建 | `candidate` → `Unknown`，exit 3，拒绝读取 |

## 4. 未执行

| 项 | 状态 | 原因 |
| --- | --- | --- |
| A/B/A（本版产物） | NOT_RUN | 需在游戏内手动切换存档 |
| 游戏关闭后进程清理 | NOT_RUN | 未关闭用户运行中的游戏 |
| 本机 PostgreSQL | NOT_RUN | 无本机 PG 实例（CI 已通过） |
| axe 无障碍扫描 | NOT_RUN | 仓库无 axe 依赖 |
| pip-audit / npm audit | NOT_RUN | 未纳入本次门禁 |

## 5. 结论

本版质量门禁全部通过；未执行项已逐条标注，未把模拟结果写成真实验收。

状态：**PASS**
