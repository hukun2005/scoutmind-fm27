/** Types for §5 球员 (`/players`, `/players/{id}` and their sub-resources). */

import type { ConfidenceLevel, CoverageMap, DataSource } from './common'

/** One row of `GET /players`, also embedded as `PlayerDetail.summary`. */
export interface PlayerSummary {
  instance_id: number
  player_id: number
  /** 存档内稳定 ID（阵容 CSV 等场景复用）。 */
  save_local_uid?: string
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
  /** 游戏内观察日期；列表接口返回，旧响应可能缺失。 */
  game_date?: string | null
  /** 身高（cm）；仅球员详情返回，列表可能为 null。 */
  height_cm?: number | null
  /** 惯用脚；仅球员详情返回，原始值由后端给出。 */
  foot?: string | null
  observed_at: string | null
  data_completeness: number | null
  source: DataSource
  is_watched: boolean | null
}

/** Sortable columns accepted by `GET /players?sort=` (prefix `-` for descending). */
export type PlayerSortField = 'age' | 'ca' | 'pa' | 'market_value' | 'name' | 'updated_at'

/** 惯用脚（协议枚举）。 */
export type PlayerFoot = 'left' | 'right' | 'both'

/** Filters accepted by `GET /players`; the same object is `filters` in `/scouting/search`. */
export interface PlayerFilters {
  query?: string
  position?: string
  position_group?: string
  min_age?: number
  max_age?: number
  min_ca?: number
  min_pa?: number
  max_pa?: number
  max_value?: number
  max_wage?: number
  club_id?: number
  /** 真实存在的国籍值，来自 `/players/facets`。 */
  nationality?: string
  /** 联赛名，来自 `/players/facets`；后端按俱乐部联赛过滤。 */
  league?: string
  /** 惯用脚；只接受协议枚举 left/right/both。 */
  foot?: PlayerFoot
  min_height?: number
  max_height?: number
  /** 合同在该日期（含）前到期。 */
  contract_end_before?: string
  watchlist_only?: boolean
}

/** One real filter value of `/players/facets` with its population count. */
export interface PlayerFacetValue {
  value: string
  count: number
}

/** `GET /players/facets` payload. */
export interface PlayerFacets {
  total_players: number | null
  nationalities: PlayerFacetValue[]
  leagues: PlayerFacetValue[]
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
