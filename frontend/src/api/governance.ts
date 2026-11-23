/** Data Governance Center endpoints (`/data-quality/*`). */

import type {
  CanonicalDetail,
  DecisionPayload,
  GovernanceOverview,
  ReviewHistory,
  ReviewQueueResponse,
} from '../types/governance'
import { apiGet, apiPost } from './client'

export interface QueueQuery {
  status?: string
  player?: string
  game_date?: string
  conflict_type?: string
  limit?: number
  offset?: number
}

/** `GET /data-quality/governance/overview` — KPI totals for the active save. */
export function getGovernanceOverview(): Promise<GovernanceOverview> {
  return apiGet<GovernanceOverview>('/data-quality/governance/overview')
}

/** `GET /data-quality/canonical/review-queue` — paginated review queue. */
export function getReviewQueue(query: QueueQuery): Promise<ReviewQueueResponse> {
  return apiGet<ReviewQueueResponse>('/data-quality/canonical/review-queue', query)
}

/** `GET /data-quality/canonical/{id}` — snapshots, attributes and timeline. */
export function getCanonicalDetail(canonicalId: number): Promise<CanonicalDetail> {
  return apiGet<CanonicalDetail>(`/data-quality/canonical/${canonicalId}`)
}

/** `GET /data-quality/canonical/{id}/history` — append-only audit trail. */
export function getReviewHistory(canonicalId: number): Promise<ReviewHistory> {
  return apiGet<ReviewHistory>(`/data-quality/canonical/${canonicalId}/history`)
}

/** `POST /data-quality/canonical/{id}/decision` — select/exclude/keep pending. */
export function submitReviewDecision(canonicalId: number, payload: DecisionPayload): Promise<unknown> {
  return apiPost(`/data-quality/canonical/${canonicalId}/decision`, payload)
}
