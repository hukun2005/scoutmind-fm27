/** Types for the Recruitment Engine (`/recruitment/*`). */

/** Candidate row shared by player score, search and shortlist responses. */
export interface RecruitmentPlayer {
  instance_id: number
  player_id?: number
  name: string
  age: number | null
  position: string | null
  slot: string | null
  slot_name: string | null
  position_group: string | null
  ca: number | null
  pa: number | null
  market_value: number | null
  wage: number | null
  contract_end: string | null
  club_id?: number | null
  club: string | null
  league?: string | null
  minutes_played?: number | null
  appearances?: number | null
}

/** One dimension of the six-dimensional player score. */
export interface PlayerDimension {
  key: 'ability' | 'potential' | 'fit' | 'form' | 'value' | 'room' | string
  label: string
  value: number | null
  weight: number
  source: string | null
  evidence: string
  missing: string[]
}

/** Position attribute template attached to a score. */
export interface PositionTemplate {
  position: string | null
  weights: Record<string, number>
  attribute_score: number | null
  coverage: number | null
}

/** Cost estimate attached to a candidate. */
export interface CostEstimate {
  market_value: number | null
  wage: number | null
  contract_end: string | null
  currency?: string
  basis?: string
}

/** `GET /recruitment/player/{instance_id}` payload. */
export interface PlayerScore {
  player: RecruitmentPlayer
  score: number | null
  dimensions: PlayerDimension[]
  position_template: PositionTemplate
  strengths: string[]
  risks: string[]
  cost_estimate: CostEstimate
  algorithm_version: string
  weights: Record<string, number>
}

/** `POST /recruitment/search` request body. */
export interface RecruitmentSearchRequest {
  save_id?: number
  slot?: string
  min_age?: number
  max_age?: number
  max_value?: number
  max_wage?: number
  min_score?: number
  exclude_own_club?: boolean
  limit?: number
}

/** `POST /recruitment/search` payload. */
export interface RecruitmentSearchResponse {
  items: PlayerScore[]
  total: number
  algorithm_version: string
  criteria: Record<string, unknown>
  data_gaps: string[]
}

/** One hidden-value hit. */
export interface HiddenValueHit {
  rule: string
  rule_label: string
  signal: number
  player: RecruitmentPlayer
  evidence: string[]
  cost_estimate: CostEstimate
}

/** `GET /recruitment/hidden-value` payload. */
export interface HiddenValueResponse {
  items: HiddenValueHit[]
  total: number
  rules: {
    evaluated: { key: string; label: string }[]
    unavailable: { key: string; label: string; missing_fields: string[]; description: string }[]
  }
  method: string
  algorithm_version: string
}

/** One ranked shortlist entry. */
export interface ShortlistEntry {
  rank: number
  player: RecruitmentPlayer
  score: number | null
  dimensions: PlayerDimension[]
  strengths: string[]
  risks: string[]
  cost_estimate: CostEstimate
  reason: string
}

/** `POST /recruitment/shortlists` request body. */
export interface ShortlistRequest {
  save_id?: number
  name: string
  slot?: string
  role_key?: string
  budget?: number
  min_age?: number
  max_age?: number
  limit?: number
  persist?: boolean
}

/** Generated or stored shortlist. */
export interface Shortlist {
  name?: string
  slot?: string | null
  role_key?: string | null
  budget?: number | null
  items: ShortlistEntry[]
  criteria?: Record<string, unknown>
  data_gaps?: string[]
  algorithm_version?: string
  generated_at?: string
  shortlist_id?: number
  id?: number
  created_at?: string
}

/** Row of `GET /recruitment/shortlists`. */
export interface ShortlistSummary {
  id: number
  name: string
  slot: string | null
  role_key: string | null
  budget: number | null
  candidates: number
  created_at: string
  criteria: Record<string, unknown>
}

/** `GET /recruitment/model` payload. */
export interface RecruitmentModel {
  position_templates: Record<string, Record<string, number>>
  dimension_weights: Record<string, Record<string, number>>
  note: string
}
