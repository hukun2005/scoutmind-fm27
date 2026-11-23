/** Automatic capture endpoints (`/captures`). */

import type { CaptureList, CaptureSummary } from '../types/captures'
import { apiGet } from './client'

export function getCaptureSummary(): Promise<CaptureSummary> {
  return apiGet<CaptureSummary>('/captures/summary')
}

export function getCaptureRuns(limit = 10): Promise<CaptureList> {
  return apiGet<CaptureList>('/captures', { limit, offset: 0 })
}
