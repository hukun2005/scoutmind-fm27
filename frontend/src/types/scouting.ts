/** Types for §7 智能球探 (`/scouting/roles`, `/scouting/evaluate`, `/scouting/search`). */

import type { PlayerFilters, PlayerSummary } from './players'

/** One role template returned by `GET /scouting/roles`. */
export interface RoleTemplate {
  key: string
  name: string
  position_group: string | null
  version: number
  weights: Record<string, number>
}

/** `GET /scouting/roles` payload. */
export interface RoleListResponse {
  items: RoleTemplate[]
}

/** One weighted attribute of `POST /scouting/evaluate` → `components`. */
export interface EvaluationComponent {
  key: string
  name: string
  weight: number
  value: number | null
  contribution: number | null
}

/** `POST /scouting/evaluate` payload. */
export interface RoleEvaluation {
  instance_id: number
  role_key: string
  role_name: string
  score: number | null
  components: EvaluationComponent[]
  template_version: number
  coverage: number | null
  strengths: string[]
  weaknesses: string[]
}

/** Request body of `POST /scouting/evaluate`. */
export interface RoleEvaluationRequest {
  instance_id: number
  role_key: string
}

/** One ranked candidate of `POST /scouting/search`. */
export interface ScoutingCandidate {
  player: PlayerSummary
  score: number | null
  coverage: number | null
  role_key: string | null
}

/** `POST /scouting/search` request body. */
export interface ScoutingSearchRequest {
  save_id?: number
  role_key?: string
  filters?: PlayerFilters
  limit?: number
}

/** `POST /scouting/search` payload. */
export interface ScoutingSearchResponse {
  items: ScoutingCandidate[]
  total: number
}
