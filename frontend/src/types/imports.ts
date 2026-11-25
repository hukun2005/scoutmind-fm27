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
  /** V3.2.7.4：已尝试次数（含重放与冲突）。 */
  attempt_count?: number
  /** 取消请求时间；null 表示未请求取消。 */
  cancel_requested_at?: string | null
  /** 最终取消时间；取消是状态转换，不删除任务。 */
  cancelled_at?: string | null
  /** 服务端判定当前是否仍可取消。 */
  cancellable?: boolean
  /** 拒绝原因（如 write_session_epoch_stale）。 */
  rejected_reason?: string | null
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
