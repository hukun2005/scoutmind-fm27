/**
 * 球员对比选择：最多 4 名、最少 2 名；按存档隔离并持久化到 localStorage。
 *
 * 只保存球员实例 ID，不缓存业务字段；对比页按 ID 重新请求详情。
 */

import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

export const MAX_COMPARE = 4
const STORAGE_KEY = 'scoutmind.compare.selection'

interface StoredSelection {
  saveId: number | null
  ids: number[]
}

/** 读取本地选择；损坏或越界时回退为空。 */
function readStored(): StoredSelection {
  if (typeof localStorage === 'undefined') return { saveId: null, ids: [] }
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { saveId: null, ids: [] }
    const parsed = JSON.parse(raw) as Partial<StoredSelection>
    const ids = Array.isArray(parsed.ids)
      ? parsed.ids.filter((value): value is number => Number.isInteger(value) && value > 0).slice(0, MAX_COMPARE)
      : []
    return { saveId: typeof parsed.saveId === 'number' ? parsed.saveId : null, ids }
  } catch {
    return { saveId: null, ids: [] }
  }
}

/** 对比选择状态。 */
export const useCompareStore = defineStore('compare', () => {
  const stored = readStored()
  const boundSaveId = ref<number | null>(stored.saveId)
  const ids = ref<number[]>(stored.ids)

  const count = computed(() => ids.value.length)
  const isFull = computed(() => ids.value.length >= MAX_COMPARE)
  const canCompare = computed(() => ids.value.length >= 2)

  function persist(): void {
    if (typeof localStorage === 'undefined') return
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ saveId: boundSaveId.value, ids: ids.value }))
  }

  /** 切换存档时清空，避免把上一存档的实例带到新存档。 */
  function ensureSave(saveId: number | null): void {
    if (boundSaveId.value === saveId) return
    boundSaveId.value = saveId
    ids.value = []
    persist()
  }

  /** @returns `added` / `exists` / `full`。 */
  function add(instanceId: number): 'added' | 'exists' | 'full' {
    if (ids.value.includes(instanceId)) return 'exists'
    if (ids.value.length >= MAX_COMPARE) return 'full'
    ids.value = [...ids.value, instanceId]
    persist()
    return 'added'
  }

  function remove(instanceId: number): void {
    ids.value = ids.value.filter((value) => value !== instanceId)
    persist()
  }

  /** 用新球员替换旧球员，保持选择顺序。 */
  function replace(oldId: number, newId: number): void {
    ids.value = ids.value.map((value) => (value === oldId ? newId : value))
    persist()
  }

  function clear(): void {
    ids.value = []
    persist()
  }

  return { boundSaveId, ids, count, isFull, canCompare, ensureSave, add, remove, replace, clear }
})
