/** §6 Watchlist 与提醒 endpoints. */

import type {
  AlertListResponse,
  WatchlistCreateListRequest,
  WatchlistCreateRequest,
  WatchlistGroup,
  WatchlistGroupResponse,
  WatchlistItem,
  WatchlistListResponse,
  WatchlistPatchRequest,
  WatchlistQuery,
  WatchlistRefreshResponse,
} from '../types/watchlist'
import { apiDelete, apiGet, apiPatch, apiPost } from './client'

/**
 * `GET /watchlist` — tracked players of one save with list/status/search filters.
 * @param query Save, list, keyword and status filters.
 * @returns Watchlist items plus the named lists of the save.
 */
export function listWatchlist(query: WatchlistQuery = {}): Promise<WatchlistListResponse> {
  return apiGet<WatchlistListResponse>('/watchlist', {
    save_id: query.saveId,
    list_id: query.listId,
    q: query.q,
    status: query.status,
  })
}

/**
 * `GET /watchlist/lists` — named watchlists and their item counts.
 * @param saveId Save identifier (defaults to the backend's active save).
 */
export function listWatchlistGroups(saveId?: number): Promise<WatchlistGroupResponse> {
  return apiGet<WatchlistGroupResponse>('/watchlist/lists', { save_id: saveId })
}

/**
 * `POST /watchlist/lists` — create one named watchlist.
 * @param body List name.
 */
export function createWatchlistGroup(body: WatchlistCreateListRequest): Promise<Pick<WatchlistGroup, 'id' | 'name'>> {
  return apiPost<Pick<WatchlistGroup, 'id' | 'name'>>('/watchlist/lists', body)
}

/**
 * `POST /watchlist/items` — track a player instance.
 * @param body Instance id plus optional tag and note.
 * @returns The created watchlist item.
 */
export function addWatchlistItem(body: WatchlistCreateRequest): Promise<WatchlistItem> {
  return apiPost<WatchlistItem>('/watchlist/items', body)
}

/**
 * `PATCH /watchlist/items/{id}` — update tag and/or note.
 * @param itemId Watchlist row identifier.
 * @param body Fields to update.
 * @returns The updated watchlist item.
 */
export function patchWatchlistItem(itemId: number, body: WatchlistPatchRequest): Promise<WatchlistItem> {
  return apiPatch<WatchlistItem>(`/watchlist/items/${itemId}`, body)
}

/**
 * `DELETE /watchlist/items/{id}` — stop tracking; answers 204.
 * @param itemId Watchlist row identifier.
 */
export function deleteWatchlistItem(itemId: number): Promise<void> {
  return apiDelete(`/watchlist/items/${itemId}`)
}

/**
 * `POST /watchlist/refresh` — rule-based watchlist and alert generation.
 * @returns Counts of created watch entries and alerts.
 */
export function refreshWatchlist(): Promise<WatchlistRefreshResponse> {
  return apiPost<WatchlistRefreshResponse>('/watchlist/refresh')
}

/**
 * `GET /alerts` — alert feed for one save.
 * @param saveId Save identifier.
 * @param unreadOnly Restrict to alerts without `read_at`.
 * @returns Paged alerts.
 */
export function listAlerts(saveId?: number, unreadOnly?: boolean): Promise<AlertListResponse> {
  return apiGet<AlertListResponse>('/alerts', { save_id: saveId, unread_only: unreadOnly })
}

/**
 * `POST /alerts/{id}/read` — mark one alert as read; answers 204.
 * @param alertId Alert identifier.
 */
export function markAlertRead(alertId: number): Promise<void> {
  return apiPost<void>(`/alerts/${alertId}/read`)
}
