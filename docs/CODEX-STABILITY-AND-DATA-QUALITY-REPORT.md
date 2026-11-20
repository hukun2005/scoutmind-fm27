# ScoutMind FM27 V2 — 稳定性与数据质量阶段报告（第一阶段）

- 基准：`main` @ `b87f5f6`（V2 审查基准）
- 开发分支：`codex/stability-and-data-quality`
- 执行范围：**仅 SM-001 / SM-002 / SM-003**（用户授权的第一批）
- 执行日期：2026-11-20
- 环境：Windows（本机）、SQLite、Python 3.13 venv、.NET 10

> 状态口径：`PASS` 表示实现 + 自动化测试通过；`FAIL` 表示实现或测试失败；
> `PARTIAL` 表示实现完成但存在未覆盖项；`NOT_RUN` 表示本轮**未执行**（不得当作通过）。

## 一、总览

| 编号 | 任务 | 状态 | 提交 |
| --- | --- | --- | --- |
| SM-001 | 统一文件上传限制与资源保护 | PASS | 见下 |
| SM-002 | 修复球员身份冲突与 UID 复用 | PASS | 见下 |
| SM-003 | 分离历史转会与未来已达成转会 | PASS | 见下 |
| SM-004 | 统一 FM27 兼容性配置与字段证据 | NOT_RUN | — |
| SM-005 | 历史转会查询与统计性能 | NOT_RUN | — |
| SM-006 | Reader 超时与资源释放 | NOT_RUN | — |
| SM-007 | AI 会话与存档隔离 | NOT_RUN | — |
| SM-008 | CI 与自动化回归流水线 | NOT_RUN | — |
| SM-009 | LLM 工具规划器 | NOT_RUN | — |

## 二、SM-001 统一上传限制与资源保护 — PASS

### 修改文件

- `backend/app/api/uploads.py`（新增）
- `backend/app/config.py`
- `backend/app/api/routes_core.py`
- `backend/app/api/routes_adapters.py`
- `backend/tests/test_sm_phase1.py`

### 修改内容

1. 新增统一入口 `read_request_payload()`：multipart 与原始请求体都走同一套分块读取，超限立即抛 413。
2. `read_body_limited()` 不依赖 `Content-Length`：按 1 MiB 分块累计计数，chunked 请求同样被拦截；`Content-Length` 只作为快速失败提示。
3. `read_upload_limited()` 对 multipart 文件分块读取；`_check_text_fields()` 限制普通字段数量与单个字段字节数。
4. 所有 multipart 路径在 `finally` 中 `await form.close()`，异常路径也不会遗留临时文件。
5. 新增 `upload_slot()` 信号量（`max_upload_concurrency`），预览 / 审查 / 导入 / 扫描共用。
6. 接入点：`/imports/scan`、`/imports/transfers`、`/imports/squad-csv`、`/imports/fmscout`、`/imports/fmscout/preview`、`/imports/fmscout/validate`。
7. 配置新增 `max_upload_files`、`upload_chunk_size`、`max_upload_concurrency`；`model_post_init` 校验：必须为正、`max_request_bytes >= max_import_bytes`、`upload_chunk_size <= max_import_bytes`，并兼容旧名 `max_multipart_files`。

### 测试

`backend/tests/test_sm_phase1.py`：

- 正常 JSON 上传、正常 multipart 上传（兼容性）
- 超限 JSON → 413
- 无 `Content-Length` 的 chunked 超大请求 → 413
- multipart 文件读取过程中超限 → 413
- 多文件上传被拒
- 读取成功后表单与底层文件均被关闭（临时文件清理）
- 信号量并发上限生效

### 结果

后端全量 `162 passed`（含本任务 9 项）。

## 三、SM-002 修复球员身份冲突与 UID 复用 — PASS

### 修改文件

- `backend/app/models.py`（`identity_conflicts` 新增生命周期字段）
- `backend/app/ingestion/identity.py`
- `backend/alembic/versions/e7b2d91c4a35_identity_conflict_lifecycle.py`（新增）
- `backend/tests/test_sm_phase1.py`

### 修改内容

1. 新增冲突字段：`status`（open/resolved）、`conflict_fields`、`confidence`、`source_scan_id`、`resolved_at`。
2. **补生日但异名**：旧身份无生日、新记录有生日且姓名不同 → 不合并、不写旧身份生日，新建 occurrence 身份 + `birth_date_added_name_mismatch` 冲突。
3. **同名补生日**：允许补齐出生日期，记录 `uid_birthdate_fill` 证据。
4. **改名**：UID + 生日一致、姓名变化 → 同一身份，记录 `uid_rename`，不产生冲突。
5. **UID 复用后再出现**：生日不同时先按"姓名 + 生日"匹配已有 occurrence，命中则复用该 occurrence（`uid_occurrence_match`），避免为同一个人反复建身份。
6. `resolve_open_conflicts()`：后续记录与某一侧完全吻合时关闭冲突（`status=resolved`、`resolution=later_evidence`、写入 `resolved_at`），只关闭冲突，不合并数据。

### 数据库迁移

`e7b2d91c4a35`（基于 `d5a1c7e04f22`）：`batch_alter_table` 增加 5 列 + `ix_identity_conflicts_status`；已在 SQLite 上完成 `upgrade → downgrade → upgrade` 往返。

### 测试

- 同 UID / 同名 / 同生日 → 1 身份
- 同 UID / 异名 / 异生日 → 2 身份 + 冲突
- 同 UID / 异名 / 旧记录无生日 → 不合并，旧身份生日保持 NULL
- 同 UID / 同名 / 旧记录无生日 → 合并并补生日
- 改名（生日一致）→ 同身份、无冲突
- 转会 / 青年队晋升 → 同身份
- 不同存档同 UID → 互不串档
- 同 `game_unique_id` 重复导入 → 幂等
- 冲突后续获得证据 → 自动 resolved
- 冲突字段与状态可查询

## 四、SM-003 分离历史转会与未来已达成转会 — PASS

### 修改文件

- `backend/app/ingestion/adapters/fmscout.py`
- `backend/app/analytics/transfers.py`
- `backend/tests/test_sm_phase1.py`

### 修改内容

1. 新增 `transfer_coverage`：`transfer_history` / `agreed_transfers` / `future_transfers` / `loan_transfers` / `completed_transfers`，每项包含 `available` 与 `records`。
2. 历史转会可用性只取决于数据源是否有历史交易数组；只有 `transferTo`/`transferDate` 时保持 `transfer_history.available = false`，并写入明确 warning。
3. 扫描报文 `coverage` 增加对应布尔字段（`transfers` 语义保持兼容），供导入报告与前端读取。
4. `transfer_price_stats` 口径收紧：只统计 `status='completed'` 且类别 `counts_in_stats` 的记录（正式转会 / 买断 / 解约金）；租借、自由转会、交换、青训、未完成、已达成、取消、失败全部排除并计入 `excluded.by_category`。
5. 新增 `availability`：历史是否可用、完成数、agreed/pending/cancelled 数量；只有 agreed 记录时明确说明价格统计不可用。

### 测试

- 有 `transferDate` 无历史数组 → history 不可用
- 有 `transferTo` 无历史数组 → history 不可用、agreed 可用
- 有历史数组无 agreed / 两者都有
- 价格统计排除 agreed、cancelled（并记录数量）
- 租借费用不进入永久转会统计
- 仅有 agreed 记录时 `transfer_history.available = false`

## 五、全量回归

| 套件 | 命令 | 结果 |
| --- | --- | --- |
| Backend | `cd backend; .\.venv\Scripts\python.exe -m pytest` | **162 passed** |
| Reader 测试 | `dotnet run -c Release`（`live-reader/tests/ScoutMind.FMReader.Tests`） | **92 / 92** |
| Reader 集成测试 | `dotnet run -c Release`（`ScoutMind.Reader.Tests`） | **46 / 46** |
| Frontend | `cd frontend; npm run build` | 成功 |
| 迁移 | `alembic upgrade head` / `downgrade -1` / `upgrade head` | 通过 |

## 六、FM27.1 真实环境验收 — NOT_RUN

本轮未执行真实游戏扫描：执行时 Football Manager 2027 进程未运行，为避免伪造结果，标记为 `NOT_RUN`。

已有的历史证据（2026-11-19，Build 26620374 / 插件 27.1.0+2505117，50,839 球员扫描成功）**未被覆盖**，仍保留在 `docs/acceptance/VERIFY-2026-11-19-EVENING.md`；本轮代码改动只影响上传、身份与转会统计，不改变读取层。

## 七、遗留风险

1. **PostgreSQL 未实跑**：`e7b2d91c4a35` 使用 `batch_alter_table`，SQLite 往返通过；PG 需在真实实例上执行一次。
2. **转会历史来源**：当前 FMSuperScout 导出没有历史转会数组，`transfer_history.available=false` 是正确结果；真实历史交易仍需独立通道导入。
3. **身份冲突人工复核**：冲突已持久化并可自动关闭，但尚无前端列表页面；建议下一阶段补一个只读接口。
4. **上传限制并发值**：`max_upload_concurrency=2` 为默认值，超大数据量部署时可按内存调整。

## 八、后续建议

1. 在真实 FM27 环境跑一次完整扫描与导入（含 5 万+ 球员），确认上传/身份/转会改动无回归。
2. 按用户确认后再开始 SM-004～SM-009。
3. 补充冲突列表 API 与前端展示，让"待人工确认"的身份真正可复核。
