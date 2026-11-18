/** Performance Analytics endpoints (`/performance/*`). */

import type {
  PerformanceBoard,
  PerformanceMetricSpec,
  PerformanceProfile,
} from '../types/performance'
import { apiGet } from './client'

/**
 * `GET /performance/metrics` — the metrics tracked per position group.
 * @returns Metric specifications and the missing-data rule.
 */
export function getPerformanceMetrics(): Promise<PerformanceMetricSpec> {
  return apiGet<PerformanceMetricSpec>('/performance/metrics')
}

/**
 * `GET /performance/board` — players with statistics, ranked by output percentile.
 * @param saveId Optional save override.
 * @param slot Optional slot filter.
 * @param minMinutes Minimum minutes to be ranked.
 * @param limit Maximum rows.
 * @returns Performance board rows.
 */
export function getPerformanceBoard(
  saveId?: number,
  slot?: string,
  minMinutes = 300,
  limit = 50,
): Promise<PerformanceBoard> {
  return apiGet<PerformanceBoard>('/performance/board', {
    save_id: saveId,
    slot,
    min_minutes: minMinutes,
    limit,
  })
}

/**
 * `GET /performance/player/{id}` — output, trend and ability comparison for one player.
 * @param instanceId Player instance id.
 * @returns The performance profile.
 */
export function getPerformanceProfile(instanceId: number): Promise<PerformanceProfile> {
  return apiGet<PerformanceProfile>(`/performance/player/${instanceId}`)
}
