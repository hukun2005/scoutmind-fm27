/** 球员状态、候选转会与真实数据审查的类型（P0-1 / P0-4）。 */

/** One availability observation. */
export interface StatusSnapshot {
  observed_at: string | null
  game_date: string | null
  flags: Record<string, boolean | null>
  injury: {
    proneness: number | null
    injured: boolean | null
    start_date: string | null
    expected_return: string | null
    note: string | null
  }
  registration: { parent_club: string | null; loan_club: string | null; team_type: string | null }
  agreed_transfer: { to_club: string | null; date: string | null } | null
}

/** A recorded change between two observations. */
export interface StatusChange {
  field: string
  label: string
  from: unknown
  to: unknown
  observed_at: string | null
  previous_observed_at: string | null
}

/** Loan relationship; option flags stay `null` when the source never stated them. */
export interface PlayerLoan {
  id: number
  parent_club: string | null
  loan_club: string | null
  start_date: string | null
  end_date: string | null
  has_option: boolean | null
  has_obligation: boolean | null
  status: string
  observed_at: string | null
  source: string
}

/** `GET /players/{instance_id}/status` payload. */
export interface PlayerStatus {
  instance_id: number
  player_name: string | null
  current: StatusSnapshot | null
  history: Array<{
    observed_at: string | null
    flags: Record<string, boolean | null>
    injured: boolean | null
    injury_proneness: number | null
    parent_club: string | null
    loan_club: string | null
    source: string
  }>
  changes: StatusChange[]
  first_seen: Record<string, { value: boolean; first_seen_at: string | null; last_confirmed_at: string | null }>
  loans: PlayerLoan[]
  candidates: CandidateRow[]
  data_gaps: string[]
  algorithm_version: string
}

/** A snapshot-diff candidate event. */
export interface CandidateRow {
  id: number
  player: { instance_id: number; name: string | null }
  from_club: string | null
  to_club: string | null
  kind: string
  status: string
  detected_at: string | null
  previous_observed_at: string | null
  confirmed_transfer_id: number | null
  evidence?: Record<string, unknown>
}

/** `GET /transfers/candidates` payload. */
export interface CandidateListResponse {
  items: CandidateRow[]
  total: number
  note: string
}

/** One row of a validation section. */
export interface ValidationRow {
  label: string
  value: string | number
  detail?: string | null
}

/** One section of the real-data review report. */
export interface ValidationSection {
  id: string
  title: string
  rows: ValidationRow[]
}

/** `POST /imports/fmscout/validate` payload. */
export interface ValidationResponse {
  sections: ValidationSection[]
  verdict: {
    status: 'pass' | 'review' | 'blocked'
    blockers: string[]
    review: string[]
    ready_to_import: boolean
  }
  report: Record<string, unknown>
  counts: { clubs: number; players: number }
}
