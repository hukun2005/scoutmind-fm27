/** Types for §5 球员 (`/players`, `/players/{id}` and their sub-resources). */

import type { ConfidenceLevel, CoverageMap, DataSource } from './common'

/** One row of `GET /players`, also embedded as `PlayerDetail.summary`. */
export interface PlayerSummary {
  instance_id: number
  player_id: number
  name: string
  age: number | null
  birth_date: string | null
  nationality: string | null
  position: string | null
  position_group: string | null
  club: string | null
  club_id: number | null
  ca: number | null
  pa: number | null
  market_value: number | null
  wage: number | null
  contract_end: string | null
  observed_at: string | null
  data_completeness: number | null
  source: DataSource
  is_watched: boolean | null
}

/** Sortable columns accepted by `GET /players?sort=` (prefix `-` for descending). */
export type PlayerSortField = 'age' | 'ca' | 'pa' | 'market_value' | 'name' | 'updated_at'

/** Filters accepted by `GET /players`; the same object is `filters` in `/scouting/search`. */
export interface PlayerFilters {
  query?: string
  position?: string
  position_group?: string
  min_age?: number
  max_age?: number
  min_ca?: number
  max_pa?: number
  max_value?: number
  max_wage?: number
  club_id?: number
  watchlist_only?: boolean
}

/** Query string of `GET /players`. */
export interface PlayerListQuery extends PlayerFilters {
  save_id?: number
  sort?: string
  limit?: number
  offset?: number
}

/** `GET /players` payload. */
export interface PlayerListResponse {
  items: PlayerSummary[]
  total: number
  coverage: CoverageMap
}

/** One row of `GET /players/{id}` → `attributes` (1–20 scale). */
export interface PlayerAttribute {
  key: string
  name: string
  category: string
  value: number | null
}

/** Valuation block shared by `PlayerDetail.valuation` and `GET /transfers/valuation`. */
export interface ValuationBasis {
  median: number | null
  p25: number | null
  p75: number | null
  /** Mixed numeric factors and human-readable notes (for example `contract_note`). */
  adjustment: Record<string, number | string | null> | null
}

/** Estimated fee range derived from comparable transfers (§8). */
export interface Valuation {
  low: number | null
  mid: number | null
  high: number | null
  sample_size: number | null
  method: string | null
  algorithm_version: string | null
  confidence: ConfidenceLevel | null
  insufficient_sample: boolean
  coverage: CoverageMap | null
  currency?: string | null
  basis?: ValuationBasis | null
  warnings?: string[]
}

/** `GET /players/{id}` payload. */
export interface PlayerDetail {
  summary: PlayerSummary
  attributes: PlayerAttribute[]
  snapshot_count: number
  first_seen: string | null
  last_seen: string | null
  latest_snapshot_id: number | null
  valuation: Valuation | null
  tags: string[]
  notes: string | null
}

/** One observation point of `GET /players/{id}/history`. */
export interface PlayerHistoryPoint {
  snapshot_id: number
  observed_at: string
  game_date: string | null
  age: number | null
  ca: number | null
  pa: number | null
  market_value: number | null
  wage: number | null
  contract_end: string | null
  minutes_played: number | null
  appearances: number | null
  goals: number | null
  assists: number | null
  attributes: Record<string, number | null> | null
}

/** `GET /players/{id}/history` payload. */
export interface PlayerHistoryResponse {
  points: PlayerHistoryPoint[]
  coverage: {
    points: number | null
    attributes: number | null
  }
}

/** Attribution class used by the development panel (事实 / 相关性 / 推测). */
export type AttributionKind = 'fact' | 'correlation' | 'speculation'

/** One row of `GET /players/{id}/development` → `records`. */
export interface DevelopmentPeriod {
  period_start: string
  period_end: string
  ca_delta: number | null
  market_value_delta: number | null
  minutes: number | null
  appearances: number | null
  goals: number | null
  assists: number | null
}

/** One explanation row of `GET /players/{id}/development` → `attributions`. */
export interface DevelopmentAttribution {
  kind: AttributionKind
  factor: string
  evidence: string
}

/** `GET /players/{id}/development` payload. */
export interface PlayerDevelopmentResponse {
  summary: {
    snapshots: number | null
    ca_delta: number | null
    market_value_delta: number | null
    minutes_delta: number | null
    window_start: string | null
    window_end: string | null
  }
  records: DevelopmentPeriod[]
  attributions: DevelopmentAttribution[]
  data_gaps: string[]
}
