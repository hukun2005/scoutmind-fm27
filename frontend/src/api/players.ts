/** §5 球员 endpoints. */

import type {
  PlayerDetail,
  PlayerDevelopmentResponse,
  PlayerFacets,
  PlayerHistoryResponse,
  PlayerListQuery,
  PlayerListResponse,
} from '../types/players'
import type { QueryParams } from './client'
import { apiGet } from './client'

/**
 * `GET /players/facets` — real nationality and league values of the save.
 * @param saveId Active save; omitted when the backend should use its default.
 */
export function getPlayerFacets(saveId?: number): Promise<PlayerFacets> {
  return apiGet<PlayerFacets>('/players/facets', { save_id: saveId })
}

/**
 * `GET /players` — server-side filtered, sorted and paged player list.
 * @param query Filters, sort key and paging window.
 * @returns Rows plus dataset coverage.
 */
export function listPlayers(query: PlayerListQuery): Promise<PlayerListResponse> {
  return apiGet<PlayerListResponse>('/players', query as QueryParams)
}

/**
 * `GET /players/{instance_id}` — profile, attributes and embedded valuation.
 * @param instanceId Player instance identifier.
 * @returns Player detail payload.
 */
export function getPlayer(instanceId: number): Promise<PlayerDetail> {
  return apiGet<PlayerDetail>(`/players/${instanceId}`)
}

/**
 * `GET /players/{instance_id}/history` — observation points for growth charts.
 * @param instanceId Player instance identifier.
 * @param range Optional game-date window.
 * @returns History points and coverage.
 */
export function getPlayerHistory(
  instanceId: number,
  range?: { from?: string; to?: string },
): Promise<PlayerHistoryResponse> {
  return apiGet<PlayerHistoryResponse>(`/players/${instanceId}/history`, range as QueryParams)
}

/**
 * `GET /players/{instance_id}/development` — period deltas and attribution rows.
 * @param instanceId Player instance identifier.
 * @returns Development summary, records, attributions and data gaps.
 */
export function getPlayerDevelopment(instanceId: number): Promise<PlayerDevelopmentResponse> {
  return apiGet<PlayerDevelopmentResponse>(`/players/${instanceId}/development`)
}
