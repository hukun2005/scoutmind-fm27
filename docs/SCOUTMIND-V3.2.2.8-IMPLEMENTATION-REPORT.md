# ScoutMind FM27 V3.2.2.8 — Unresolved 身份持久化与安全导入实施报告

- 基线：`7043a1aa1d8e3fdc0d7691c6b8d41ddcf41af451`（`origin/main`，2026-11-23 fetch 核实）
- 分支：`codex/v3.2.2.8-unresolved-identity`（独立 worktree `C:\Users\hukun\Desktop\FM27-v328`，基于 `origin/main`）
- 真实环境：FM27 27.1.0 · build 26620374 · appId 4530370 · 插件 27.1.0+2505117 · 布局 FM27_1
- 日期：2026-11-23

## 1. 状态总览

| 任务 | 状态 | 依据 |
| --- | --- | --- |
| SM-113 上游 Mapper 哨兵 UID | **PASS** | `MapperSentinelUidTests` 12 例；真实 dump 无哨兵行（见 §12） |
| SM-114 协议身份模式 | **PASS** | `test_unresolved_protocol.py` 23 例；1.0/1.1 兼容、2.0 拒绝 |
| SM-115 Unresolved 模型 | **PASS** | 三张新表；`test_unresolved_persistence/idempotency/save_isolation` |
| SM-116 Migration | **PASS（SQLite）** / **NOT_RUN（本机 PG）** | 全新库与真实存档副本 up→down→up；PG 由 CI job 覆盖（本机无 PG、Docker daemon 未运行） |
| SM-117 Importer 分流 | **PASS** | 合法 UID 走既有解析器；无 UID 走 savepoint 隔离持久化；新计数齐全 |
| SM-118 Unresolved API | **PASS** | `test_unresolved_api_auth.py` 11 例 |
| SM-119 前端界面 | **PASS** | `npm run build` 通过；Playwright 9/9（新增 7 例） |
| SM-120 Canonical 安全隔离 | **PASS** | `test_unresolved_canonical_isolation.py` 6 例 |
| SM-121 多存档/重载/重启 | **PASS（自动化）** / **PARTIAL（真实 FM27）** | 自动化 2 例；真实导入 44,084 + 重启保留；真实「14 自由球员」场景不可复现（§12.3） |
| SM-122 脱敏导出 | **PASS** | `test_unresolved_redaction.py` 4 例；真实验收库导出成功 |

**最终状态：PARTIAL。** 代码、协议、迁移、API、前端与自动化验收全部通过；真实 FM27 完整导入与重启持久化通过，
但真实存档的 dump 不包含那 14 名哨兵自由球员，因此「真实 14 条 Unresolved」未被真实数据验证。

## 2. 修改文件

后端（`backend/`）

| 文件 | 说明 |
| --- | --- |
| `app/ingestion/uid_status.py`（新增） | UID 判定：`valid / sentinel / missing / invalid`，哨兵 `4294967295`、`-1`、`0xFFFFFFFF`；`0`/空/非法文本不成为身份 |
| `app/ingestion/protocol.py` | `PlayerIdentityRecord`；`PlayerRecord` 双身份模式（合法 UID / unresolved，互斥）；`uid_status`/`uid_reason` 由后端推导；identity 证据上限 2000 字符；1.x 兼容 |
| `app/ingestion/unresolved.py`（新增） | 候选/观察持久化、stable-id 关联、匹配建议、`payload_hash`、`candidate_key` |
| `app/ingestion/importer.py` | 合法 UID 与 Unresolved 分流；`begin_nested()` 行级 savepoint；新计数 `players_imported`、`unresolved_created`、`unresolved_observations_created`、`rows_skipped`、`canonical_candidates_created` |
| `app/ingestion/adapters/fmscout.py` | 适配层同样判定哨兵/缺失/非法 ID，输出 identity 块与报告计数 |
| `app/api/routes_unresolved.py`（新增） | 列表/详情/观察/确认/忽略 |
| `app/api/routes_adapters.py`、`routes_core.py` | 无 UID 行不再 `KeyError`；导入响应暴露新计数 |
| `app/models.py` | 三张新表（见 §3） |
| `alembic/versions/a8c4d5e6f701_unresolved_players.py`（新增） | 只新增表/索引/外键（见 §4） |
| `app/schemas.py`、`app/main.py` | 请求体与路由注册 |

读取器（`live-reader/`）

| 文件 | 说明 |
| --- | --- |
| `ScoutMind.FMReader/Integration/PlayerIdentityClassifier.cs`（新增） | C# 侧身份判定，规则与后端一致 |
| `ScoutMind.FMReader/Integration/UpstreamDumpMapper.cs` | 哨兵/缺失/非法 ID 输出 `identity.kind=unresolved`，绝不写 `save_local_uid`；`schema_version` 1.1；覆盖度与告警 |
| `ScoutMind.Reader/ScanWriter.cs` | 信封沿用扫描器声明的协议版本（修复固定写回 1.0 的问题） |
| `ScoutMind.Contracts/ScanEnvelope.cs` | 版本字段文档更新 |

前端（`frontend/`）：`views/UnresolvedPlayerView.vue`、`api/unresolved.ts`、`types/unresolved.ts`、`router/index.ts`、
`App.vue`（导航）、`tests/e2e/unresolved.spec.ts`、`.gitignore`（修正 Playwright 产物路径）。

脚本与文档：`scripts/export_unresolved_redacted.py`（新增）、`docs/DATA_PROTOCOL.md`、`docs/API.md`、`docs/DATA_MODEL.md`、本报告。

## 3. 新增数据库模型

| 表 | 关键约束 | 作用 |
| --- | --- | --- |
| `unresolved_player_candidates` | `UNIQUE(fm_save_id, candidate_key)`；`status ∈ {pending, review_required, resolved, dismissed}`；`uid_status ∈ {sentinel, missing, invalid}` | 一个待确认的无身份球员；姓名、哨兵值都不是唯一键 |
| `unresolved_player_observations` | `UNIQUE(fm_save_id, scan_id, row_index)` | 每次扫描的原始观察；`raw_uid`/`uid_status`/`raw_evidence_json`/`payload_hash` |
| `unresolved_player_actions` | 追加写；ORM 事件拒绝 `UPDATE`/`DELETE` | 人工决定的不可覆盖审计 |

候选上的 `observation_count` / `first_seen_at` / `last_seen_at` / `latest_ca` / `latest_pa` 是导入器维护的派生缓存，
观察表仍是唯一事实来源。`candidate_key` 仅在**已验证**稳定 ID（`evidence.stable_identity_verified=true`）时跨扫描复用，
否则为 `row:<scan>:<index>`，即一观察一候选——所以两个哨兵球员不会因为同一个 `4294967295` 合并。

## 4. Migration 结果

新增迁移 `a8c4d5e6f701`（`down_revision=f6a7b8c9d0e1`），只建三张表、外键与索引；没有修改任何历史迁移，
没有把 `player_instances.save_local_uid` 改成允许哨兵，也没有改写 1.x 数据。

| 场景 | 命令 | 结果 |
| --- | --- | --- |
| 全新 SQLite | `alembic upgrade head` → `downgrade -1` → `upgrade head` | PASS（version `a8c4d5e6f701`，三表 + 14 个索引） |
| 真实存档副本（105,027 instances / 198,711 snapshots / 106,106 players） | 同上 | PASS：升级后行数不变；降级移除三表；再升级回到 head |
| PostgreSQL 16 | `scripts/pg_migration_validation.py` | **NOT_RUN（本机）**：本机没有 PostgreSQL 服务，Docker daemon 未运行；CI `postgres-migrations` job 会真实执行 |
| 历史迁移 checksum | `git diff --name-status 7043a1a..HEAD -- backend/alembic/versions` | 仅新增 `A a8c4d5e6f701_...`，无修改 |

## 5. Mapper 结果（SM-113）

- 合法 UID：写 `save_local_uid` 与 `identity.kind=save_local_uid`，与 1.0 报文向后兼容。
- 哨兵（`4294967295` / `-1` / `0xFFFFFFFF`）：不写 `save_local_uid`，输出
  `identity.kind=unresolved` + `raw_uid` + `reason=sentinel_uid` + `uid_status=sentinel` + 来源证据。
- 缺失 ID：保留球员，`uid_status=missing`，不编造 `raw_uid`。
- 非法（`0`、非数字）：保留原值，`uid_status=invalid`，进入待确认。
- 协议版本 1.1（新增字段，1.x 兼容）；信封不再把 1.1 改写成 1.0。
- 单元测试：`MapperSentinelUidTests` 12 例 + `MapperTests` 既有断言（版本断言更新为 1.1）+ `EngineTests` 129 例全部通过。

## 6. Importer 结果（SM-117）

- 合法 UID 行：仍走 `resolve_player_instance()` → 快照/属性/统计，行为不变。
- 无 UID 行：`persist_unresolved_observation()`，在 `begin_nested()` savepoint 内执行；**不调用**
  `resolve_player_instance()`，不创建 `PlayerInstance`，不写 `4294967295`，不产生快照或 Canonical 关系。
- 单行持久化失败 → 记 `import_rows`（`code=unresolved_persist_failed`），导入状态为 `partial`，不会标记完成。
- 幂等：`UNIQUE(fm_save_id, scan_id, row_index)` 兜底；同一 `scan_id` 重复上传返回 `duplicate=true`；失败任务可重试且不产生重复观察。
- 报告计数：`players_imported`、`unresolved_created`、`unresolved_observations_created`、`rows_skipped`、
  `canonical_candidates_created`、`rows_rejected`。

## 7. API 结果（SM-118）

- `GET /unresolved-players`（status/name/position/min_ca/min_pa/page/page_size + 存档级 counts）
- `GET /unresolved-players/{id}`（证据、建议、审计历史、保留说明）
- `GET /unresolved-players/{id}/observations`（分页）
- `POST /unresolved-players/{id}/resolve`：必须 `confirm=true`；目标必须是同存档身份；条件 `UPDATE` 防重复确认；
  事务内写 `identity_matches(strategy=unresolved_manual_link)` 与审计行；已处理返回 409。
- `POST /unresolved-players/{id}/dismiss`：必须给原因；观察记录保留；重复忽略 409。
- 越权：候选不属于当前存档 → 404；他人存档 `save_id` → 404 `save_not_found`。
- 测试：`test_unresolved_api_auth.py` 11 例（含列表/筛选/空态/重复确认/忽略/跨存档/目标越权）。

## 8. 前端结果（SM-119）

- `UnresolvedPlayerView.vue`：待确认/需复核/已确认/已忽略 KPI，筛选，分页表格，证据优先详情面板
  （UID 原始状态、观察历史、匹配建议、审计历史），确认需二次确认，忽略需填原因。
- 页面不出现「默认已确认身份」的表述；建议一律标注为建议。
- `npm run build`（typecheck + vite build）通过；Playwright 9/9：normal / empty / load failure / unauthorized /
  manual confirmation / duplicate confirmation / cross-save 404 / 既有 governance 2 例。

## 9. Canonical 安全验证（SM-120）

导入 2 名合法球员 + 2 名哨兵球员后：`PlayerInstance=2`、`PlayerSnapshot=2`、`PlayerObservationCanonical=0`、
`PlayerStatistic/PlayerAvailability/TransferCandidate=0`；`/players` 与治理总览只统计这 2 名球员；
人工确认候选后仍不新增快照、不写 canonical、不改写既有身份姓名。测试 6 例全部通过。

## 10. 多存档验证（SM-121）

| 场景 | 结果 |
| --- | --- |
| A 首次扫描（3 合法 + 2 哨兵） | 3 instance / 3 snapshot / 2 候选 / 2 观察 |
| B 同存档同 `scan_id` 重复上传 | `duplicate=true`，无新增观察/快照 |
| C 同存档新 `scan_id` | 新增观察；同名同哨兵不自动合并（3 候选） |
| D 切换另一存档 | 同名同哨兵不跨存档合并（save A:3 / save B:1） |
| E 关闭并重启（文件库 + 新引擎） | 候选 4、观察 4、实例 3 全部保留 |
| F 重启后继续扫描 | 按 `scan_id` 新建观察，不粘连历史候选 |
| G 后续签约出现合法 UID | 只产生关联建议（`save_local_uid=A200`），候选仍 `pending`，不自动合并 |

## 11. 重启验证（真实数据）

真实导入后停止 uvicorn 进程、用同一 SQLite 文件重新启动：`/players` 仍返回 44,084，`/unresolved-players` 返回 0，
存档数 1。数据完整保留。

## 12. 真实 FM27 验收（本机，2026-11-23）

### 12.1 读取器

| 步骤 | 结果 |
| --- | --- |
| `status` | Compatible：pid 105040，build 26620374，插件 27.1.0+2505117，布局 FM27_1 命中已验证条目 |
| `probe` | **PASS**（7.8 s） |
| `scan` | **PASS**：44,084 名球员，dump 87,071,210 字节，输出 79,855,027 字节，scan_id `fmreader-8d03570078236825`，耗时 32 s |

### 12.2 导入（后端 + Agent）

| 指标 | 实测 |
| --- | --- |
| 导入任务 | `import_jobs.id=1`，`status=succeeded`，`player_count=44,084` |
| `PlayerInstance` | 44,084（唯一 UID 44,084，重复 UID 0） |
| `PlayerSnapshot` | 44,084 |
| `Player`（稳定身份） | 44,044（40 条同名同生日按既有规则共享身份） |
| `identity_matches` | 44,084 |
| 哨兵 UID 实例 | **0** |
| Unresolved 候选 / 观察 | **0 / 0** |
| Canonical 行 | 0 |
| 同 `scan_id` 重新上传 | `duplicate=true`，未重复写入 |
| 后端重启后 | 44,084 保留 |

真实扫描记录的 `schema_version` 为 `1.0`：读取器当时仍用自身常量覆盖扫描器声明值；该问题已修复并由
`ScanEnvelopeTests`「信封保留扫描器声明的协议版本」覆盖，但未再做第二次完整真实导入（见 12.4）。

### 12.3 与「71 / 57 / 14」预期的差异（根因）

- 「71 个对象 / 57 合法 UID / 14 哨兵」来自 V3.2.2.6 的内存对象探针样本，不是上游 dump 的球员列表。
- 对本次真实 dump（44,084 名球员）逐项核对：`id=4294967295`、`-1`、`0`、`null` 的行数均为 **0**；
  用 V3.2.2.6 报告的 14 个姓名（Trejo、Uysal、Cubo、Pousa、Kucka、Fyvie、Halliday、Koffi、Masi 等）检索，
  命中的都是**同姓的其他人**，这 14 人本身不在 dump 中。
- 结论：上游 FMSuperScout 导出只输出“已有身份”的球员，14 名哨兵自由球员被上游排除。因此真实扫描的
  Unresolved 为 0 是数据事实，不是本阶段功能失效；哨兵路径由 12 例 Mapper 测试、23 例协议测试与持久化/幂等测试覆盖。
- 一个真实副作用是：本次扫描因物理内存不足只启用 2 个 worker（44,084 人，历史扫描 48k–50k），可能与排除有关，
  但没有证据表明扩大扫描会带回这 14 人。

### 12.4 未执行的真实步骤

| 步骤 | 状态 | 根因 |
| --- | --- | --- |
| 第二次完整真实扫描（验证 1.1 信封） | **NOT_RUN** | 扫描结束后 FM27 进程退出（pid 105040 不存在），未擅自重启游戏 |
| 真实「14 条 Unresolved」导入 | **NOT_RUN** | 上游 dump 不含这 14 名球员（§12.3） |
| PostgreSQL 16 迁移 | **NOT_RUN（本机）** | 本机无 PostgreSQL，Docker daemon 未运行；由 CI 覆盖 |

## 13. 脱敏导出验证（SM-122）

`python scripts/export_unresolved_redacted.py --database backend/data/acceptance-v328.db --output artifacts/diagnostics/unresolved-redacted.json`

- 输出：候选 0 / 观察 0 / 导入 1；`source.database="[redacted-path]"`；存档用 `save-1` 别名，不写真实 id 与名称。
- 默认去掉姓名（`[name withheld]`）、完整生日（只保留年份）、路径、PID、内存地址；证据只保留**键名**，
  告警只保留**分类计数**。`--include-names` 仅供本地核对。
- 测试 4 例：脱敏断言、源库 SHA-256 不变（只读打开）、缺失库 fail-loud、状态保留。
- `artifacts/diagnostics/` 已在 `.gitignore` 中，本地报告不会被提交或自动上传。

## 14. CI

- 推送分支后由 `.github/workflows/ci.yml` 执行：backend pytest + SQLite 迁移往返、security 回归、.NET（129 + 47 例）、
  前端构建、Playwright、PostgreSQL 16 迁移。
- 本地已执行：pytest 480 例（3 例 PG 相关 skip）、.NET 176 例、Playwright 9 例、`npm run build`、SQLite 迁移往返（含真实存档副本）。
- CI Run：见推送后的 Actions 记录（本报告在推送前完成，CI 结果不在此处伪造）。

## 15. Commit

| Commit | 内容 |
| --- | --- |
| `64d342e` | SM-113..SM-117：mapper/协议/模型/迁移/importer |
| `e8af6e2` | SM-118：Unresolved API |
| `d504ec0` | SM-120：canonical 隔离测试 |
| `5fc2246` | SM-119：前端界面 + Playwright |
| `2fd4a49` | SM-121：多存档/重载/重启验证 |
| `45b8acd` | SM-122：脱敏导出脚本与测试 |
| `fb5102b` | 读取器信封保留协议版本 |
| `5281060` | 协议/API/数据模型文档 |

## 16. 未解决问题

1. **真实 14 名哨兵自由球员不在上游 dump 中**：要让真实扫描产生 Unresolved，需要读取器直接枚举内存对象并输出
   无 UID 行（当前 dump 路径拿不到），或上游导出包含这些对象。属于下一阶段的数据源问题，不是本阶段的持久化缺陷。
2. **读取器 1.1 信封未做第二次真实导入**：修复已合入并有单测；FM27 已退出，未重启游戏重复验收。
3. **Agent 上传超时 60 s 对 44k 级导入过短**：导入仍在服务端完成，但 Agent 报 `同步失败` 并排队；
   队列重试因缺少 `.meta.json` 边车被隔离。建议后续把 sync 超时改为可配置、并在入队时复制边车。
4. **PostgreSQL 16 本机未验证**：依赖 CI job；如 CI 未通过，需按日志修复后再合并。
5. **真实导入记录 schema_version=1.0**：数据本身合法（1.x 兼容），但版本标记早于修复；重跑一次真实扫描即可消除。

## 17. 结论

本阶段把「无 UID 自由球员」从诊断结论做成了可运行的产品能力：协议双身份模式、哨兵防护、三张表与迁移、
导入分流、审核 API、前端界面、Canonical 隔离、多存档/重启验证和脱敏导出全部落地并有测试。

真实 FM27 的**完整导入与持久化**已通过（44,084 名球员、重启保留）；但真实数据里没有那 14 名哨兵球员，
因此「真实 14 条 Unresolved」未能验收。按任务书“只有真实完整导入和持久化验收全部通过才允许 PASS”的口径，
最终状态为 **PARTIAL**。
