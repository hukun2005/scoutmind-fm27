/** 全局搜索（`GET /search`）的类型。 */

export type SearchEntityType = 'player' | 'club' | 'transfer'

export type SearchType = 'all' | 'players' | 'clubs' | 'transfers'

/** 统一搜索结果；`meta` 字段按实体类型不同。 */
export interface SearchResultItem {
  entity_type: SearchEntityType
  entity_id: number
  display_name: string
  subtitle: string
  navigation_target: string
  meta: Record<string, unknown>
}

/** `GET /search` 响应。 */
export interface SearchResponse {
  query: string
  type: SearchType
  categories: {
    players: SearchResultItem[]
    clubs: SearchResultItem[]
    transfers: SearchResultItem[]
  }
  total: number
  limits: { per_category: number }
}

/** 读取 meta 中的数字，缺失返回 null（不按 0 处理）。 */
export function metaNumber(meta: Record<string, unknown>, key: string): number | null {
  const value = meta[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

/** 读取 meta 中的字符串，缺失返回 null。 */
export function metaText(meta: Record<string, unknown>, key: string): string | null {
  const value = meta[key]
  return typeof value === 'string' && value.length > 0 ? value : null
}
