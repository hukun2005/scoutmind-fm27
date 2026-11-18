/**
 * Transfer-intelligence store: unified filters drive both the rows and the statistics
 * header, so the sample size always matches the visible table.
 */

import { reactive, ref } from 'vue'
import { defineStore } from 'pinia'
import { asApiError, type ApiError } from '../api/client'
import { getTransferStats, listTransfers } from '../api/transfers'
import type { CoverageMap } from '../types/common'
import type {
  Transfer,
  TransferFilters,
  TransferStatsResponse,
  TransferStatus,
} from '../types/transfers'
import { useSessionStore } from './session'

/** Default page size for transfers; smaller than players because rows are wider. */
export const TRANSFER_PAGE_SIZE = 25

/** Transfer list and statistics state. */
export const useTransfersStore = defineStore('transfers', () => {
  const filters = reactive<TransferFilters>({ status: 'completed' })
  const page = ref(1)
  const pageSize = ref(TRANSFER_PAGE_SIZE)
  const items = ref<Transfer[]>([])
  const total = ref(0)
  const coverage = ref<CoverageMap>({})
  const loading = ref(false)
  const error = ref<ApiError | null>(null)
  const stats = ref<TransferStatsResponse | null>(null)
  const statsLoading = ref(false)
  const statsError = ref<ApiError | null>(null)
  let listSeq = 0
  let statsSeq = 0

  /**
   * Fetch the current page of transfers.
   * @param saveId Active save id.
   */
  async function loadList(saveId: number | null): Promise<void> {
    const seq = ++listSeq
    loading.value = true
    error.value = null
    try {
      const response = await listTransfers({
        save_id: saveId ?? undefined,
        status: filters.status ?? 'completed',
        transfer_type: filters.transfer_type,
        from_date: filters.from_date,
        to_date: filters.to_date,
        club_id: filters.club_id,
        position_group: filters.position_group,
        min_fee: filters.min_fee,
        max_fee: filters.max_fee,
        min_age: filters.min_age,
        max_age: filters.max_age,
        sort: filters.sort,
        limit: pageSize.value,
        offset: (page.value - 1) * pageSize.value,
      })
      if (seq !== listSeq) return
      items.value = response.items ?? []
      total.value = response.total ?? 0
      coverage.value = response.coverage ?? {}
      useSessionStore().markSources(items.value.map((item) => item.source))
    } catch (caught) {
      if (seq !== listSeq) return
      error.value = asApiError(caught)
      items.value = []
      total.value = 0
    } finally {
      if (seq === listSeq) loading.value = false
    }
  }

  /**
   * Fetch the statistics header for the current filter set.
   * @param saveId Active save id.
   */
  async function loadStats(saveId: number | null): Promise<void> {
    const seq = ++statsSeq
    statsLoading.value = true
    statsError.value = null
    try {
      const response = await getTransferStats({
        save_id: saveId ?? undefined,
        position_group: filters.position_group,
        min_age: filters.min_age,
        max_age: filters.max_age,
        from_date: filters.from_date,
        to_date: filters.to_date,
        club_id: filters.club_id,
      })
      if (seq !== statsSeq) return
      stats.value = response
    } catch (caught) {
      if (seq !== statsSeq) return
      statsError.value = asApiError(caught)
      stats.value = null
    } finally {
      if (seq === statsSeq) statsLoading.value = false
    }
  }

  /**
   * Update one filter and reset paging.
   * @param key Filter name.
   * @param value New value; `undefined` removes it.
   */
  function setFilter<K extends keyof TransferFilters>(key: K, value: TransferFilters[K]): void {
    if (value === undefined) delete filters[key]
    else filters[key] = value
    page.value = 1
  }

  /** Reset filters to the completed-transfers view. */
  function reset(): void {
    for (const key of Object.keys(filters) as Array<keyof TransferFilters>) {
      delete filters[key]
    }
    filters.status = 'completed'
    page.value = 1
  }

  /**
   * Change the status tab.
   * @param status `completed` | `pending` | `all`.
   */
  function setStatus(status: TransferStatus | 'all'): void {
    filters.status = status
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
    page,
    pageSize,
    items,
    total,
    coverage,
    loading,
    error,
    stats,
    statsLoading,
    statsError,
    loadList,
    loadStats,
    setFilter,
    reset,
    setStatus,
    setPage,
    setPageSize,
  }
})
