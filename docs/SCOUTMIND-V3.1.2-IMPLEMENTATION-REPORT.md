# ScoutMind FM27 V3.1.2 实施报告

- 仓库：`hukun2005/scoutmind-fm27`
- 基线：`ce44a29`（开始前 fetch 确认，main 与工作分支一致）
- 工作分支：`codex/scoutmind-v3.1-hardening`
- 范围：**SM-030 / SM-031 / SM-032 / SM-033 / SM-034**
- 日期：2026-11-21
- 状态口径：`PASS` / `PARTIAL` / `FAIL` / `NOT_RUN` / `BLOCKED`

## 总览

| 编号 | 任务 | 状态 |
| --- | --- | --- |
| SM-030 | 转会候选事件权限修复 | PASS |
| SM-031 | IdentityMatch 跨存档隔离 | PASS |
| SM-032 | 全 API 存档权限审计 | PASS（已修复全部发现项） |
| SM-033 | FM27.1 版本验证文档统一 | PASS |
| SM-034 | 数据库迁移与历史兼容性 | PARTIAL（升级 PASS；base downgrade BLOCKED；PostgreSQL NOT_RUN） |

---

## SM-030 转会候选事件权限修复 — PASS

### 修改文件

- `backend/app/api/routes_transfers.py`
- `backend/app/api/deps.py`（新增 `candidate_in_save_or_404`）
- `backend/tests/test_sm030_candidate_ownership.py`（新增）

### 问题原因

`GET /transfers/candidates` 只依赖查询串 `save_id`；`confirm` / `dismiss` 直接 `db.get(TransferCandidate, id)`，
没有任何用户或存档校验。任何进程内调用者都能确认/驳回其他存档的候选事件；关联交易也只校验与候选同存档，
不校验当前用户。

### 修复方式

1. `confirm` / `dismiss` 增加 `get_current_user`、`get_active_save` 与可选 `save_id`；
   通过 `owned_save_or_404` 解析目标存档，再用 `candidate_in_save_or_404` 校验候选归属。
2. 关联 `transfer_id` 通过 `transfer_in_save_or_404` 校验属于同一存档；非法 ID 在写入前返回 404。
3. 列表接口同样显式解析归属；跨存档查询返回 404。
4. 保留 `candidate` 状态机与重复确认 409；失败路径不写数据库。

### 新增测试（7 项）

- 本人确认成功、本人驳回成功；
- 跨用户确认/驳回 404，状态不变；
- 关联其他存档交易 404，候选保持 open；
- 重复确认 409；
- 非法交易 ID 不创建交易、不改状态；
- 列表跨存档 404。

---

## SM-031 IdentityMatch 跨存档隔离 — PASS

### 修改文件

- `backend/app/api/routes_identity.py`
- `backend/tests/test_sm031_identity_match_isolation.py`（新增）

### 问题原因

`_player_payload()` 的 `recent_matches` 只按 `player_id` 查询，未过滤 `fm_save_id`；同一全局 Player 在另一个存档的
匹配证据会出现在当前存档的冲突详情里。

### 修复方式

`IdentityMatch` 查询增加 `IdentityMatch.fm_save_id == save_id`；只返回当前存档的证据。SM-027 的 save-scoped merge
保持不变。

### 新增测试（2 项）

- 两个存档共享同一 Player、各自有不同 `IdentityMatch`：A 的详情只出现 `uid` 证据，B 只出现 `name` 证据；
- 合并 A 后 B 的匹配仍指向原身份、存档不变。

---

## SM-032 全 API 存档权限审计 — PASS

### 修改文件

- `backend/app/api/deps.py`
- `backend/app/api/routes_players.py`
- `backend/app/api/routes_development.py`
- `backend/app/api/routes_performance.py`
- `backend/app/api/routes_scouting.py`
- `backend/app/api/routes_clubs.py`
- `backend/app/api/routes_transfers.py`
- `backend/tests/test_sm032_api_ownership_audit.py`（新增）

### 审计发现与修复

| 接口 | 问题 | 修复 |
| --- | --- | --- |
| `GET /players/{id}`、`/history`、`/status`、`/development` | 无归属校验，按 ID 可读他人球员 | `instance_owned_or_404` |
| `GET /development/player/{id}`、`/performance/player/{id}` | 同上 | 同上 |
| `POST /scouting/evaluate`、`GET /scouting/rank` | 按 `instance_id` 可评分他人球员 | 同上；同时修复 rank 对 `None` 分数排序崩溃 |
| `POST /watchlist/items` | 未校验实例属于目标存档 | `instance_in_save_or_404` |
| `PATCH/DELETE /watchlist/items/{id}` | 无归属校验，可改/删他人关注 | `watch_item_owned_or_404` |
| `POST /alerts/{id}/read` | 无归属校验 | `alert_owned_or_404` |
| `GET/PUT/DELETE /saves/{id}/user-club` | 路径 `save_id` 未校验 | `owned_save_or_404` |
| `GET /transfers/similar`、`/valuation`、`/clubs/{id}/transfer-profile` | 无归属校验；valuation 还会写估值记录 | `instance_owned_or_404` / 校验俱乐部所属存档 |
| `POST /transfers/candidates/...` | 见 SM-030 | 统一依赖 |

其余路由复核：导入类接口都使用 `get_active_save`（查询串 `save_id` 已校验）或 `_resolve_save(user.id)`；
阵容/球队/招聘/职业轨迹/AI 会话均已有存档或用户校验；AI 工具仍由服务端注入 `save_id` 并拒绝模型参数中的 `save_id`。

### 新增测试（14 项）

- 6 类球员读取接口跨用户 404；
- scouting evaluate 跨用户 404；
- user-club 读/写/删跨用户 404；
- watch item 改/删跨用户 404 且数据不变；
- alert 跨用户 404 且未读状态不变；
- 俱乐部 profile 跨用户 404；
- 本人读取、指定主队、更新关注、标记提醒、俱乐部 profile 正常；
- `similar` / `valuation` / `scouting/rank` 跨用户 404、本人正常。

---

## SM-033 FM27.1 版本验证文档统一 — PASS

### 修改文件

- `README.md`
- `docs/FM27-VERSION-VERIFICATION.md`（重写为当前状态）
- `docs/FM27-27.1-FIELD-VALIDATION.md`（加当前状态横幅，历史记录保留）
- `docs/acceptance/VERIFY-2026-11-20-SM012-READER.md`（交叉链接）

### 修复内容

1. 以 `config/compatibility.json` 与 `verified-versions.json` 为准：build **26620374** + plugin
   **27.1.0+2505117** 为 **verified**，允许扫描；27.0 组合仍是 candidate，会被拒绝。
2. 清除"27.1 candidate / 拒绝扫描"的过时结论，保留为历史说明。
3. 明确四个维度：版本兼容 PASS、字段可信度 PARTIAL（11 Verified / 7 Candidate / 32 Pending）、
   扫描稳定性 PASS（10 次真实扫描）、业务数据完整性 PARTIAL（合同到期字段异常）。
4. 明确 `PLAO_HEIGHT` 仍为 Candidate（1–6 cm 差异），`CON_EXPIRY` 仍为 Candidate 且 24/32 年份异常未修复。
5. README 测试数量更新为当前实际值 **335**。

---

## SM-034 数据库迁移与历史兼容性 — PARTIAL

### 修改文件

- `scripts/check_migration_safety.py`（新增，只读预检）
- `backend/tests/test_sm034_migration_safety.py`（新增）
- `docs/MIGRATION-COMPATIBILITY.md`（新增）

### 调查结果

1. **旧库升级 PASS**：`f3a9c57e21d8` 备份副本升级到 `d2f7a91b64e0`，球员/实例/快照/交易行数不变，
   新表与新列已创建。
2. **当前 head 往返 PASS**：`d2f7 → b6e2 → d2f7` 成功。
3. **downgrade base BLOCKED**：在 `992f85fb22b8` 失败，`UNIQUE constraint failed: _alembic_tmp_import_jobs.scan_id`。
   真实库存在跨存档重复 `scan_id`（唯一约束是 `(fm_save_id, scan_id)`），旧迁移的 downgrade 却要恢复全局唯一。
4. **不修改旧迁移**：该迁移已发布；修改会破坏已有数据库的迁移历史。新增修复迁移也无法改变 downgrade 顺序，
   要成功只能删除/改写历史 `scan_id`，属于有损操作。
5. **PostgreSQL NOT_RUN**：本机 Docker daemon 未运行，没有可用 PG 实例；`batch_alter_table` 在 PG 上的行为需单独验证。

### 交付的安全措施

- `scripts/check_migration_safety.py`：只读检查重复 `scan_id`，输出 `downgrade_below_992_safe`；
- 真实库结果：9 条导入、1 组跨存档重复 → 不安全；
- 备份/回滚步骤写入 `docs/MIGRATION-COMPATIBILITY.md`：SQLite 在线备份 API、只允许降级到 `992...` 之后、
  更早结构用备份恢复，不依赖 `downgrade base`。

### 新增测试（3 项）

- 跨存档重复 `scan_id` → 判定不安全；
- 唯一 `scan_id` → 安全；
- 数据库不存在 → 明确报告。

---

## 质量门禁

| 项目 | 命令 | 结果 |
| --- | --- | --- |
| 后端 | `cd backend; python -m pytest` | **335 passed** |
| 前端 | `cd frontend; npm ci; npm run build` | PASS |
| .NET | `dotnet build ScoutMind.sln -c Release` | 0 error |
| SQLite 迁移 | 旧库副本升级、head 往返、downgrade base 复现 | 升级 PASS；base downgrade BLOCKED |
| GitHub Actions | 推送后云端检查 | 见下方 CI 记录 |

### CI

推送后检查云端实际结果：

- 运行：`CI` #**44865122970**，提交 `d4a6365`；
- 结论：**success**（4 个 job 全部通过）；
- Backend (pytest + migrations)：success；
- Frontend (typecheck + build)：success；
- .NET readers and agent：success；
- Upload / identity / agent isolation regressions：success。

说明：随后仅更新本文档会再触发一次 docs-only CI；代码与测试与 `d4a6365` 一致。

## 未解决问题

1. **`downgrade base` 仍不可用**：需要业务确认是否允许改写历史 `scan_id`，再设计数据迁移；本轮按要求不改旧迁移。
2. **PostgreSQL 兼容性未验证**：Docker daemon 不可用。
3. **合同到期字段异常未修复**：24/32 年份不在 2000..2060，`CON_EXPIRY` 仍为 Candidate。
4. **字段可信度仍为 PARTIAL**：32 个 Pending 字段没有界面级证据。
5. **SM-013 自动历史转会来源 BLOCKED**、**SM-018 真实 LLM PARTIAL**、**SM-019 真实回测 NOT_RUN**（沿用前一轮结论）。
6. 性能与权限测试均基于本地 SQLite 测试库，不是生产 PostgreSQL。

## 状态汇总

| 任务 | 状态 | 说明 |
| --- | --- | --- |
| SM-030 | PASS | 候选事件所有权 + 关联交易校验 + 7 项测试 |
| SM-031 | PASS | IdentityMatch 按存档过滤 + 2 项测试 |
| SM-032 | PASS | 全 API 审计 + 14 项权限回归 |
| SM-033 | PASS | 版本/字段/验收文档统一，README 计数 335 |
| SM-034 | PARTIAL | 升级 PASS；base downgrade BLOCKED；PG NOT_RUN |
| SM-035+ | NOT_RUN | 本轮未授权 |
