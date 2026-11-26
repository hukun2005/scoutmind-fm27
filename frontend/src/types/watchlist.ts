/** Types for §6 Watchlist 与提醒. */

import type { DataSource } from './common'
import type { PlayerSummary } from './players'

/** Workflow status of one watched player; stored as an enum-like string. */
export type WatchStatus = 'watching' | 'preparing' | 'paused' | 'done'

/** One named watchlist of `GET /watchlist/lists`. */
export interface WatchlistGroup {
  id: number
  name: string
  count: number
  is_default: boolean
}

/** One tracked player of `GET /watchlist`. */
export interface WatchlistItem {
  id: number
  instance_id: number
  list_id: number
  list_name: string | null
  player: PlayerSummary
  status: WatchStatus
  tag: string | null
  note: string | null
  source: DataSource | string
  added_at: string
}

/** `GET /watchlist` payload. */
export interface WatchlistListResponse {
  items: WatchlistItem[]
  total: number
  lists: WatchlistGroup[]
}

/** `GET /watchlist/lists` payload. */
export interface WatchlistGroupResponse {
  items: WatchlistGroup[]
  total: number
}

/** Query filters of `GET /watchlist`. */
export interface WatchlistQuery {
  saveId?: number
  listId?: number
  q?: string
  status?: WatchStatus
}

/** Request body of `POST /watchlist/lists`. */
export interface WatchlistCreateListRequest {
  name: string
}

/** Request body of `POST /watchlist/items`. */
export interface WatchlistCreateRequest {
  instance_id: number
  list_id?: number
  status?: WatchStatus
  tag?: string
  note?: string
}

/** Request body of `PATCH /watchlist/items/{id}`. */
export interface WatchlistPatchRequest {
  list_id?: number
  status?: WatchStatus
  tag?: string
  note?: string
}

/** Result of `POST /watchlist/refresh`. */
export interface WatchlistRefreshResponse {
  created: number
  alerts: number
}

/** `severity` values observed for alerts; the API also allows other strings. */
export type AlertSeverity = 'low' | 'medium' | 'high'

/** One alert of `GET /alerts`. */
export interface Alert {
  id: number
  instance_id: number | null
  type: string
  severity: AlertSeverity | null
  title: string
  message: string
  created_at: string
  read_at: string | null
}

/** `GET /alerts` payload. */
export interface AlertListResponse {
  items: Alert[]
  total: number
}
