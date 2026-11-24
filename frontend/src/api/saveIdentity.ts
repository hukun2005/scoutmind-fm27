/** 存档身份诊断端点（save-identity/v1）。所有请求都归属当前活动存档。 */

import type {
  SaveIdentityAuditResponse,
  SaveIdentityDetail,
  SaveIdentityListResponse,
} from '../types/saveIdentity'
import { apiGet } from './client'

/** `GET /save-identities` — 当前存档的身份列表与状态计数。 */
export function listSaveIdentities(params: {
  status?: string
  limit?: number
  offset?: number
} = {}): Promise<SaveIdentityListResponse> {
  return apiGet<SaveIdentityListResponse>('/save-identities', params)
}

/** `GET /save-identities/{id}` — 身份、证据、最近会话与采集阻断原因。 */
export function getSaveIdentity(identityId: number): Promise<SaveIdentityDetail> {
  return apiGet<SaveIdentityDetail>(`/save-identities/${identityId}`)
}

/** `GET /save-identity-audit` — 身份/会话/采集归属的审计事件。 */
export function listSaveIdentityAudit(params: {
  identity_id?: number
  session_id?: number
  capture_id?: number
  limit?: number
  offset?: number
} = {}): Promise<SaveIdentityAuditResponse> {
  return apiGet<SaveIdentityAuditResponse>('/save-identity-audit', params)
}
