/** V3.3.2-08 在线持续学习 endpoints。 */

import { apiGet, apiPost } from './client'

export interface OnlineLearningCounts {
  events_observed: number
  events_confirmed: number
  confirmed_transfers: number
  global_clubs: number
  focus_clubs: number
}

export interface OnlineLearningCoverage {
  transfer_history_available: boolean
  native_reader_transfers: boolean
  offers_available: boolean
  note: string
}

export interface OnlineLearningStatus {
  save_id: number
  status: string
  status_label: string
  enabled: boolean
  paused: boolean
  save_name: string | null
  last_monitor_at: string | null
  last_event_at: string | null
  last_learning_at: string | null
  counts: OnlineLearningCounts
  latest_error: string | null
  coverage: OnlineLearningCoverage
  engine_version: string
}

export interface LearningConfidence {
  level: string
  label: string
  sample_size: number
  quality_score?: number
  basis?: string[]
}

export interface LearningClub {
  club_id: number
  club_name: string | null
  league: string | null
  priority: 'global' | 'focus'
  sample_size: number
  confidence: LearningConfidence
  buying: { completed: number; loans: number; total_fee?: number }
  selling: { completed: number; loans: number; total_fee?: number }
  trade_counts?: { buying: number; selling: number; loans: number }
  promotion_reason?: string
  last_transaction_at?: string | null
  updated_at?: string | null
}

export interface LearningActivity {
  activity_id: number
  activity_type: string
  title: string
  created_at: string | null
  club_id: number | null
  event_id: number | null
  detail: Record<string, unknown>
}

export function getOnlineLearningStatus() {
  return apiGet<OnlineLearningStatus>('/transfer-learning/status')
}

export function startOnlineLearning() {
  return apiPost<{ status: string; started: unknown }>('/transfer-learning/start')
}

export function pauseOnlineLearning() {
  return apiPost<{ status: string; enabled: boolean }>('/transfer-learning/pause')
}

export function resumeOnlineLearning() {
  return apiPost<{ status: string; enabled: boolean; started: unknown }>('/transfer-learning/resume')
}

export function listFocusClubs(limit = 10) {
  return apiGet<{ items: LearningClub[]; total: number }>('/transfer-learning/focus-clubs', { limit })
}

export function listLearningActivity(limit = 8) {
  return apiGet<{ items: LearningActivity[]; total: number }>('/transfer-learning/activity', { limit })
}
