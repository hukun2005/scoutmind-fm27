/** §8 俱乐部 endpoints. */

import type { Club, ClubListResponse, ClubTransferProfile } from '../types/clubs'
import { apiGet } from './client'

/**
 * `GET /clubs` — club identity list used by filters and the profile tab.
 *
 * The contract documents the profile payload but not the collection envelope,
 * so both `{items, total}` and a bare array are accepted.
 * @returns Normalized club list.
 */
export async function listClubs(): Promise<{ items: Club[]; total: number }> {
  const data = await apiGet<ClubListResponse>('/clubs')
  if (Array.isArray(data)) return { items: data, total: data.length }
  return { items: data.items, total: data.total }
}

/**
 * `GET /clubs/{club_id}/transfer-profile` — buying/selling profile of one club.
 * @param clubId Club identifier.
 * @returns Club transfer profile.
 */
export function getClubTransferProfile(clubId: number): Promise<ClubTransferProfile> {
  return apiGet<ClubTransferProfile>(`/clubs/${clubId}/transfer-profile`)
}
