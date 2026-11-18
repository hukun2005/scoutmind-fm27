/**
 * Session store: bootstrap metadata, active save, API token and demo-mode flags.
 *
 * The active save is persisted per browser so reloads keep the same dataset, and
 * every data store passes it to the endpoints that accept `save_id`.
 */

import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { getBootstrap } from '../api/bootstrap'
import { asApiError, getAuthToken, onUnauthorized, setAuthToken, type ApiError } from '../api/client'
import type { BootstrapMeta, Capabilities, DataSourceCount, Save } from '../types/bootstrap'

const SAVE_STORAGE_KEY = 'scoutmind.saveId'
const DEMO_DISMISS_KEY = 'scoutmind.demoDismissed'

/** Capability defaults used before `/meta/bootstrap` resolves. */
const EMPTY_CAPABILITIES: Capabilities = {
  live_reader: false,
  save_parser: false,
  agent_llm: false,
  watchlist: false,
  transfer_intelligence: false,
}

function readStoredSaveId(): number | null {
  try {
    const raw = window.localStorage.getItem(SAVE_STORAGE_KEY)
    if (!raw) return null
    const parsed = Number.parseInt(raw, 10)
    return Number.isFinite(parsed) ? parsed : null
  } catch {
    return null
  }
}

function persistSaveId(saveId: number | null): void {
  try {
    if (saveId === null) window.localStorage.removeItem(SAVE_STORAGE_KEY)
    else window.localStorage.setItem(SAVE_STORAGE_KEY, String(saveId))
  } catch {
    // Persistence is a convenience; storage failures must not break the session.
  }
}

function readDemoDismissed(): boolean {
  try {
    return window.sessionStorage.getItem(DEMO_DISMISS_KEY) === '1'
  } catch {
    return false
  }
}

/** Session metadata shared by the shell and every view. */
export const useSessionStore = defineStore('session', () => {
  const meta = ref<BootstrapMeta | null>(null)
  const loading = ref(false)
  const error = ref<ApiError | null>(null)
  const activeSaveId = ref<number | null>(null)
  const token = ref(getAuthToken())
  const authRequired = ref(false)
  const syntheticSeen = ref(false)
  const demoDismissed = ref(readDemoDismissed())
  /** Incremented whenever the metadata or the token changes; views watch it to refetch. */
  const dataRevision = ref(0)

  const saves = computed<Save[]>(() => meta.value?.saves ?? [])
  const capabilities = computed<Capabilities>(() => meta.value?.capabilities ?? EMPTY_CAPABILITIES)
  const warnings = computed<string[]>(() => meta.value?.warnings ?? [])
  const version = computed(() => meta.value?.version ?? '—')
  const product = computed(() => meta.value?.product ?? 'ScoutMind')
  const dataSources = computed<DataSourceCount[]>(() => meta.value?.data_sources ?? [])
  const activeSave = computed<Save | null>(() => saves.value.find((save) => save.id === activeSaveId.value) ?? null)
  const demoMode = computed(() => meta.value?.demo_mode === true)
  const agentLlm = computed(() => capabilities.value.agent_llm)
  const showDemoBanner = computed(() => (demoMode.value || syntheticSeen.value) && !demoDismissed.value)

  /** True once any real (non-synthetic) reader produced records. */
  const hasRealScanData = computed(() =>
    dataSources.value.some(
      (entry) =>
        (entry.source === 'fm27_live_reader' ||
          entry.source === 'fm_save_parser' ||
          entry.source === 'fmsuperscout') &&
        entry.records > 0,
    ),
  )

  /** Load (or reload) `/meta/bootstrap` and resolve the active save. */
  async function load(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const data = await getBootstrap()
      meta.value = data
      const ids = data.saves.map((save) => save.id)
      const stored = readStoredSaveId()
      const storedValid = stored !== null && ids.includes(stored)
      const activeValid = data.active_save_id !== null && ids.includes(data.active_save_id)
      const nextId = storedValid ? stored : activeValid ? data.active_save_id : (ids[0] ?? null)
      activeSaveId.value = nextId
      persistSaveId(nextId)
      dataRevision.value += 1
    } catch (caught) {
      error.value = asApiError(caught)
      meta.value = null
    } finally {
      loading.value = false
    }
  }

  /**
   * Switch the save used by every data surface.
   * @param saveId Save identifier, or `null` to clear the selection.
   */
  function selectSave(saveId: number | null): void {
    activeSaveId.value = saveId
    persistSaveId(saveId)
  }

  /**
   * Persist the optional API token and clear the auth warning.
   * @param value Raw token value; empty string removes the header.
   */
  function applyToken(value: string): void {
    token.value = value.trim()
    setAuthToken(token.value)
    authRequired.value = false
    dataRevision.value += 1
  }

  /**
   * Record the provenance of loaded records; `synthetic_fixture` raises the banner.
   * @param sources Source values of the rows that were just loaded.
   */
  function markSources(sources: Array<string | null | undefined>): void {
    if (sources.includes('synthetic_fixture')) syntheticSeen.value = true
  }

  /** Hide the demo banner for the rest of the browser tab session. */
  function dismissDemo(): void {
    demoDismissed.value = true
    try {
      window.sessionStorage.setItem(DEMO_DISMISS_KEY, '1')
    } catch {
      // Dismissal then only lasts in memory.
    }
  }

  onUnauthorized(() => {
    authRequired.value = true
  })

  return {
    meta,
    loading,
    error,
    activeSaveId,
    token,
    authRequired,
    syntheticSeen,
    demoDismissed,
    dataRevision,
    saves,
    capabilities,
    warnings,
    version,
    product,
    dataSources,
    activeSave,
    demoMode,
    agentLlm,
    showDemoBanner,
    hasRealScanData,
    load,
    selectSave,
    applyToken,
    markSources,
    dismissDemo,
  }
})
