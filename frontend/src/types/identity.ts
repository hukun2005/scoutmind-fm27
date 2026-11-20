/** Identity Resolution Center 的数据契约（SM-011）。 */

export type ConflictDecision = 'same' | 'different' | 'defer'

export interface ConflictSideSummary {
  player_id: number | null
  name: string | null
  birth_date: string | null
}

export interface ConflictSuggestion {
  decision: ConflictDecision
  reason: string
  confidence: number | null
  days: number | null
}

export interface ConflictListItem {
  id: number
  uid: string
  reason: string
  status: 'open' | 'resolved' | 'deferred'
  conflict_fields: string[]
  confidence: number | null
  existing: ConflictSideSummary
  incoming: ConflictSideSummary
  suggestion: ConflictSuggestion
  created_at: string
  resolved_at: string | null
}

export interface ConflictCounts {
  open: number
  resolved: number
  deferred: number
}

export interface ConflictListResponse {
  items: ConflictListItem[]
  total: number
  page: number
  page_size: number
  counts: ConflictCounts
  note: string
}

export interface ConflictListQuery {
  status?: 'open' | 'resolved' | 'deferred' | 'all'
  reason?: string
  min_confidence?: number
  sort?: 'confidence_desc' | 'confidence_asc' | 'created_desc' | 'created_asc'
  page?: number
  page_size?: number
  save_id?: number | null
}

export interface ConflictInstance {
  instance_id: number
  save_local_uid: string
  game_unique_id: string | null
  uid_occurrence: number
  club_id: number | null
  position: string | null
  last_seen_at: string
}

export interface ConflictSource {
  import_job_id: number
  scan_id: string
  source: string
  received_at: string
  status: string
}

export interface ConflictMatch {
  strategy: string
  confidence: number
  evidence: Record<string, unknown>
  created_at: string
}

export interface ConflictSideDetail {
  player_id: number
  full_name: string
  birth_date: string | null
  nationality: string | null
  instances: ConflictInstance[]
  instance_count: number
  snapshot_count: number
  transfer_count: number
  sources: ConflictSource[]
  recent_matches: ConflictMatch[]
}

export interface ConflictHistoryEntry {
  id: number
  action: string
  decision: string
  note: string | null
  user_id: number
  created_at: string
  payload: Record<string, unknown>
}

export interface ConflictDetail {
  id: number
  uid: string
  reason: string
  status: string
  resolution: string
  conflict_fields: string[]
  confidence: number | null
  evidence: Record<string, unknown>
  suggestion: ConflictSuggestion
  existing: ConflictSideDetail | null
  incoming: ConflictSideDetail | null
  history: ConflictHistoryEntry[]
  retention: string
}

export interface ResolveConflictResponse {
  id: number
  status: string
  resolution: string
  merged: Record<string, number> | null
  note: string
}
