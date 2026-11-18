/** 俱乐部解析（主执教俱乐部）与阵容 CSV 导入接口。 */

import type { ClubSearchResponse, SquadCsvResult, UserClubResponse } from '../types/clubResolution'
import { apiDelete, apiGet, apiPut, apiUpload } from './client'

/**
 * `GET /clubs/search` — 搜索当前存档的俱乐部，带来源与可信度。
 * @param query 名称模糊搜索词。
 * @param limit 返回上限。
 * @returns 俱乐部列表。
 */
export function searchClubs(query?: string, limit = 50): Promise<ClubSearchResponse> {
  return apiGet<ClubSearchResponse>('/clubs/search', { query, limit })
}

/**
 * `GET /saves/{save_id}/user-club` — 当前主执教俱乐部及其来源。
 * @param saveId 存档 ID。
 * @returns 俱乐部与来源信息。
 */
export function getUserClub(saveId: number): Promise<UserClubResponse> {
  return apiGet<UserClubResponse>(`/saves/${saveId}/user-club`)
}

/**
 * `PUT /saves/{save_id}/user-club` — 指定主执教俱乐部（不会移动任何球员）。
 * @param saveId 存档 ID。
 * @param clubId 选中的俱乐部 ID。
 * @returns 更新后的俱乐部。
 */
export function setUserClub(saveId: number, clubId: number): Promise<UserClubResponse> {
  return apiPut<UserClubResponse>(`/saves/${saveId}/user-club`, { club_id: clubId })
}

/**
 * `DELETE /saves/{save_id}/user-club` — 清除主执教俱乐部。
 * @param saveId 存档 ID。
 */
export function clearUserClub(saveId: number): Promise<void> {
  return apiDelete(`/saves/${saveId}/user-club`)
}

/**
 * `POST /imports/squad-csv` — 导入阵容名单。
 * @param saveId 存档 ID。
 * @param file CSV 文件。
 * @returns 每行的匹配结果与汇总。
 */
export function uploadSquadCsv(saveId: number, file: File): Promise<SquadCsvResult> {
  const form = new FormData()
  form.append('file', file, file.name)
  return apiUpload<SquadCsvResult>(`/imports/squad-csv?save_id=${saveId}`, form)
}

/**
 * `GET /imports/squad-csv/template` — 可填写模板的内容。
 * @returns 文件名与 CSV 文本。
 */
export function fetchSquadCsvTemplate(): Promise<{ filename: string; content: string }> {
  return apiGet<{ filename: string; content: string }>('/imports/squad-csv/template')
}
