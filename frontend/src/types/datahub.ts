/**
 * V3.3.0 数据中心契约（与后端 `routes_datahub.py` 对应）。
 *
 * 只描述界面真正消费的字段；缺失字段不猜测，展示时显示「—」。
 */

/** 游戏进程检测结果（后端只读进程元数据，不读取游戏内存）。 */
export interface DataHubGame {
  running: boolean
  detected: boolean
  pid: number | null
  version: string | null
  exe_path: string | null
  message: string | null
  /** `supported` | `unknown` | `unsupported` */
  compatibility: string
  compatibility_message: string
}

/** 存档身份与可写状态。 */
export interface DataHubSave {
  id: number
  name: string
  recognized: boolean
  identity_status: string
  can_sync: boolean
  message: string
}

/** 当前存档的记录数。 */
export interface DataHubRecords {
  players: number
  clubs: number
  transfers: number
  snapshots: number
}

/** 最近一次导入摘要。 */
export interface DataHubLastSync {
  job_id: number
  status: string
  source: string
  received_at: string | null
  finished_at: string | null
  players: number | null
  transfers: number | null
}

/** `GET /data-hub/status` 响应。 */
export interface DataHubStatus {
  game: DataHubGame
  save: DataHubSave
  records: DataHubRecords
  last_sync: DataHubLastSync | null
  health: { status: string; issues: string[] }
  needs_confirmation: {
    unresolved_players: number
    identity_conflicts: number
    quarantined_rows: number
    total: number
  }
  repairs: Record<string, number>
}

/** 自动识别结果。 */
export interface DataHubDetection {
  source: string
  format: string
  schema_version: string | null
  encoding: string | null
  compatible: boolean
  code: string | null
  message: string | null
  warnings: string[]
}

/** 一条自动修复记录。 */
export interface DataHubRepair {
  entity: string
  row: number
  rule: string
  field: string | null
  before: unknown
  after: unknown
  level: number
  reason: string | null
}

/** 一条被隔离的行。 */
export interface DataHubQuarantineRow {
  row: number
  entity: string
  code: string
  message: string
}

/** 导入阶段进度（`pass` | `warn` | `blocked` | `skipped`）。 */
export interface DataHubStage {
  id: string
  label: string
  status: string
}

/** 导入计数（后端 `counts`）。 */
export interface DataHubCounts {
  created: number
  updated: number
  duplicates: number
  repaired: number
  quarantined: number
  rejected: number
}

/** 导入后自检结果。 */
export interface DataHubVerification {
  status?: string
  checks?: Array<{ id: string; status: string; detail: string }>
}

/** `POST /data-hub/import` 响应。 */
export interface DataHubImportResponse {
  /** `PASS` | `PARTIAL` | `BLOCKED` | 其他后端状态。 */
  status: string
  stages: DataHubStage[]
  detection: DataHubDetection
  counts: DataHubCounts
  import: {
    dry_run: boolean
    job_id?: number
    save_id?: number
    scan_id?: string | null
    duplicate?: boolean
    status?: string
  }
  verification: DataHubVerification
  warnings: string[]
  repairs: DataHubRepair[]
  repairs_total: number
  quarantine: DataHubQuarantineRow[]
  quarantine_total: number
  adapted_by?: Record<string, unknown>
}

/** 兼容命名：导入报告与导入响应是同一结构。 */
export type DataHubImportReport = DataHubImportResponse

/** `GET /data-hub/capabilities` 响应。 */
export interface DataHubCapabilities {
  schema_major: string
  sources: Array<{ id: string; label: string }>
  formats: Array<{ id: string; label: string }>
  auto_detection: boolean
  repair_levels: number[]
}
