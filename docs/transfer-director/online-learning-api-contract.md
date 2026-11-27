# V3.3.2-08 在线学习 API 契约

前缀：`/api/v1`。鉴权与既有接口一致（`Depends(require_token)` + `get_active_save`）。
错误格式统一 `{"error": {"code": "...", "message": "..."}}`。所有查询以服务端当前存档为作用域，`save_id` 不接受客户端传入。

## 1. 学习状态

`GET /transfer-learning/status`

响应：

```json
{
  "save_id": 1,
  "status": "MONITORING",
  "status_label": "正在监视转会市场",
  "enabled": true,
  "paused": false,
  "save_name": "My Career",
  "last_monitor_at": "2026-11-27T09:00:00Z",
  "last_event_at": "2026-11-27T08:59:00Z",
  "last_learning_at": "2026-11-27T09:00:05Z",
  "counts": {
    "events_observed": 120,
    "events_confirmed": 35,
    "confirmed_transfers": 12,
    "global_clubs": 76,
    "focus_clubs": 3
  },
  "latest_error": null,
  "coverage": {
    "transfer_history_available": true,
    "native_reader_transfers": false,
    "offers_available": false,
    "note": "原生读取器不提供转会历史；只有导入的成交记录会计入学习"
  }
}
```

## 2. 学习控制

- `POST /transfer-learning/start` → `{"status": "...", "task": {...} | null}`
- `POST /transfer-learning/pause` → `{"status": "PAUSED", "enabled": false}`
- `POST /transfer-learning/resume` → `{"status": "MONITORING", "enabled": true, "task": {...} | null}`

说明：`start/resume` 在存在未处理数据时创建 `TRANSFER_LEARNING` 后台任务；同存档已有活跃任务时返回既有任务（`reused=true`），不重复启动。`pause` 只阻止新的自动学习，不删除已有成果。

## 3. 事件查询

`GET /transfer-learning/events`

| 参数 | 类型 | 说明 |
|---|---|---|
| `club_id` | int | 买方或卖方俱乐部 |
| `player_instance_id` | int | 球员实例 |
| `event_type` | str | 事件类型枚举 |
| `verification_status` | str | `CONFIRMED/OBSERVED/INFERRED/UNVERIFIED/REJECTED` |
| `since` / `until` | date | 按 `game_date` 过滤 |
| `limit` / `offset` | int | 默认 50，最大 200 |

响应：

```json
{
  "items": [{
    "event_id": 1,
    "event_type": "TRANSFER_COMPLETED",
    "transaction_type": "permanent",
    "verification_status": "CONFIRMED",
    "player_instance_id": 10,
    "player_name": "…",
    "buying_club_id": 2,
    "buying_club_name": "…",
    "selling_club_id": 3,
    "selling_club_name": "…",
    "amount": 25000000.0,
    "currency": "EUR",
    "currency_known": true,
    "game_date": "2026-07-01",
    "observed_at": "2026-11-27T09:00:00Z",
    "source": "fm27_live_reader",
    "learning_eligible": true
  }],
  "total": 120,
  "limit": 50,
  "offset": 0
}
```

金额未知时 `amount=null`、`currency=null`、`currency_known=false`；不默认 EUR。

## 4. 全球俱乐部画像

`GET /transfer-learning/clubs?search=&league=&transaction_type=&min_sample=&limit=&offset=`

```json
{
  "items": [{
    "club_id": 2,
    "club_name": "…",
    "league": "…",
    "priority": "global",
    "sample_size": 7,
    "confidence": {"level": "limited", "label": "有限参考", "sample_size": 7, "quality_score": 0.71, "basis": ["…"]},
    "buying": {"completed": 4, "loans": 1, "total_fee": 41000000.0, "currency": "EUR", "mixed_currency": false},
    "selling": {"completed": 2, "loans": 0, "total_fee": 12000000.0, "currency": "EUR", "mixed_currency": false},
    "updated_at": "2026-11-27T09:00:05Z"
  }],
  "total": 76,
  "limit": 50,
  "offset": 0
}
```

`GET /transfer-learning/clubs/{club_id}` 额外返回 `patterns[]`（样本量与置信度）、`recent_events[]`。

## 5. 重点学习对象

`GET /transfer-learning/focus-clubs?limit=&offset=`

返回 `priority='focus'` 的俱乐部，附带 `promotion_reason`、`last_transaction_at`、`trade_counts`、`confidence`。

## 6. 策略查询

`GET /transfer-learning/strategies`

```json
{
  "save_id": 1,
  "available": true,
  "global": {"clubs": 40, "samples": 88, "confidence": {...}},
  "patterns": [{"key": "loan_preference", "label": "租借倾向", "sample_size": 6, "confidence": {...}, "summary": "…"}],
  "focus": [{"club_id": 2, "club_name": "…", "patterns": [...]}],
  "message": null
}
```

无样本时 `available=false`、`patterns=[]`、`message` 说明原因；不虚构结论。

## 7. 最近学习动态

`GET /transfer-learning/activity?limit=20`

```json
{"items": [{"activity_id": 5, "activity_type": "event_detected", "title": "已观察到一笔永久转会", "created_at": "…", "club_id": 2, "event_id": 12, "detail": {}}], "total": 5}
```

## 8. 报价接口（既有，增强响应）

`POST /transfer-director/player/{instance_id}/purchase-offers` 等既有接口在响应中新增：

```json
"learning_adjustment": {
  "applied": true,
  "club_id": 2,
  "club_priority": "focus",
  "multiplier": 1.07,
  "before": 25000000.0,
  "after": 26750000.0,
  "sample_size": 5,
  "confidence": {"level": "limited", "label": "有限参考", "sample_size": 5, "quality_score": 0.66, "basis": ["…"]},
  "basis": "对方俱乐部相似成交金额中位数高于当前估值（倍数限制在 0.85–1.15）"
}
```

未应用时 `applied=false`，`basis` 说明原因（无画像/样本不足/币种未知），报价保持既有规则结果。

## 9. 校验与安全

- 未知 `event_type` / `verification_status` 返回 422。
- `club_id` / `player_instance_id` 不属于当前存档返回 404（复用 `deps.get_active_save` 与既有 404 语义）。
- 分页上限 200；`activity` 上限 100。
- 不返回原始 SQL、堆栈、内部阈值或开发参数。
