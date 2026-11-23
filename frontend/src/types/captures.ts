/** Automatic capture types (V3.2.2 SM-067). */

export interface CaptureRun {
  id: number
  save_id: number
  game_date: string | null
  reader_version: string | null
  game_build: string | null
  scan_scope: string
  status: string
  attempt_count: number
  max_attempts: number
  next_retry_at: string | null
  scan_id: string | null
  import_job_id: number | null
  supplemental: boolean
  revision: number
  observed_at: string | null
  started_at: string | null
  finished_at: string | null
  error_code: string | null
  error_message: string | null
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface CaptureSummary {
  save_id: number
  counts: Record<string, number>
  total: number
  latest: CaptureRun | null
}

export interface CaptureList {
  items: CaptureRun[]
  total: number
  limit: number
  offset: number
}
