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
