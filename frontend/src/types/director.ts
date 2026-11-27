/** AI 足球总监（`/agent/director/*`）的类型。 */

export interface DirectorClub {
  id: number
  name: string
  league: string | null
  nation: string | null
}

export interface DirectorContext {
  save: { id: number; name: string | null }
  club: DirectorClub | null
  data_updated_at: string | null
  data_completeness: number
  coverage: Record<string, number>
  counts: {
    players: number
    snapshots: number
    transfers: number
    statistics: number
    watchlist: number
  }
  data_gaps: string[]
  generated_at: string
}

export interface DirectorTable {
  columns: string[]
  rows: string[][]
}

export interface DirectorSection {
  key: string
  title: string
  reliability: 'fact' | 'computed' | 'inference' | 'unavailable' | string
  bullets?: string[]
  table?: DirectorTable
}

export interface DirectorAction {
  label: string
  target: string
}

export interface DirectorRecommendation {
  instance_id: number | null
  name: string | null
  age: number | null
  position: string | null
  club: string | null
  ca: number | null
  pa: number | null
  market_value: number | null
  score: number | null
  reason: string
  actions: DirectorAction[]
}

export interface DirectorCard {
  instance_id: number
  name: string
  age: number | null
  position: string | null
  club: string | null
  ca: number | null
  pa: number | null
  market_value: number | null
  source_tool: string
}

export interface DirectorAnswer {
  intent: string
  intent_label: string
  conclusion: string
  sections: DirectorSection[]
  recommendations: DirectorRecommendation[]
  player_cards: DirectorCard[]
  data_gaps: string[]
  citations: Array<{ tool?: string; summary?: string }>
  disclaimers?: string[]
  mode: string
  director?: boolean
  generated_at: string
}
