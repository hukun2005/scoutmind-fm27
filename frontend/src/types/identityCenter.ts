/** V3.2.9 Player Identity Center 的响应类型。 */

export interface UidSummary {
  player_instances: number
  distinct_save_local_uids: number
  observations: number
  by_status: Record<string, number>
  duplicate_uid_count: number
  duplicate_uids: Array<{ uid: string; player_count: number; first_player_id: number; last_player_id: number }>
  note: string
}

export interface TransferLinkSummary {
  transfers: number
  linked_transfers: number
  unlinked_transfers: number
  linked_by_type: Record<string, number>
  by_status: Record<string, number>
  note: string
}

export interface IdentityCenterSummary {
  save_id: number
  players: number
  player_instances: number
  uid: UidSummary
  identity_links: Record<string, number>
  reviews: Record<string, number>
  scans: Record<string, number>
  transfer_links: TransferLinkSummary
  current_save_identity_fingerprint: string | null
  verified_note: string
  generated_at: string
}

export type ReviewDecision = 'same' | 'different' | 'independent' | 'defer'

export interface ReviewInstance {
  instance_id: number
  player_id: number
  save_local_uid: string
  uid_occurrence: number
  club_id: number | null
  position: string | null
}

export interface ReviewHistoryEntry {
  id: number
  action: string
  decision: string
  previous_status: string | null
  new_status: string
  previous_version: number | null
  new_version: number | null
  request_key: string | null
  note: string | null
  created_at: string
}

export interface ReviewQueueItem {
  id: number
  item_type: string
  severity: string
  status: string
  version: number
  subject_uid: string | null
  primary_player_id: number | null
  candidate_player_ids: number[]
  conflict_reason: string | null
  payload: Record<string, unknown>
  detected_at: string
  resolved_at: string | null
  instances: ReviewInstance[]
  history: ReviewHistoryEntry[]
  retention: string
}

export interface ReviewQueueResponse {
  items: ReviewQueueItem[]
  total: number
  page: number
  page_size: number
  counts: Record<string, number>
  decisions: ReviewDecision[]
  note: string
}

export interface ScanRun {
  id: number
  scan_id: string
  status: string
  cursor: number
  batch_size: number
  total_instances: number
  processed_count: number
  matched_count: number
  conflict_count: number
  failed_count: number
  payload_checksum: string | null
  save_identity_fingerprint: string | null
  game_build: string | null
  layout_version: string | null
  started_at: string | null
  finished_at: string | null
  error_code: string | null
  error_message: string | null
  created_at: string
  updated_at: string
}

export interface CrossSaveCandidate {
  id: number
  other_save_id: number
  subject_player_id: number
  other_player_id: number
  normalized_name: string
  birth_date: string | null
  match_score: number
  status: string
  uid_equal: boolean
  evidence: Record<string, unknown>
  resolved_at: string | null
}

export interface CrossSaveResponse {
  items: CrossSaveCandidate[]
  note: string
}
