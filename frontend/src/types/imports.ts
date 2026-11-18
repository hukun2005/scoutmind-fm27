/** Types for §4 导入 (`POST /imports/scan`, `GET /imports`). */

import type { CoverageMap, DataSource } from './common'

/** One job of `GET /imports`. */
export interface ImportJob {
  id: number
  save_id: number
  scan_id: string | null
  source: DataSource | string | null
  status: string
  received_at: string | null
  finished_at: string | null
  player_count: number | null
  transfer_count: number | null
  warnings: string[]
  coverage: CoverageMap | null
  raw_payload_path: string | null
}

/** `GET /imports` payload. */
export interface ImportListResponse {
  items: ImportJob[]
  total: number
}

/** One rejected row of `POST /imports/scan` → `errors`. */
export interface ImportRowError {
  row: number | null
  entity: string | null
  code: string
  message: string
}

/** `POST /imports/scan` payload. */
export interface ScanImportResponse {
  job_id: number
  status: string
  duplicate: boolean
  scan_id: string | null
  save_id: number | null
  players_created: number
  players_updated: number
  instances_matched: number
  snapshots_created: number
  transfers_created: number
  transfers_skipped: number
  rows_rejected: number
  warnings: string[]
  errors: ImportRowError[]
  coverage: CoverageMap | null
}
