/** Data Governance Center types (V3.2.1 SM-066C/D). */

export interface GovernanceOverview {
  save_id: number
  total_snapshots: number
  unique_game_dates: number
  players: number
  canonical_groups: number
  resolved_auto: number
  resolved_manual: number
  needs_review: number
  excluded: number
  review_required: number
  quality_anomalies: number
  quality_error_groups: number
  quality_warning_groups: number
  conflict_types: { type: string; count: number }[]
}

export interface ReviewQueueItem {
  id: number
  player_instance_id: number
  player_name: string
  player_uid: string
  game_date: string
  status: string
  conflict: boolean
  snapshot_count: number
  distinct_content_count: number
  conflict_types: string[]
  canonical_snapshot_id: number | null
  reason: string
}

export interface ReviewQueueResponse {
  items: ReviewQueueItem[]
  total: number
  limit: number
  offset: number
}

export interface GovernanceAttribute {
  key: string
  name: string
  name_zh: string
  category: string
  value: number
}

export interface GovernanceSnapshot {
  id: number
  observed_at: string | null
  game_date: string
  ca: number | null
  pa: number | null
  wage: number | null
  market_value: number | null
  contract_end: string | null
  club_id: number | null
  club_name?: string | null
  position: string | null
  height_cm: number | null
  foot: string | null
  source: string | null
  reader_version: string | null
  game_build: string | null
  attributes: GovernanceAttribute[]
}

export interface CanonicalTimelinePoint {
  id: number
  game_date: string
  status: string
  canonical_snapshot_id: number | null
  conflict: boolean
  snapshot_count: number
  reason: string
}

export interface CanonicalDetail {
  canonical: ReviewQueueItem & {
    fm_save_id: number
    conflict_types: string[]
  }
  snapshots: GovernanceSnapshot[]
  timeline: CanonicalTimelinePoint[]
}

export interface ReviewAction {
  id: number
  action: string
  selected_snapshot_id: number | null
  previous_status: string | null
  new_status: string
  reason: string
  evidence: Record<string, unknown>
  reviewer_user_id: number
  created_at: string | null
}

export interface ReviewHistory {
  canonical_id: number
  status: string
  items: ReviewAction[]
}

export type DecisionAction = 'select_snapshot' | 'exclude_game_date' | 'keep_pending'

export interface DecisionPayload {
  action: DecisionAction
  selected_snapshot_id?: number | null
  reason: string
  evidence?: Record<string, unknown>
}
