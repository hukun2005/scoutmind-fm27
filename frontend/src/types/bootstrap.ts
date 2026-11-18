/** Types for §2 健康与元信息 (`/health`, `/meta/bootstrap`). */

import type { DataSource } from './common'

/** `GET /health` payload. */
export interface HealthResponse {
  status: string
  version: string
  database: string
  demo_mode: boolean
  timestamp: string
}

/** A game save as returned by `GET /saves` (§3). */
export interface Save {
  id: number
  name: string
  game_version: string | null
  game_build: string | null
  created_at: string | null
  is_active: boolean | null
  player_count: number | null
  snapshot_count: number | null
  transfer_count: number | null
  last_import_at: string | null
}

/** Feature switches returned by `GET /meta/bootstrap`. */
export interface Capabilities {
  live_reader: boolean
  save_parser: boolean
  agent_llm: boolean
  watchlist: boolean
  transfer_intelligence: boolean
}

/** Records-per-source counts used by the diagnostics screen. */
export interface DataSourceCount {
  source: DataSource
  records: number
}

/** `GET /meta/bootstrap` payload. */
export interface BootstrapMeta {
  product: string
  version: string
  demo_mode: boolean
  auth_required: boolean
  active_save_id: number | null
  saves: Save[]
  data_sources: DataSourceCount[]
  capabilities: Capabilities
  warnings: string[]
}

/** `GET /saves/{id}/summary` payload (§3). */
export interface SaveSummary {
  save: Save
  coverage: {
    players: number | null
    snapshots: number | null
    transfers: number | null
    clubs: number | null
  }
  last_import: import('./imports').ImportJob | null
}
