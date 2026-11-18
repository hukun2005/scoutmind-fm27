/** §9 概览与诊断 endpoints. */

import type { CompatibilityResponse, OverviewResponse } from '../types/analytics'
import { apiGet } from './client'

/**
 * `GET /analytics/overview` — dashboard counters, coverage, trend and last import.
 * @param saveId Save identifier; the backend falls back to its active save when omitted.
 * @returns Overview payload.
 */
export function getOverview(saveId?: number): Promise<OverviewResponse> {
  return apiGet<OverviewResponse>('/analytics/overview', { save_id: saveId })
}

/**
 * `GET /compatibility` — known FM27 builds and reader versions.
 * @returns Compatibility list.
 */
export function getCompatibility(): Promise<CompatibilityResponse> {
  return apiGet<CompatibilityResponse>('/compatibility')
}
