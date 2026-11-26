/** V3.2.9 Player Identity Center endpoints（/identity/center 与 /identity/scans）。 */

import type {
  CrossSaveResponse,
  IdentityCenterSummary,
  ReviewDecision,
  ReviewQueueItem,
  ReviewQueueResponse,
  ScanRun,
} from '../types/identityCenter'
import { apiGet, apiPost } from './client'

export function getIdentityCenterSummary(saveId?: number): Promise<IdentityCenterSummary> {
  return apiGet<IdentityCenterSummary>('/identity/center/summary', { save_id: saveId })
}

export function listReviewQueue(params: {
  status?: string
  item_type?: string
  page?: number
  page_size?: number
  save_id?: number
}): Promise<ReviewQueueResponse> {
  return apiGet<ReviewQueueResponse>('/identity/center/queue', params)
}

export function getReviewItem(itemId: number): Promise<ReviewQueueItem> {
  return apiGet<ReviewQueueItem>(`/identity/center/queue/${itemId}`)
}

export function resolveReviewItem(
  itemId: number,
  decision: ReviewDecision,
  note?: string,
): Promise<{ id: number; status: string; resolved_at: string | null }> {
  return apiPost(`/identity/center/queue/${itemId}/resolve`, {
    decision,
    note: note ?? null,
    payload: {},
  })
}

export function listScans(): Promise<{ items: ScanRun[] }> {
  return apiGet<{ items: ScanRun[] }>('/identity/scans')
}

export function startScan(body: {
  scan_id: string
  batch_size?: number
  max_batches?: number | null
}): Promise<ScanRun> {
  return apiPost<ScanRun>('/identity/scans', body)
}

export function resumeScan(
  scanId: string,
  body: { save_identity_fingerprint?: string | null; game_build?: string | null; layout_version?: string | null },
): Promise<ScanRun> {
  return apiPost<ScanRun>(`/identity/scans/${scanId}/resume`, body)
}

export function cancelScan(scanId: string): Promise<ScanRun> {
  return apiPost<ScanRun>(`/identity/scans/${scanId}/cancel`)
}

export function pauseScan(scanId: string): Promise<ScanRun> {
  return apiPost<ScanRun>(`/identity/scans/${scanId}/pause`)
}

export function listCrossSaveCandidates(params: {
  other_save_id?: number
  generate?: boolean
  status?: string
}): Promise<CrossSaveResponse> {
  return apiGet<CrossSaveResponse>('/identity/center/cross-save', params)
}

export function reviewCrossSaveCandidate(
  candidateId: number,
  decision: 'same' | 'different' | 'defer',
  note?: string,
): Promise<{ id: number; status: string; resolved_at: string | null }> {
  return apiPost(`/identity/center/cross-save/${candidateId}/review`, { decision, note: note ?? null })
}
