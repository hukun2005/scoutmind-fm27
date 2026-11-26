# Automatic Data Import Engine（V3.3.0 架构设计）

- 目标：把「识别 → 校验 → 匹配 → 去重 → 修复 → 事务导入 → 导入后验证 → 审计」收敛为一个入口。
- 原则：复杂性留给开发人员，简单性留给用户；自动化不以牺牲数据正确性为代价。
- 约束：不重写现有 Vue / FastAPI / SQLite / C# Reader / Agent；不新增云端依赖。

## 1. 总体结构

```
调用方（数据中心 UI / Desktop Agent / Reader 上传）
        │
        ▼
POST /api/v1/data-hub/import
        │
        ▼
AutomaticDataImportEngine.run()
  ├─ 1. detect          来源 / 格式 / 版本 / 编码 / 存档归属
  ├─ 2. parse           统一转成「原始行集合」（clubs / players / transfers）
  ├─ 3. normalize       Level 1 确定性修复（逐行、无外部依赖）
  ├─ 4. validate        字段/类型/范围/枚举/日期校验
  ├─ 5. resolve         Level 2 有依据修复（稳定 UID、同存档唯一俱乐部名）
  ├─ 6. dedupe          批次内完全重复行去除（不改写业务语义）
  ├─ 7. quarantine      Level 3 隔离（不写入正式数据）
  ├─ 8. import          ScanImporter.import_payload（既有事务/幂等/写栅栏）
  ├─ 9. verify          导入后计数与引用完整性校验
  └─ 10. audit          data_repair_audits（与业务写入同一 Session 提交）
        │
        ▼
统一结果：status + 计数 + 修复摘要 + 隔离摘要 + 验证结论
```

关键点：**第 8 步复用现有 `ScanImporter`**，不复制第二套写库逻辑。
`datahub` 只负责「写库之前」与「写库之后」的治理。

## 2. 阶段输入 / 输出

| 阶段 | 输入 | 输出 | 失败分类 |
| --- | --- | --- | --- |
| detect | `bytes` + 文件名 | `Detection(source, format, schema_version, encoding, compatible, warnings)` | `unsupported_format` / `unsupported_version` / `empty_payload` |
| parse | bytes + Detection | `RawScan(clubs, players, transfers, meta)` | `invalid_json` / `invalid_ndjson` / `invalid_structure` |
| normalize | 行字典 | 规范化行 + `list[Repair]` | 不失败，逐条记录 |
| validate | 规范化行 | 合法行 + `list[Rejection]` | `missing_name` / `invalid_player` / `missing_transfer_date` 等 |
| resolve | 合法行 + DB 会话 | 补全行 + `list[Repair]`（Level 2） | 无法确定 → 进入隔离 |
| dedupe | 行集合 | 去重后行 + `duplicates_removed` | 不失败 |
| quarantine | 被拒绝/不确定行 | `list[QuarantineEntry]` | 不失败 |
| import | `ScanPayload` + fence | `ImportOutcome` | `import_failed` / `write_fence_stale` / `import_cancelled` |
| verify | save_id + job_id | `Verification(status, checks)` | `verify_failed` |
| audit | 全部阶段记录 | `data_repair_audits` 行 | 审计失败使整个事务回滚 |

## 3. 自动识别规则（detect）

按顺序判定，命中即停：

1. **空内容** → `empty_payload`。
2. **UTF-8 BOM / GBK 回退**：先 `utf-8-sig`，失败后尝试 `gb18030`（仅解码，不猜测内容）。
3. **JSON 单对象且含 `schema_version`** → `scan_json`，版本取 `schema_version`。
4. **JSON 单对象且 `fmscout.detect()` 为真** → `fmscout_dump`，交给现有适配器。
5. **首行是合法 JSON 且含 `scan_id` 或 `schema_version`** → `scan_ndjson`。
6. **首行含逗号且字段名命中阵容名单模板（姓名/Name 等）** → `squad_csv`（本版本只做识别并提示使用阵容名单入口，不在这条链路里写入）。
7. 其余 → `unsupported_format`。

版本规则：`schema_version` 主版本必须为 1；否则返回 `unsupported_version` 且**不写入任何数据**。

## 4. 修复等级与规则

### Level 1（确定性，自动执行）

| rule_id | 动作 | 例子 |
| --- | --- | --- |
| `l1.trim_whitespace` | 去除首尾空白与零宽字符 | `" John Smith "` → `"John Smith"` |
| `l1.blank_to_null` | 空字符串 → `None`（仅可选字段） | `""` → `null` |
| `l1.date_format` | 合法日期格式转换 | `"2029/06/30"` → `"2029-06-30"` |
| `l1.numeric_string` | 纯数字字符串 → 数字 | `"140"` → `140` |
| `l1.enum_case` | 枚举大小写/别名标准化 | `"Left"` → `left`；`"LOAN"` → `loan` |
| `l1.duplicate_row` | 批次内完全重复行去除 | 两条 hash 相同的球员行 |
| `l1.encoding_fix` | 已知 BOM/全角空格修复 | `\ufeff`、`\u3000` |

所有 Level 1 修复必须可逆描述：记录字段、前值、后值、规则、规则版本、行号。

### Level 2（有依据，自动执行）

| rule_id | 依据 | 动作 |
| --- | --- | --- |
| `l2.uid_identity` | `save_local_uid` 在同一存档已存在 | 使用既有实例，不新建身份 |
| `l2.club_by_uid` | 行内 `club_uid` 已存在于同存档 | 关联既有俱乐部 |
| `l2.club_by_unique_name` | 行内 `club_uid` 缺失，俱乐部名在同存档唯一命中 | 补全 `club_uid`，并记录依据 |
| `l2.transfer_club_name` | 转会行缺 from/to uid，名称唯一命中 | 补全 uid |

Level 2 **禁止**：按姓名相似度合并球员、按年龄猜生日、把未知费用改 0、把租借改永久、把传闻改成交。

### Level 3（隔离，不自动修复）

- 缺 `name` / 缺 `record_id` / 缺 `transfer_date`。
- 同一 `save_local_uid` 在同一行批次内出现内容冲突且无法用稳定标识区分。
- 俱乐部名在同存档命中多个不同 uid（歧义）。
- `schema_version` 不支持。
- 存档归属不明确（无法确定写入哪个存档）。

处理：写入 `data_repair_audits`（`decision='quarantined'`），**不进入正式数据**；
前端只展示「被隔离 N 条，可展开查看原因」。

## 5. 幂等键

| 层级 | 幂等键 | 保证 |
| --- | --- | --- |
| 批次 | `(fm_save_id, scan_id)` | 既有 `import_jobs` 唯一约束 |
| 操作 | `(fm_save_id, operation_id)` | 既有唯一约束，冲突返回 409 |
| 修复审计 | `(import_job_id, entity, row_index, rule_id, field)` 唯一 | 重复导入不重复写审计 |
| 去重行 | 行内容规范化后的 SHA-256 | 同批完全重复行只保留一条 |
| 修复结果 | 修复前后值相等时不写审计 | 已修复数据再次导入不再变化 |

## 6. 事务边界

```
Session 事务开始
  ├─ 修复审计（暂存，flush 前不 commit）
  ├─ ScanImporter.import_payload(...)  ← 内部 commit 之前
  │     ├─ 业务写入
  │     └─ ImportJob 状态
  ├─ 审计写入
  └─ commit
```

- `ScanImporter.import_payload` 内部已经 `commit`；因此引擎必须在调用前完成所有「不写业务表」的阶段。
- 审计写入失败 → 整个事务回滚（业务数据与审计同生共死）。
- 取消 / fence 拒绝 → 不写审计，返回既有 409 语义。
- 崩溃恢复复用 `recover_interrupted_imports`。

## 7. 存档隔离规则

1. 目标存档由 `get_active_save` / 显式 `save_id` 解析，必须属于当前用户。
2. 传入 `save_identity_id` / `save_session_id` 时复用 `resolve_write_context` + `acquire_write_fence`。
3. 存档身份不明确（写入上下文缺失且 `write_safety_legacy_allowed=false`）→ 409，不写入。
4. 所有 Level 2 查询都带 `fm_save_id` 过滤，禁止跨存档读取俱乐部/实例。
5. 不同存档可复用同一 `scan_id`；唯一约束按存档隔离。

## 8. API 设计

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/data-hub/status` | 游戏连接、存档识别、记录数、最近同步、健康状态、待确认数 |
| POST | `/api/v1/data-hub/import` | 统一导入入口（multipart `file` 或原始体） |
| GET | `/api/v1/data-hub/repairs` | 按 `import_job_id` 查询修复/隔离审计 |
| GET | `/api/v1/data-hub/capabilities` | 自动识别支持的来源与格式（无技术参数展示给普通用户） |

`POST /data-hub/import` 请求参数（全部可选）：
`save_id`、`save_identity_id`、`save_session_id`、`operation_id`、`dry_run`（只检查不写库）。

响应统一为：

```json
{
  "status": "PASS | PARTIAL | FAIL | ROLLED_BACK | BLOCKED",
  "stages": [{"id": "detect", "label": "正在识别数据", "status": "pass"}],
  "detection": {"source": "scan_json", "format": "json", "schema_version": "1.0", "compatible": true},
  "counts": {"created": 0, "updated": 0, "duplicates": 0, "repaired": 0, "quarantined": 0, "rejected": 0},
  "import": {"job_id": 0, "save_id": 0, "duplicate": false},
  "verification": {"status": "PASS", "checks": []},
  "quarantine": [{"row": 3, "entity": "player", "code": "missing_name", "message": "…"}]
}
```

兼容性：旧接口 `/imports/scan`、`/imports/fmscout`、`/imports/squad-csv` 全部保留且行为不变。

## 9. 前端设计

数据中心只保留三块：

- **A 游戏连接**：FM27 是否运行、版本、存档是否识别、是否可安全同步、按钮「同步游戏数据」。
- **B 文件导入**：一个按钮「导入数据」，自动识别格式/版本，6 阶段进度条。
- **C 数据状态**：球员/俱乐部/转会数量、最近同步时间、最近导入状态、健康状态、待确认问题。

技术信息（scan_id、原始报文、适配器字段、兼容性表、导入历史）收进「开发者诊断」折叠区。

## 10. 测试计划

### 单元测试

- `detection`：scan JSON / NDJSON / FMSuperScout / 阵容 CSV / 未知格式 / 不支持版本 / GBK 编码 / 空内容。
- `normalize`：空白、空串、日期、数字字符串、枚举大小写、BOM、完全重复行。
- `validate`：缺 name、无效日期、负值、枚举非法、超范围。
- `resolve`：稳定 UID 命中、俱乐部名唯一命中、名称歧义进入隔离。
- `quarantine`：不写入正式数据、审计记录 `quarantined`。

### 集成测试

- 首次导入 → 计数正确、验证 PASS。
- 同一文件重复导入 → `duplicate=true`、无新增实体、审计不重复。
- 部分异常数据 → `PARTIAL`、隔离数量正确、合法行成功写入。
- 并发导入同一 scan → 只有一个成功，另一个返回进行中/重放。
- 存档切换 → 旧 fence 拒绝，不产生跨存档写入。
- 事务回滚 → 业务数据不落库、审计不落库。
- 修复审计查询 → 按 `import_job_id` 返回完整前后值与规则版本。

### 回归

球员查询、球员详情、阵容分析、转会列表/统计、历史交易、合同信息、身份审核、存档切换、备份恢复。

### 真实 FM27

`status → 检测 → 识别存档 → 同步 → 校验/去重/修复 → 导入 → 验证 → 再次同步（幂等）→ 切换存档（隔离）`。
环境不可用则标记 `NOT_RUN`，不使用模拟数据冒充。
