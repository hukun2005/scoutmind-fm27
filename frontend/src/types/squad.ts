/** Types for Squad Intelligence (`/squad/*`): six-component squad score, depth and planning. */

/** One component of the squad score. `value === null` means the save cannot support it. */
export interface SquadComponent {
  key: 'coverage' | 'depth' | 'age' | 'fit' | 'wage' | 'potential' | string
  label: string
  value: number | null
  weight: number
  evidence: string[]
  missing: string[]
  available: boolean
}

/** Weight profile of the six components; weights are normalised to sum to 1. */
export interface SquadProfile {
  key: string
  name: string
  description?: string | null
  is_default?: boolean
  weights: Record<string, number>
  overridden?: boolean
}

/** One squad member inside a depth row. */
export interface SquadMember {
  instance_id: number
  name: string
  position: string | null
  slot: string | null
  position_group: string | null
  age: number | null
  ca: number | null
  pa: number | null
  market_value: number | null
  wage: number | null
  contract_end: string | null
  minutes_played: number | null
  appearances: number | null
  fit_score: number | null
  fit_role: string | null
}

/** One position row of the depth table. */
export interface DepthRow {
  slot: string
  slot_name: string
  count: number
  required: number
  importance: number
  coverage: number
  depth_quality: number
  status: string
  suggestion: string
  players: SquadMember[]
}

/** Age distribution bucket. */
export interface AgeBucket {
  bucket: string
  count: number
  share: number
  ideal_share: number
  players: string[]
}

/** Age structure section. */
export interface AgeStructure {
  average_age: number | null
  median_age: number | null
  buckets: AgeBucket[]
  missing: string[]
}

/** Wage structure section. */
export interface WageStructure {
  total: number | null
  median: number | null
  max: number | null
  top3_share: number | null
  earners: number
  missing_players?: number
  top_earners: {
    instance_id: number
    name: string
    wage: number | null
    minutes_played: number | null
    age: number | null
    ca: number | null
  }[]
  missing: string[]
}

/** One player listed in a contract bucket. */
export interface ContractEntry {
  instance_id: number
  name: string
  contract_end: string | null
  age: number | null
  ca: number | null
  pa: number | null
  wage: number | null
  market_value: number | null
}

/** Contract monitoring section. */
export interface ContractMonitoring {
  today?: string
  buckets: Record<string, ContractEntry[]>
  at_risk_count: number
  at_risk_names: string[]
  missing: string[]
}

/** One ranked squad weakness. */
export interface WeaknessRow {
  slot: string
  slot_name: string
  severity: number
  count: number
  required: number
  status: string
  suggestion: string
  evidence: string[]
}

/** Succession plan for one ageing key player. */
export interface SuccessionRow {
  player: SquadMember
  internal_options: SquadMember[]
  ready_now: SquadMember[]
  external_profile: {
    slot: string | null
    slot_name: string | null
    age_max: number
    ca_floor: number
    pa_floor: number | null
    key_attributes: { key: string; value: number }[]
    note: string
  }
  verdict: string
  evidence: string[]
}

/** `GET /squad/overview` payload. */
export interface SquadOverview {
  save_id: number
  club: { id: number; name: string; league: string | null; nation: string | null } | null
  squad_size: number
  score: number | null
  profile: SquadProfile
  components: SquadComponent[]
  depth: DepthRow[]
  age_structure: AgeStructure
  wage_structure: WageStructure
  contracts: ContractMonitoring
  weakness: WeaknessRow[]
  succession: SuccessionRow[]
  algorithm_version: string
  data_gaps?: string[]
  computed_at?: string
}

/** `GET /squad/profiles` payload. */
export interface SquadProfileList {
  items: SquadProfile[]
  total: number
  default_weights: Record<string, number>
}

/** Query for `GET /squad/overview`. */
export interface SquadOverviewQuery {
  save_id?: number
  profile?: string
  club_id?: number
  coverage?: number
  depth?: number
  age?: number
  fit?: number
  wage?: number
  potential?: number
}
