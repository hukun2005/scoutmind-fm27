# ScoutMind HTTP API 契约（v1）

本文件是前端、Desktop Agent 与后端之间的**唯一接口契约**。任何字段变更必须先改本文件，再同步实现与测试。

## 1. 通用约定

- Base URL：`http://127.0.0.1:8000/api/v1`
- 编码：`application/json; charset=utf-8`；金额单位随记录的 `currency` 字段（默认 `EUR`），不做隐式换算。
- 时间：`observed_at` / `imported_at` / `created_at` 使用 UTC ISO-8601（`2026-11-18T03:00:00Z`）；`game_date`、`contract_end`、`transfer_date` 使用游戏内日期 `YYYY-MM-DD`。
- 缺失值：一律 `null`，禁止用 `0` / `""` 冒充未知。前端必须把 `null` 显示为 `—`。
- 分页：`limit`（默认 50，最大 200）、`offset`（默认 0）。响应带 `total`。
- 认证：当后端配置了 `SCOUTMIND_API_TOKEN` 时，所有请求必须带请求头 `X-ScoutMind-Token: <token>`；`GET /health` 不需要。未配置时后端只允许绑定 `127.0.0.1` 并在启动日志中告警。
- 错误：`{"error": {"code": "string", "message": "string", "details": {...}}}`，HTTP 状态码遵循 REST 语义（400 校验失败、401 未授权、404 不存在、409 冲突、422 请求体不合法、503 数据库不可用）。
- 数据来源标记：每条球员/交易记录都带 `source`，取值 `fm27_live_reader | fm_save_parser | manual | ocr | external | estimated | synthetic_fixture`。`synthetic_fixture` 只用于开发演示，前端必须在页面上显示演示数据横幅。

## 2. 健康与元信息

### GET /health
```json
{"status": "ok", "version": "0.1.0", "database": "sqlite", "demo_mode": false, "timestamp": "2026-11-18T03:00:00Z"}
```

### GET /meta/bootstrap
```json
{
  "product": "ScoutMind",
  "version": "0.1.0",
  "demo_mode": false,
  "auth_required": false,
  "active_save_id": 1,
  "saves": [{"id": 1, "name": "默认存档", "game_version": "27.0", "game_build": "unknown"}],
  "data_sources": [{"source": "fm27_live_reader", "records": 120}],
  "capabilities": {
    "live_reader": false,
    "save_parser": false,
    "agent_llm": false,
    "watchlist": true,
    "transfer_intelligence": true
  },
  "warnings": []
}
```

## 3. 存档（fm_saves）

`GET /saves` → `{"items": [Save], "total": n}`，`Save = {id, name, game_version, game_build, created_at, is_active, player_count, snapshot_count, transfer_count, last_import_at}`。

`POST /saves` body `{name, game_version?, game_build?}` → `Save`。

`GET /saves/{id}/summary` → `{save: Save, coverage: {players: n, snapshots: n, transfers: n, clubs: n}, last_import: ImportJob|null}`。

## 4. 导入（imports）

### POST /imports/scan
请求体为扫描协议 JSON（见 `DATA_PROTOCOL.md`），或 `multipart/form-data` 上传同结构 `.json` 文件（字段名 `file`），或 `application/x-ndjson` 每行一条（首行 header）。响应：

```json
{
  "job_id": 12,
  "status": "succeeded",
  "duplicate": false,
  "scan_id": "6f1f...",
  "save_id": 1,
  "players_created": 820,
  "players_updated": 0,
  "instances_matched": 0,
  "snapshots_created": 820,
  "transfers_created": 310,
  "transfers_skipped": 5,
  "rows_rejected": 0,
  "warnings": ["..."],
  "errors": [{"row": 12, "entity": "player", "code": "missing_uid", "message": "..."}],
  "coverage": {"players": 820, "transfers": 310, "attributes": 0.93}
}
```

- `duplicate=true` 表示同一 `scan_id` 已成功导入，后端未写入任何数据（幂等）。
- 部分行失败时 `status="partial"`，成功行照常入库，失败行写入 `import_rows`。

`GET /imports?save_id=&limit=&offset=` → `{"items": [ImportJob], "total": n}`，
`ImportJob = {id, save_id, scan_id, source, status, received_at, finished_at, player_count, transfer_count, warnings, coverage, raw_payload_path}`。

### V3.3.0 数据中心（data-hub）

普通用户只需要两个动作：查看连接状态、导入一次文件。格式/版本识别、校验、修复、去重与验证全部自动完成。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/data-hub/status` | 游戏连接、存档识别、记录数、最近同步、健康状态、待确认数量 |
| POST | `/data-hub/import` | 统一导入入口；`multipart/form-data`（字段 `file`）或原始请求体 |
| GET | `/data-hub/repairs?import_job_id=&decision=&limit=&offset=` | 按批次查看修复前后的值与隔离原因 |
| GET | `/data-hub/capabilities` | 自动识别支持的来源与格式 |

`POST /data-hub/import` 查询参数：`save_id`、`save_identity_id`、`save_session_id`、`operation_id`、
`dry_run`（只检查不写库）、`filename`。响应示例：

```json
{
  "status": "PASS",
  "stages": [{"id": "detect", "label": "正在识别数据", "status": "pass"}],
  "detection": {"source": "scan_json", "format": "json", "schema_version": "1.0", "compatible": true},
  "counts": {"created": 820, "updated": 0, "duplicates": 3, "repaired": 41, "quarantined": 2, "rejected": 0},
  "import": {"job_id": 12, "save_id": 1, "duplicate": false, "status": "succeeded"},
  "verification": {"status": "PASS", "checks": []},
  "quarantine": [{"row": 8, "entity": "player", "code": "missing_name", "message": "..."}]
}
```

- `status` 只允许 `PASS` / `PARTIAL` / `FAIL` / `ROLLED_BACK` / `BLOCKED`。
- 不支持的版本或格式返回 `422`，`error.code` 为 `unsupported_version` / `unsupported_format`，**不写入任何数据**。
- 同一 `scan_id` 重复导入返回 `duplicate=true`，不新增数据、不重复写修复审计。
- 修复审计写入 `data_repair_audits`（`decision=repaired|quarantined`），与业务写入同一事务。


## 5. 球员（players）

### GET /players
查询参数（全部可选）：`save_id, query（姓名模糊）, position, position_group, min_age, max_age, min_ca, max_pa, max_value, max_wage, club_id, watchlist_only, sort（age|ca|pa|market_value|name|updated_at，前缀 - 表示降序）, limit, offset`。

```json
{
  "items": [{
    "instance_id": 11, "player_id": 5, "name": "Adam Wharton", "age": 22,
    "birth_date": "2004-02-06", "nationality": "England", "position": "DM",
    "position_group": "MF", "club": "Crystal Palace", "club_id": 3,
    "ca": 148, "pa": 165, "market_value": 42000000, "wage": 60000,
    "contract_end": "2029-06-30", "observed_at": "2026-11-18T03:00:00Z",
    "data_completeness": 0.91, "source": "fm27_live_reader", "is_watched": true
  }],
  "total": 1,
  "coverage": {"ca": 0.98, "pa": 0.98, "market_value": 0.93, "contract_end": 0.71}
}
```

### GET /players/{instance_id}
```json
{
  "summary": { "...同 GET /players 的元素..." },
  "attributes": [{"key": "passing", "name": "传球", "category": "technical", "value": 15}],
  "snapshot_count": 4, "first_seen": "2026-08-01", "last_seen": "2026-11-18",
  "latest_snapshot_id": 44,
  "valuation": {"low": 34000000, "mid": 41000000, "high": 52000000,
                "sample_size": 23, "method": "similar_transfers_quantile",
                "algorithm_version": "valuation-1", "confidence": "medium",
                "insufficient_sample": false, "coverage": {"fee": 0.9}},
  "tags": ["核心培养"], "notes": "…"
}
```

### GET /players/{instance_id}/history?from=&to=
```json
{
  "points": [{
    "snapshot_id": 44, "observed_at": "2026-11-18T03:00:00Z", "game_date": "2027-03-01",
    "age": 22, "ca": 148, "pa": 165, "market_value": 42000000, "wage": 60000,
    "contract_end": "2029-06-30", "minutes_played": 2140, "appearances": 31,
    "goals": 4, "assists": 7, "attributes": {"passing": 15, "tackling": 13}
  }],
  "coverage": {"points": 4, "attributes": 0.86}
}
```

### GET /players/{instance_id}/development
```json
{
  "summary": {"snapshots": 4, "ca_delta": 6, "market_value_delta": 12000000,
              "minutes_delta": 900, "window_start": "2026-08-01", "window_end": "2026-11-18"},
  "records": [{"period_start": "2026-08-01", "period_end": "2026-11-18", "ca_delta": 2,
               "market_value_delta": 2000000, "minutes": 640, "appearances": 9, "goals": 1, "assists": 2}],
  "attributions": [
    {"kind": "fact", "factor": "出场时间", "evidence": "窗口内出场 2140 分钟，4 次快照均记录到比赛时间"},
    {"kind": "correlation", "factor": "出场时间与 CA 变化", "evidence": "3 个区间中 2 个同时上升（样本 4）"},
    {"kind": "speculation", "factor": "训练强度", "evidence": "数据源未提供训练强度，任何归因都不可验证"}
  ],
  "data_gaps": ["缺少训练与伤病字段"]
}
```

## 6. Watchlist 与提醒

- `GET /watchlist?save_id=` → `{"items": [{"id": 1, "instance_id": 11, "player": PlayerSummary, "tag": "核心培养", "note": "", "source": "manual", "added_at": "..."}], "total": n}`
- `POST /watchlist/items` body `{instance_id, tag?, note?}` → 同上单条。
- `PATCH /watchlist/items/{id}` body `{tag?, note?}` → 单条。
- `DELETE /watchlist/items/{id}` → 204。
- `POST /watchlist/refresh` → `{"created": n, "alerts": n}`：按规则（U21、PA 阈值、身价变化、合同到期）生成关注与提醒。
- `GET /alerts?save_id=&unread_only=` → `{"items": [{"id": 3, "instance_id": 11, "type": "contract_expiry", "severity": "high", "title": "合同 6 个月内到期", "message": "...", "created_at": "...", "read_at": null}], "total": n}`
- `POST /alerts/{id}/read` → 204。

## 7. 智能球探（scouting）

- `GET /scouting/roles` → `{"items": [{"key": "if_inside_forward", "name": "内锋（IF）", "position_group": "FW", "version": 1, "weights": {"finishing": 1.0, "dribbling": 0.9, "...": 0.5}}]}`
- `POST /scouting/evaluate` body `{instance_id, role_key}` →
```json
{"instance_id": 11, "role_key": "dm_anchor", "role_name": "后腰（DM）", "score": 78.4,
 "components": [{"key": "passing", "name": "传球", "weight": 0.18, "value": 15, "contribution": 13.5}],
 "template_version": 1, "coverage": 0.92,
 "strengths": ["传球 15/20"], "weaknesses": ["抢断 11/20"]}
```
- `POST /scouting/search` body `{save_id, role_key?, filters: {...同 /players 查询参数...}, limit}` → `{"items": [{"player": PlayerSummary, "score": 78.4, "coverage": 0.92, "role_key": "dm_anchor"}], "total": n}`。

## 8. 转会（transfers / Transfer Intelligence）

### GET /transfers
参数：`save_id, status（completed|pending|all，默认 completed）, transfer_type, from_date, to_date, club_id, position_group, min_fee, max_fee, min_age, max_age, sort, limit, offset`。
```json
{"items": [{
  "id": 21, "player_instance_id": 11, "player_name": "Adam Wharton",
  "from_club": "Blackburn", "to_club": "Crystal Palace",
  "transfer_type": "permanent", "status": "completed", "transfer_date": "2026-07-01",
  "base_fee": 22000000, "fee_paid": 22000000, "addons_potential": 3000000,
  "effective_fee": 22000000, "currency": "EUR",
  "player_age_at_transfer": 22, "player_ca_at_transfer": 141, "player_pa_at_transfer": 165,
  "contract_remaining_months": 24, "season": "2026/27",
  "source": "fm27_live_reader", "confidence": 0.9,
  "fee_components": [{"type": "base_fee", "amount": 22000000, "status": "paid", "due_date": null}]
}], "total": 1,
 "coverage": {"transfer_date": 0.99, "ca_at_transfer": 0.42, "contract_remaining_months": 0.31}}
```

### GET /transfers/stats
参数：`save_id, position_group, min_age, max_age, min_ca, max_ca, from_date, to_date, club_id, league`。
```json
{"sample_size": 128, "currency": "EUR", "median": 8500000, "p25": 3000000, "p75": 18000000,
 "mean": 12400000, "min": 0, "max": 120000000,
 "distribution": [{"bucket_start": 0, "bucket_end": 5000000, "count": 44}],
 "filters": {"position_group": "FW", "min_age": 18, "max_age": 23},
 "coverage": {"fee": 0.97, "ca_at_transfer": 0.41},
 "algorithm_version": "transfer-stats-1",
 "excluded": {"incomplete": 3, "non_completed": 0},
 "warnings": ["样本中 41% 缺少成交时 CA，分位数未按 CA 校正"]}
```

### GET /transfers/similar?instance_id=&limit=20
```json
{"target": {"instance_id": 11, "name": "Adam Wharton", "age": 22, "position_group": "MF", "ca": 148, "pa": 165},
 "items": [{"transfer_id": 21, "transfer": {...同 /transfers 元素...}, "similarity": 0.91,
            "factors": [{"key": "age", "value": 22, "target": 22, "distance": 0.0, "weight": 0.25}]}],
 "effective_weights": {"age": 0.25, "ca": 0.3, "pa": 0.2, "position": 0.15, "contract": 0.1},
 "missing_fields": ["contract_remaining_months"],
 "sample_size": 20, "data_gaps": ["目标球员缺少合同剩余月数，已重新分配权重"]}
```

### GET /transfers/valuation?instance_id=
```json
{"instance_id": 11, "currency": "EUR",
 "low": 34000000, "mid": 41000000, "high": 52000000,
 "sample_size": 23, "method": "similar_transfers_quantile",
 "algorithm_version": "valuation-1", "confidence": "medium",
 "insufficient_sample": false,
 "basis": {"median": 41000000, "p25": 34000000, "p75": 52000000,
           "adjustment": {"market_value_ratio": 1.02, "contract_factor": 0.95}},
 "coverage": {"fee": 0.9}, "warnings": []}
```
`insufficient_sample=true` 时 `low/mid/high` 为 `null`，`warnings` 说明原因（样本 < 5）。

### GET /clubs 与 GET /clubs/{club_id}/transfer-profile
```json
{"club_id": 3, "name": "Crystal Palace", "nation": "England", "league": "Premier League",
 "reputation": 6200, "is_user_club": true, "currency": "EUR",
 "bought": {"count": 12, "total": 180000000, "median": 12000000},
 "sold": {"count": 6, "total": 90000000, "median": 14000000},
 "net_spend": 90000000, "avg_profit_per_sale": 2000000,
 "young_signing_ratio": 0.58, "loan_in_count": 2, "loan_out_count": 3,
 "top_transfers": [{"...": "同 /transfers 元素"}],
 "sample_size": 18, "coverage": {"fee": 0.94}}
```

## 9. 概览与诊断

- `GET /analytics/overview?save_id=` →
```json
{"save": Save, "players": 820, "snapshots": 2410, "transfers": 310, "clubs": 42,
 "completed_transfer_value": 1240000000, "watchlist": 14, "alerts": 5,
 "coverage": {"ca": 0.97, "fee": 0.92}, "last_import": ImportJob,
 "trend": [{"date": "2026-11-01", "ca_avg": 121.4, "value_total": 900000000}]}
```
- `GET /compatibility` → `{"items": [{"app_id": "4530370", "build_id": "26577676", "plugin_version": "27.0.1+2503222", "status": "candidate", "notes": "待本机验证"}], "reader_versions": ["0.1.0"]}`

## 10. AI 决策中心

- `GET /agent/conversations?save_id=` → `{"items": [{"id": 1, "title": "相似成交价格", "created_at": "...", "message_count": 4}]}`
- `POST /agent/conversations` body `{title?}` → 会话。
- `GET /agent/conversations/{id}/messages` → `{"items": [{"id": 1, "role": "user|assistant", "content": "...", "created_at": "...", "tool_calls": [...], "answer": AgentAnswer|null}]}`
- `POST /agent/conversations/{id}/messages` body `{question, save_id?, instance_id?}` →
```json
{"message_id": 9, "mode": "deterministic",
 "answer": {
   "conclusion": "建议首报 3600 万，目标区间 3400–4100 万，上限 5200 万（样本 23 笔）。",
   "sections": [
     {"key": "sample", "title": "样本说明", "bullets": ["筛选：MF、20–24 岁、CA 135–160"]},
     {"key": "stats", "title": "价格统计", "table": {"columns": ["指标", "数值"], "rows": [["中位数", "4100 万"], ["P25", "3400 万"]]}},
     {"key": "comparables", "title": "可比交易", "table": {"columns": ["球员", "日期", "费用"], "rows": [["...", "...", "..."]]}},
     {"key": "risks", "title": "风险提示", "bullets": ["41% 样本缺少成交时 CA"]}
   ],
   "sample_size": 23, "filters": {"position_group": "MF"},
   "evidence": [{"type": "tool", "label": "get_transfer_price_stats", "value": {"sample_size": 23}}],
   "disclaimers": ["结论是决策辅助，不是游戏内真实报价。"],
   "confidence": "medium", "data_gaps": [], "mode": "deterministic"
 },
 "tool_calls": [{"name": "get_transfer_price_stats", "arguments": {...}, "result_summary": "sample_size=23"}]
}
```

回答硬性要求：任何数字都来自工具结果；样本不足时必须给出 `insufficient_sample` 并拒绝精确估值；必须出现 `sample` 与 `risks` 两个 section。

## 11. V2 智能模块接口

所有 V2 接口沿用第 1 节约定：缺失值为 `null`，响应带 `algorithm_version`，未配置令牌时不做鉴权。

### 11.1 阵容智能 `/squad/*`

- `GET /squad/overview?save_id=&profile=&coverage=&depth=&age=&fit=&wage=&potential=`
  返回六维评分、位置深度、年龄结构、工资结构、合同预警、短板排序与接班规划：
```json
{"save_id": 1, "club": {"id": 1, "name": "Northbridge United", "league": "Premier Division"},
 "squad_size": 26, "score": 74.66,
 "profile": {"key": "balanced", "name": "均衡评估", "weights": {"coverage": 0.25, "depth": 0.2, "age": 0.15, "fit": 0.15, "wage": 0.15, "potential": 0.1}, "overridden": false},
 "components": [{"key": "coverage", "label": "位置覆盖（C）", "value": 100.0, "weight": 0.25,
                 "evidence": ["10/10 个位置有人可用"], "missing": [], "available": true}],
 "depth": [{"slot": "CB", "slot_name": "中后卫", "count": 4, "required": 4, "importance": 1.0,
            "coverage": 1.0, "depth_quality": 0.72, "status": "一般",
            "suggestion": "寻找替补：中后卫替补与主力差距过大", "players": [{"instance_id": 12, "name": "..."}]}],
 "age_structure": {"average_age": 25.8, "median_age": 26.0, "buckets": [{"bucket": "21-24", "count": 3, "share": 0.12, "ideal_share": 0.3, "players": []}]},
 "wage_structure": {"total": 1890897, "median": 52000, "top3_share": 0.18, "top_earners": []},
 "contracts": {"today": "2027-03-01", "buckets": {"expired": [], "6m": [], "12m": [], "24m": [], "later": [], "unknown": []}, "at_risk_count": 6, "at_risk_names": []},
 "weakness": [{"slot": "LW", "slot_name": "左边锋", "severity": 46.8, "count": 3, "required": 2, "status": "一般", "suggestion": "...", "evidence": ["..."]}],
 "succession": [{"player": {...}, "internal_options": [], "ready_now": [], "external_profile": {"slot": "ST", "age_max": 23, "ca_floor": 120}, "verdict": "内部有培养对象", "evidence": []}],
 "algorithm_version": "squad-score-1", "data_gaps": []}
```
  `components[].value` 为 `null` 表示该维度缺少输入，`missing` 说明原因，权重会在可用维度间重新分配。
- `GET /squad/depth` — 只返回深度表（`items` / `squad_size` / `missing_position`）。
- `GET /squad/contracts` — 合同分桶。
- `GET /squad/succession` — 接班规划。
- `GET /squad/profiles` — 权重模板列表（含 `default_weights`）。
- `PUT /squad/profiles` — 新建或更新模板：`{"key", "name", "description", "weights": {"coverage": 0.3, ...}, "is_default"}`；
  权重自动归一化。
- `GET /squad/weights` — 展示一次请求会使用的权重，不修改任何状态。
- `GET /squad/club` — 当前被视为「我的俱乐部」的球队；没有时返回 404 `user_club_missing`。

### 11.2 智能球探引擎 `/recruitment/*`

- `GET /recruitment/model` — 位置属性模板与六维权重（口径说明）。
- `POST /recruitment/search` — `{"slot": "ST", "min_age": 18, "max_age": 23, "max_value": 30000000, "limit": 20}`；
  返回 `items[]`（每条含 `player` / `score` / `dimensions[]` / `position_template` / `strengths` / `risks` / `cost_estimate`）
  与 `data_gaps`。
- `GET /recruitment/player/{instance_id}` — 单个球员的完整球探报告。
- `POST /recruitment/compare` — `{"instance_ids": [11, 12]}`；返回 `shared_dimensions`，只比较所有球员都能评分的维度。
- `GET /recruitment/hidden-value?slot=&limit=` — 隐藏价值命中与规则覆盖：
```json
{"items": [{"rule": "contract_expiring", "rule_label": "合同即将到期", "signal": 74.0, "player": {...}, "evidence": ["合同 6 个月后到期（2027-01-28）"]}],
 "rules": {"evaluated": [{"key": "contract_expiring", "label": "合同即将到期"}], "unavailable": [{"key": "transfer_listed", "label": "被俱乐部挂牌", "missing_fields": ["transfer_listed"], "description": "..."}]}}
```
- `GET /recruitment/shortlists` / `GET /recruitment/shortlists/{id}` — 存储的候选名单。
- `POST /recruitment/shortlists` — `{"name": "中锋引援", "slot": "ST", "budget": 30000000, "limit": 10}`；
  返回生成结果与 `shortlist_id`。

### 11.3 球员发展 `/development/*`

- `GET /development/board?limit=&min_age=` — 至少两个快照的球员按成长速率排序。
- `GET /development/player/{instance_id}`:
```json
{"player": {"instance_id": 12, "name": "...", "age": 18, "ca": 122, "pa": 165},
 "points": [{"date": "2026-08-01", "age": 18, "ca": 110, "pa": 165, "ca_delta": null, "change_label": "初始记录"}],
 "rates": {"overall_per_month": 2.0, "recent_per_month": 2.0, "classification": "fast", "formula": "GrowthRate = (CA_t − CA_t−1) / Δ月", "sample_size": 1, "intervals": []},
 "advice": [{"action": "增加比赛时间", "reason": "...", "confidence": "medium", "evidence": ["..."]}],
 "outlook": {"band": "on_track", "label": "大概率达到潜力区间", "probability": 0.96,
             "projected_low": 130.0, "projected_high": 165.0, "projected_center": 139.0, "horizon_age": 24,
             "rationale": "...这是等级与区间，不是精确 CA 预测"},
 "data_gaps": [], "algorithm_version": "development-1"}
```

### 11.4 表现分析 `/performance/*`

- `GET /performance/metrics` — 每个位置组跟踪的指标。
- `GET /performance/board?slot=&min_minutes=&limit=` — 有统计的球员按产出百分位排序。
- `GET /performance/player/{instance_id}` — 分位置产出、趋势与能力对比：
```json
{"season": {"period": "2026/27", "minutes_played": 1800, "goals": 8, "xg": 7.5},
 "metrics": [{"key": "goals", "label": "进球", "total": 8, "per90": 1.164, "percentile": 0.93, "peer_sample": 22, "higher_is_better": true, "available": true}],
 "trend": {"available": true, "windows": ["season"], "unavailable_windows": {"last5": "需要逐场统计，数据源未提供"}},
 "ability_vs_output": {"available": true, "ability_percentile": 0.62, "output_percentile": 0.93, "gap": 0.31, "verdict": "表现优于属性预期"},
 "data_gaps": []}
```

### 11.5 转会成本与复盘 `/transfers/*`

- `GET /transfers/review?save_id=&club_id=` — 本队已完成交易的复盘（同类分位、能力与身价变化、结论、依据）。
- `GET /transfers/categories` — 交易类型体系：`categories[]`（`label` / `count` / `known_spend` / `counts_in_stats` / `treatment`）。
- `GET /transfers/{transfer_id}/cost?wage_period=week&contract_years=` — 单个交易的总成本模型。
- `POST /transfers/deal-report` — `{"instance_id": 11, "fee": 30000000, "budget": 35000000}`；
  返回 `cost`（含每个成本项 `status`）、`investment`、`rows[]`、`recommendation`、`data_gaps`。
- `GET /transfers/investment?instance_id=&total_cost=` — 给定总成本的投资效率。

### 11.6 AI 体育总监 `/agent/*`

- 工具名固定为：`get_squad_overview`、`get_player_profile`、`search_players`、`evaluate_player`、`compare_players`、
  `analyze_position_depth`、`find_transfer_targets`、`analyze_transfer_history`、`get_player_growth_history`、
  `generate_recruitment_report`。
- 回答新增两段：
```json
{"reliability": {"facts": ["阵容评分"], "computed": ["六个维度"], "inferences": ["推荐理由与风险"],
                 "unavailable": ["数据源未提供伤病记录"], "rule": "数据库事实 / 模型计算结果 / AI 推断 / 无法获得的数据 四类必须分开呈现"},
 "citations": [{"tool": "get_squad_overview", "arguments": {"save_id": 1}, "summary": "...", "warnings": []}]}
```
- `GET /agent/reports?save_id=&limit=` — 已保存的 AI 报告（含可靠性分类与引用）。

## 12. 外部数据源适配

- `GET /imports/fmscout/adapter` — 上游身份、许可证、可映射/缺失/忽略字段与属性映射表。
- `POST /imports/fmscout/preview` — 上传 dump（multipart `file` 或原始 JSON），只转换并返回报告，不写库：
```json
{"report": {"players_total": 3, "players_skipped": 1, "players_converted": 2, "clubs_converted": 2,
            "user_club": "Northbridge United", "attributes_mapped": 12, "attributes_ignored": ["Corners"],
            "mapped_fields": ["id", "name", "ca", "pa", "attrs"],
            "absent_fields": ["minutes_played", "appearances", "goals", "assists", "statistics", "transfers"],
            "ignored_fields": [{"field": "professionalism", "reason": "隐藏性格属性，ScoutMind 未建模"}],
            "coverage": {"ca": 1.0, "pa": 1.0, "market_value": 0.5},
            "warnings": ["..."]},
 "scan": {"scan_id": "fmscout-1a2b...", "game_date": "2027-03-01"},
 "counts": {"clubs": 2, "players": 2},
 "sample_players": [{"name": "Adam Wharton", "ca": 148, "pa": 165}]}
```
- `POST /imports/fmscout` — 转换并幂等导入，返回同一份 `report` 与 `import`（字段同 `/imports/scan`）。
- `POST /imports/scan` 也会自动识别 dump：响应多一个 `adapted_by` 字段说明这次导入经过适配层转换。

## 13. P0 阶段新增接口

### 13.1 真实数据审查 `POST /imports/fmscout/validate`
上传 dump，返回分节报告（不写库）：
```json
{"sections": [
   {"id": "file", "title": "[1] File", "rows": [{"label": "JSON valid", "value": "PASS"},
     {"label": "Dump version", "value": "FM27"}, {"label": "Scan id", "value": "fmscout-506ba1acbf8a8fad"}]},
   {"id": "dataset", "title": "[2] Dataset", "rows": [{"label": "Total players", "value": 24}]},
   {"id": "coverage", "title": "[3] Field coverage", "rows": [{"label": "CA / PA", "value": "100%"}]},
   {"id": "identity", "title": "[4] Identity / 与现有数据的关系", "rows": [{"label": "将在存档中新建的球员", "value": 24}]},
   {"id": "risks", "title": "[5] Risks", "rows": [{"label": "未知字段", "value": 0}]}],
 "verdict": {"status": "review", "blockers": [], "review": ["导出没有当前伤病状态…"], "ready_to_import": true},
 "report": {...适配报告...}, "counts": {"clubs": 3, "players": 24}}
```
`verdict.status`：`pass` 可直接导入；`review` 有需要人工判断的项；`blocked` 不要导入。

### 13.2 球员状态 `GET /players/{instance_id}/status`
```json
{"instance_id": 12, "player_name": "Adam Wharton",
 "current": {"observed_at": "...", "flags": {"listed": true, "loan_listed": false, "not_for_sale": false, "set_for_release": false},
   "injury": {"proneness": 13, "injured": null, "start_date": null, "expected_return": null},
   "registration": {"parent_club": null, "loan_club": null, "team_type": null}, "agreed_transfer": null},
 "history": [{"observed_at": "...", "flags": {...}, "injured": null, "injury_proneness": 13,
              "parent_club": null, "loan_club": null, "source": "fmsuperscout"}],
 "changes": [{"field": "listed", "label": "挂牌出售", "from": false, "to": true, "observed_at": "..."}],
 "first_seen": {"listed": {"value": true, "first_seen_at": "...", "last_confirmed_at": "..."}},
 "loans": [{"id": 1, "parent_club": "A", "loan_club": "B", "has_option": null, "has_obligation": null, "status": "active"}],
 "candidates": [{"id": 3, "to_club": "B", "kind": "unknown", "status": "candidate"}],
 "data_gaps": ["数据源未提供当前伤病状态，不能据此判断球员是否受伤"],
 "algorithm_version": "player-status-1"}
```
三态字段 `null` 表示来源没有提供，**不能读作否**；`has_option=null` 表示条款未知，不是「无条款」。

### 13.3 候选转会
- `GET /transfers/candidates?save_id=&status=candidate&limit=100` → `items[]`：`player`、`from_club`、`to_club`、
  `kind`（`loan`/`unknown`）、`detected_at`、`status`、`evidence`（含「只能作为候选」规则）。
- `POST /transfers/candidates/{id}/confirm`，body `{"transfer_date": "2027-07-01", "fee": 12000000}`（都可选）；
  未给 `transfer_id` 时按候选信息创建一笔 `status=completed`、金额未知的交易，并返回 `transfer_id`。
- `POST /transfers/candidates/{id}/dismiss`，body `{"reason": "租借回归"}`；已处理的候选再次确认返回 409。

### 13.4 历史交易独立通道 `POST /imports/transfers`
只导入 `transfers`（可带 `clubs`），允许 `players` 为空；缺少 `transfers` 返回 422 `no_transfers`。
`scan_id` 可用报文自带值，否则按内容哈希生成，因此同一份历史重复导入返回 `duplicate=true`。

## 14. 俱乐部解析与阵容名单（2026-11 新增）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/clubs/search` | 搜索俱乐部；返回 `source` / `source_label` / `confidence` / `players` |
| `GET` | `/clubs` | 同上的完整列表（保留 `club_id` 兼容字段） |
| `GET` | `/saves/{save_id}/user-club` | 当前本队、记录来源与指定方式（`assignment_source`） |
| `PUT` | `/saves/{save_id}/user-club` | 指定本队，body `{"club_id": 17}`；不移动球员 |
| `DELETE` | `/saves/{save_id}/user-club` | 清除本队 |
| `POST` | `/imports/squad-csv?save_id=` | 导入阵容名单（multipart `file` 或裸 CSV），返回逐行结果 |
| `GET` | `/imports/squad-csv/template` | 可填写的 CSV 模板 |

`POST /imports/squad-csv` 响应：

```json
{
  "counts": {"assigned": 17, "review": 0, "unmatched": 0, "invalid": 0},
  "total": 17,
  "clubs_created": 0,
  "assignments_written": 17,
  "duplicate": false,
  "warnings": [],
  "detected_columns": {"name": "姓名", "player_id": "球员ID"},
  "rows": [
    {"index": 1, "name": "...", "status": "assigned", "confidence": 1.0, "matched_by": ["player_id"], "reason": null}
  ]
}
```

`GET /squad/overview` 增加 `composition`：`available`、`counts`/`buckets`（`senior`/`reserve`/`youth`/`loaned_out`/`loaned_in`/`unknown`）、`gaps`。
`GET /players` 的每一行增加 `save_local_uid`，用于填写阵容 CSV。

## 15. 自由球员待确认（Unresolved，2026-11 新增）

无可用身份的球员（上游哨兵 `4294967295`、缺失 ID 或非法 ID）不会写成 `save_local_uid`，也不会创建
`PlayerInstance`。它们以「候选 + 观察」的形式保存，只有人工确认后才建立身份关联。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/unresolved-players` | 当前存档的候选列表；`status`、`name`、`position`、`min_ca`、`min_pa`、`page`、`page_size` |
| `GET` | `/unresolved-players/{candidate_id}` | 详情：UID 原始状态、证据、匹配建议、审计历史 |
| `GET` | `/unresolved-players/{candidate_id}/observations` | 分页的原始观察记录 |
| `POST` | `/unresolved-players/{candidate_id}/resolve` | 人工关联到同一存档内的既有身份（必须 `confirm=true`） |
| `POST` | `/unresolved-players/{candidate_id}/dismiss` | 忽略候选；观察记录保留 |

列表响应：

```json
{
  "items": [{
    "id": 1, "save_id": 1, "status": "pending",
    "display_name": "Free Agent One", "birth_date": "2003-07-01", "position": "ST",
    "observation_count": 1, "first_seen_at": "2026-11-23T10:00:00Z", "last_seen_at": "2026-11-23T10:00:00Z",
    "uid": {"status": "sentinel", "reason": "sentinel_uid", "raw_uid": "4294967295",
            "note": "原始 UID 只作为证据保存，不会写入 save_local_uid"},
    "latest_observation": {"observation_id": 11, "scan_id": "scan-1", "row_index": 14,
                           "ca": 118, "pa": 132, "club_name": null, "contract_end": null},
    "resolution": null, "dismissal": null, "suggestions_are_advisory": true
  }],
  "total": 14, "page": 1, "page_size": 20,
  "counts": {"pending": 14, "review_required": 0, "resolved": 0, "dismissed": 0},
  "note": "这些球员没有可用身份；确认之前不进入任何正式统计"
}
```

`POST /unresolved-players/{id}/resolve` body：

```json
{"player_instance_id": 9, "confirm": true, "note": "人工核对姓名与生日"}
```

- `confirm` 必须为 `true`，否则 400 `confirmation_required`；
- 目标必须是**同一存档**内的 `player_instance_id` 或 `player_id`，否则 404 `target_not_in_save`；
- 已处理过的候选再次确认返回 409 `unresolved_already_decided`（并发用条件 UPDATE 拦截）；
- 成功后在事务内写 `identity_matches`（`strategy=unresolved_manual_link`）与不可覆盖的
  `unresolved_player_actions` 审计行，返回 `audit_action_id`。

`POST /unresolved-players/{id}/dismiss` body：`{"reason": "不是目标球员", "note": "可选"}`；
`reason` 必填；重复忽略返回 409。两个接口都不会删除观察记录，越权访问一律 404。

## 16. 存档身份与会话（V3.2.7.2 新增）

协议：`save-identity/v1`，完整字段与状态机见 `docs/SCOUTMIND-V3.2.7.2-IDENTITY-PROTOCOL.md`。
所有接口归属当前活动存档（`get_active_save`，可用 `save_id` 查询参数显式指定）。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/save-identities/register` | 幂等注册/更新身份；状态由后端按证据封顶 |
| POST | `/save-identities/{id}/verify` | 人工确认升级（必须 `confirmed_fingerprint` + `basis`） |
| GET | `/save-identities` | 列表、状态计数（`status` / `limit` / `offset`） |
| GET | `/save-identities/{id}` | 详情：证据、最近会话、`capture_allowed` 与 `blockers` |
| POST | `/save-sessions/start` | 开始会话；`session_key` 幂等 |
| POST | `/save-sessions/{id}/heartbeat` | 上报指纹/build；不一致即使会话失效 |
| POST | `/save-sessions/{id}/end` | 正常结束 |
| POST | `/save-sessions/{id}/invalidate` | 主动失效（切换/退出） |
| GET | `/save-identity-audit` | 审计事件，可按 `identity_id` / `session_id` / `capture_id` 过滤 |

关键错误码：`save_context_mismatch`、`save_identity_unverified`、`save_session_invalidated`、
`save_switch_in_progress`、`save_identity_conflict`。错误体统一为
`{"error": {"code": "...", "message": "..."}}`。

`POST /captures` 与 `PATCH /captures/{id}` 可携带 `save_identity_id` / `save_session_id`；
声明时回填归属列，后续写入必须与解析出的上下文一致，否则 409。

