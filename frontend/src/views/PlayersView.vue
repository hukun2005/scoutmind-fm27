<script setup lang="ts">
/**
 * 球员探索（V4.0-03，Premium Light Scouting Workspace）。
 *
 * 信息架构：紧凑页头 → 搜索工作区 → 筛选摘要 → 数据状态栏 → 球员结果 → 详情抽屉。
 * 所有筛选、排序与分页都由后端执行；缺失值显示“—”，不使用 Mock 或推算数据。
 */

import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import dayjs from 'dayjs'
import { asApiError, type ApiError } from '../api/client'
import { listClubs } from '../api/clubs'
import { getPlayerFacets, listPlayers } from '../api/players'
import { addWatchlistItem, deleteWatchlistItem, listWatchlist } from '../api/watchlist'
import PlayerDetailDrawer from '../components/PlayerDetailDrawer.vue'
import AppIcon from '../components/AppIcon.vue'
import { MAX_COMPARE, useCompareStore } from '../stores/compare'
import { usePlayersStore } from '../stores/players'
import { useSessionStore } from '../stores/session'
import type { Club } from '../types/clubs'
import type { PlayerFacets, PlayerFoot, PlayerSummary } from '../types/players'
import { displayText, formatInt, formatMoney, formatPercent } from '../utils/format'
import { POSITION_GROUPS, POSITION_LABELS, POSITION_OPTIONS, coverageLabel } from '../utils/labels'

const route = useRoute()
const router = useRouter()
const session = useSessionStore()
const players = usePlayersStore()
const compare = useCompareStore()

/** 列表形态；只影响展示，不改变服务端查询。 */
const viewMode = ref<'table' | 'cards'>('table')

/** 原生搜索输入框的草稿值，避免每次输入都重建组件。 */
const searchDraft = ref(players.filters.query ?? '')
const searchInput = ref<HTMLInputElement | null>(null)

const clubs = ref<Club[]>([])
const clubsError = ref<ApiError | null>(null)
const facets = ref<PlayerFacets | null>(null)
const facetsError = ref<ApiError | null>(null)

/** 关注名单总数：只取 total，不拉整页数据。 */
const watchCount = ref<number | null>(null)
const watchState = reactive<Record<number, boolean>>({})
const watchItemIds = reactive<Record<number, number>>({})
const watchPending = reactive<Record<number, boolean>>({})

/** 身价、周薪在界面上按“万”输入，发送前换算为基础单位。 */
const maxValueWan = ref<number | undefined>(undefined)
const maxWageWan = ref<number | undefined>(undefined)

const advancedOpen = ref(false)
const detailId = ref<number | null>(null)
const toast = ref<{ tone: 'success' | 'warning' | 'danger'; text: string } | null>(null)
let toastTimer: ReturnType<typeof setTimeout> | null = null

const SORT_OPTIONS = [
  { value: '-updated_at', label: '最近更新' },
  { value: '-market_value', label: '身价从高到低' },
  { value: 'market_value', label: '身价从低到高' },
  { value: '-ca', label: '当前能力从高到低' },
  { value: '-pa', label: '潜力从高到低' },
  { value: 'age', label: '年龄从小到大' },
  { value: 'name', label: '姓名 A–Z' },
]

const PAGE_SIZES = [25, 50, 100, 200]

const FOOT_OPTIONS: Array<{ value: PlayerFoot; label: string }> = [
  { value: 'left', label: '左脚' },
  { value: 'right', label: '右脚' },
  { value: 'both', label: '双脚' },
]

/** 合同到期预设：值直接是可传给后端的截止日期。 */
const contractOptions = computed(() => [
  { value: '', label: '不限' },
  { value: dayjs().add(6, 'month').format('YYYY-MM-DD'), label: '6 个月内到期' },
  { value: dayjs().add(12, 'month').format('YYYY-MM-DD'), label: '12 个月内到期' },
  { value: dayjs().add(24, 'month').format('YYYY-MM-DD'), label: '24 个月内到期' },
])

const hasActiveFilters = computed(() => Object.keys(players.filters).length > 0)

/** 存档球员总数：优先使用 facets 真实计数，其次使用存档元信息。 */
const saveTotal = computed<number | null>(
  () => facets.value?.total_players ?? session.activeSave?.player_count ?? null,
)

/** 高级筛选中当前生效的条件数量，用于按钮角标。 */
const advancedCount = computed(() => {
  const filters = players.filters
  return [
    filters.position,
    filters.club_id,
    filters.nationality,
    filters.league,
    filters.foot,
    filters.min_height,
    filters.max_height,
    filters.max_wage,
    filters.max_pa,
    filters.contract_end_before,
    filters.watchlist_only === true ? true : undefined,
  ].filter((value) => value !== undefined).length
})

const pageCount = computed(() => Math.max(1, Math.ceil(players.total / players.pageSize)))

const clubById = computed<Map<number, Club>>(() => new Map(clubs.value.map((club) => [club.club_id, club])))

/** 结果为空时区分“存档无数据”和“筛选无结果”。 */
const isEmpty = computed(() => !players.loading && !players.error && players.items.length === 0)
const showSkeleton = computed(() => players.loading && players.items.length === 0 && !players.error)

interface FilterChip {
  key: string
  label: string
  clear: () => void
}

const chips = computed<FilterChip[]>(() => {
  const filters = players.filters
  const list: FilterChip[] = []
  if (filters.query) {
    list.push({
      key: 'query',
      label: `姓名「${filters.query}」`,
      clear: () => {
        searchDraft.value = ''
        players.setFilter('query', undefined)
      },
    })
  }
  if (filters.position_group) {
    const label = POSITION_GROUPS.find((group) => group.value === filters.position_group)?.label ?? filters.position_group
    list.push({ key: 'position_group', label: `位置 ${label}`, clear: () => players.setFilter('position_group', undefined) })
  }
  if (filters.position) {
    list.push({
      key: 'position',
      label: `具体位置 ${POSITION_LABELS[filters.position] ?? filters.position}`,
      clear: () => players.setFilter('position', undefined),
    })
  }
  if (filters.min_age !== undefined || filters.max_age !== undefined) {
    list.push({
      key: 'age',
      label: `年龄 ${filters.min_age ?? '不限'}–${filters.max_age ?? '不限'}`,
      clear: () => {
        players.setFilter('min_age', undefined)
        players.setFilter('max_age', undefined)
      },
    })
  }
  if (filters.min_ca !== undefined) {
    list.push({ key: 'min_ca', label: `CA ≥ ${filters.min_ca}`, clear: () => players.setFilter('min_ca', undefined) })
  }
  if (filters.max_pa !== undefined) {
    list.push({ key: 'max_pa', label: `PA ≤ ${filters.max_pa}`, clear: () => players.setFilter('max_pa', undefined) })
  }
  if (filters.max_value !== undefined) {
    list.push({
      key: 'max_value',
      label: `身价 ≤ ${Math.round(filters.max_value / 10_000)} 万`,
      clear: () => {
        maxValueWan.value = undefined
        players.setFilter('max_value', undefined)
      },
    })
  }
  if (filters.max_wage !== undefined) {
    list.push({
      key: 'max_wage',
      label: `周薪 ≤ ${Math.round(filters.max_wage / 10_000)} 万`,
      clear: () => {
        maxWageWan.value = undefined
        players.setFilter('max_wage', undefined)
      },
    })
  }
  if (filters.nationality) {
    list.push({ key: 'nationality', label: `国籍 ${filters.nationality}`, clear: () => players.setFilter('nationality', undefined) })
  }
  if (filters.league) {
    list.push({ key: 'league', label: `联赛 ${filters.league}`, clear: () => players.setFilter('league', undefined) })
  }
  if (filters.club_id !== undefined) {
    const club = clubById.value.get(filters.club_id)
    list.push({ key: 'club_id', label: `俱乐部 ${club?.name ?? `#${filters.club_id}`}`, clear: () => players.setFilter('club_id', undefined) })
  }
  if (filters.foot) {
    const foot = FOOT_OPTIONS.find((option) => option.value === filters.foot)?.label ?? filters.foot
    list.push({ key: 'foot', label: `惯用脚 ${foot}`, clear: () => players.setFilter('foot', undefined) })
  }
  if (filters.min_height !== undefined || filters.max_height !== undefined) {
    list.push({
      key: 'height',
      label: `身高 ${filters.min_height ?? '不限'}–${filters.max_height ?? '不限'} cm`,
      clear: () => {
        players.setFilter('min_height', undefined)
        players.setFilter('max_height', undefined)
      },
    })
  }
  if (filters.contract_end_before) {
    const preset = contractOptions.value.find((option) => option.value === filters.contract_end_before)
    list.push({
      key: 'contract',
      label: preset && preset.value ? preset.label : `合同在 ${filters.contract_end_before} 前到期`,
      clear: () => players.setFilter('contract_end_before', undefined),
    })
  }
  if (filters.watchlist_only) {
    list.push({ key: 'watchlist', label: '只看关注名单', clear: () => players.setFilter('watchlist_only', undefined) })
  }
  return list
})

/** 查询签名：任一条件、分页、排序、存档或令牌变化都会重新请求。 */
const querySignature = computed(() =>
  JSON.stringify({
    filters: players.filters,
    page: players.page,
    pageSize: players.pageSize,
    sort: players.sort,
    saveId: session.activeSaveId,
    revision: session.dataRevision,
  }),
)

let reloadTimer: ReturnType<typeof setTimeout> | null = null
let firstRun = true

/** 防抖加载：输入姓名时不必每敲一个字就请求一次；过期响应由 store 序号丢弃。 */
function scheduleReload(): void {
  if (reloadTimer) clearTimeout(reloadTimer)
  const delay = firstRun ? 0 : 200
  firstRun = false
  reloadTimer = setTimeout(() => {
    void players.load(session.activeSaveId)
  }, delay)
}

/** 轻量反馈，避免深色 Element Plus 消息破坏浅色工作台。 */
function showToast(tone: 'success' | 'warning' | 'danger', text: string): void {
  toast.value = { tone, text }
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => {
    toast.value = null
  }, 2400)
}

async function loadClubs(): Promise<void> {
  clubsError.value = null
  try {
    const response = await listClubs()
    clubs.value = response.items
  } catch (caught) {
    clubsError.value = asApiError(caught)
    clubs.value = []
  }
}

async function loadFacets(): Promise<void> {
  facetsError.value = null
  try {
    const response = await getPlayerFacets(session.activeSaveId ?? undefined)
    facets.value = {
      total_players: typeof response?.total_players === 'number' ? response.total_players : null,
      nationalities: Array.isArray(response?.nationalities) ? response.nationalities : [],
      leagues: Array.isArray(response?.leagues) ? response.leagues : [],
    }
  } catch (caught) {
    facetsError.value = asApiError(caught)
    facets.value = null
  }
}

async function loadWatchCount(): Promise<void> {
  try {
    const response = await listPlayers({
      save_id: session.activeSaveId ?? undefined,
      watchlist_only: true,
      limit: 1,
      offset: 0,
    })
    watchCount.value = response.total ?? 0
  } catch {
    watchCount.value = null
  }
}

/** 列表返回后同步关注状态；只采用后端真实 is_watched。 */
watch(
  () => players.items,
  (items) => {
    for (const item of items) {
      if (item.is_watched !== null) watchState[item.instance_id] = item.is_watched
    }
  },
)

function isWatched(id: number): boolean {
  return watchState[id] === true
}

function isInCompare(id: number): boolean {
  return compare.ids.includes(id)
}

async function toggleWatch(id: number): Promise<void> {
  if (watchPending[id]) return
  watchPending[id] = true
  const was = isWatched(id)
  try {
    if (was) {
      let itemId: number | undefined = watchItemIds[id]
      if (!itemId) {
        const response = await listWatchlist({ saveId: session.activeSaveId ?? undefined })
        itemId = response.items.find((item) => item.instance_id === id)?.id
      }
      if (!itemId) throw new Error('关注记录已不存在')
      await deleteWatchlistItem(itemId)
      delete watchItemIds[id]
      watchState[id] = false
      if (watchCount.value !== null) watchCount.value = Math.max(0, watchCount.value - 1)
      showToast('success', '已取消关注')
    } else {
      await addWatchlistItem({ instance_id: id })
      watchState[id] = true
      watchCount.value = (watchCount.value ?? 0) + 1
      showToast('success', '已加入关注名单')
    }
  } catch (caught) {
    watchState[id] = was
    showToast('danger', `关注状态更新失败：${asApiError(caught).message}`)
  } finally {
    delete watchPending[id]
  }
}

function toggleCompare(row: Pick<PlayerSummary, 'instance_id' | 'name'>): void {
  compare.ensureSave(session.activeSaveId)
  if (isInCompare(row.instance_id)) {
    compare.remove(row.instance_id)
    showToast('warning', `已移出对比：${displayText(row.name)}`)
    return
  }
  const outcome = compare.add(row.instance_id)
  if (outcome === 'added') showToast('success', `已加入对比：${displayText(row.name)}（${compare.count}/${MAX_COMPARE}）`)
  else if (outcome === 'full') showToast('warning', `对比最多 ${MAX_COMPARE} 名球员`)
  else showToast('warning', '该球员已在对比中')
}

function openDetail(row: PlayerSummary): void {
  detailId.value = row.instance_id
}

/** 列表中的位置只显示中文；真实存档可能是多位置字符串，取第一个位置。 */
function shortPosition(position: string | null | undefined): string {
  if (!position) return '—'
  const first = position.split(',')[0]?.trim() ?? ''
  if (!first) return '—'
  return POSITION_LABELS[first.toUpperCase()] ?? first
}

const detailIndex = computed(() => players.items.findIndex((row) => row.instance_id === detailId.value))
const hasPrev = computed(() => detailIndex.value > 0)
const hasNext = computed(() => detailIndex.value >= 0 && detailIndex.value < players.items.length - 1)

function stepDetail(delta: number): void {
  const next = players.items[detailIndex.value + delta]
  if (next) detailId.value = next.instance_id
}

function toggleCompareById(id: number): void {
  const row = players.items.find((item) => item.instance_id === id)
  if (row) toggleCompare(row)
}

/** 位置组用胶囊按钮切换：再次点击同一组即取消。 */
function togglePositionGroup(value: string): void {
  players.setFilter('position_group', players.filters.position_group === value ? undefined : value)
}

function onQueryInput(event: Event): void {
  const value = (event.target as HTMLInputElement).value
  searchDraft.value = value
  players.setFilter('query', value.trim() === '' ? undefined : value)
}

function clearQuery(): void {
  searchDraft.value = ''
  players.setFilter('query', undefined)
  searchInput.value?.focus()
}

/** 数字输入：空字符串与非法值都表示“不筛选”，不发送 0。 */
function toNumber(raw: string): number | undefined {
  if (raw.trim() === '') return undefined
  const parsed = Number(raw)
  return Number.isFinite(parsed) ? parsed : undefined
}

function onMaxValueInput(event: Event): void {
  const raw = toNumber((event.target as HTMLInputElement).value)
  maxValueWan.value = raw
  players.setFilter('max_value', raw === undefined ? undefined : Math.round(raw * 10_000))
}

function onMaxWageInput(event: Event): void {
  const raw = toNumber((event.target as HTMLInputElement).value)
  maxWageWan.value = raw
  players.setFilter('max_wage', raw === undefined ? undefined : Math.round(raw * 10_000))
}

function onContractChange(event: Event): void {
  const value = (event.target as HTMLSelectElement).value
  players.setFilter('contract_end_before', value === '' ? undefined : value)
}

function resetFilters(): void {
  maxValueWan.value = undefined
  maxWageWan.value = undefined
  searchDraft.value = ''
  players.reset()
}

function focusSearch(): void {
  searchInput.value?.focus()
}

function applySort(value: string): void {
  players.sort = value
  players.page = 1
}

function sortBy(field: string): void {
  const current = players.sort
  if (current === `-${field}`) players.sort = field
  else if (current === field) players.sort = `-${field}`
  else players.sort = field === 'name' ? field : `-${field}`
  players.page = 1
}

function sortMark(field: string): string {
  if (players.sort === `-${field}`) return '↓'
  if (players.sort === field) return '↑'
  return ''
}

function goSync(): void {
  void router.push('/data')
}

function goCompare(): void {
  void router.push('/compare')
}

/** 读取 URL 带来的筛选，只应用一次。 */
function applyQueryFilters(): void {
  const { position_group: group, position, club_id: clubId, query } = route.query
  if (typeof position === 'string' && position) players.setFilter('position', position.toUpperCase())
  if (typeof group === 'string' && group) players.setFilter('position_group', group.toUpperCase())
  if (typeof clubId === 'string' && clubId) {
    const parsed = Number.parseInt(clubId, 10)
    if (Number.isInteger(parsed) && parsed > 0) players.setFilter('club_id', parsed)
  }
  if (typeof query === 'string' && query) {
    players.setFilter('query', query)
    searchDraft.value = query
  }
}

applyQueryFilters()

watch(querySignature, scheduleReload, { immediate: true })

watch(
  [() => session.activeSaveId, () => session.dataRevision],
  () => {
    compare.ensureSave(session.activeSaveId)
    maxValueWan.value = undefined
    maxWageWan.value = undefined
    searchDraft.value = players.filters.query ?? ''
    void loadFacets()
    void loadWatchCount()
  },
  { immediate: true },
)

watch(advancedOpen, (open) => {
  if (!open) return
  if (clubs.value.length === 0) void loadClubs()
})

onBeforeUnmount(() => {
  if (reloadTimer) clearTimeout(reloadTimer)
  if (toastTimer) clearTimeout(toastTimer)
})

void loadClubs()
</script>

<template>
  <div class="player-workspace">
    <header class="pw-head">
      <div class="pw-head__text">
        <h1 class="pw-title">球员探索</h1>
        <p class="pw-desc">
          在{{ session.activeSave?.name ?? '当前存档' }}中搜索、筛选并评估球员；列表由服务端分页，所有数值来自真实存档。
        </p>
      </div>
      <div class="pw-head__actions">
        <button type="button" class="pw-btn" @click="goCompare">
          球员对比（{{ compare.count }}/{{ MAX_COMPARE }}）
        </button>
        <button type="button" class="pw-btn" :disabled="players.loading" @click="players.load(session.activeSaveId)">
          {{ players.loading ? '刷新中…' : '刷新' }}
        </button>
      </div>
    </header>

    <section class="pw-search" aria-label="球员搜索与常用筛选">
      <div class="pw-search__row">
        <label class="pw-search__box">
          <span class="pw-search__icon" aria-hidden="true"><AppIcon name="search" :size="16" /></span>
          <input
            ref="searchInput"
            :value="searchDraft"
            type="search"
            placeholder="输入球员姓名"
            aria-label="按球员姓名搜索"
            @input="onQueryInput"
          />
          <button v-if="searchDraft" type="button" class="pw-search__clear" aria-label="清空搜索" title="清空搜索" @click="clearQuery">
            <AppIcon name="close" :size="12" />
          </button>
        </label>

        <div class="pw-quick" role="group" aria-label="位置组">
          <button
            v-for="group in POSITION_GROUPS"
            :key="group.value"
            type="button"
            class="pw-pill"
            :class="{ 'pw-pill--active': players.filters.position_group === group.value }"
            :aria-pressed="players.filters.position_group === group.value"
            @click="togglePositionGroup(group.value)"
          >
            {{ group.label }}
          </button>
        </div>

        <label class="pw-mini">
          <span>年龄</span>
          <input
            :value="players.filters.min_age ?? ''"
            type="number"
            min="10"
            max="60"
            placeholder="最小"
            aria-label="最小年龄"
            @change="players.setFilter('min_age', toNumber(($event.target as HTMLInputElement).value))"
          />
          <i aria-hidden="true">–</i>
          <input
            :value="players.filters.max_age ?? ''"
            type="number"
            min="10"
            max="60"
            placeholder="最大"
            aria-label="最大年龄"
            @change="players.setFilter('max_age', toNumber(($event.target as HTMLInputElement).value))"
          />
        </label>

        <label class="pw-mini">
          <span>CA ≥</span>
          <input
            :value="players.filters.min_ca ?? ''"
            type="number"
            min="0"
            max="400"
            placeholder="不限"
            aria-label="当前能力下限"
            @change="players.setFilter('min_ca', toNumber(($event.target as HTMLInputElement).value))"
          />
        </label>

        <label class="pw-mini">
          <span>身价 ≤</span>
          <input
            :value="maxValueWan ?? ''"
            type="number"
            min="0"
            step="100"
            placeholder="万"
            aria-label="身价上限，单位万"
            @change="onMaxValueInput"
          />
          <i aria-hidden="true">万</i>
        </label>

        <button type="button" class="pw-btn pw-btn--primary" @click="advancedOpen = true">
          高级筛选
          <span v-if="advancedCount" class="pw-btn__badge pw-btn__badge--on">{{ advancedCount }}</span>
        </button>
      </div>

      <div v-if="chips.length > 0" class="pw-chips" aria-label="当前筛选条件">
        <span v-for="chip in chips" :key="chip.key" class="pw-chip">
          {{ chip.label }}
          <button type="button" :aria-label="`清除 ${chip.label}`" @click="chip.clear()">×</button>
        </span>
        <button type="button" class="pw-chips__clear" @click="resetFilters">清空全部</button>
      </div>
    </section>

    <div class="pw-status" role="status">
      <span class="pw-status__item">
        存档球员
        <strong>{{ saveTotal === null ? '—' : formatInt(saveTotal) }}</strong>
      </span>
      <span class="pw-status__item">
        当前结果
        <strong>{{ showSkeleton ? '…' : formatInt(players.total) }}</strong>
      </span>
      <span class="pw-status__item">
        已关注
        <strong>{{ watchCount === null ? '—' : formatInt(watchCount) }}</strong>
      </span>
      <span class="pw-status__spacer" />
      <span class="pw-status__meta">
        <template v-if="players.loading && players.items.length > 0">正在更新结果…</template>
        <template v-else>第 {{ players.page }} / {{ pageCount }} 页 · 每页 {{ players.pageSize }} 名</template>
      </span>
    </div>

    <section class="pw-results" aria-label="球员结果">
      <div class="pw-results__bar">
        <div class="pw-results__count">
          共 <strong>{{ formatInt(players.total) }}</strong> 名球员
          <span v-if="players.coverage.ca !== undefined" class="pw-results__coverage">
            CA 覆盖 {{ formatPercent(players.coverage.ca) }}
          </span>
        </div>
        <div class="pw-results__tools">
          <label class="pw-sort">
            <span>排序</span>
            <select :value="players.sort" aria-label="排序方式" @change="applySort(($event.target as HTMLSelectElement).value)">
              <option v-for="option in SORT_OPTIONS" :key="option.value" :value="option.value">{{ option.label }}</option>
            </select>
          </label>
          <div class="pw-seg" role="group" aria-label="列表显示方式">
            <button
              type="button"
              :class="{ 'pw-seg__btn--active': viewMode === 'table' }"
              class="pw-seg__btn"
              :aria-pressed="viewMode === 'table'"
              @click="viewMode = 'table'"
            >
              列表
            </button>
            <button
              type="button"
              :class="{ 'pw-seg__btn--active': viewMode === 'cards' }"
              class="pw-seg__btn"
              :aria-pressed="viewMode === 'cards'"
              @click="viewMode = 'cards'"
            >
              卡片
            </button>
          </div>
        </div>
      </div>

      <div v-if="players.error && players.items.length === 0" class="pw-state">
        <p class="pw-state__title">球员列表加载失败</p>
        <p class="pw-state__text">{{ players.error.message }}</p>
        <div class="pw-state__actions">
          <button type="button" class="pw-btn pw-btn--primary" @click="players.load(session.activeSaveId)">重试</button>
          <button type="button" class="pw-btn" @click="goSync">检查数据同步</button>
        </div>
      </div>

      <div v-else-if="showSkeleton" class="pw-skeleton" aria-busy="true" aria-label="正在加载球员">
        <div v-for="index in 8" :key="index" class="pw-skeleton__row">
          <span class="pw-skeleton__avatar" />
          <span class="pw-skeleton__line pw-skeleton__line--wide" />
          <span class="pw-skeleton__line" />
          <span class="pw-skeleton__line" />
        </div>
      </div>

      <div v-else-if="isEmpty" class="pw-state">
        <template v-if="!hasActiveFilters">
          <p class="pw-state__title">还没有可探索的球员</p>
          <p class="pw-state__text">同步 FM27 游戏数据后，即可开始搜索和分析球员。</p>
          <div class="pw-state__actions">
            <button type="button" class="pw-btn pw-btn--primary" @click="goSync">同步游戏数据</button>
          </div>
        </template>
        <template v-else>
          <p class="pw-state__title">没有找到符合条件的球员</p>
          <p class="pw-state__text">当前条件没有匹配结果，可以放宽条件或清空筛选后重新查看。</p>
          <div class="pw-state__actions">
            <button type="button" class="pw-btn pw-btn--primary" @click="resetFilters">清空筛选条件</button>
            <button type="button" class="pw-btn" @click="focusSearch">修改搜索条件</button>
          </div>
        </template>
      </div>

      <template v-else>
        <div v-if="viewMode === 'table'" class="pw-table">
          <div class="pw-grid pw-table__head" role="row">
            <button type="button" class="pw-th pw-th--name" @click="sortBy('name')">
              球员 <i>{{ sortMark('name') }}</i>
            </button>
            <span class="pw-th">位置</span>
            <button type="button" class="pw-th pw-th--num pw-col--age" @click="sortBy('age')">年龄 <i>{{ sortMark('age') }}</i></button>
            <span class="pw-th pw-col--club">俱乐部 / 联赛</span>
            <button type="button" class="pw-th pw-th--num" @click="sortBy('ca')">CA <i>{{ sortMark('ca') }}</i></button>
            <button type="button" class="pw-th pw-th--num pw-col--pa" @click="sortBy('pa')">PA <i>{{ sortMark('pa') }}</i></button>
            <button type="button" class="pw-th pw-th--num" @click="sortBy('market_value')">
              身价 <i>{{ sortMark('market_value') }}</i>
            </button>
            <span class="pw-th pw-col--contract">合同</span>
            <span class="pw-th pw-th--ops">操作</span>
          </div>

          <div class="pw-table__body">
            <div
              v-for="row in players.items"
              :key="row.instance_id"
              class="pw-grid pw-row"
              :class="{ 'pw-row--open': detailId === row.instance_id }"
              role="row"
              tabindex="0"
              @click="openDetail(row)"
              @keydown.enter="openDetail(row)"
            >
              <div class="pw-cell pw-cell--player">
                <span class="pw-avatar" aria-hidden="true">{{ (row.name || '?').slice(0, 2).toUpperCase() }}</span>
                <div class="pw-cell__stack">
                  <button type="button" class="pw-name" @click.stop="openDetail(row)">{{ displayText(row.name) }}</button>
                  <span class="pw-sub">{{ displayText(row.nationality) }}</span>
                </div>
              </div>
              <div class="pw-cell">
                <span class="pw-pos">{{ shortPosition(row.position) }}</span>
              </div>
              <div class="pw-cell pw-cell--num pw-col--age">{{ row.age ?? '—' }}</div>
              <div class="pw-cell pw-col--club">
                <div class="pw-cell__stack">
                  <span class="pw-ellipsis" :title="displayText(row.club)">{{ displayText(row.club) }}</span>
                  <span class="pw-sub pw-ellipsis">{{ row.club_id ? clubById.get(row.club_id)?.league ?? '' : '' }}</span>
                </div>
              </div>
              <div class="pw-cell pw-cell--num pw-cell--strong">{{ formatInt(row.ca) }}</div>
              <div class="pw-cell pw-cell--num pw-col--pa">{{ formatInt(row.pa) }}</div>
              <div class="pw-cell pw-cell--num pw-cell--money" :title="formatMoney(row.market_value)">
                {{ formatMoney(row.market_value) }}
              </div>
              <div class="pw-cell pw-col--contract">
                <span v-if="row.contract_end" :class="dayjs(row.contract_end).diff(dayjs(), 'month') < 12 ? 'pw-contract--warn' : ''">
                  {{ dayjs(row.contract_end).format('YYYY') }} 年
                </span>
                <span v-else class="pw-sub">—</span>
              </div>
              <div class="pw-cell pw-cell--ops" @click.stop>
                <button
                  type="button"
                  class="pw-icon-btn"
                  :class="{ 'pw-icon-btn--on': isWatched(row.instance_id) }"
                  :aria-label="isWatched(row.instance_id) ? `取消关注 ${row.name}` : `关注 ${row.name}`"
                  :title="isWatched(row.instance_id) ? '取消关注' : '关注'"
                  :disabled="watchPending[row.instance_id]"
                  @click="toggleWatch(row.instance_id)"
                >
                  <AppIcon name="star" :size="15" :filled="isWatched(row.instance_id)" />
                </button>
                <button
                  type="button"
                  class="pw-compare-btn"
                  :class="{ 'pw-compare-btn--on': isInCompare(row.instance_id) }"
                  :aria-pressed="isInCompare(row.instance_id)"
                  @click="toggleCompare(row)"
                >
                  {{ isInCompare(row.instance_id) ? '已选' : '对比' }}
                </button>
                <button type="button" class="pw-icon-btn" aria-label="查看球员档案" title="查看档案" @click="openDetail(row)">
                  <AppIcon name="chevron-right" :size="15" />
                </button>
              </div>
            </div>
          </div>
        </div>

        <div v-else class="pw-cards">
          <article
            v-for="row in players.items"
            :key="row.instance_id"
            class="pw-card"
            :class="{ 'pw-row--open': detailId === row.instance_id }"
          >
            <header class="pw-card__head">
              <span class="pw-avatar" aria-hidden="true">{{ (row.name || '?').slice(0, 2).toUpperCase() }}</span>
              <div class="pw-cell__stack">
                <button type="button" class="pw-name" @click="openDetail(row)">{{ displayText(row.name) }}</button>
                <span class="pw-sub">
                  {{ row.age === null ? '年龄未知' : `${row.age} 岁` }} · {{ displayText(row.nationality) }}
                </span>
              </div>
              <span class="pw-pos">{{ shortPosition(row.position) }}</span>
            </header>
            <p class="pw-card__club" :title="displayText(row.club)">
              {{ displayText(row.club) }}
              <span class="pw-sub">{{ row.club_id ? clubById.get(row.club_id)?.league ?? '' : '' }}</span>
            </p>
            <dl class="pw-card__stats">
              <div><dt>CA</dt><dd>{{ formatInt(row.ca) }}</dd></div>
              <div><dt>PA</dt><dd>{{ formatInt(row.pa) }}</dd></div>
              <div><dt>身价</dt><dd>{{ formatMoney(row.market_value) }}</dd></div>
            </dl>
            <footer class="pw-card__actions">
              <button
                type="button"
                class="pw-icon-btn pw-icon-btn--label"
                :class="{ 'pw-icon-btn--on': isWatched(row.instance_id) }"
                :aria-label="isWatched(row.instance_id) ? `取消关注 ${row.name}` : `关注 ${row.name}`"
                :disabled="watchPending[row.instance_id]"
                @click="toggleWatch(row.instance_id)"
              >
                <AppIcon name="star" :size="14" :filled="isWatched(row.instance_id)" />
                {{ isWatched(row.instance_id) ? '已关注' : '关注' }}
              </button>
              <button
                type="button"
                class="pw-compare-btn"
                :class="{ 'pw-compare-btn--on': isInCompare(row.instance_id) }"
                @click="toggleCompare(row)"
              >
                {{ isInCompare(row.instance_id) ? '已加入对比' : '加入对比' }}
              </button>
              <button type="button" class="pw-btn pw-btn--small" @click="openDetail(row)">查看档案</button>
            </footer>
          </article>
        </div>

        <footer class="pw-pager">
          <label class="pw-pager__size">
            每页
            <select :value="players.pageSize" aria-label="每页数量" @change="players.setPageSize(Number(($event.target as HTMLSelectElement).value))">
              <option v-for="size in PAGE_SIZES" :key="size" :value="size">{{ size }}</option>
            </select>
            名
          </label>
          <div class="pw-pager__nav">
            <button type="button" class="pw-btn pw-btn--small" :disabled="players.page <= 1" @click="players.setPage(players.page - 1)">
              上一页
            </button>
            <span class="pw-pager__label">第 {{ players.page }} / {{ pageCount }} 页</span>
            <button
              type="button"
              class="pw-btn pw-btn--small"
              :disabled="players.page >= pageCount"
              @click="players.setPage(players.page + 1)"
            >
              下一页
            </button>
          </div>
        </footer>
      </template>
    </section>

    <Transition name="pw-toast">
      <div v-if="toast" class="pw-toast" :class="`pw-toast--${toast.tone}`" role="status">{{ toast.text }}</div>
    </Transition>

    <Teleport to="body">
      <Transition name="pw-adv">
        <div v-if="advancedOpen" class="pw-adv">
          <div class="pw-adv__scrim" @click="advancedOpen = false" />
          <aside class="pw-adv__panel" role="dialog" aria-modal="true" aria-label="高级筛选">
            <header class="pw-adv__head">
              <div>
                <h2>高级筛选</h2>
                <p>只列出存档真实存在的字段；修改后自动查询。</p>
              </div>
              <button type="button" class="pw-icon-btn" aria-label="关闭高级筛选" title="关闭" @click="advancedOpen = false">
                <AppIcon name="close" :size="14" />
              </button>
            </header>

            <div class="pw-adv__body">
              <label class="pw-field">
                <span>国籍</span>
                <select
                  :value="players.filters.nationality ?? ''"
                  :disabled="(facets?.nationalities.length ?? 0) === 0"
                  @change="players.setFilter('nationality', ($event.target as HTMLSelectElement).value || undefined)"
                >
                  <option value="">全部国籍</option>
                  <option v-for="item in facets?.nationalities ?? []" :key="item.value" :value="item.value">
                    {{ item.value }}（{{ item.count }}）
                  </option>
                </select>
                <small v-if="facetsError" class="pw-field__error">国籍数据加载失败：{{ facetsError.message }}</small>
                <small v-else-if="facets && facets.nationalities.length === 0" class="pw-field__hint">存档未提供国籍数据</small>
              </label>

              <label class="pw-field">
                <span>联赛</span>
                <select
                  :value="players.filters.league ?? ''"
                  :disabled="(facets?.leagues.length ?? 0) === 0"
                  @change="players.setFilter('league', ($event.target as HTMLSelectElement).value || undefined)"
                >
                  <option value="">全部联赛</option>
                  <option v-for="item in facets?.leagues ?? []" :key="item.value" :value="item.value">
                    {{ item.value }}（{{ item.count }}）
                  </option>
                </select>
                <small v-if="facets && facets.leagues.length === 0" class="pw-field__hint">存档未提供联赛数据</small>
              </label>

              <label class="pw-field">
                <span>俱乐部</span>
                <select
                  :value="players.filters.club_id ?? ''"
                  @change="players.setFilter('club_id', ($event.target as HTMLSelectElement).value ? Number(($event.target as HTMLSelectElement).value) : undefined)"
                >
                  <option value="">全部俱乐部</option>
                  <option v-for="club in clubs" :key="club.club_id" :value="club.club_id">{{ club.name }}</option>
                </select>
                <small v-if="clubsError" class="pw-field__error">俱乐部加载失败：{{ clubsError.message }}</small>
              </label>

              <label class="pw-field">
                <span>具体位置</span>
                <select
                  :value="players.filters.position ?? ''"
                  @change="players.setFilter('position', ($event.target as HTMLSelectElement).value || undefined)"
                >
                  <option value="">全部位置</option>
                  <option v-for="option in POSITION_OPTIONS" :key="option.value" :value="option.value">{{ option.label }}</option>
                </select>
              </label>

              <label class="pw-field">
                <span>惯用脚</span>
                <select
                  :value="players.filters.foot ?? ''"
                  @change="players.setFilter('foot', (($event.target as HTMLSelectElement).value || undefined) as PlayerFoot | undefined)"
                >
                  <option value="">不限</option>
                  <option v-for="option in FOOT_OPTIONS" :key="option.value" :value="option.value">{{ option.label }}</option>
                </select>
              </label>

              <div class="pw-field">
                <span>身高（cm）</span>
                <div class="pw-field__pair">
                  <input
                    :value="players.filters.min_height ?? ''"
                    type="number"
                    min="120"
                    max="250"
                    placeholder="最低"
                    aria-label="最低身高"
                    @change="players.setFilter('min_height', toNumber(($event.target as HTMLInputElement).value))"
                  />
                  <i>–</i>
                  <input
                    :value="players.filters.max_height ?? ''"
                    type="number"
                    min="120"
                    max="250"
                    placeholder="最高"
                    aria-label="最高身高"
                    @change="players.setFilter('max_height', toNumber(($event.target as HTMLInputElement).value))"
                  />
                </div>
              </div>

              <div class="pw-field">
                <span>年龄（岁）</span>
                <div class="pw-field__pair">
                  <input
                    :value="players.filters.min_age ?? ''"
                    type="number"
                    min="10"
                    max="60"
                    placeholder="最小"
                    aria-label="高级筛选最小年龄"
                    @change="players.setFilter('min_age', toNumber(($event.target as HTMLInputElement).value))"
                  />
                  <i>–</i>
                  <input
                    :value="players.filters.max_age ?? ''"
                    type="number"
                    min="10"
                    max="60"
                    placeholder="最大"
                    aria-label="高级筛选最大年龄"
                    @change="players.setFilter('max_age', toNumber(($event.target as HTMLInputElement).value))"
                  />
                </div>
              </div>

              <label class="pw-field">
                <span>潜力上限（PA）</span>
                <input
                  :value="players.filters.max_pa ?? ''"
                  type="number"
                  min="0"
                  max="400"
                  placeholder="不限"
                  aria-label="潜力上限"
                  @change="players.setFilter('max_pa', toNumber(($event.target as HTMLInputElement).value))"
                />
              </label>

              <label class="pw-field">
                <span>周薪上限（万）</span>
                <input
                  :value="maxWageWan ?? ''"
                  type="number"
                  min="0"
                  step="1"
                  placeholder="不限"
                  aria-label="周薪上限，单位万"
                  @change="onMaxWageInput"
                />
              </label>

              <label class="pw-field">
                <span>合同到期</span>
                <select :value="players.filters.contract_end_before ?? ''" @change="onContractChange">
                  <option v-for="option in contractOptions" :key="option.value || 'any'" :value="option.value">
                    {{ option.label }}
                  </option>
                </select>
              </label>

              <label class="pw-field pw-field--switch">
                <span>只看关注名单</span>
                <input
                  type="checkbox"
                  :checked="players.filters.watchlist_only === true"
                  @change="players.setFilter('watchlist_only', ($event.target as HTMLInputElement).checked ? true : undefined)"
                />
              </label>

              <div v-if="Object.keys(players.coverage).length > 0" class="pw-field pw-field--wide">
                <span>数据完整度</span>
                <div class="pw-coverage">
                  <span v-for="(value, key) in players.coverage" :key="key">{{ coverageLabel(key) }} {{ formatPercent(value) }}</span>
                </div>
              </div>
            </div>

            <footer class="pw-adv__foot">
              <button type="button" class="pw-btn" @click="resetFilters">清空全部条件</button>
              <button type="button" class="pw-btn pw-btn--primary" @click="advancedOpen = false">查看 {{ formatInt(players.total) }} 个结果</button>
            </footer>
          </aside>
        </div>
      </Transition>
    </Teleport>

    <PlayerDetailDrawer
      :instance-id="detailId"
      :watched="detailId !== null && isWatched(detailId)"
      :watch-pending="detailId !== null && watchPending[detailId] === true"
      :compare-active="detailId !== null && isInCompare(detailId)"
      :has-prev="hasPrev"
      :has-next="hasNext"
      @close="detailId = null"
      @toggle-watch="detailId !== null && toggleWatch(detailId)"
      @toggle-compare="detailId !== null && toggleCompareById(detailId)"
      @prev="stepDetail(-1)"
      @next="stepDetail(1)"
    />
  </div>
</template>

<style scoped>
.player-workspace {
  /* Premium Light：与全局浅色 Token 对齐，避免页面自成一套配色。 */
  --pl-bg: var(--sm-bg-primary);
  --pl-surface: var(--sm-surface);
  --pl-surface-2: var(--sm-surface-2);
  --pl-text: var(--sm-text-primary);
  --pl-text-2: var(--sm-text-secondary);
  --pl-text-3: var(--sm-text-tertiary);
  --pl-primary: var(--sm-accent-blue);
  --pl-primary-weak: var(--sm-accent-weak);
  --pl-success: var(--sm-success);
  --pl-warn: var(--sm-warn);
  --pl-danger: var(--sm-danger);
  --pl-border: var(--sm-border);
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: calc(100vh - var(--sm-topbar-height) - 2 * var(--sm-space-5));
  padding: 22px 24px 28px;
  margin: calc(-1 * var(--sm-space-5));
  border-radius: 18px;
  background: var(--pl-bg);
  color: var(--pl-text);
  font-family: var(--sm-font-sans);
  color-scheme: light;
}

/* 镜像覆盖：内容区原有内边距在外侧，这里用负边距铺满并重新排版。 */
.player-workspace::before {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: inherit;
  border: 1px solid var(--sm-border-subtle);
  pointer-events: none;
}

.pw-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.pw-title {
  margin: 0;
  font-size: 24px;
  font-weight: 700;
  letter-spacing: -0.02em;
  line-height: 1.2;
}

.pw-desc {
  margin: 4px 0 0;
  color: var(--pl-text-2);
  font-size: 13px;
}

.pw-head__actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.pw-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 34px;
  padding: 0 14px;
  border: 1px solid var(--pl-border);
  border-radius: 9px;
  background: var(--pl-surface);
  color: var(--pl-text);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: border-color 120ms ease, background-color 120ms ease;
}

.pw-btn:hover:not(:disabled) {
  border-color: var(--sm-border-strong);
  background: var(--sm-surface);
}

.pw-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.pw-btn--primary {
  border-color: var(--sm-accent-blue);
  background: var(--sm-accent-blue);
  color: #fff;
}

.pw-btn--primary:hover:not(:disabled) {
  background: var(--sm-accent-hover);
}

.pw-btn--small {
  height: 30px;
  padding: 0 10px;
  font-size: 12px;
}

.pw-btn__badge {
  padding: 1px 6px;
  border-radius: 999px;
  background: var(--pl-surface-2);
  color: var(--pl-text-2);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.pw-btn__badge--on {
  background: rgba(49, 95, 206, 0.12);
  color: var(--sm-accent-blue);
}

.pw-search {
  padding: 12px;
  border: 1px solid var(--pl-border);
  border-radius: 14px;
  background: var(--pl-surface);
  box-shadow: 0 1px 2px rgba(23, 35, 52, 0.04);
}

.pw-search__row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.pw-search__box {
  position: relative;
  display: flex;
  align-items: center;
  flex: 1 1 300px;
  min-width: 220px;
  height: 38px;
  padding: 0 10px;
  border: 1px solid var(--pl-border);
  border-radius: 10px;
  background: var(--sm-surface);
}

.pw-search__box:focus-within {
  border-color: rgba(49, 95, 206, 0.45);
  box-shadow: 0 0 0 3px rgba(49, 95, 206, 0.12);
}

.pw-search__icon {
  color: var(--pl-text-3);
  font-size: 16px;
}

.pw-search__box input {
  flex: 1 1 auto;
  min-width: 0;
  height: 100%;
  padding: 0 8px;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--pl-text);
  font: inherit;
  font-size: 13px;
}

.pw-search__box input::placeholder {
  color: var(--pl-text-3);
}

.pw-search__clear {
  width: 22px;
  height: 22px;
  border: 0;
  border-radius: 50%;
  background: var(--pl-surface-2);
  color: var(--pl-text-2);
  font-size: 14px;
  line-height: 1;
  cursor: pointer;
}

.pw-quick {
  display: inline-flex;
  gap: 4px;
  padding: 3px;
  border: 1px solid var(--pl-border);
  border-radius: 10px;
  background: var(--pl-surface-2);
}

.pw-pill {
  height: 28px;
  padding: 0 10px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--pl-text-2);
  font-size: 12px;
  cursor: pointer;
}

.pw-pill:hover {
  color: var(--pl-text);
}

.pw-pill--active {
  background: var(--pl-surface);
  color: var(--sm-accent-blue);
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(23, 35, 52, 0.1);
}

.pw-mini {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 38px;
  padding: 0 10px;
  border: 1px solid var(--pl-border);
  border-radius: 10px;
  background: var(--pl-surface);
  color: var(--pl-text-2);
  font-size: 12px;
}

.pw-mini span {
  white-space: nowrap;
}

.pw-mini i {
  color: var(--pl-text-3);
  font-style: normal;
}

.pw-mini input {
  width: 44px;
  height: 26px;
  padding: 0 4px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: var(--pl-surface-2);
  color: var(--pl-text);
  font: inherit;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  text-align: center;
}

.pw-mini input:focus {
  outline: 0;
  border-color: rgba(49, 95, 206, 0.45);
  background: #fff;
}

.pw-chips {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed var(--pl-border);
}

.pw-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 26px;
  padding: 0 4px 0 9px;
  border: 1px solid rgba(49, 95, 206, 0.2);
  border-radius: 999px;
  background: var(--pl-primary-weak);
  color: var(--sm-accent-blue);
  font-size: 12px;
}

.pw-chip button {
  display: grid;
  place-items: center;
  width: 18px;
  height: 18px;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: inherit;
  font-size: 13px;
  line-height: 1;
  cursor: pointer;
}

.pw-chip button:hover {
  background: rgba(37, 99, 235, 0.14);
}

.pw-chips__clear {
  padding: 0 6px;
  border: 0;
  background: none;
  color: var(--pl-text-2);
  font-size: 12px;
  cursor: pointer;
  text-decoration: underline;
}

.pw-status {
  display: flex;
  align-items: center;
  gap: 18px;
  min-height: 34px;
  padding: 0 14px;
  border: 1px solid var(--pl-border);
  border-radius: 10px;
  background: var(--pl-surface);
  color: var(--pl-text-2);
  font-size: 12px;
}

.pw-status__item strong {
  margin-left: 6px;
  color: var(--pl-text);
  font-size: 14px;
  font-variant-numeric: tabular-nums;
}

.pw-status__spacer {
  flex: 1 1 auto;
}

.pw-status__meta {
  color: var(--pl-text-3);
}

.pw-results {
  display: flex;
  flex-direction: column;
  min-height: 320px;
  border: 1px solid var(--pl-border);
  border-radius: 14px;
  background: var(--pl-surface);
  box-shadow: 0 1px 2px rgba(23, 35, 52, 0.04);
  overflow: hidden;
}

.pw-results__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 10px 14px;
  border-bottom: 1px solid var(--pl-border);
}

.pw-results__count {
  color: var(--pl-text-2);
  font-size: 12px;
}

.pw-results__count strong {
  color: var(--pl-text);
  font-size: 15px;
  font-variant-numeric: tabular-nums;
}

.pw-results__coverage {
  margin-left: 10px;
  color: var(--pl-text-3);
}

.pw-results__tools {
  display: flex;
  align-items: center;
  gap: 10px;
}

.pw-sort {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--pl-text-3);
  font-size: 12px;
}

.pw-sort select,
.pw-pager__size select,
.pw-field select {
  height: 30px;
  padding: 0 26px 0 8px;
  border: 1px solid var(--pl-border);
  border-radius: 8px;
  background: var(--pl-surface)
    url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'%3E%3Cpath d='M1 1l4 4 4-4' fill='none' stroke='%2368778a' stroke-width='1.5' stroke-linecap='round'/%3E%3C/svg%3E")
    no-repeat right 8px center;
  color: var(--pl-text);
  font: inherit;
  font-size: 12px;
  appearance: none;
  cursor: pointer;
}

.pw-seg {
  display: inline-flex;
  padding: 2px;
  border: 1px solid var(--pl-border);
  border-radius: 8px;
  background: var(--pl-surface-2);
}

.pw-seg__btn {
  height: 26px;
  padding: 0 10px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--pl-text-2);
  font-size: 12px;
  cursor: pointer;
}

.pw-seg__btn--active {
  background: var(--pl-surface);
  color: var(--pl-text);
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(23, 35, 52, 0.1);
}

.pw-table {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

/* 共享列模板：表头与数据行严格对齐。 */
.pw-grid {
  display: grid;
  grid-template-columns:
    minmax(190px, 2.4fr) 74px 58px minmax(130px, 1.3fr) 56px 56px 92px 84px 128px;
  align-items: center;
  gap: 10px;
  padding: 0 14px;
}

.pw-table__head {
  position: sticky;
  top: 0;
  z-index: 2;
  min-height: 34px;
  border-bottom: 1px solid var(--pl-border);
  background: var(--sm-surface-2);
  color: var(--pl-text-3);
  font-size: 11px;
}

.pw-th {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  height: 34px;
  padding: 0;
  border: 0;
  background: none;
  color: inherit;
  font: inherit;
  font-size: 11px;
  font-weight: 500;
  text-align: left;
  cursor: default;
}

button.pw-th {
  cursor: pointer;
}

button.pw-th:hover {
  color: var(--pl-text);
}

.pw-th i {
  color: var(--sm-accent-blue);
  font-style: normal;
}

.pw-th--num {
  justify-content: flex-end;
  font-variant-numeric: tabular-nums;
}

.pw-th--ops {
  justify-content: flex-end;
}

.pw-table__body {
  display: flex;
  flex-direction: column;
}

.pw-row {
  min-height: 48px;
  border-bottom: 1px solid var(--sm-surface-3);
  cursor: pointer;
  transition: background-color 100ms ease;
}

.pw-row:last-child {
  border-bottom: 0;
}

.pw-row:hover,
.pw-row--open {
  background: var(--sm-surface-hover);
}

.pw-row:focus-visible {
  outline: 2px solid rgba(37, 99, 235, 0.45);
  outline-offset: -2px;
}

.pw-cell {
  min-width: 0;
  color: var(--pl-text);
  font-size: 12.5px;
}

.pw-cell--player {
  display: flex;
  align-items: center;
  gap: 10px;
}

.pw-avatar {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  flex: 0 0 auto;
  border-radius: 9px;
  background: linear-gradient(160deg, #eaf1ff, #dfe9f9);
  color: #2a52b4;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.02em;
}

.pw-cell__stack {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.pw-name {
  padding: 0;
  border: 0;
  background: none;
  color: var(--pl-text);
  font: inherit;
  font-size: 13px;
  font-weight: 600;
  text-align: left;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: pointer;
}

.pw-name:hover {
  color: var(--sm-accent-blue);
}

.pw-sub {
  color: var(--pl-text-3);
  font-size: 11px;
}

.pw-ellipsis {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pw-pos {
  display: inline-flex;
  align-items: center;
  height: 20px;
  padding: 0 7px;
  border: 1px solid var(--pl-border);
  border-radius: 6px;
  background: var(--pl-surface-2);
  color: var(--pl-text-2);
  font-size: 11px;
  white-space: nowrap;
}

.pw-cell--num {
  text-align: right;
  font-variant-numeric: tabular-nums;
  color: var(--pl-text-2);
}

.pw-cell--strong {
  color: var(--pl-text);
  font-weight: 600;
}

.pw-cell--money {
  color: var(--pl-text);
  font-weight: 600;
}

.pw-contract--warn {
  color: var(--pl-warn);
  font-weight: 600;
}

.pw-cell--ops {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
}

.pw-icon-btn {
  display: grid;
  place-items: center;
  min-width: 26px;
  height: 26px;
  padding: 0 4px;
  border: 1px solid var(--pl-border);
  border-radius: 7px;
  background: var(--pl-surface);
  color: var(--pl-text-2);
  font-size: 13px;
  line-height: 1;
  cursor: pointer;
}

.pw-icon-btn:hover:not(:disabled) {
  border-color: var(--sm-border-strong);
  color: var(--pl-text);
}

.pw-icon-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.pw-icon-btn--on {
  border-color: rgba(183, 121, 31, 0.3);
  background: var(--sm-warn-weak);
  color: var(--sm-status-warning);
}

.pw-icon-btn--label {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 0 8px;
}

.pw-compare-btn {
  height: 26px;
  padding: 0 8px;
  border: 1px solid var(--pl-border);
  border-radius: 7px;
  background: var(--pl-surface);
  color: var(--pl-text-2);
  font-size: 11px;
  cursor: pointer;
}

.pw-compare-btn:hover {
  border-color: var(--sm-border-strong);
  color: var(--pl-text);
}

.pw-compare-btn--on {
  border-color: rgba(49, 95, 206, 0.28);
  background: var(--pl-primary-weak);
  color: var(--sm-accent-blue);
}

.pw-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(262px, 1fr));
  gap: 10px;
  padding: 12px;
}

.pw-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  border: 1px solid var(--pl-border);
  border-radius: 12px;
  background: var(--pl-surface);
  transition: border-color 120ms ease, box-shadow 120ms ease;
}

.pw-card:hover {
  border-color: var(--sm-border-strong);
  box-shadow: 0 6px 18px -14px rgba(23, 35, 52, 0.35);
}

.pw-card__head {
  display: flex;
  align-items: center;
  gap: 9px;
}

.pw-card__head .pw-cell__stack {
  flex: 1 1 auto;
}

.pw-card .pw-name {
  display: -webkit-box;
  overflow: hidden;
  white-space: normal;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  line-height: 1.25;
}

.pw-card__club {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  margin: 0;
  color: var(--pl-text-2);
  font-size: 12px;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.pw-card__stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
  margin: 0;
  padding: 8px 10px;
  border-radius: 9px;
  background: var(--pl-surface-2);
}

.pw-card__stats dt {
  color: var(--pl-text-3);
  font-size: 10px;
}

.pw-card__stats dd {
  margin: 1px 0 0;
  color: var(--pl-text);
  font-size: 13px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.pw-card__actions {
  display: flex;
  align-items: center;
  gap: 6px;
  padding-top: 8px;
  border-top: 1px solid var(--sm-surface-3);
}

.pw-card__actions .pw-btn {
  margin-left: auto;
}

.pw-pager {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 10px 14px;
  border-top: 1px solid var(--pl-border);
  background: var(--sm-surface-2);
  color: var(--pl-text-2);
  font-size: 12px;
}

.pw-pager__size {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.pw-pager__nav {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.pw-pager__label {
  color: var(--pl-text-2);
  font-variant-numeric: tabular-nums;
}

.pw-state {
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 260px;
  padding: 32px 20px;
  text-align: center;
}

.pw-state__title {
  margin: 0;
  color: var(--pl-text);
  font-size: 15px;
  font-weight: 600;
}

.pw-state__text {
  max-width: 460px;
  margin: 0;
  color: var(--pl-text-2);
  font-size: 13px;
  line-height: 1.6;
}

.pw-state__actions {
  display: flex;
  gap: 8px;
  margin-top: 8px;
  flex-wrap: wrap;
  justify-content: center;
}

.pw-skeleton {
  display: flex;
  flex-direction: column;
  padding: 8px 14px;
}

.pw-skeleton__row {
  display: grid;
  grid-template-columns: 30px 1.4fr 1fr 0.7fr;
  gap: 12px;
  align-items: center;
  min-height: 44px;
  border-bottom: 1px solid var(--sm-surface-3);
}

.pw-skeleton__avatar,
.pw-skeleton__line {
  border-radius: 7px;
  background: linear-gradient(90deg, var(--sm-surface-3) 25%, var(--sm-surface-2) 50%, var(--sm-surface-3) 75%);
  background-size: 200% 100%;
  animation: pw-shimmer 1.4s ease-in-out infinite;
}

.pw-skeleton__avatar {
  width: 30px;
  height: 30px;
}

.pw-skeleton__line {
  height: 10px;
}

.pw-skeleton__line--wide {
  height: 12px;
}

@keyframes pw-shimmer {
  0% {
    background-position: 160% 0;
  }
  100% {
    background-position: -60% 0;
  }
}

.pw-toast {
  position: fixed;
  right: 28px;
  bottom: 28px;
  z-index: 1400;
  max-width: 360px;
  padding: 10px 14px;
  border: 1px solid var(--pl-border);
  border-radius: 10px;
  background: #fff;
  color: var(--pl-text);
  font-size: 13px;
  box-shadow: 0 16px 40px -24px rgba(23, 35, 52, 0.45);
}

.pw-toast--success {
  border-color: rgba(22, 134, 91, 0.24);
  background: var(--sm-success-weak);
  color: var(--sm-status-success);
}

.pw-toast--warning {
  border-color: rgba(183, 121, 31, 0.24);
  background: var(--sm-warn-weak);
  color: var(--sm-status-warning);
}

.pw-toast--danger {
  border-color: rgba(194, 65, 75, 0.24);
  background: var(--sm-danger-weak);
  color: var(--sm-status-danger);
}

.pw-toast-enter-active,
.pw-toast-leave-active {
  transition: opacity 160ms ease, transform 160ms ease;
}

.pw-toast-enter-from,
.pw-toast-leave-to {
  opacity: 0;
  transform: translateY(6px);
}

/* ---------- 高级筛选抽屉 ---------- */

.pw-adv {
  --pl-surface: var(--sm-surface);
  --pl-surface-2: var(--sm-surface-2);
  --pl-text: var(--sm-text-primary);
  --pl-text-2: var(--sm-text-secondary);
  --pl-text-3: var(--sm-text-tertiary);
  --pl-primary: var(--sm-accent-blue);
  --pl-border: var(--sm-border);
  position: fixed;
  inset: 0;
  z-index: 1150;
  color-scheme: light;
}

.pw-adv__scrim {
  position: absolute;
  inset: 0;
  background: rgba(23, 35, 52, 0.32);
}

.pw-adv__panel {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  display: flex;
  flex-direction: column;
  width: min(420px, 94vw);
  background: var(--pl-surface);
  border-left: 1px solid var(--pl-border);
  box-shadow: -20px 0 50px -30px rgba(23, 35, 52, 0.35);
}

.pw-adv__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 18px 18px 12px;
  border-bottom: 1px solid var(--pl-border);
}

.pw-adv__head h2 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
}

.pw-adv__head p {
  margin: 3px 0 0;
  color: var(--pl-text-2);
  font-size: 12px;
}

.pw-adv__body {
  flex: 1 1 auto;
  overflow-y: auto;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  padding: 16px 18px;
}

.pw-field {
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-width: 0;
  color: var(--pl-text-2);
  font-size: 12px;
}

.pw-field--wide {
  grid-column: 1 / -1;
}

.pw-field > input[type='number'],
.pw-field > select {
  width: 100%;
}

.pw-field > input[type='number'] {
  height: 32px;
  padding: 0 9px;
  border: 1px solid var(--pl-border);
  border-radius: 8px;
  background: var(--pl-surface);
  color: var(--pl-text);
  font: inherit;
  font-size: 12px;
}

.pw-field__pair {
  display: flex;
  align-items: center;
  gap: 5px;
}

.pw-field__pair input {
  flex: 1 1 0;
  min-width: 0;
  height: 32px;
  padding: 0 8px;
  border: 1px solid var(--pl-border);
  border-radius: 8px;
  background: var(--pl-surface);
  color: var(--pl-text);
  font: inherit;
  font-size: 12px;
}

.pw-field__pair i {
  color: var(--pl-text-3);
  font-style: normal;
}

.pw-field--switch {
  grid-column: 1 / -1;
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
  padding: 8px 10px;
  border: 1px solid var(--pl-border);
  border-radius: 9px;
  background: var(--pl-surface-2);
}

.pw-field--switch input {
  width: 34px;
  height: 18px;
  accent-color: var(--sm-accent-blue);
}

.pw-field__hint,
.pw-field__error {
  font-size: 11px;
}

.pw-field__hint {
  color: var(--pl-text-3);
}

.pw-field__error {
  color: var(--pl-danger);
}

.pw-coverage {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.pw-coverage span {
  padding: 2px 8px;
  border: 1px solid var(--pl-border);
  border-radius: 999px;
  background: var(--pl-surface-2);
  color: var(--pl-text-2);
  font-size: 11px;
}

.pw-adv__foot {
  display: flex;
  gap: 8px;
  padding: 12px 18px;
  border-top: 1px solid var(--pl-border);
}

.pw-adv__foot .pw-btn {
  flex: 1 1 0;
  justify-content: center;
}

.pw-adv-enter-active,
.pw-adv-leave-active {
  transition: opacity 160ms ease;
}

.pw-adv-enter-active .pw-adv__panel,
.pw-adv-leave-active .pw-adv__panel {
  transition: transform 220ms cubic-bezier(0.22, 1, 0.36, 1);
}

.pw-adv-enter-from,
.pw-adv-leave-to {
  opacity: 0;
}

.pw-adv-enter-from .pw-adv__panel,
.pw-adv-leave-to .pw-adv__panel {
  transform: translateX(24px);
}

/* ---------- 响应式：窗口越窄，隐藏优先级越低的列 ---------- */

@media (max-width: 1400px) {
  .pw-grid {
    grid-template-columns: minmax(180px, 2.4fr) 70px 54px minmax(110px, 1fr) 52px 52px 84px 118px;
  }

  .pw-col--contract {
    display: none;
  }
}

@media (max-width: 1120px) {
  .pw-grid {
    grid-template-columns: minmax(170px, 2.4fr) 66px 52px 52px 84px 118px;
  }

  .pw-col--club,
  .pw-col--age {
    display: none;
  }
}

@media (max-width: 960px) {
  .pw-grid {
    grid-template-columns: minmax(160px, 2.4fr) 60px 52px 84px 112px;
  }

  .pw-col--pa {
    display: none;
  }

  .pw-search__box {
    flex-basis: 100%;
  }
}

@media (max-width: 720px) {
  .player-workspace {
    margin: 0;
    padding: 16px 12px 22px;
    border-radius: 12px;
  }

  .pw-head {
    flex-direction: column;
  }

  .pw-head__actions {
    justify-content: flex-start;
  }

  .pw-adv__body {
    grid-template-columns: minmax(0, 1fr);
  }

  .pw-status {
    flex-wrap: wrap;
    gap: 10px;
    padding: 8px 12px;
  }

  .pw-status__spacer {
    display: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .pw-skeleton__avatar,
  .pw-skeleton__line {
    animation: none;
  }

  .pw-adv-enter-active,
  .pw-adv-leave-active,
  .pw-adv-enter-active .pw-adv__panel,
  .pw-adv-leave-active .pw-adv__panel,
  .pw-toast-enter-active,
  .pw-toast-leave-active {
    transition: none;
  }
}
</style>
