/** Types for §9 概览与诊断 (`/analytics/overview`, `/compatibility`). */

import type { CoverageMap } from './common'
import type { Save } from './bootstrap'
import type { ImportJob } from './imports'

/** One point of `GET /analytics/overview` → `trend`. */
export interface TrendPoint {
  date: string
  ca_avg: number | null
  value_total: number | null
}

/** `GET /analytics/overview` payload. */
export interface OverviewResponse {
  save: Save | null
  players: number
  snapshots: number
  transfers: number
  clubs: number
  completed_transfer_value: number | null
  watchlist: number
  alerts: number
  coverage: CoverageMap
  last_import: ImportJob | null
  trend: TrendPoint[]
}

/** One row of `GET /compatibility` → `items`. */
export interface CompatibilityItem {
  app_id: string | null
  build_id: string | null
  plugin_version: string | null
  status: string
  notes: string | null
}

/** `GET /compatibility` payload. */
export interface CompatibilityResponse {
  items: CompatibilityItem[]
  reader_versions: string[]
}
