# V3.3.2-08 在线学习架构说明

## 1. 设计边界

- **不新建调度器**：周期采集由既有 `desktop-agent auto` 负责（`--interval-minutes`、`--pause/--resume/--status`、采集锁、重启恢复）。后端只在“新数据落地后”做增量学习。
- **不在页面打开时启动学习**：`/transfer-director/opportunities` 的惰性扫描保持原样；在线学习由导入完成、用户反馈、应用启动恢复、显式 `start` 触发。
- **不重建后台任务系统**：新增 `TRANSFER_LEARNING` 任务类型，复用 `BackgroundTask` 的锁、检查点、心跳、重试与 `recover()`。
- **不重复建表**：转会历史、租借、挂牌、谈判、反馈、俱乐部、快照全部复用。只新增学习会话、事件日志、俱乐部画像、学习动态四张表。
- **不伪造事件**：没有真实来源的事件类型只保留常量，永不写入；`INFERRED/UNVERIFIED` 不进入价格统计。

## 2. 运行闭环

```
FM27 运行
  → desktop-agent auto（每 N 分钟，已有）
  → Reader scan（原生：球员/俱乐部/挂牌/游戏日期；transfers 为空）
  → POST /api/v1/imports/scan（或 /imports/transfers）
  → ImportJob 成功
  → 创建 TRANSFER_LEARNING 后台任务（同存档唯一，lock_key=learning）
  → 增量读取新游标之后的数据
  → 识别事件 → 指纹去重 → 存档隔离
  → 更新俱乐部画像（增量）
  → 重点俱乐部升级（与用户俱乐部发生交易的对象）
  → 记录学习动态
  → 报价接口读取画像做“学习调整层”
  → 结果持久化，重启后按检查点继续
```

## 3. 数据模型（只新增）

### 3.1 `transfer_learning_sessions`（每存档一行）

| 字段 | 说明 |
|---|---|
| `fm_save_id` | 唯一，存档隔离 |
| `status` | `STOPPED/INITIALIZING/MONITORING/PROCESSING/LEARNING/PAUSED/RECOVERING/PARTIAL/FAILED` |
| `enabled` | 用户是否开启自动学习（默认 True） |
| `last_monitor_at` | 最近一次采集/导入时间（来自 ImportJob/CaptureRun） |
| `last_event_at` | 最近事件观测时间 |
| `last_learning_at` | 最近学习完成时间 |
| `events_processed / events_new / events_skipped` | 累计计数 |
| `learning_cycles` | 完成的学习轮次 |
| `last_error` | 最近可读错误 |
| `cursor_json` | `{last_transfer_id,last_availability_id,last_candidate_id,last_negotiation_event_id}` |
| `last_import_job_id` | 最近处理的导入批次 |

### 3.2 `transfer_learning_events`（只追加）

`event_key`（指纹）、`event_type`、`transaction_type`、`verification_status`（`CONFIRMED/OBSERVED/INFERRED/UNVERIFIED/REJECTED`）、`player_instance_id`、`player_identity`、`buying_club_id`、`selling_club_id`、`amount`、`currency`、`game_date`、`observed_at`、`source`、`learning_eligible`、`evidence_json`、`origin`（`imported/user_confirmed/unverified`）。
唯一约束 `(fm_save_id, event_key)`。

### 3.3 `club_transfer_profiles`（每存档每俱乐部一行）

`club_id`、`priority`（`global/focus`）、`last_event_id`、`stats_json`（买/卖/租计数、金额合计、年龄/位置分布、币种集合、金额缺失数）、`sample_size`、`confidence_json`（等级、多维依据）、`updated_at`。
唯一约束 `(fm_save_id, club_id)`。

### 3.4 `transfer_learning_activities`（最近学习动态）

`activity_type`（`event_detected/profile_updated/focus_promoted/strategy_updated/cycle_failed`）、`title`、`detail_json`、`event_id`、`club_id`、`created_at`。
只记录由真实事件或真实策略变化产生的内容。

## 4. 增量算法

1. 读取会话游标；无会话则从 0 开始，首次学习会吸收当前存档已有的真实历史（事件指纹保证重复运行不重复写入）。
2. **转会**：`transfer_history.id > last_transfer_id`，按 id 升序分批。
   - `status='completed'` 且 `transfer_type='loan'` → `LOAN_COMPLETED`；
   - `status='completed'` → `TRANSFER_COMPLETED`；
   - `status='agreed'` → `TRANSFER_CONFIRMED`（`learning_eligible=False`）；
   - 来源以 `synthetic/demo` 开头 → 跳过（合成数据不入正式学习库）。
3. **租借条款**：`loan_records.id > last_loan_id`，`has_option/has_obligation` 为 True 时生成条款事件。
4. **挂牌**：`player_availability.id > last_availability_id`，与该球员上一行比较；只在三值明确且发生 True/False 变化时生成，首次观测建基线。
5. **俱乐部变化候选**：`transfer_event_candidates.id > last_candidate_id` → `CLUB_CHANGE_OBSERVED`，`UNVERIFIED`，`learning_eligible=False`。
6. **用户确认谈判**：`negotiation_events.id > last_negotiation_event_id` → `OFFER_*`/`NEGOTIATION_CANCELLED`，`user_confirmed`；
   `transfer_feedback.id > last_feedback_id` 的终态反馈生成对应事件（与 negotiation 事件按指纹去重）。
7. 每个事件写入前按 `(fm_save_id, event_key)` 查重；批量插入，IntegrityError 回滚该批并逐条忽略重复。
8. 事件写入后更新相关俱乐部画像（只处理 `id > profile.last_event_id`），并更新游标与计数，提交。
9. 无新数据时：只更新 `last_monitor_at` 与状态，**不写事件、不重建画像**。

## 5. 俱乐部画像与置信度

- 永久转会与租借分开统计；不同币种不混算（出现多币种时只计数，不计算均值）。
- 画像维度：买入/卖出/租借次数、金额合计与中位数、年龄分布、位置分布、金额缺失数、条款使用数、涉及球员数、时间跨度。
- 置信度 = 样本分级（复用 `transfer_strategy.confidence_tier`）+ 质量因子：
  `confirmed_ratio`、`identity_ratio`、`amount_known_ratio`、`player_diversity`、`time_span_days`。
  输出 `level/label/sample_size/quality_score/basis[]`，不把样本数量单独等同于可靠性。
- 重点升级：事件中 buying/selling 任一方为用户俱乐部时，把另一方 `priority='focus'`；升级只写一次并记录动态。

## 6. 报价接入

- 基础层保持 `transfer_director.generate_*_offers` 的确定性规则。
- 学习调整层：读取对方俱乐部画像（focus 优先），当“同交易类型、可用金额样本 ≥ 3、且与当前币种一致”时计算中位成交/估值比值，夹紧 `[0.85, 1.15]`，输出：
  `applied/multiplier/before/after/sample_size/confidence/basis/club_id/priority`。
- 样本不足或币种未知/混币 → 不调整并给出原因（回退既有规则）。
- 与既有 `strategy_adjustment` 串联：先案例调整，再俱乐部画像调整，两步都完整展示；金额为 None 时不调。

## 7. 并发、存档隔离与故障恢复

- 锁：`(fm_save_id, lock_key='learning')` 部分唯一索引，同存档不允许并行学习任务。
- 事件唯一约束兜底重复写入；画像更新在事务内完成，失败回滚不影响既有事件。
- 存档切换：所有查询以 `fm_save_id` 过滤；事件/画像/会话/检查点全部带 save 作用域。
- 应用重启：`background_scan.recover()` 会把 `TRANSFER_LEARNING` 按检查点续跑；无检查点则标记 `PARTIAL`。
- 数据库忙：沿用 `OperationalError` 重试策略；一次学习失败不删除既有事件与画像。

## 8. 状态与 UI 映射

- `STOPPED`：未开启或无数据；`MONITORING`：已就绪等待新数据；`PROCESSING/LEARNING`：有学习任务运行；
  `PAUSED`：用户暂停；`PARTIAL`：最近一次只处理了部分（有检查点）；`FAILED`：最近一次失败。
- 前端只展示：学习状态、当前存档、最近监控/学习时间、已观察事件、已确认交易、全球俱乐部数、重点俱乐部数、最近动态、报价学习依据。不暴露轮询频率、权重、阈值等开发参数。
