/** Types for Performance Analytics (`/performance/*`). */

/** One tracked metric of a player's position group. */
export interface PerformanceMetric {
  key: string
  label: string
  total: number | null
  per90: number | null
  percentile: number | null
  peer_sample: number
  higher_is_better: boolean
  available: boolean
}

/** Trend block; match windows stay unavailable without per-match rows. */
export interface PerformanceTrend {
  available: boolean
  windows: string[]
  unavailable_windows?: Record<string, string>
  season_over_season?: {
    previous_period: string
    current_period: string
    changes: { key: string; label: string; previous: number | null; current: number | null; delta: number | null }[]
  } | null
  reason: string
}

/** Ability-versus-output comparison. */
export interface AbilityVsOutput {
  available: boolean
  ability_percentile: number | null
  output_percentile: number | null
  gap?: number
  verdict?: string
  evidence?: string[]
  reason?: string
}

/** `GET /performance/player/{id}` payload. */
export interface PerformanceProfile {
  player: {
    instance_id: number
    name: string
    position: string | null
    slot: string | null
    slot_name: string | null
    position_group: string | null
    club_id: number | null
    club: string | null
  }
  periods: { period: string; competition: string | null; appearances: number | null; minutes_played: number | null; source: string }[]
  season: {
    period: string
    competition: string | null
    appearances: number | null
    minutes_played: number | null
    goals: number | null
    assists: number | null
    xg: number | null
    source: string
  } | null
  trend: PerformanceTrend
  ability_vs_output: AbilityVsOutput
  metrics: PerformanceMetric[]
  data_gaps: string[]
  algorithm_version: string
}

/** One row of the performance board. */
export interface PerformanceBoardRow {
  instance_id: number
  name: string
  age: number | null
  position: string | null
  slot: string | null
  slot_name: string | null
  position_group: string | null
  club: string | null
  ca: number | null
  minutes_played: number | null
  period: string
  metrics: PerformanceMetric[]
  output_percentile: number | null
  ability_percentile: number | null
  verdict: string
}

/** `GET /performance/board` payload. */
export interface PerformanceBoard {
  items: PerformanceBoardRow[]
  total: number
  excluded_below_minutes: number
  min_minutes: number
  slot: string | null
  algorithm_version: string
  note: string
}

/** `GET /performance/metrics` payload. */
export interface PerformanceMetricSpec {
  position_metrics: Record<string, { key: string; label: string; per90: boolean; higher_is_better: boolean }[]>
  note: string
}
