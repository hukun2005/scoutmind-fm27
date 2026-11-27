/** 最近访问对象：只保存在本地浏览器，按存档隔离，不上传。 */

export interface RecentEntry {
  entity_type: string
  entity_id: number
  display_name: string
  subtitle: string
  navigation_target: string
  save_id: number | null
}

const KEY = 'scoutmind.search.recent'
const MAX = 8

function read(): RecentEntry[] {
  if (typeof localStorage === 'undefined') return []
  try {
    const raw = localStorage.getItem(KEY)
    const parsed = raw ? (JSON.parse(raw) as unknown) : []
    if (!Array.isArray(parsed)) return []
    return parsed.filter(
      (item): item is RecentEntry =>
        typeof item === 'object' &&
        item !== null &&
        typeof (item as RecentEntry).navigation_target === 'string' &&
        typeof (item as RecentEntry).display_name === 'string',
    )
  } catch {
    return []
  }
}

/** 记录一次访问（同一目标去重并置顶）。 */
export function rememberRecent(entry: RecentEntry): void {
  if (typeof localStorage === 'undefined') return
  const rest = read().filter(
    (item) => !(item.entity_type === entry.entity_type && item.entity_id === entry.entity_id),
  )
  const next = [entry, ...rest].slice(0, MAX)
  try {
    localStorage.setItem(KEY, JSON.stringify(next))
  } catch {
    // 存储失败不影响搜索本身。
  }
}

/** 当前存档的最近访问；其他存档的结果不显示。 */
export function recentFor(saveId: number | null): RecentEntry[] {
  return read().filter((item) => item.save_id === saveId)
}

/** 清空当前存档的最近访问。 */
export function clearRecent(saveId: number | null): void {
  if (typeof localStorage === 'undefined') return
  try {
    localStorage.setItem(KEY, JSON.stringify(read().filter((item) => item.save_id !== saveId)))
  } catch {
    // ignore
  }
}
