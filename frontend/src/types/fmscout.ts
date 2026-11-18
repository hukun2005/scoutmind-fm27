/** FMSuperScout 适配层类型（`/imports/fmscout*`）。 */

/** One field the adapter refused to map, with the reason shown to the operator. */
export interface IgnoredField {
  field: string
  reason: string
}

/** 字段映射报告：解释这次导出能喂给 ScoutMind 什么、不能喂什么。 */
export interface FmscoutReport {
  detected: boolean
  adapter: string
  adapter_version: string
  dump_generated: string | null
  dump_game: string | null
  scan_id: string | null
  players_total: number
  players_skipped: number
  players_converted: number
  clubs_converted: number
  user_club: string | null
  attributes_mapped: number
  attributes_ignored: string[]
  mapped_fields: string[]
  absent_fields: string[]
  ignored_fields: IgnoredField[]
  coverage: Record<string, number>
  warnings: string[]
}

/** 已转换的球员样例（预览用）。 */
export interface FmscoutSamplePlayer {
  save_local_uid: string
  name: string
  age: number | null
  birth_date: string | null
  nationality: string | null
  position: string | null
  club_uid: string | null
  ca: number | null
  pa: number | null
  market_value: number | null
  wage: number | null
  contract_end: string | null
  attributes: Record<string, number>
}

/** `POST /imports/fmscout/preview` payload. */
export interface FmscoutPreviewResponse {
  report: FmscoutReport
  scan: { scan_id: string; observed_at: string; game_date: string | null; user_club_uid: string | null }
  counts: { clubs: number; players: number }
  sample_players: FmscoutSamplePlayer[]
  sample_clubs: { uid: string; name: string; league: string | null; is_user_club: boolean }[]
}

/** `POST /imports/fmscout` payload. */
export interface FmscoutImportResponse {
  report: FmscoutReport
  import: {
    job_id: number
    status: string
    duplicate: boolean
    scan_id: string | null
    save_id: number | null
    players_created: number
    players_updated: number
    snapshots_created: number
    snapshots_skipped: number
    rows_rejected: number
    warnings: string[]
    coverage: Record<string, number> | null
  }
}

/** `GET /imports/fmscout/adapter` payload. */
export interface FmscoutAdapterInfo {
  adapter: string
  version: string
  upstream: { name: string; url: string; license: string; note: string }
  mapped_fields: string[]
  absent_fields: string[]
  ignored_fields: IgnoredField[]
  attribute_map: Record<string, string>
  unmapped_attributes: string[]
}
