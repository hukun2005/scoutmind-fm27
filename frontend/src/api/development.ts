/** Player Development endpoints (`/development/*`). */

import type { DevelopmentBoard, GrowthProfile } from '../types/development'
import { apiGet } from './client'

/**
 * `GET /development/board` — tracked players ordered by growth rate.
 * @param saveId Optional save override.
 * @param limit Maximum rows.
 * @param minAge Age ceiling; pass `null` for no ceiling.
 * @returns Development board rows.
 */
export function getDevelopmentBoard(saveId?: number, limit = 30, minAge?: number): Promise<DevelopmentBoard> {
  return apiGet<DevelopmentBoard>('/development/board', { save_id: saveId, limit, min_age: minAge })
}

/**
 * `GET /development/player/{id}` — growth timeline, rate, advice and outlook.
 * @param instanceId Player instance id.
 * @returns The growth profile.
 */
export function getGrowthProfile(instanceId: number): Promise<GrowthProfile> {
  return apiGet<GrowthProfile>(`/development/player/${instanceId}`)
}
