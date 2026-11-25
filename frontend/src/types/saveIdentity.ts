/** Types for `/save-identities`、`/save-sessions` 与 `/save-identity-audit`（save-identity/v1）。 */

/** 身份状态；只有 `verified` 允许采集写入。 */
export type SaveIdentityStatus =
  | 'unknown'
  | 'discovered'
  | 'candidate'
  | 'verified'
  | 'conflict'
  | 'invalidated'

/** 会话状态；只有 `verified` 且心跳未超时才算可用。 */
export type SaveSessionStatus = 'created' | 'verified' | 'switching' | 'invalidated' | 'closed'

/** 证据等级由服务端按证据类型推导。 */
export type SaveEvidenceLevel = 'primary' | 'secondary' | 'auxiliary' | 'none'

/** 一条规范化证据（只含哈希与公开诊断字段）。 */
export interface SaveIdentityEvidence {
  type: string
  source: string
  hash: string | null
  version: string | null
  confidence: string
  observed_at: string | null
}

/** 一个游戏进程会话。 */
export interface SaveSession {
  session_id: number
  save_id: number | null
  identity_id: number | null
  session_key: string
  process_id: number | null
  process_start_time: string | null
  game_build: string | null
  plugin_version: string | null
  agent_id: string | null
  status: SaveSessionStatus | string
  session_epoch: number
  started_at: string | null
  last_heartbeat_at: string | null
  last_verified_at: string | null
  ended_at: string | null
  invalidated_reason: string | null
}

/** `GET /save-identities` 的一行。 */
export interface SaveIdentitySummary {
  identity_id: number
  save_id: number | null
  fingerprint: string
  fingerprint_version: string
  identity_status: SaveIdentityStatus
  confidence: string
  kind: string
  evidence_level: SaveEvidenceLevel
  game_build: string | null
  plugin_version: string | null
  first_seen_at: string | null
  last_seen_at: string | null
  verified_at: string | null
  verified_by: string | null
  protocol_version: string
}

/** `GET /save-identities` 响应。 */
export interface SaveIdentityListResponse {
  items: SaveIdentitySummary[]
  total: number
  counts: Partial<Record<SaveIdentityStatus, number>>
  limit: number
  offset: number
  protocol_version: string
}

/** 写入代次门（V3.2.7.3）；generation 只增不减，切换后旧会话立即失去写入资格。 */
export interface SaveWriteGate {
  generation: number
  current_session_id: number | null
  current_identity_id: number | null
  last_switch_at: string | null
  last_switch_reason: string | null
}

/** `GET /save-identities/{id}`：摘要 + 证据 + 会话 + 采集闸门。 */
export interface SaveIdentityDetail extends SaveIdentitySummary {
  evidence: SaveIdentityEvidence[]
  sessions: SaveSession[]
  capture_allowed: boolean
  blockers: string[]
  write_gate: SaveWriteGate | null
}

/** `GET /save-identity-audit` 的一条事件。 */
export interface SaveIdentityAuditEvent {
  event_id: number
  save_id: number | null
  identity_id: number | null
  session_id: number | null
  capture_id: number | null
  event_type: string
  old_status: string | null
  new_status: string | null
  old_fingerprint: string | null
  new_fingerprint: string | null
  evidence_summary: Record<string, unknown>
  actor: string | null
  reason: string | null
  occurred_at: string | null
  correlation_id: string | null
}

/** `GET /save-identity-audit` 响应。 */
export interface SaveIdentityAuditResponse {
  items: SaveIdentityAuditEvent[]
  total: number
  limit: number
  offset: number
}
