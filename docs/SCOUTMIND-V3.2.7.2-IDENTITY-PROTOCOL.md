# ScoutMind FM27 V3.2.7.2 存档身份协议（Identity Protocol v1）

**协议标识：** `save-identity/v1`
**适用范围：** Live Reader → Desktop Agent → Backend 的存档身份、会话与采集上下文
**基线：** V3.2.7（`187f4ad`）已实现的身份模型与 `save_context` 校验
**原则：** 扩展现有模型，不新建重复身份体系；字段以 `backend/app/models.py` 与 Reader 现有 JSON 为准。

---

## 1. 分层

```text
Live Reader  --(stdout JSON: save-identity/v1)-->  Desktop Agent
Desktop Agent --(HTTP: register / session / heartbeat / captures)--> Backend
Backend       --(证据 + 规则判定)-->  SaveIdentity / SaveSession / AuditEvent
```

- Reader 只**生产**身份证据与解析结论，不决定后端状态。
- Agent 只**转发**证据，不把 `candidate` 说成 `verified`。
- Backend 是唯一有权把身份升级为 `verified` 的一方。

## 2. Reader 输出（已存在，保持不变）

`ScoutMind.LiveReader.exe save-identity --diagnostics --json` 输出（`live-reader/ScoutMind.Reader/Cli.cs#L768-L805`）：

```json
{
  "status": "verified|candidate|discovered|unknown|conflict|invalidated",
  "identity": {
    "fingerprint": "si:v1:file:<sha256>",
    "kind": "save_file|user_confirmed|internal_save_id|world_id|unresolved",
    "version": 1,
    "confidence": "none|low|medium|high|verified"
  },
  "save_id": null,
  "session": {
    "session_key": "<pid>:<process_start_iso>:<build>",
    "status": "verified|candidate|...",
    "game_build": "26620374",
    "plugin_version": "27.1.0+2505117"
  },
  "evidence": [
    {
      "type": "game_internal_save_id|world_id|save_file_metadata|save_file_hash|save_file_header|career_metadata|game_session_metadata|user_confirmed|legacy_unverified",
      "source": "memory|file|scanner|process|user|backend",
      "hash": "<sha256>",
      "version": "<size|build|null>",
      "confidence": "none|low|medium|high|verified",
      "detail": "人类可读说明",
      "observed_at": "<ISO8601|null>"
    }
  ],
  "missing_evidence": ["game_internal_save_id", "world_id"],
  "conflicts": ["..."],
  "explanation": ["..."],
  "ambiguous": false,
  "snapshot_eligible": false,
  "automatic_snapshot_enabled": false,
  "state_path": "...",
  "verify_requested": false,
  "verify_applied": false,
  "diagnostics": ["..."]
}
```

约束：

- `fingerprint` 只由第一/第二优先级证据生成；`si:v1:unresolved:<build>` **不是身份**。
- `session_key` 只用于会话，绝不进入身份指纹。
- `snapshot_eligible` 在 v1 恒为 `false`，`automatic_snapshot_enabled` 恒为 `false`。
- `ambiguous=true` 时不得给出稳定文件指纹。

## 3. Backend 身份对象（IdentityView）

协议字段 ↔ 数据库字段（`backend/app/models.py#L1135-L1164`）：

| 协议字段 | 数据库 / 来源 | 说明 |
|---|---|---|
| `identity_id` | `save_identities.id` | 后端主键 |
| `fingerprint` | `identity_fingerprint` | `si:v1:...` |
| `fingerprint_version` | `identity_version` | 现有行默认 1；与 `si:v1` 前缀一致 |
| `identity_status` | `identity_status` | `unknown/discovered/candidate/verified/conflict/invalidated` |
| `confidence` | `identity_confidence` | `none/low/medium/high/verified` |
| `evidence_level` | **派生** | 有 `game_internal_save_id`/`world_id` → `primary`；仅 `save_file_metadata` → `secondary`；仅 `career_metadata`/`game_session_metadata` → `auxiliary` |
| `ambiguous` | **派生**（证据/冲突） | 后端不单独存列；注册时由 `ambiguous=true` 记录冲突证据，状态不得为 `verified` |
| `game_build` | `game_build` | Steam build |
| `plugin_version` | `plugin_version` | `game_plugin.dll` 版本 |
| `save_file_identity` | `SaveEvidence(SaveFileMetadata).hash` | 卷序列号 + FileId 的规范化哈希 |
| `save_file_version` | `SaveEvidence(SaveFileMetadata).version` | 文件大小 |
| `content_hash` | `SaveEvidence(SaveFileHash).hash` | **只作版本证据，不参与身份** |
| `first_seen_at` | `first_seen_at` | 首次注册时间 |
| `last_seen_at` | `last_seen_at` | 最近一次注册/心跳 |
| `verified_at` | 新增列（Phase 7 迁移） | 只有 `verified` 后写入 |
| `verified_by` | 新增列（Phase 7 迁移） | `reader_user_confirmed` / `operator:<id>` / `strong_evidence` |

数据库唯一约束：`(fm_save_id, identity_version, identity_fingerprint)`。同指纹重复注册必须**更新 `last_seen_at` 并返回同一 `identity_id`**，不得新建行。

## 4. Backend 会话对象（SessionView）

协议字段 ↔ 数据库字段（`backend/app/models.py#L1187-L1211`）：

| 协议字段 | 数据库 / 来源 | 说明 |
|---|---|---|
| `session_id` | `save_sessions.id` | 后端主键 |
| `identity_id` | `save_identity_id` | 必须属于同一存档 |
| `agent_id` | 新增列（Phase 7 迁移） | Agent 实例标识；仅用于会话 |
| `process_id` | `process_id` | 辅助证据 |
| `process_start_time` | `process_start_time` | 辅助证据 |
| `session_key` | `session_key`（唯一） | `PID:启动时间:Build` |
| `game_build` | `game_build` | 必须与身份一致或身份为空 |
| `status` | `session_status` | `created/verified/switching/invalidated/closed` |
| `started_at` | `session_started_at` | |
| `last_heartbeat_at` | 新增列（Phase 7 迁移） | 心跳时间；用于过期判断 |
| `last_verified_at` | `last_verified_at` | 最近一次心跳通过时间 |
| `ended_at` | `session_ended_at` | |
| `invalidated_reason` | `invalidated_reason` | `save_switched` / `game_closed` / `agent_restarted` / `fingerprint_mismatch` / `expired` |

状态规则：

- 只有 `verified` 会话可以写入（与 `save_context.ACTIVE_SESSION_STATUSES` 一致）。
- `switching` → `save_switch_in_progress`（暂停，不报失效）。
- `invalidated` / `closed` → `save_session_invalidated`。
- 心跳超过 `SESSION_HEARTBEAT_TIMEOUT`（默认 120 秒）未更新 → 视为 `invalidated_reason='expired'`，写接口返回 `save_session_invalidated`。
- 同一 `session_key` 重复 `start` 返回同一行（幂等）；不同 `session_key` 的新进程不得复用旧会话。

## 5. 采集上下文（CaptureContext）

```json
{
  "capture_id": 1,
  "identity_id": 3,
  "session_id": 7,
  "fingerprint": "si:v1:file:...",
  "fingerprint_version": 1,
  "game_build": "26620374",
  "agent_id": "agent-<machine>-<pid>",
  "started_at": "2026-11-25T00:00:00Z",
  "protocol_version": "save-identity/v1"
}
```

后端校验（复用并扩展现有规则）：

1. `identity_id` 存在且 `fm_save_id` 等于请求存档。
2. `identity_status` 不是 `conflict`/`invalidated`；不是 `unknown`/`discovered`/`candidate`（否则 `save_identity_unverified`）。
3. `session_id` 存在，属于当前存档，且 `save_identity_id` 等于 `identity_id`。
4. `session_status == verified`，未过期，未失效。
5. `fingerprint` 与会话绑定身份一致；`fingerprint_version` 一致。
6. `game_build` 与身份/会话不矛盾。
7. 请求体中的 `save_id`/`fm_save_id`/`user_id` 一律忽略或拒绝，由服务端从鉴权上下文注入。

错误码（沿用 V3.2.7）：

| code | HTTP | 含义 |
|---|---|---|
| `save_context_mismatch` | 409 | 跨存档、跨身份、指纹/build 不一致 |
| `save_identity_unverified` | 409 | 身份未验证 |
| `save_session_invalidated` | 409 | 会话失效/结束/过期 |
| `save_switch_in_progress` | 409 | 会话切换中 |
| `save_identity_conflict` | 409 | 身份处于冲突，需人工处理 |

## 6. HTTP 接口（Phase 2 实现）

所有接口位于 `/api/v1`，沿用 `X-ScoutMind-Token` 与 `get_active_save` 的存档归属校验。

### 6.1 身份

```http
POST /save-identities/register         # 幂等注册/更新；返回 IdentityView
POST /save-identities/{id}/verify      # 人工确认升级；必须带 actor + basis
GET  /save-identities                  # 当前存档列表 + 状态统计
GET  /save-identities/{id}             # 详情（含证据与审计）
```

`register` 请求：

```json
{
  "save_id": 1,
  "fingerprint": "si:v1:file:...",
  "fingerprint_version": 1,
  "identity_status": "candidate",
  "confidence": "medium",
  "kind": "save_file",
  "game_build": "26620374",
  "plugin_version": "27.1.0+2505117",
  "ambiguous": false,
  "evidence": [
    {"type": "save_file_metadata", "source": "file", "hash": "...", "version": "31434197", "confidence": "medium", "observed_at": "..."}
  ],
  "agent_id": "agent-...",
  "session_key": "66972:2026-11-24T15:57:31.1218361Z:26620374"
}
```

注册规则：

- `identity_status` 是**上报声明**，不是最终状态；后端取 `min(声明, 规则允许)`。
- `unknown`/`discovered` → 最多落 `discovered`；`candidate` 需第二优先级证据；`verified` 只有以下情况才接受：
  - 携带 `user_confirmed` 证据且 `actor`/`basis` 齐全；或
  - 存在第一优先级证据（`game_internal_save_id`/`world_id`）。
- 指纹相同 → 幂等更新；指纹不同且同一 `save_id` 已有 `verified` 身份 → 创建 `candidate` 并写 `save_identity_conflicts`，不得自动替换。
- `game_build` 变化只记录证据，不改变身份指纹。

### 6.2 会话

```http
POST /save-sessions/start
POST /save-sessions/{id}/heartbeat
POST /save-sessions/{id}/end
POST /save-sessions/{id}/invalidate
```

- `start`：`session_key` 幂等；身份必须属于当前存档；未验证身份只能得到 `created`（不可写）。
- `heartbeat`：携带 `identity_id`、`fingerprint`、`game_build`、`agent_version`；指纹或身份不一致 → 409 `save_context_mismatch` 并把会话置 `invalidated`。
- `end`：正常结束 → `closed`。
- `invalidate`：切换/游戏关闭/Agent 重启 → `invalidated` + `invalidated_reason`。

### 6.3 采集

```http
POST /captures?save_identity_id=..&save_session_id=..
PATCH /captures/{id}?save_identity_id=..&save_session_id=..
POST /imports/scan?save_identity_id=..&save_session_id=..
```

- 查询参数形式保持不变（兼容 V3.2.7）。
- `PATCH /captures/{id}` 必须补齐上下文校验（当前缺失）。
- 幂等键：导入仍以 `(fm_save_id, scan_id)`，采集以 `(fm_save_id, game_date, reader_version, scan_scope, revision)`；归属列只追加，不参与去重。

## 7. 审计事件（Phase 6）

```text
save_identity_audit_events
├── event_id
├── fm_save_id
├── identity_id
├── session_id
├── capture_id
├── event_type        # discovered/registered/verified/conflict_detected/switch_detected/session_started/session_invalidated/capture_blocked/worker_rollback/user_confirmed
├── old_status
├── new_status
├── old_fingerprint
├── new_fingerprint
├── evidence_summary  # JSON，禁止原始内存/文件内容
├── actor
├── reason
├── occurred_at
└── correlation_id
```

审计表只追加；禁止 UPDATE/DELETE（与 `UnresolvedPlayerAction` 相同策略）。

## 8. 兼容性

- 未携带身份/会话的旧客户端：保持 V3.2.7 行为（放行），但 Agent 自 V3.2.7.2 起强制携带。
- 未携带 `protocol_version`：按 `save-identity/v1` 处理。
- 未知字段：注册/心跳接口忽略并记录警告，不因新增字段 4xx。
- 缺失字段绝不自动填 `verified`。
- `verified` 只对当前 `game_build` 有效；build 变化不得沿用旧验证结论（需重新验证或降级为 `candidate`）。
- Mock/单元/HTTP/数据库测试结果与真实 FM27 验收分开记录，不得互相冒充。
