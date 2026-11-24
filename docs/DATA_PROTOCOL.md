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
  "identity": {"kind": "save_local_uid", "value": "770123"},
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
- `name` 必填；其余缺失写 `null`。
- 身份二选一，互斥：
  - **合法 UID**：`save_local_uid`（1.0 写法）与/或 `identity: {"kind": "save_local_uid", "value": "<uid>"}`。只有通过校验的 UID 才会写入 `save_local_uid`。
  - **Unresolved**：`identity: {"kind": "unresolved", "raw_uid": "4294967295", "reason": "sentinel_uid", "source_record_id": "dump_row:14", "evidence": {"source": "fmsuperscout_dump"}}`。此时**不得**带 `save_local_uid`；该行保存为待确认候选，不创建球员身份。
- 哨兵 `4294967295`（`0xFFFFFFFF`）、`-1`、`0`、空字符串与非法文本都不会成为 `save_local_uid`：哨兵与非法值进入 Unresolved，空值按缺 UID 处理（该行拒绝）。
- `uid_status`/`uid_reason` 由后端根据身份模式推导并覆盖，报文自报的值不会被采信。
- `age` 可选：数据源直接给出年龄时写入，导入时优先使用它，不再由 `birth_date` 反推。
- 属性键使用 `player_attributes` 字典（英文小写下划线，如 `passing`/`off_the_ball`）；未知键记录 `warnings` 并忽略，不写入伪值。
- 身价、工资为整数（游戏货币单位），不做汇率换算。

#### Unresolved 示例（自由球员 / 上游哨兵 ID）

```json
{
  "name": "Free Agent Example",
  "identity": {
    "kind": "unresolved",
    "raw_uid": "4294967295",
    "reason": "sentinel_uid",
    "uid_status": "sentinel",
    "source_record_id": "dump_row:42",
    "evidence": {"source": "fmsuperscout_dump", "field": "id", "row_index": 42, "dump_generated": "2026-11-23T10:00:00"}
  },
  "birth_date": "2003-07-01", "nationality": "England", "position": "ST",
  "ca": 118, "pa": 132, "contract_end": null
}
```

`identity.evidence` 必填（上限 2000 字符）。`reason` 缺失时由 `raw_uid` 的判定结果补全；`raw_uid` 若本身是合法 UID
则拒绝（必须走合法 UID 模式）。


#### 可选：赛季统计块

读取器能读到比赛统计时，`player` 行可以带 `statistics` 数组（每个统计周期一项）。整块可省略，
省略时表现分析会明确报告「没有统计」，不会用 0 代替：

```json
{
  "save_local_uid": "770123",
  "name": "Adam Wharton",
  "statistics": [
    {"period": "2026/27", "competition": "Premier League", "appearances": 31, "starts": 29,
     "minutes_played": 2580, "goals": 4, "assists": 7, "shots": 38, "shots_on_target": 15, "xg": 5.2,
     "key_passes": 42, "passes_attempted": 1580, "passes_completed": 1420, "dribbles": 36,
     "tackles": 68, "interceptions": 51, "clearances": 24, "aerials_won": 33,
     "saves": null, "conceded": null, "clean_sheets": null}
  ]
}
```

- `period` 必填（如 `2026/27`）；同一球员同一 `period` 只保留一行：新观测时间更晚时覆盖计数，否则跳过。
- 所有指标可空；不适用的指标写 `null`（门将行不写射门，前锋行不写扑救）。

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
- `transfer_type`: `permanent | loan | loan_with_option | free | end_of_contract | clause_release | swap | youth_promotion | other`
- `status`: `completed | pending | future | cancelled | failed | unknown`
- `fee_components[].type`: `base_fee | installment | addon | signing_bonus | agent_fee | loan_fee | sell_on | buy_back | buy_option | wage_contribution`
- `fee_components[].status`: `paid | scheduled | triggered | untriggered | conditional_unknown | unknown`

`loan_with_option` 表示租借附买断：租借费用写 `loan_fee`，买断条款写 `buy_option` 且 `status=untriggered`，
触发前不计入任何已支付金额。

只有 `status=completed` 且至少有一个金额来源的交易进入成交统计。`addons_potential` 与 `untriggered` 组件不计入已支付金额。

## 4. 校验规则（导入时强制执行）

| 规则 | 结果 |
| --- | --- |
| `scan_id` 已成功导入 | 整包跳过，`duplicate=true` |
| `observed_at` 非 ISO-8601 / 缺失 | 整包拒绝（400） |
| `source` 不在枚举内 | 整包拒绝（400） |
| 球员缺 `save_local_uid`、`identity` 或 `name` | 该行拒绝，写 `import_rows` |
| 球员 `save_local_uid` 是哨兵（`4294967295` / `-1`）或非法值（`0`、非数字） | 转为 Unresolved 观察，绝不写成合法 UID；`identity.kind=unresolved` 必须自带 `evidence` |
| Unresolved 行同时带 `save_local_uid`，或 `identity.value` 是哨兵 | 该行拒绝（`identity_conflict` / `sentinel_uid`） |
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

当前读取器输出 `1.1`：相对 `1.0` 只增加可选 `identity` 块（合法 UID 与 Unresolved 两种模式）。后端接受全部 `1.x`；
`1.0` 报文里的哨兵 `save_local_uid` 会被降级为 Unresolved 观察，而不是写成身份。`2.0` 仍被拒绝。

## 6. 来源适配层（source = fmsuperscout）

第三方读取器（FMSuperScout）的导出由适配层转换成本协议，转换后的报文与人工/读取器报文走同一条导入路径：

- `source` 新增取值 `fmsuperscout`；
- `scan.scan_id` = `fmscout-<dump 内容 sha256 前 16 位>`，同一份导出重复导入返回 `duplicate=true`；
- `clubs[].uid` 由俱乐部名称派生（`fs-<slug>`），`clubs[].is_user_club` 由导出里的 `meta.myClub` 决定；
- `coverage` 中 `transfers` 与 `statistics` 固定为 `false`：该导出不含转会与统计；
- `warnings` 首条固定声明数据来自 FMSuperScout（MIT），其后是适配层报告的问题。

字段映射、忽略规则与哨兵处理见 [FMSUPERSCOUT.md](FMSUPERSCOUT.md)。

## 7. P0-2 协议扩展（状态、租借、待生效转会）

`player` 行新增可选块，全部缺省即视为未知：

```json
{
  "save_local_uid": "9001",
  "name": "Adam Wharton",
  "height_cm": 182,
  "foot": "right",
  "world_reputation": 5200,
  "availability": {
    "listed": true, "loan_listed": false, "not_for_sale": false, "set_for_release": false,
    "injury_proneness": 12, "injured": null,
    "injury_start_date": null, "expected_return_date": null, "injury_note": null
  },
  "ownership": {
    "parent_club_uid": "fs-northbridge-united", "loan_club_uid": "fs-kingsport-city",
    "team_type": "senior", "loan_start_date": null, "loan_end_date": null,
    "has_option": null, "has_obligation": null
  },
  "agreed_transfer": {"to_club_uid": "fs-kingsport-city", "transfer_date": "2027-07-01"}
}
```

约束：

- 挂牌四标志为三态布尔；`injured=false` 时不得带伤病日期（协议会拒绝）。
- `injury_proneness` 是 0-20 的属性，不是当前伤病状态。
- 租借关系必须同时给出 `parent_club_uid` 与 `loan_club_uid`，否则不落租借记录。
- 买断条款缺失即 `null`，不允许用 `false` 冒充「无条款」。
- `agreed_transfer` 只是「已达成未生效」，导入为 `status=agreed` 的交易，不计支出。

交易枚举同步扩展：

- `status`: `completed | pending | future | agreed | bid_rejected | cancelled | failed | unknown`
- `transfer_type` 增加 `loan_buyout`（租借买断，计入成交统计）

## 8. 存档身份协议（save-identity/v1，V3.2.7.2）

扫描报文之外，Agent 还需上报“这份数据属于哪个存档”的身份证据与会话心跳。完整定义见
`docs/SCOUTMIND-V3.2.7.2-IDENTITY-PROTOCOL.md`，摘要：

- 指纹：`si:v1:file:<sha256>` 或 `si:v1:unresolved:<build>`；
- 证据类型：`game_internal_save_id`、`world_id`、`save_file_hash`、`save_file_metadata`、
  `save_file_header`、`career_metadata`、`game_session_metadata`、`user_confirmed`、`legacy_unverified`；
- 身份状态：`unknown / discovered / candidate / verified / conflict / invalidated`；
- 会话键：`PID:进程启动时间:Build`；会话状态：`created / verified / switching / invalidated / closed`；
- 写入采集/导入时必须携带 `save_identity_id` 与 `save_session_id`，后端校验归属、指纹、build 与会话状态；
- 未解析或 ambiguous 的身份不得作为 `verified`，也不会被静默升级。
