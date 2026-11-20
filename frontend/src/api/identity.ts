/** Identity Resolution Center endpoints（SM-011）。 */

import type {
  ConflictDecision,
  ConflictDetail,
  ConflictListQuery,
  ConflictListResponse,
  ResolveConflictResponse,
} from '../types/identity'
import { apiGet, apiPost } from './client'

/**
 * `GET /identity/conflicts` — 身份冲突列表。
 * 只返回当前存档（或显式指定且属于当前用户的存档）的冲突。
 */
export function listIdentityConflicts(query: ConflictListQuery): Promise<ConflictListResponse> {
  return apiGet<ConflictListResponse>('/identity/conflicts', query)
}

/** `GET /identity/conflicts/{id}` — 双方球员、来源、建议与操作历史。 */
export function getIdentityConflict(conflictId: number): Promise<ConflictDetail> {
  return apiGet<ConflictDetail>(`/identity/conflicts/${conflictId}`)
}

/**
 * `POST /identity/conflicts/{id}/resolve` — 人工确认。
 * `same` 会迁移实例与快照；`different` / `defer` 只改状态并写审计。
 */
export function resolveIdentityConflict(
  conflictId: number,
  decision: ConflictDecision,
  options: { keep?: 'existing' | 'incoming'; note?: string } = {},
): Promise<ResolveConflictResponse> {
  return apiPost<ResolveConflictResponse>(`/identity/conflicts/${conflictId}/resolve`, {
    decision,
    keep: options.keep ?? 'existing',
    note: options.note ?? null,
  })
}
