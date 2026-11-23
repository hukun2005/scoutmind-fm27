/** Unresolved (free-agent) candidate types for `GET /unresolved-players`（SM-119）。 */

/** Lifecycle of one candidate; none of these means "identity confirmed by default". */
export type UnresolvedStatus = 'pending' | 'review_required' | 'resolved' | 'dismissed'

/** Raw upstream identity evidence. It is never a legal `save_local_uid`. */
export interface UnresolvedUidInfo {
  status: 'sentinel' | 'missing' | 'invalid'
  reason: string | null
  raw_uid: string | null
  note: string
}

/** Newest observation of the candidate. */
export interface UnresolvedLatestObservation {
  observation_id: number
  scan_id: string
  row_index: number
  observed_at: string | null
  game_date: string | null
  ca: number | null
  pa: number | null
  club_name: string | null
  contract_end: string | null
}

/** One unresolved candidate. */
export interface UnresolvedCandidate {
  id: number
  save_id: number
  status: UnresolvedStatus
  display_name: string
  normalized_name: string
  birth_date: string | null
  nationality: string | null
  position: string | null
  observation_count: number
  first_seen_at: string | null
  last_seen_at: string | null
  uid: UnresolvedUidInfo
  latest_observation: UnresolvedLatestObservation | null
  resolution: {
    method: string | null
    player_id: number | null
    player_instance_id: number | null
    resolved_at: string | null
  } | null
  dismissal: { reason: string | null; dismissed_at: string | null } | null
  suggestions_are_advisory: boolean
}

/** A possible match to an existing save-local identity. Advisory only. */
export interface UnresolvedPlayerSuggestion {
  kind: 'player_instance'
  player_id: number
  player_instance_id: number
  name: string
  birth_date: string | null
  save_local_uid: string | null
  confidence: number
  reasons: string[]
}

/** Another unresolved candidate with the same folded name. */
export interface UnresolvedSiblingCandidate {
  candidate_id: number
  display_name: string
  birth_date: string | null
  status: UnresolvedStatus
  uid_status: string
}

/** Matching suggestions returned with a candidate. */
export interface UnresolvedSuggestions {
  player_matches: UnresolvedPlayerSuggestion[]
  sibling_candidates: UnresolvedSiblingCandidate[]
  note: string
}

/** One append-only audit record. */
export interface UnresolvedAction {
  id: number
  action: string
  decision: string
  previous_status: string | null
  new_status: string
  target_player_id: number | null
  note: string | null
  created_at: string | null
  evidence: Record<string, unknown>
}

/** Candidate detail including evidence, suggestions and audit history. */
export interface UnresolvedDetail extends UnresolvedCandidate {
  evidence_summary: Record<string, unknown>
  suggestions: UnresolvedSuggestions
  history: UnresolvedAction[]
  retention: string
}

/** One stored observation. */
export interface UnresolvedObservation {
  id: number
  scan_id: string
  row_index: number
  observed_at: string | null
  game_date: string | null
  raw_uid: string | null
  uid_status: string
  name: string
  birth_date: string | null
  nationality: string | null
  position: string | null
  ca: number | null
  pa: number | null
  club_name: string | null
  contract_end: string | null
  import_job_id: number | null
  payload_hash: string
}

/** Paginated list response. */
export interface UnresolvedListResponse {
  items: UnresolvedCandidate[]
  total: number
  page: number
  page_size: number
  counts: { pending: number; review_required: number; resolved: number; dismissed: number }
  note: string
}

/** Paginated observation response. */
export interface UnresolvedObservationsResponse {
  candidate_id: number
  items: UnresolvedObservation[]
  total: number
  page: number
  page_size: number
  import_job_ids: number[]
}

/** Query filters accepted by the list endpoint. */
export interface UnresolvedListQuery {
  status?: 'all' | UnresolvedStatus
  name?: string
  position?: string
  min_ca?: number
  min_pa?: number
  page?: number
  page_size?: number
}

/** Body of `POST /unresolved-players/{id}/resolve`. */
export interface UnresolvedResolveRequest {
  player_instance_id?: number
  player_id?: number
  confirm: boolean
  note?: string
}

/** Result of a manual identity link. */
export interface UnresolvedResolveResponse {
  id: number
  status: UnresolvedStatus
  resolution_method: string | null
  player_id: number | null
  player_instance_id: number | null
  resolved_at: string | null
  evidence: Record<string, unknown>
  audit_action_id: number
  note: string
}

/** Result of dismissing a candidate. */
export interface UnresolvedDismissResponse {
  id: number
  status: UnresolvedStatus
  dismiss_reason: string | null
  dismissed_at: string | null
  observations_kept: number
  audit_action_id: number
}
