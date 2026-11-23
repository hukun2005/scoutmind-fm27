/** Free-agent / unresolved candidate endpoints（SM-119）。 */

import type {
  UnresolvedDetail,
  UnresolvedDismissResponse,
  UnresolvedListQuery,
  UnresolvedListResponse,
  UnresolvedObservationsResponse,
  UnresolvedResolveRequest,
  UnresolvedResolveResponse,
} from '../types/unresolved'
import { apiGet, apiPost } from './client'

/**
 * `GET /unresolved-players` — current save's candidates.
 * Counts are save-wide; `items` follow the filters and pagination.
 */
export function listUnresolvedPlayers(query: UnresolvedListQuery): Promise<UnresolvedListResponse> {
  return apiGet<UnresolvedListResponse>('/unresolved-players', query)
}

/** `GET /unresolved-players/{id}` — evidence, suggestions and audit history. */
export function getUnresolvedPlayer(candidateId: number): Promise<UnresolvedDetail> {
  return apiGet<UnresolvedDetail>(`/unresolved-players/${candidateId}`)
}

/** `GET /unresolved-players/{id}/observations` — stored observations. */
export function listUnresolvedObservations(
  candidateId: number,
  query: { page?: number; page_size?: number } = {},
): Promise<UnresolvedObservationsResponse> {
  return apiGet<UnresolvedObservationsResponse>(`/unresolved-players/${candidateId}/observations`, query)
}

/**
 * `POST /unresolved-players/{id}/resolve` — attach the candidate to an existing identity.
 * The backend rejects the call unless `confirm` is true.
 */
export function resolveUnresolvedPlayer(
  candidateId: number,
  body: UnresolvedResolveRequest,
): Promise<UnresolvedResolveResponse> {
  return apiPost<UnresolvedResolveResponse>(`/unresolved-players/${candidateId}/resolve`, body)
}

/** `POST /unresolved-players/{id}/dismiss` — ignore a candidate; observations stay. */
export function dismissUnresolvedPlayer(
  candidateId: number,
  body: { reason: string; note?: string },
): Promise<UnresolvedDismissResponse> {
  return apiPost<UnresolvedDismissResponse>(`/unresolved-players/${candidateId}/dismiss`, body)
}
