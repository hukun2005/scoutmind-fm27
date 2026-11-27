/** V3.3.2-07 普通用户体验：首次启动、数据中心、诊断与安全修复。 */

import { apiGet, apiPost } from './client'

export type SystemCheckStatus = 'ready' | 'checking' | 'needs_attention' | 'unavailable'

export interface OnboardingCheck {
  key: string
  label: string
  status: SystemCheckStatus
  detail?: string
}

export interface OnboardingTask {
  task_id: string
  task_type: string
  status: string
  message: string
  processed: number
  total: number
}

export interface OnboardingAction {
  key: 'import' | 'scan' | 'data'
  label: string
  enabled: boolean
}

export interface OnboardingResponse {
  save: { id: number; name: string; game_version: string | null; status: string }
  checks: OnboardingCheck[]
  status: 'ready' | 'checking' | 'needs_attention' | 'unavailable'
  data: {
    has_players: boolean
    player_count: number
    club_count: number
    linked_players: number
    unlinked_players: number
    opportunity_count: number
    transfer_count: number
    last_updated_at: string | null
    recoverable_tasks: OnboardingTask[]
    pending_checks: string[]
  }
  summary: {
    player_count: number
    club_count: number
    opportunity_count: number
    last_updated_at: string | null
    save_status: string
  }
  actions: OnboardingAction[]
}

export interface DataHealthResponse {
  save: { id: number; name: string; game_date: string | null }
  players: { count: number; linked: number; unlinked: number; missing_source_field: number }
  clubs: { count: number; linked_players: number }
  transfers: { count: number; completed: number }
  opportunities: { active: number; confirmed: number; inferred: number }
  status: { level: 'ok' | 'warn' | 'error'; label: string; reasons: string[] }
  last_updated_at: string | null
  background: {
    active: number
    latest: { task_id: string; status: string; message: string } | null
  }
  can_repair: boolean
  notes: string[]
}

export interface DiagnosticCheck {
  key: string
  label: string
  status: 'pass' | 'warn' | 'fail'
  detail?: string
  count?: number
}

export interface DiagnosticsResponse {
  checks: DiagnosticCheck[]
  summary: { pass: number; warn: number; fail: number }
  repairable: string[]
}

export interface RepairResponse {
  dry_run: boolean
  executed: Array<{ target: string; scanned: number; linked: number; failed: number }>
  skipped: Array<{ target: string; reason: string }>
  health: DataHealthResponse
  message: string
}

export function getOnboarding(): Promise<OnboardingResponse> {
  return apiGet<OnboardingResponse>('/system/onboarding')
}

export function getDataHealth(): Promise<DataHealthResponse> {
  return apiGet<DataHealthResponse>('/system/data-health')
}

export function runDiagnostics(): Promise<DiagnosticsResponse> {
  return apiPost<DiagnosticsResponse>('/system/diagnostics')
}

export function runRepair(
  targets: string[] = ['club_links'],
  dryRun = false,
): Promise<RepairResponse> {
  return apiPost<RepairResponse>('/system/repair', { targets, dry_run: dryRun })
}
