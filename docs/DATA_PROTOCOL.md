# ScoutMind 数据协议 v1（扫描 → 导入）

扫描器、Desktop Agent 与后端之间交换的数据格式。后端 `POST /imports/scan` 接收本协议；校验失败的行不会入库，也不会被填充默认值。

## 1. 传输形式

1. `application/json`：单个 JSON 对象（字段如下）。
2. `multipart/form-data`：`file` 字段上传 `.json` 文件（内容同 1）。
3. `application/x-ndjson`：第一条为 header，包含 `schema_version/source/game/scan/coverage/warnings`；其后每行一条 `{"entity": "player"|"transfer"|"club", ...}`。适合扫描器流式输出。

## 2. 报文结构

```json
{
  "schema_version": "1.0",
  "source": "fm27_live_reader",
  "reader_version": "0.1.0",
  "game": {"version": "27.0.1", "build": "26577676", "app_id": "4530370"},
  "scan": {
    "scan_id": "8b1d2c2a-0e6e-4b0b-9a5a-0b1f5d7a3c11",
    "observed_at": "2026-11-18T03:00:00Z",
    "game_date": "2027-03-01",
    "user_club_uid": "1001"
  },
  "coverage": {"players": true, "transfers": true, "attributes": true, "finances": false},
  "warnings": ["扫描器未提供伤病字段"],
  "clubs": [],
  "players": [],
  "transfers": []
}
```

必填：`schema_version`、`source`、`scan.scan_id`、`scan.observed_at`。
`scan_id` 是幂等键：同一 `scan_id` 成功导入后再次提交，后端返回 `duplicate=true` 且不写入任何数据。

## 3. 实体

### club
```json
{"uid": "1001", "name": "Crystal Palace", "nation": "England", "league": "Premier League",
 "reputation": 6200, "is_user_club": true}
```
`uid` 为存档内唯一 ID；缺失时后端按名称创建并按名称匹配。`reputation`、`league` 可为 `null`。

### player
```json
{
  "record_id": "p-1001",
  "save_local_uid": "770123",
  "game_unique_id": "1234567890",
  "name": "Adam Wharton",
  "birth_date": "2004-02-06",
  "nationality": "England",
  "position": "DM",
  "club_uid": "1001",
  "ca": 148, "pa": 165,
  "market_value": 42000000, "wage": 60000,
  "contract_end": "2029-06-30",
  "minutes_played": 2140, "appearances": 31, "goals": 4, "assists": 7,
  "attributes": {"passing": 15, "tackling": 13, "stamina": 16}
}
```
- `save_local_uid` 必填；`name` 必填；其余缺失写 `null`。
- 属性键使用 `player_attributes` 字典（英文小写下划线，如 `passing`/`off_the_ball`）；未知键记录 `warnings` 并忽略，不写入伪值。
- 身价、工资为整数（游戏货币单位），不做汇率换算。

### transfer
```json
{
  "record_id": "t-551",
  "player_record_id": "p-1001",
  "player_name": "Adam Wharton",
  "transfer_type": "permanent",
  "status": "completed",
  "transfer_date": "2026-07-01",
  "season": "2026/27",
  "from_club_uid": "1010", "from_club_name": "Blackburn",
  "to_club_uid": "1001", "to_club_name": "Crystal Palace",
  "currency": "EUR",
  "base_fee": 22000000,
  "fee_paid": 22000000,
  "addons_potential": 3000000,
  "player_age_at_transfer": 22,
  "player_ca_at_transfer": 141,
  "player_pa_at_transfer": 165,
  "contract_remaining_months": 24,
  "confidence": 0.9,
  "fee_components": [
    {"type": "base_fee", "amount": 22000000, "status": "paid", "due_date": null},
    {"type": "addon", "amount": 3000000, "status": "untriggered", "condition": "出场 50 次"}
  ]
}
```

枚举：
- `transfer_type`: `permanent | loan | free | end_of_contract | clause_release | swap | youth_promotion | other`
- `status`: `completed | pending | future | cancelled | failed | unknown`
- `fee_components[].type`: `base_fee | installment | addon | signing_bonus | agent_fee | loan_fee | sell_on | buy_back | wage_contribution`
- `fee_components[].status`: `paid | scheduled | triggered | untriggered | conditional_unknown | unknown`

只有 `status=completed` 且至少有一个金额来源的交易进入成交统计。`addons_potential` 与 `untriggered` 组件不计入已支付金额。

## 4. 校验规则（导入时强制执行）

| 规则 | 结果 |
| --- | --- |
| `scan_id` 已成功导入 | 整包跳过，`duplicate=true` |
| `observed_at` 非 ISO-8601 / 缺失 | 整包拒绝（400） |
| `source` 不在枚举内 | 整包拒绝（400） |
| 球员缺 `save_local_uid` 或 `name` | 该行拒绝，写 `import_rows` |
| 同一 `save_local_uid` 但 `birth_date` 不一致 | 视为 ID 复用：新建 player+instance，写 warning，不覆盖旧身份 |
| 重复提交同一球员同一 `observed_at` | 不新增快照（追加语义按 `(instance, observed_at)` 去重） |
| 交易缺 `status` | 按 `unknown` 入库，但不进成交统计 |
| 交易缺 `transfer_date` | 该行拒绝 |
| 金额为负 | 该行拒绝 |
| 属性键未知 | 忽略该键并记录 warning |

## 5. 原始文件落盘

后端把每次导入的原始报文保存到 `data/raw/<save_id>/<scan_id>.json`（路径写入 `import_jobs.raw_payload_path`），便于重新解析与排错；删除存档时一并删除。

## 6. 版本策略

`schema_version` 采用 `major.minor`；`major` 变化表示不兼容，后端拒绝并提示升级；`minor` 变化向后兼容，未知字段忽略并记录 warning。读取器与协议版本必须写入 `import_jobs`，便于追溯。
