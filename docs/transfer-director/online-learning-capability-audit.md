# V3.3.2-08 在线学习能力审计（Phase 0/1）

基线：`origin/main` @ `21346db3d5fbebbf780be9b7306353421bb31c08`，分支 `feature/v3.3.2-08-online-learning`。
本文件只记录仓库中可验证的事实；结论附代码位置。状态口径：PASS / PARTIAL / FAIL / NOT_RUN / BLOCKED_BY_REAL_DATA。

## 1. 结论摘要

1. **在线监控基础设施已存在，必须复用**：`desktop-agent` 已提供 `auto --interval-minutes` 周期扫描、`--pause/--resume/--status`、采集锁、队列与存档身份门禁（`desktop-agent/ScoutMind.Agent/AgentApplication.cs#L223-L330`）。不新建第二套调度。
2. **原生 Live Reader 不提供转会历史**：`UpstreamDumpMapper` 明确把 `transfers` 写成空数组，覆盖率为 `transfers=false / agreed_transfers=false / loans=false / teams=false / statistics=false`（`live-reader/ScoutMind.FMReader/Integration/UpstreamDumpMapper.cs#L168-L191`、`#L412-L446`）。只依赖原生读取器时，`TRANSFER_COMPLETED` **不可观测**。
3. **可观测的是球员快照与挂牌字段**：`upstream` 球员节包含 `name/birth_date/position/ca/pa/market_value/wage/contract_end/availability(listed, loanListed, notForSale, setForRelease)/club_uid`（`UpstreamDumpMapper.cs#L203-L230`、`#L360-L391`）。挂牌状态变化可稳定生成事件。
4. **转会历史与租借条款只能来自导入通道**：后端 `POST /api/v1/imports/scan`、`POST /api/v1/imports/transfers` 接收 `transfers` 数组并写入 `transfer_history`（`backend/app/api/routes_core.py#L256-L316`、`#L599-L690`；`backend/app/ingestion/importer.py#L1229-L1330`）。有真实导入时事件为 `CONFIRMED`，否则该存档零成交样本。
5. **报价/谈判没有游戏内来源**：只能由用户确认产生（`transfer_negotiations` / `negotiation_events` / `transfer_feedback`，`backend/app/models.py#L1703-L1780`）。这些事件标记 `user_confirmed`，不得冒充游戏事实。
6. **俱乐部变化只能作为未验证候选**：快照 `club_id` 变化只写 `transfer_event_candidates`（`backend/app/analytics/transfer_events.py#L19-L75`），不得推断费用或永久转会。
7. **数据库与后台任务可复用**：`BackgroundTask` 已具备任务类型、锁键、检查点、心跳、重试与重启恢复（`backend/app/models.py#L1855-L1899`；`backend/app/services/background_scan.py`）。08 只新增“在线学习”任务类型与四张学习专表。
8. **当前迁移单头**：`b1f4d7e82c90`（V3.3.2-07 `transfer_feedback`）。08 新迁移 `down_revision = "b1f4d7e82c90"`，只新增。

## 2. Live Reader 能力矩阵

| 数据类型 | 现状 | 来源 | 频率/增量 | 身份风险 | 真实数据验证 |
|---|---|---|---|---|---|
| 游戏运行状态 | 支持（进程探测） | `live-reader/ScoutMind.FMReader/Engine/WinMemorySource.cs#L20-L52`；`ScoutMind.Reader/ProcessDetector.cs` | 每次采集 | 无 | 需要（Phase 7） |
| 当前存档 / 存档身份 | 支持（`save-identity` 子命令 + 后端安全门） | `ScoutMind.Reader/CliCommandParser.cs#L5-L49`；`backend/app/services/save_identity.py#L214-L366` | 每次采集 | 中（指纹/代次） | 需要 |
| 游戏日期 | 支持（`date` / `world-date`，带日期来源与置信度） | `ScoutMind.Contracts/ScanEnvelope.cs`；`CaptureRun.date_source/date_confidence`（`models.py#L1014-L1020`） | 每次采集 | 低 | 需要 |
| 球员身份/年龄/位置/CA/PA/身价/工资/合同 | 支持（上游 dump 字段映射） | `UpstreamDumpMapper.cs#L203-L240`；`backend/app/ingestion/importer.py#L63-L66` | 每次扫描全量，后端快照 append-only | 中（`save_local_uid`，缺 UID 进 unresolved） | 需要 |
| 俱乐部身份/名称/声望/主队 | 支持 | `UpstreamDumpMapper.cs#L396-L410`；`models.Club#L158-L177` | 每次扫描 | 低（uid） | 需要 |
| 俱乐部预算 | 不支持 | 无字段；`transfer_director.overview` 明确 `auto_budget=false`（`services/transfer_director.py#L1391-L1396`） | — | — | BLOCKED_BY_REAL_DATA |
| 挂牌/可租借/解约挂牌 | 支持（三值） | `UpstreamDumpMapper.cs#L360-L391`；`models.PlayerAvailability#L591-L627` | 每次扫描新增一行 | 低 | 需要 |
| 转会历史（买入/出售） | 原生不支持；导入支持 | `UpstreamDumpMapper.cs#L190`（空数组）、`#L425-L426`（coverage=false）；导入见 `importer.py#L1229-L1330` | 仅导入时 | 中（from/to 俱乐部可能为空） | 需要真实导入文件 |
| 租借历史/条款 | 原生不支持；导入支持 | `coverage["loans"]=false`（`#L424`）；`LoanRecord`（`models.py#L629-L666`） | 仅导入时 | 中 | 需要 |
| 报价记录 / 谈判结果 | 不支持（无游戏来源） | 仅用户确认：`TransferNegotiation/NegotiationEvent/TransferFeedback` | 用户操作时 | 低（用户确认） | 不可用 → BLOCKED_BY_REAL_DATA |
| 合同条款（分期/附加/买断） | 仅导入时 | `TransferFeeComponent` / `LoanRecord` | 导入时 | 中 | 需要 |
| 游戏时间推进 | 支持（`game_date` 每快照） | `models.PlayerSnapshot#L297-L330` | 每次扫描 | 低 | 需要 |

> 特别声明：数据库里存在字段不等于 Live Reader 能读到。`transfer_history` 的表结构由导入通道写入；原生读取器扫描结果中 `transfers` 恒为空。

## 3. 转会事件可观测性矩阵

| 事件 | 可观测性 | 数据来源 | 可信度 | 进入学习样本 | 说明 |
|---|---|---|---|---|---|
| `PLAYER_LISTED` | 支持 | `player_availability.listed` 由 False→True | `CONFIRMED` | 否（市场状态） | 首次观测只建基线 |
| `PLAYER_UNLISTED` | 支持 | `listed` True→False | `CONFIRMED` | 否 | — |
| `PLAYER_LOAN_LISTED` | 支持 | `loan_listed` False→True | `CONFIRMED` | 否 | — |
| `PLAYER_RELEASED` | 支持 | `set_for_release` False→True | `CONFIRMED` | 否 | 表示解约挂牌，不是已解约 |
| `TRANSFER_COMPLETED` | 仅导入 | `transfer_history.status='completed'` | `CONFIRMED` | 是 | 原生读取器不提供 |
| `TRANSFER_CONFIRMED` | 仅导入 | `status='agreed'` | `CONFIRMED`（未完成） | 否（不计价） | 明确与成交区分 |
| `TRANSFER_STATUS_CHANGED` | 仅导入 | `transfer_status_history` | `CONFIRMED` | 否 | 状态迁移记录 |
| `LOAN_COMPLETED` | 仅导入 | `transfer_type='loan'` + `completed` | `CONFIRMED` | 是（租借统计） | 与永久转学分账 |
| `LOAN_OPTION_RECORDED` | 仅导入 | `loan_records.has_option=True` | `CONFIRMED` | 否（条款统计） | 三值：NULL 表示未知 |
| `LOAN_OBLIGATION_RECORDED` | 仅导入 | `loan_records.has_obligation=True` | `CONFIRMED` | 否 | 强制买断单独处理 |
| `OFFER_SUBMITTED` | 仅用户确认 | `negotiation_events.event_type=offer_submitted/offer_revised` | `CONFIRMED`（用户） | 否 | 不是游戏内报价 |
| `OFFER_ACCEPTED` | 仅用户确认 | `accepted/completed` | `CONFIRMED`（用户） | 仅 completed 另由既有策略案例计入 | — |
| `OFFER_REJECTED` | 仅用户确认 | `rejected` | `CONFIRMED`（用户） | 否 | 拒绝样本用于重点俱乐部行为 |
| `COUNTER_OFFER_RECEIVED` | 仅用户确认 | `counter_received` | `CONFIRMED`（用户） | 否 | — |
| `NEGOTIATION_CANCELLED` | 仅用户确认 | `cancelled/withdrawn` | `CONFIRMED`（用户） | 否 | — |
| `CLUB_CHANGE_OBSERVED` | 支持（推断） | `transfer_event_candidates` | `UNVERIFIED` | 否 | 禁止据此推断价格/永久转会 |
| 合同到期 | 可计算 | `player_snapshots.contract_end` | `CONFIRMED`（日期） | 否 | 只做机会分析，不生成自由转会事件 |

不可观测事件（保留类型定义，绝不生成）：游戏内报价与还价、真实成交费用（无导入时）。

## 4. 事件身份与去重

- 球员身份只用存档内稳定键：`player_instances.save_local_uid` + `uid_occurrence`（`models.py#L196-L207`）；缺失 UID 的球员进入 `unresolved_player_candidates`，**不**参与学习。
- 俱乐部身份只用 `clubs.id`（同存档内），不按名称匹配。
- 事件指纹 = `sha256(save_id | event_type | player_identity | buying_club | selling_club | game_date | amount | source_ref)`；唯一约束落在 `(fm_save_id, event_key)`。
- 存档切换：所有查询以 `fm_save_id` 过滤；同一俱乐部在不同存档是不同的学习实体。

## 5. 可复用数据库与 API

| 能力 | 现状 | 复用方式 |
|---|---|---|
| 转会历史 | `transfer_history` + `transfer_fee_components` | 直接读取，不新建 |
| 租借条款 | `loan_records` | 直接读取 |
| 挂牌状态 | `player_availability` | 直接读取，事件来自状态差分 |
| 俱乐部变化候选 | `transfer_event_candidates` | 直接读取，仅作 `UNVERIFIED` |
| 谈判/反馈 | `transfer_negotiations`、`negotiation_events`、`transfer_feedback` | 直接读取，用户确认事件 |
| 后台任务 | `background_tasks` + `services/background_scan.py` | 新增 `TRANSFER_LEARNING` 任务类型与 `learning` 锁键 |
| 存档身份 | `save_identities` / `save_sessions` | 事件与会话记录 save 归属 |
| 学习状态/画像 API | `/api/v1/transfer-director/learning-status`、`/clubs/{id}/habits` | 保留；新增聚合视图复用其结果 |
| 三套报价 | `services/transfer_director.py#L562-L984` | 在既有调整层上叠加“在线学习调整”，不另建报价引擎 |

## 6. 后台任务机制（复用结论）

- 任务类型：`FULL_SCAN / INCREMENTAL_SCAN / CLUB_LINK_REPAIR / RECOVERY_SCAN`；锁键 `scan / club_link`（`background_scan.py#L31-L43`）。
- 同存档同锁键只允许一个活跃任务，数据库部分唯一索引兜底（`models.py#L1867-L1874`）。
- 支持检查点、心跳、取消、有限重试、应用重启恢复（`background_scan.py#L284-L447`）。
- 08 仅新增 `TRANSFER_LEARNING`，`lock_key="learning"`，检查点保存各类游标与游标对应 ID，不新建执行器。

## 7. 真实 FM27 验证要求与阻塞项

| 验证项 | 状态 | 说明 |
|---|---|---|
| 真实运行状态/存档识别 | 需要真机 | 没有真实 FM27 进程时 `NOT_RUN` |
| 挂牌状态变化 → 事件 | 需要真实快照 | 代码可验证，真实数据待 Phase 7 |
| 转会历史 → 成交事件 | 需要真实导入 | 原生读取器不提供，标 `BLOCKED_BY_REAL_DATA` |
| 报价/谈判真实记录 | 不可用 | 游戏不暴露，标 `BLOCKED_BY_REAL_DATA` |
| 预算/币种 | 部分 | 币种仅来自导入的 `currency_original`，否则未知；预算不可读 |
| 游戏关闭/重启恢复 | 需要真机 | 依赖 desktop-agent auto 与后端任务恢复 |

## 8. 后续开发优先级

1. **P0**：学习会话/事件表 + 迁移 + 增量游标 + 指纹去重 + save 隔离。
2. **P0**：挂牌状态差分与导入转会事件；用户确认谈判事件；俱乐部变化仅未验证。
3. **P1**：全球俱乐部画像与重点俱乐部升级；样本数与多维置信度。
4. **P1**：报价学习调整层接入（买/卖/租），样本不足回退既有规则。
5. **P2**：`/transfer-learning/*` API 与前端学习面板。
6. **P2**：性能（无变化轮询不写库、批量写入、分页）与并发/恢复验证。
7. **P3**：真实 FM27 验收；无法验证项如实标注。
