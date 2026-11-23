# ScoutMind FM27 V3.2.1 — Canonical Governance & Data Integrity 实施报告

- 分支：`codex/scoutmind-v3.2-field-capture`
- 起始 HEAD：`6f4c469`
- 最终 HEAD：`25fd471`
- 日期：2026-11-23
- 范围：SM-061C / SM-061D / SM-061E / SM-061F / SM-066C / SM-066D
- **未合并 main**

## 1. 状态总览

| 任务 | 状态 | 说明 |
| --- | --- | --- |
| SM-061C Canonical 接入成长时间轴 | **PASS** | 真实 10,669 条 canonical 可用；43,901 条冲突排除 |
| SM-061D 完整属性签名 | **PASS** | 属性 + source/reader/build；统一统计 43,901 |
| SM-061E 人工审核与审计 | **PASS** | 追加式审计、队列/历史/决策 API |
| SM-061F 真实 canonical 写入 | **PASS** | 54,570 条写入；原始快照/属性不变 |
| SM-066C 数据治理中心前端 | **PASS** | 构建 + 真实数据浏览器验证 |
| SM-066D 治理操作/前端回归 | **PARTIAL** | 导出/历史/进度/冲突统计；未提供批量自动裁决 |
| 43,901 组人工冲突治理 | **PARTIAL** | 机制就绪，尚无人工逐组完成 |
| 后端全量测试 | **PASS** | 404 passed, 3 skipped |
| SQLite migration 往返 | **PASS** | c8 / d9 均验证 |
| PostgreSQL 16 | **NOT_RUN** | GitHub Billing 阻止 CI 启动 |
| GitHub Actions | **BLOCKED** | 非代码失败；5 job 均 1–4 秒未启动 |

## 2. 当前远程与提交

- 远程分支 HEAD：`25fd471aceb39e8f37846726ae0fa26a6a963e05`
- 关键提交：
  - `c9983a6` SM-061C/D
  - `9ea39a7` 500k 价格统计性能修复
  - `3f6e685` SM-061E/F
  - `25fd471` SM-066C/D
- `main` 仍为 `3c01093`，未合并。

## 3. 数据模型与 Migration

| 变更 | 内容 |
| --- | --- |
| Migration `c8d2e5f7a013` | `player_observation_canonicals` |
| Migration `d9e3f6a8b124` | canonical 冲突明细/审核字段；`player_observation_canonical_actions` 追加审计表 |
| 未修改历史 migration | 是 |
| 未删除原始快照 | 是 |

审计动作：`select_snapshot` / `exclude_game_date` / `keep_pending`。
`resolved_manual` / `excluded` 不被重扫描覆盖；组变化标记 `review_required`。

## 4. 真实数据库写入（save_id=2）

备份：`backend/data/backup-before-sm061f-20261122.db`

| 指标 | 写入前 | 写入后 |
| --- | --- | --- |
| PlayerSnapshot | 198,711 | **198,711** |
| PlayerAttributeValue | 8,734,392 | **8,734,392** |
| canonical groups | 0 | **54,570** |
| resolved（自动） | 0 | **10,669** |
| needs_review | 0 | **43,901** |
| resolved_manual | 0 | 0 |
| excluded | 0 | 0 |
| 审计 actions | 0 | 0 |

- 冲突组 `canonical_snapshot_id = NULL`，没有自动选中；
- 重跑写入仍为 54,570 行，无重复，原始表计数不变；
- 真实玩家 29233529 等 resolved 观测可进入时间轴；冲突玩家（109160、29125842）被排除；
- 真实成长分析不再 last-wins 兜底。

## 5. 冲突统计统一

| 口径 | 冲突组 | 说明 |
| --- | --- | --- |
| SM-066A | 35,468 | 仅 CA/PA/工资/身价/合同 |
| SM-061B | 36,556 | + 俱乐部/位置/身高/脚 |
| **本轮** | **43,901** | + 全部 PlayerAttributeValue + source/reader/build + missing-vs-present |

差异来自字段覆盖扩大（属性变化 43,731 组、来源 1,500 组、缺失/有值 1,062 组），不是放宽/收紧阈值。

## 6. SM-061C 时间轴

- 仅 `resolved` / `resolved_auto` / `resolved_manual` 且快照属于当前存档/实例/日期才纳入；
- `needs_review` / `excluded` / `review_required` 不进入，无 last-wins fallback；
- 无 canonical 返回 `canonicalization_pending`；`legacy=True` 明示 legacy 模式；
- `SeriesBuild`：raw/excluded/pending/legacy 字段；
- `growth_report`、Player Development、Forecast 使用 canonical；`quality_summary` 保留原始计数。

## 7. 前端 Data Governance Center

路由：`/governance`，导航“数据治理”。

功能：

- KPI：原始快照、独立日期、canonical 组、自动/人工确认、待审核、已排除、质量异常计数；
- 审核进度和冲突类型统计；
- 队列筛选：姓名/UID、game_date、冲突类型、状态、分页；
- 快照差异：核心字段 + 全部属性（来自 `PlayerAttribute`，不硬编码）+ 来源/Reader/构建；
- 人工决策：选择快照 / 排除日期 / 保持待审，必填理由、二次确认、审计历史；
- 成长时间轴：每个 game_date 的状态、canonical 快照、排除原因；
- 导出当前页 CSV；未提供“全部 43,901 一键 resolved”的批量写操作。

### 页面验证（真实 save 2，headless Chromium）

![治理总览](docs/evidence/governance-overview.png)

![冲突差异与审核](docs/evidence/governance-detail-full.png)

验证地址：`http://127.0.0.1:5173/governance`（本地开发服务器，已停止）。
页面显示 148,070 快照、54,570 组、43,901 待审核；详情显示 4 条快照、属性差异、审核表单和时间轴。

## 8. 测试与门禁

| 项目 | 结果 |
| --- | --- |
| 后端全量 | **404 passed, 3 skipped**（517s） |
| SM-061C/D 回归 | 13 项 |
| SM-061E 回归 | 8 项 |
| 前端 `npm run build` | PASS（含 vue-tsc） |
| .NET Release | PASS |
| FMReader 单测 | 114 passed |
| 浏览器验证 | PASS（overview + detail + 行点击） |
| 自动化前端 workflow 测试 | **NOT_RUN**（项目无前端单测运行器，本轮未新增） |
| PostgreSQL 16 | **NOT_RUN**（CI Billing） |

## 9. CI 阻塞

- run **45108104957**（`25fd471`）：5 job 全部在 1–4 秒内失败；
- annotation：*“The job was not started because recent account payments have failed or your spending limit needs to be increased.”*
- 这是 GitHub 账户 Billing 问题，**不是代码或迁移失败**；
- 不能把本提交的 PostgreSQL 16 写成 PASS；需恢复 Billing 后重跑 CI。

## 10. 未解决问题

1. 43,901 组真实冲突仍待人工逐组审核；机制完成不等于数据治理完成；
2. PostgreSQL 16 对本轮新 migration 未执行（CI BLOCKED）；
3. `source_changed` 目前仍进入 needs_review，是否忽略来源差异需产品确认；
4. 真实库当前只有 1 个 game_date，成长趋势仍不可计算（不是 canonical 问题）；
5. 前端审核 workflow 无自动化浏览器测试，仅人工/截图验证；
6. 未提供批量裁决，避免违反“不得将 36,556 组默认批量 resolved”。

## 11. 结论

V3.2.1 的 canonical 治理链路已经打通：真实 54,570 组 canonical 写入、43,901 组冲突被明确隔离、人工审核与追加审计可用、治理中心可浏览和操作。真实数据治理仍是 **PARTIAL**，因为 43,901 组冲突尚未逐组完成人工审核；CI 仍是 **BLOCKED**，因为 GitHub Billing 阻止了 PostgreSQL 16 验证。未合并 main，未开始 V3.3。
