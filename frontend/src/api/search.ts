/** 全局搜索 endpoint。 */

import type { SearchResponse, SearchType } from '../types/search'
import { apiGet } from './client'

/**
 * `GET /search` — 当前存档内的球员、俱乐部与转会。
 * @param q 关键字；空串由后端直接返回空分类。
 * @param type 分类过滤。
 * @param options 存档与每类上限。
 * @returns 统一结构的结果。
 */
export function searchAll(
  q: string,
  type: SearchType = 'all',
  options: { saveId?: number | null; limit?: number } = {},
): Promise<SearchResponse> {
  return apiGet<SearchResponse>('/search', {
    q,
    type,
    save_id: options.saveId ?? undefined,
    limit: options.limit ?? 8,
  })
}
