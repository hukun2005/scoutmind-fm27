/** §8 转会 endpoints — transfer intelligence, statistics, comparables and idempotent valuation. */

import type { PlayerDetail, Valuation } from '../types/players'
import type {
  SimilarTransfersResponse,
  TransferListQuery,
  TransferListResponse,
  TransferStatsQuery,
  TransferStatsResponse,
} from '../types/transfers'
import { apiGet } from './client'

/**
 * `GET /transfers` — completed/pending transfer rows with fee components.
 * @param query Status, type, date and value filters plus paging.
 * @returns Rows and field coverage.
 */
export function listTransfers(query: TransferListQuery): Promise<TransferListResponse> {
  return apiGet<TransferListResponse>('/transfers', query)
}

/**
 * `GET /transfers/stats` — quantiles, histogram and sample warnings.
 * @param query Filters of the statistic window.
 * @returns Statistics payload.
 */
export function getTransferStats(query: TransferStatsQuery): Promise<TransferStatsResponse> {
  return apiGet<TransferStatsResponse>('/transfers/stats', query)
}

/**
 * `GET /transfers/similar` — comparable transfers for one player instance.
 * @param instanceId Player instance identifier.
 * @param limit Maximum number of comparables (backend default 20).
 * @returns Target, comparables, effective weights and data gaps.
 */
export function getSimilarTransfers(instanceId: number, limit?: number): Promise<SimilarTransfersResponse> {
  return apiGet<SimilarTransfersResponse>('/transfers/similar', { instance_id: instanceId, limit })
}

/**
 * `GET /transfers/valuation` — comparable-transfer valuation range.
 * @param instanceId Player instance identifier.
 * @returns Valuation with sample size, method and warnings.
 */
export function getValuation(instanceId: number): Promise<Valuation> {
  return apiGet<Valuation>('/transfers/valuation', { instance_id: instanceId })
}

/**
 * `GET /players/{instance_id}` is the detail payload that also embeds a valuation;
 * the transfer screen reuses this helper to resolve a player name for a comparable.
 * @param instanceId Player instance identifier.
 * @returns Player detail payload.
 */
export function getValuationSubject(instanceId: number): Promise<PlayerDetail> {
  return apiGet<PlayerDetail>(`/players/${instanceId}`)
}
