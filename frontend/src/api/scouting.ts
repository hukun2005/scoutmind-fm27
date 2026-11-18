/** §7 智能球探 endpoints. */

import type {
  RoleEvaluation,
  RoleEvaluationRequest,
  RoleListResponse,
  ScoutingSearchRequest,
  ScoutingSearchResponse,
} from '../types/scouting'
import { apiGet, apiPost } from './client'

/**
 * `GET /scouting/roles` — role templates with their attribute weights.
 * @returns Role templates.
 */
export function listRoles(): Promise<RoleListResponse> {
  return apiGet<RoleListResponse>('/scouting/roles')
}

/**
 * `POST /scouting/evaluate` — score one player against one role.
 * @param body Instance id and role key.
 * @returns Score, weighted components, strengths and weaknesses.
 */
export function evaluateRole(body: RoleEvaluationRequest): Promise<RoleEvaluation> {
  return apiPost<RoleEvaluation>('/scouting/evaluate', body)
}

/**
 * `POST /scouting/search` — ranked candidates for a role and filter set.
 * @param body Save, optional role, player filters and limit.
 * @returns Ranked candidates with coverage.
 */
export function searchScouting(body: ScoutingSearchRequest): Promise<ScoutingSearchResponse> {
  return apiPost<ScoutingSearchResponse>('/scouting/search', body)
}
