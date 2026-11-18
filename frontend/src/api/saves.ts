/** §3 存档 endpoints. */

import type { Save, SaveSummary } from '../types/bootstrap'
import type { Paged } from '../types/common'
import { apiGet, apiPost } from './client'

/**
 * `GET /saves` — every save known to the backend.
 * @returns Paged saves.
 */
export function listSaves(): Promise<Paged<Save>> {
  return apiGet<Paged<Save>>('/saves')
}

/**
 * `POST /saves` — create a save.
 * @param body Save name plus optional game version/build.
 * @returns The created save.
 */
export function createSave(body: { name: string; game_version?: string; game_build?: string }): Promise<Save> {
  return apiPost<Save>('/saves', body)
}

/**
 * `GET /saves/{id}/summary` — coverage counters and the latest import job.
 * @param saveId Save identifier.
 * @returns Save, coverage and last import.
 */
export function getSaveSummary(saveId: number): Promise<SaveSummary> {
  return apiGet<SaveSummary>(`/saves/${saveId}/summary`)
}
