/** Squad Intelligence endpoints (`/squad/*`). */

import type { DepthRow, SquadOverview, SquadOverviewQuery, SquadProfile, SquadProfileList } from '../types/squad'
import { apiGet } from './client'

/**
 * `GET /squad/overview` — six-component squad score plus depth, age, wage, contracts and succession.
 * @param query Save, weight profile and optional component overrides.
 * @returns The full squad overview payload.
 */
export function getSquadOverview(query?: SquadOverviewQuery): Promise<SquadOverview> {
  return apiGet<SquadOverview>('/squad/overview', query)
}

/**
 * `GET /squad/depth` — position depth table only.
 * @param saveId Optional save override.
 * @returns Depth rows plus squad size.
 */
export function getSquadDepth(saveId?: number): Promise<{
  items: DepthRow[]
  total: number
  squad_size: number
  missing_position: number
}> {
  return apiGet('/squad/depth', { save_id: saveId })
}

/**
 * `GET /squad/profiles` — weight profiles of the save.
 * @returns Profiles with their normalised weights.
 */
export function listSquadProfiles(): Promise<SquadProfileList> {
  return apiGet<SquadProfileList>('/squad/profiles')
}

/**
 * `GET /squad/weights` — the weights one request would use.
 * @param query Save, profile and overrides.
 * @returns Effective weights and the resolved profile.
 */
export function previewSquadWeights(query?: SquadOverviewQuery): Promise<{
  weights: Record<string, number>
  profile: SquadProfile
  resolved_at: string
}> {
  return apiGet('/squad/weights', query)
}
