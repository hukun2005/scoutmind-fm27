/** 俱乐部解析与阵容名单导入的类型（来源、可信度、阵容构成）。 */

/** 一条俱乐部记录及其来源；`confidence` 是渠道固定值，不是猜测。 */
export interface ClubOption {
  id: number
  uid: string
  name: string
  nation: string | null
  league: string | null
  reputation: number | null
  is_user_club: boolean
  source: string | null
  source_label: string | null
  confidence: number | null
  players: number
}

/** `GET /clubs/search` 的响应。 */
export interface ClubSearchResponse {
  items: ClubOption[]
  total: number
}

/** `GET`/`PUT /saves/{id}/user-club` 的响应。 */
export interface UserClubResponse {
  club: { id: number; name: string; league: string | null; nation: string | null; reputation?: number | null } | null
  source: string | null
  source_label: string | null
  confidence: number | null
  /** How the managed club was chosen: `manual` / `payload` / null. */
  assignment_source?: string | null
  note?: string
}

/** 阵容 CSV 的一行结果；`review` / `unmatched` 不会写入归属。 */
export interface SquadCsvRow {
  index: number
  name: string
  club: string | null
  squad_type: string
  loan_status: string
  status: 'assigned' | 'review' | 'unmatched' | 'invalid'
  confidence: number | null
  instance_id: number | null
  matched_by: string[]
  reason: string | null
  candidates: { instance_id: number; confidence: number }[]
}

/** `POST /imports/squad-csv` 的响应。 */
export interface SquadCsvResult {
  counts: Record<string, number>
  total: number
  clubs_created: number
  assignments_written: number
  assignments_skipped: number
  duplicate: boolean
  warnings: string[]
  detected_columns: Record<string, string>
  rows: SquadCsvRow[]
}

/** 阵容构成中的一个球员。 */
export interface CompositionEntry {
  instance_id: number
  name: string | null
  club: string | null
  squad_type: string
  loan_status: string
  confidence: number
  source: string
}

/** 阵容构成：一线队 / 预备队 / 青年队 / 外租 / 租入 / 未知。 */
export interface SquadComposition {
  available: boolean
  source: string | null
  buckets: Record<string, CompositionEntry[]>
  counts: Record<string, number>
  missing?: string[]
  gaps?: string[]
}
