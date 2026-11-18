/** Types for Player Development (`/development/*`). */

/** Player header of a growth profile. */
export interface DevelopmentPlayer {
  instance_id: number
  name: string
  position: string | null
  slot: string | null
  slot_name: string | null
  position_group: string | null
  positions?: Record<string, unknown>
  /** Latest observed age; `null` when the save has no age for this player. */
  age?: number | null
  ca?: number | null
  pa?: number | null
  market_value?: number | null
  club_id?: number | null
}

/** One observed growth point. */
export interface GrowthPoint {
  snapshot_id: number
  date: string
  observed_at: string
  age: number | null
  ca: number | null
  pa: number | null
  market_value: number | null
  wage: number | null
  minutes_played: number | null
  appearances: number | null
  goal_contributions: number | null
  ca_delta: number | null
  value_delta: number | null
  minutes_delta: number | null
  change_label: string
}

/** One growth interval. */
export interface GrowthInterval {
  from: string
  to: string
  months: number | null
  ca_delta: number | null
  per_month: number | null
}

/** Growth rate block. */
export interface GrowthRates {
  intervals: GrowthInterval[]
  overall_per_month: number | null
  recent_per_month: number | null
  classification: string
  formula?: string
  sample_size?: number
}

/** One development recommendation. */
export interface DevelopmentAdvice {
  action: string
  reason: string
  confidence: string
  evidence: string[]
}

/** Potential outlook band: an interval plus a grade, never a single predicted CA. */
export interface DevelopmentOutlook {
  band: string
  label: string
  probability: number | null
  projected_low: number | null
  projected_high: number | null
  projected_center?: number | null
  horizon_age?: number
  rationale: string
  inputs?: Record<string, unknown>
  missing?: string[]
}

/** `GET /development/player/{id}` payload. */
export interface GrowthProfile {
  player: DevelopmentPlayer
  points: GrowthPoint[]
  rates: GrowthRates
  advice: DevelopmentAdvice[]
  outlook: DevelopmentOutlook
  data_gaps: string[]
  algorithm_version: string
}

/** One row of the development board. */
export interface DevelopmentBoardRow {
  player: DevelopmentPlayer
  overall_per_month: number | null
  recent_per_month: number | null
  classification: string
  ca_delta: number | null
  outlook: DevelopmentOutlook
  advice_top: DevelopmentAdvice
}

/** `GET /development/board` payload. */
export interface DevelopmentBoard {
  items: DevelopmentBoardRow[]
  total: number
  min_age: number | null
  algorithm_version: string
  note: string
}
