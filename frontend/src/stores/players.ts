/**
 * Players store: filter state, server-side sorting/paging and the last response.
 *
 * Filters survive navigation so returning from a player detail keeps the table
 * context. Stale responses are discarded by request sequence.
 */

import { reactive, ref } from 'vue'
import { defineStore } from 'pinia'
import { asApiError, type ApiError } from '../api/client'
import { listPlayers } from '../api/players'
import type { CoverageMap } from '../types/common'
import type { PlayerFilters, PlayerSummary } from '../types/players'
import { useSessionStore } from './session'

/** Default page size; the API caps `limit` at 200. */
export const PLAYER_PAGE_SIZE = 50

/** Sortable column prop → API sort key (`age|ca|pa|market_value|name|updated_at`). */
export const PLAYER_SORT_FIELDS: Record<string, string> = {
  age: 'age',
  ca: 'ca',
  pa: 'pa',
  market_value: 'market_value',
  name: 'name',
  updated_at: 'updated_at',
}

/** Player list state and fetch actions. */
export const usePlayersStore = defineStore('players', () => {
  const filters = reactive<PlayerFilters>({})
  const sort = ref('-updated_at')
  const page = ref(1)
  const pageSize = ref(PLAYER_PAGE_SIZE)
  const items = ref<PlayerSummary[]>([])
  const total = ref(0)
  const coverage = ref<CoverageMap>({})
  const loading = ref(false)
  const error = ref<ApiError | null>(null)
  let requestSeq = 0

  /**
   * Fetch the current page with the current filters.
   * @param saveId Active save; omitted when the backend should use its default.
   */
  async function load(saveId: number | null): Promise<void> {
    const seq = ++requestSeq
    loading.value = true
    error.value = null
    try {
      const response = await listPlayers({
        save_id: saveId ?? undefined,
        sort: sort.value || undefined,
        limit: pageSize.value,
        offset: (page.value - 1) * pageSize.value,
        ...filters,
      })
      if (seq !== requestSeq) return
      items.value = response.items ?? []
      total.value = response.total ?? 0
      coverage.value = response.coverage ?? {}
      useSessionStore().markSources(items.value.map((item) => item.source))
    } catch (caught) {
      if (seq !== requestSeq) return
      error.value = asApiError(caught)
      items.value = []
      total.value = 0
    } finally {
      if (seq === requestSeq) loading.value = false
    }
  }

  /**
   * Update one filter and reset to the first page.
   * @param key Filter name.
   * @param value New value; `undefined` removes the filter.
   */
  function setFilter<K extends keyof PlayerFilters>(key: K, value: PlayerFilters[K]): void {
    if (value === undefined) delete filters[key]
    else filters[key] = value
    page.value = 1
  }

  /** Clear every filter and sort, keeping the page size. */
  function reset(): void {
    for (const key of Object.keys(filters) as Array<keyof PlayerFilters>) {
      delete filters[key]
    }
    sort.value = '-updated_at'
    page.value = 1
  }

  /**
   * Apply a table sort.
   * @param prop Column prop; ignored when it is not sortable server-side.
   * @param order Direction, or `null` to clear.
   */
  function setSort(prop: string, order: 'ascending' | 'descending' | null): void {
    const field = PLAYER_SORT_FIELDS[prop]
    if (!field) return
    sort.value = order === null ? '-updated_at' : order === 'ascending' ? field : `-${field}`
    page.value = 1
  }

  /**
   * Change page.
   * @param value 1-based page number.
   */
  function setPage(value: number): void {
    page.value = value
  }

  /**
   * Change page size and return to page 1.
   * @param value Rows per page.
   */
  function setPageSize(value: number): void {
    pageSize.value = value
    page.value = 1
  }

  return {
    filters,
    sort,
    page,
    pageSize,
    items,
    total,
    coverage,
    loading,
    error,
    load,
    setFilter,
    reset,
    setSort,
    setPage,
    setPageSize,
  }
})
