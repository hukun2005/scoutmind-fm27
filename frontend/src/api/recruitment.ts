/** Recruitment Engine endpoints (`/recruitment/*`). */

import type {
  HiddenValueResponse,
  PlayerScore,
  RecruitmentModel,
  RecruitmentSearchRequest,
  RecruitmentSearchResponse,
  Shortlist,
  ShortlistRequest,
  ShortlistSummary,
} from '../types/recruitment'
import { apiGet, apiPost } from './client'

/**
 * `GET /recruitment/model` — position templates and six-dimension weights.
 * @returns The model currently in use.
 */
export function getRecruitmentModel(): Promise<RecruitmentModel> {
  return apiGet<RecruitmentModel>('/recruitment/model')
}

/**
 * `POST /recruitment/search` — ranked candidates for one slot.
 * @param body Filter set.
 * @returns Scored candidates and the criteria that produced them.
 */
export function searchRecruitment(body: RecruitmentSearchRequest): Promise<RecruitmentSearchResponse> {
  return apiPost<RecruitmentSearchResponse>('/recruitment/search', body)
}

/**
 * `GET /recruitment/player/{id}` — full scout report for one player.
 * @param instanceId Player instance id.
 * @param saveId Optional save override.
 * @returns Score, dimensions, strengths, risks and cost.
 */
export function getPlayerScore(instanceId: number, saveId?: number): Promise<PlayerScore> {
  return apiGet<PlayerScore>(`/recruitment/player/${instanceId}`, { save_id: saveId })
}

/**
 * `POST /recruitment/compare` — compare players with identical weights.
 * @param instanceIds Two to five player instance ids.
 * @param saveId Optional save override.
 * @returns Compared scores and the shared dimension list.
 */
export function compareRecruitmentPlayers(
  instanceIds: number[],
  saveId?: number,
): Promise<{ items: PlayerScore[]; compared: number; shared_dimensions: string[]; note: string }> {
  return apiPost('/recruitment/compare', { instance_ids: instanceIds, save_id: saveId })
}

/**
 * `GET /recruitment/hidden-value` — cheap-upside candidates plus the rules that cannot run.
 * @param slot Optional slot filter.
 * @param limit Maximum hits.
 * @returns Hits and rule coverage.
 */
export function getHiddenValue(slot?: string, limit = 15): Promise<HiddenValueResponse> {
  return apiGet<HiddenValueResponse>('/recruitment/hidden-value', { slot, limit })
}

/**
 * `GET /recruitment/shortlists` — stored shortlists.
 * @returns Shortlist summaries, newest first.
 */
export function listShortlists(): Promise<{ items: ShortlistSummary[]; total: number }> {
  return apiGet('/recruitment/shortlists')
}

/**
 * `GET /recruitment/shortlists/{id}` — one stored shortlist with its candidates.
 * @param shortlistId Shortlist id.
 * @returns The stored shortlist.
 */
export function getShortlist(shortlistId: number): Promise<Shortlist> {
  return apiGet<Shortlist>(`/recruitment/shortlists/${shortlistId}`)
}

/**
 * `POST /recruitment/shortlists` — generate and store a shortlist.
 * @param body Shortlist criteria.
 * @returns The generated shortlist, including its new id.
 */
export function createShortlist(body: ShortlistRequest): Promise<Shortlist> {
  return apiPost<Shortlist>('/recruitment/shortlists', body)
}
