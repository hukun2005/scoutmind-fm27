/** 转会情报：成交样本统计、费用构成、相似成交与俱乐部画像。 */

<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { asApiError, type ApiError } from '../api/client'
import { getClubTransferProfile, listClubs } from '../api/clubs'
import { getSimilarTransfers } from '../api/transfers'
import { getTransactionSummary, getTransferReview, postDealReport } from '../api/deals'
import { confirmTransferCandidate, dismissTransferCandidate, listTransferCandidates } from '../api/status'
import type { DealReport, TransactionSummary, TransferReview } from '../types/transfers-deals'
import type { CandidateRow } from '../types/status'
import ChartCard from '../components/ChartCard.vue'
import CoverageBar from '../components/CoverageBar.vue'
import DataTable from '../components/DataTable.vue'
import EChart from '../components/EChart.vue'
import EmptyState from '../components/EmptyState.vue'
import ErrorState from '../components/ErrorState.vue'
import InsightPanel from '../components/InsightPanel.vue'
import NumberCell from '../components/NumberCell.vue'
import PageHeader from '../components/PageHeader.vue'
import SectionCard from '../components/SectionCard.vue'
import StatHeader from '../components/StatHeader.vue'
import StatStrip from '../components/StatStrip.vue'
import TransferFlowCard from '../components/TransferFlowCard.vue'
import AppTag from '../components/AppTag.vue'
import type { Club, ClubTransferProfile } from '../types/clubs'
import type { TableColumn } from '../types/table'
import type { InsightItem, InsightTone, StatItem } from '../types/ui'
import type {
  FeeComponent,
  SimilarTransferItem,
  SimilarTransfersResponse,
  Transfer,
  TransferStatus,
  TransferType,
} from '../types/transfers'
import { useSessionStore } from '../stores/session'
import { useTransfersStore } from '../stores/transfers'
import { buildFeeHistogram } from '../utils/chart'
import {
  EMPTY,
  displayText,
  formatDate,
  formatDecimal,
  formatInt,
  formatMoney,
  formatMonths,
  formatPercent,
} from '../utils/format'
import {
  FEE_COMPONENT_LABELS,
  FEE_STATUS_LABELS,
  POSITION_GROUPS,
  TRANSFER_TYPE_LABELS,
  coverageLabel,
  similarityFactorLabel,
  sourceLabel,
  transferStatusLabel,
  transferTypeLabel,
} from '../utils/labels'

type TransferTab = 'list' | 'clubs' | 'cost' | 'similar' | 'deals'

const session = useSessionStore()
const transfers = useTransfersStore()

const route = useRoute()
const router = useRouter()

/** Tabs are deep-linkable (/transfers?tab=deals) so a report can be shared as a URL. */
const TAB_KEYS: TransferTab[] = ['list', 'clubs', 'cost', 'similar', 'deals']
const initialTab = typeof route.query.tab === 'string' && TAB_KEYS.includes(route.query.tab as TransferTab) ? (route.query.tab as TransferTab) : 'list'
const activeTab = ref<TransferTab>(initialTab)

const clubs = ref<Club[]>([])
const clubsLoading = ref(false)
const clubsError = ref<ApiError | null>(null)

const minFeeWan = ref<number | undefined>(undefined)
const maxFeeWan = ref<number | undefined>(undefined)
const dateRange = ref<[string, string] | null>(null)

const similarForm = reactive<{ instanceId: number | undefined; limit: number }>({ instanceId: undefined, limit: 20 })
const similar = ref<SimilarTransfersResponse | null>(null)
const similarLoading = ref(false)
const similarError = ref<ApiError | null>(null)
const similarSearched = ref(false)

const clubProfileId = ref<number | undefined>(undefined)
const clubProfile = ref<ClubTransferProfile | null>(null)
const clubProfileLoading = ref(false)
const clubProfileError = ref<ApiError | null>(null)

// ---------- V2: deal model, taxonomy and club review ----------

const dealForm = reactive<{ instanceId: number | undefined; feeWan: number | undefined; budgetWan: number | undefined }>({
  instanceId: undefined,
  feeWan: undefined,
  budgetWan: undefined,
})
const dealReport = ref<DealReport | null>(null)
const dealLoading = ref(false)
const dealError = ref<ApiError | null>(null)
const dealSearched = ref(false)

const taxonomy = ref<TransactionSummary | null>(null)
const taxonomyError = ref<ApiError | null>(null)
const review = ref<TransferReview | null>(null)
const reviewLoading = ref(false)
const reviewError = ref<ApiError | null>(null)

const candidates = ref<CandidateRow[]>([])
/** Observability counters for the summary; `null` means the interface has not answered yet. */
const candidateCount = ref<number | null>(null)
const candidateBusy = ref(false)
const candidateError = ref<ApiError | null>(null)

/** Currency of the statistics sample; falls back to the documented default. */
const currency = computed(() => transfers.stats?.currency ?? 'EUR')

/** Fee histogram for the current filter window. */
const histogramOption = computed(() => buildFeeHistogram(transfers.stats?.distribution ?? []))

/** Field coverage text shared by the conclusion panel and the cost tab footnote. */
const coverageText = computed(() => {
  const stats = transfers.stats
  if (!stats) return ''
  return Object.entries(stats.coverage)
    .map(([key, value]) => `${coverageLabel(key)} ${formatPercent(value)}`)
    .join(' · ')
})

/** Compact metrics for the page top, replacing the former KPI card stack. */
const statStripItems = computed<StatItem[]>(() => {
  const stats = transfers.stats
  return [
    { label: '样本数', value: stats ? formatInt(stats.sample_size) : EMPTY, hint: '已完成且含金额来源' },
    { label: `中位数（${currency.value}）`, value: formatMoney(stats?.median), hint: 'P50' },
    {
      label: `区间（${currency.value}）`,
      value: stats && (stats.p25 !== null || stats.p75 !== null) ? `${formatMoney(stats.p25)} – ${formatMoney(stats.p75)}` : EMPTY,
      hint: 'P25 – P75，样本不足显示 —',
    },
    { label: `均值（${currency.value}）`, value: formatMoney(stats?.mean), hint: '易受极端值影响' },
    {
      label: '可观测交易',
      value: transfers.error ? EMPTY : formatInt(transfers.total),
      hint: '当前筛选下已返回的成交总数',
    },
    {
      label: '待确认候选',
      value: candidateCount.value === null ? EMPTY : formatInt(candidateCount.value),
      hint: '两次快照发现的俱乐部变化',
      tone: candidateCount.value !== null && candidateCount.value > 0 ? 'warning' : 'default',
    },
  ]
})

/** Full quantile detail kept in the cost-structure tab. */
const costStatItems = computed<StatItem[]>(() => {
  const stats = transfers.stats
  return [
    { label: '样本数', value: stats ? formatInt(stats.sample_size) : EMPTY, hint: '已完成且含金额来源' },
    { label: `最小（${currency.value}）`, value: formatMoney(stats?.min), hint: '可能为 0（自由转会）' },
    { label: `P25（${currency.value}）`, value: formatMoney(stats?.p25), hint: '下四分位' },
    { label: `中位数（${currency.value}）`, value: formatMoney(stats?.median), hint: 'P50' },
    { label: `P75（${currency.value}）`, value: formatMoney(stats?.p75), hint: '上四分位' },
    { label: `最大（${currency.value}）`, value: formatMoney(stats?.max), hint: '' },
  ]
})

const statsFootnote = computed(() => {
  const stats = transfers.stats
  if (!stats) return ''
  const excluded = `排除：不完整 ${formatInt(stats.excluded.incomplete)} 笔 / 非完成 ${formatInt(stats.excluded.non_completed)} 笔`
  return `算法 ${displayText(stats.algorithm_version)} · 币种 ${currency.value} · ${coverageText.value} · ${excluded}`
})

const statsEmpty = computed(() => transfers.stats !== null && transfers.stats.sample_size === 0)

/** Current-page trades, newest first; presentation-only rail, the table stays authoritative. */
const recentTrades = computed(() =>
  transfers.items
    .slice()
    .sort((a, b) => String(b.transfer_date ?? '').localeCompare(String(a.transfer_date ?? '')))
    .slice(0, 8),
)

/** Largest effective fee on the current page, used only for the rail bar width. */
const timelineMaxFee = computed(() =>
  Math.max(0, ...recentTrades.value.map((row) => row.effective_fee ?? 0)),
)

const statsEmptyDescription = computed(() => {
  const stats = transfers.stats
  if (!stats) return ''
  return stats.warnings.length > 0
    ? stats.warnings.join(' ')
    : '当前筛选窗口内没有可统计的已完成交易。放宽日期、费用或年龄筛选后重试。'
})

/** One club aggregated from the current page of observable trades. */
interface ClubSignal {
  name: string
  clubId: number | null
  league: string | null
  deals: number
  knownFees: number
  netSpend: number
  loans: number
  frees: number
  latest: string | null
}

/** Club lookup used to attach ids and leagues to the observable club cards. */
const clubDirectory = computed(() => {
  const map = new Map<string, Club>()
  for (const club of clubs.value) map.set(club.name, club)
  return map
})

/** Club cards built only from the current page of transfers plus the club directory. */
const clubSignals = computed<ClubSignal[]>(() => {
  const byName = new Map<string, ClubSignal>()
  const touch = (name: string | null): ClubSignal | null => {
    if (!name) return null
    let entry = byName.get(name)
    if (!entry) {
      const club = clubDirectory.value.get(name)
      entry = {
        name,
        clubId: club?.club_id ?? null,
        league: club?.league ?? null,
        deals: 0,
        knownFees: 0,
        netSpend: 0,
        loans: 0,
        frees: 0,
        latest: null,
      }
      byName.set(name, entry)
    }
    return entry
  }
  for (const row of transfers.items) {
    const incoming = touch(row.to_club)
    const outgoing = touch(row.from_club)
    for (const [entry, direction] of [
      [incoming, 1],
      [outgoing, -1],
    ] as const) {
      if (!entry) continue
      entry.deals += 1
      if (row.transfer_date && (!entry.latest || row.transfer_date > entry.latest)) entry.latest = row.transfer_date
      if (row.transfer_type === 'loan') entry.loans += 1
      if (row.transfer_type === 'free') entry.frees += 1
      if (row.effective_fee !== null && row.currency === currency.value) {
        entry.knownFees += 1
        entry.netSpend += row.effective_fee * direction
      }
    }
  }
  return [...byName.values()].sort((a, b) => b.deals - a.deals || a.name.localeCompare(b.name))
})

/** Transfer-type preference of one club card. */
function clubPreference(signal: ClubSignal): string {
  const parts: string[] = []
  if (signal.loans > 0) parts.push(`租借 ${signal.loans} 笔`)
  if (signal.frees > 0) parts.push(`自由转会 ${signal.frees} 笔`)
  return parts.length > 0 ? parts.join(' · ') : '类型信息不足'
}

/** Highest-activity club on the current page, used by the summary only. */
const focusText = computed(() => {
  if (candidateCount.value !== null && candidateCount.value > 0) {
    return `有待确认的俱乐部变化 ${formatInt(candidateCount.value)} 条，进入「交易决策与复盘」确认或标记误报。`
  }
  const top = clubSignals.value[0]
  if (top) return `当前页交易最活跃：${top.name}（${formatInt(top.deals)} 笔）。`
  return '暂无可关注的俱乐部或候选（当前没有可观测成交）。'
})

const insightTone = computed<InsightTone>(() => {
  if (transfers.statsError && !transfers.stats) return 'warning'
  if (transfers.stats && (transfers.stats.sample_size === 0 || transfers.stats.median === null)) return 'warning'
  return 'info'
})

/** Summary items; every sentence maps to a returned field or the current page. */
const insightItems = computed<InsightItem[]>(() => {
  const stats = transfers.stats
  const items: InsightItem[] = []
  if (!stats) {
    items.push({
      label: '样本',
      text: transfers.statsError ? '统计数据加载失败，暂无法给出价格区间。' : '统计数据尚未返回。',
      tone: transfers.statsError ? 'warning' : 'neutral',
    })
  } else if (stats.sample_size === 0 || stats.median === null) {
    items.push({
      label: '样本',
      text: '当前筛选窗口内没有可统计的已完成交易，样本不足，不给出价格区间。',
      tone: 'warning',
    })
  } else {
    items.push({
      label: '样本',
      text: `${formatInt(stats.sample_size)} 笔已完成交易；中位 ${formatMoney(stats.median)}，区间 ${formatMoney(stats.p25)} – ${formatMoney(stats.p75)}（${currency.value}）。`,
    })
  }
  items.push({ label: '覆盖字段', text: coverageText.value || '数据源未提供字段覆盖信息' })
  items.push({
    label: '可观测',
    text: `当前筛选下可观测 ${formatInt(transfers.total)} 笔成交${
      candidateCount.value === null ? '；候选数量暂未返回' : `；待确认俱乐部变化 ${formatInt(candidateCount.value)} 条`
    }。`,
  })
  items.push({ label: '关注对象', text: focusText.value })
  if (stats && (stats.sample_size === 0 || stats.median === null)) {
    items.push({
      label: '下一步',
      text: '到「游戏数据」同步游戏数据，或导入转会记录后刷新本页。',
      tone: 'warning',
    })
  }
  return items
})

/** Open one club's profile from its observable card and filter the list by the same club. */
function filterByClub(signal: ClubSignal): void {
  if (signal.clubId === null) {
    ElMessage.info('该俱乐部未在俱乐部列表中找到，无法按俱乐部筛选')
    return
  }
  transfers.setFilter('club_id', signal.clubId)
  clubProfileId.value = signal.clubId
  activeTab.value = 'list'
  void loadClubProfile()
}

const transferColumns: TableColumn<Transfer>[] = [
  { prop: 'transfer_date', label: '日期', width: 104, formatter: (row) => formatDate(row.transfer_date) },
  { prop: 'player_name', label: '球员', minWidth: 150, showOverflowTooltip: true, formatter: (row) => displayText(row.player_name) },
  {
    prop: 'clubs',
    label: '从 → 到',
    minWidth: 210,
    formatter: (row) => `${displayText(row.from_club)} → ${displayText(row.to_club)}`,
  },
  { prop: 'transfer_type', label: '类型', width: 96, formatter: (row) => transferTypeLabel(row.transfer_type) },
  { prop: 'status', label: '状态', width: 84, formatter: (row) => transferStatusLabel(row.status) },
  { prop: 'base_fee', label: '基础费用', width: 114, align: 'right', title: '币种随记录，悬停单元格查看确切金额与币种' },
  { prop: 'addons_potential', label: '附加条款', width: 114, align: 'right', title: '不计入已支付金额；币种随记录' },
  { prop: 'effective_fee', label: '已支付费用', width: 122, align: 'right', title: '币种随记录，悬停单元格查看确切金额与币种' },
  { prop: 'player_ca_at_transfer', label: '成交时 CA', width: 104, align: 'right' },
  { prop: 'contract_remaining_months', label: '合同剩余', width: 100, align: 'right' },
  { prop: 'season', label: '赛季', width: 88, formatter: (row) => displayText(row.season) },
  { prop: 'confidence', label: '记录置信度', width: 96, align: 'right' },
]

const similarColumns: TableColumn<SimilarTransferItem>[] = [
  { prop: 'player', label: '球员', minWidth: 150, formatter: (row) => displayText(row.transfer.player_name) },
  { prop: 'similarity', label: '相似度', width: 92, align: 'right' },
  { prop: 'date', label: '日期', width: 104, formatter: (row) => formatDate(row.transfer.transfer_date) },
  {
    prop: 'clubs',
    label: '从 → 到',
    minWidth: 190,
    formatter: (row) => `${displayText(row.transfer.from_club)} → ${displayText(row.transfer.to_club)}`,
  },
  { prop: 'fee', label: '已支付费用', width: 122, align: 'right', title: '币种随记录，悬停单元格查看确切金额与币种' },
  { prop: 'ca', label: '成交时 CA', width: 104, align: 'right' },
  { prop: 'status', label: '状态', width: 84, formatter: (row) => transferStatusLabel(row.transfer.status) },
]

const clubTransferColumns: TableColumn<Transfer>[] = [
  { prop: 'transfer_date', label: '日期', width: 104, formatter: (row) => formatDate(row.transfer_date) },
  { prop: 'player_name', label: '球员', minWidth: 150, formatter: (row) => displayText(row.player_name) },
  {
    prop: 'clubs',
    label: '从 → 到',
    minWidth: 210,
    formatter: (row) => `${displayText(row.from_club)} → ${displayText(row.to_club)}`,
  },
  { prop: 'transfer_type', label: '类型', width: 96, formatter: (row) => transferTypeLabel(row.transfer_type) },
  { prop: 'effective_fee', label: '费用', width: 122, align: 'right' },
  { prop: 'status', label: '状态', width: 84, formatter: (row) => transferStatusLabel(row.status) },
]

const taxonomyColumns: TableColumn<TransactionSummary['categories'][number]>[] = [
  { prop: 'label', label: '类型', width: 132 },
  { prop: 'count', label: '笔数', width: 76, align: 'right' },
  { prop: 'known_amount', label: '已支付金额', width: 128, align: 'right', formatter: (row) => formatMoney(row.known_amount) },
  { prop: 'known_spend', label: '计入统计', width: 118, align: 'right', formatter: (row) => formatMoney(row.known_spend) },
  {
    prop: 'counts_in_stats',
    label: '进入价格统计',
    width: 112,
    align: 'center',
    formatter: (row) => (row.counts_in_stats ? '是' : '否'),
  },
  { prop: 'treatment', label: '处理方式', minWidth: 320 },
]

/** Stat header items for the club review summary. */
const reviewStats = computed(() => {
  const summary = review.value?.summary
  if (!summary) return []
  return [
    { label: '交易笔数', value: formatInt(summary.deals) },
    { label: '已升值', value: formatInt(summary.profitable), hint: `带身价对比 ${formatInt(summary.with_value_delta)} 笔` },
    { label: '身价变化中位数', value: formatMoney(summary.median_value_delta) },
    { label: '年龄段', value: formatInt(summary.by_age_band.length) },
  ]
})

const reviewColumns: TableColumn<TransferReview['items'][number]>[] = [  { prop: 'player', label: '球员', minWidth: 150, formatter: (row) => row.player.name },
  { prop: 'direction', label: '方向', width: 72, align: 'center', formatter: (row) => (row.direction === 'in' ? '买入' : '卖出') },
  { prop: 'transfer_date', label: '日期', width: 104, formatter: (row) => formatDate(row.transfer_date) },
  { prop: 'fee', label: '成交价', width: 118, align: 'right', formatter: (row) => formatMoney(row.fee) },
  {
    prop: 'percentile',
    label: '同类分位',
    width: 96,
    align: 'right',
    formatter: (row) => (row.fee_percentile === null ? EMPTY : formatPercent(row.fee_percentile, 0)),
  },
  {
    prop: 'value_delta',
    label: '身价变化',
    width: 118,
    align: 'right',
    formatter: (row) => formatMoney(row.value_delta_since),
  },
  { prop: 'verdict', label: '结论', width: 140 },
  { prop: 'evidence', label: '依据', minWidth: 280, formatter: (row) => row.evidence.join('；') },
]

const similarWeights = computed(() =>
  Object.entries(similar.value?.effective_weights ?? {}).map(([key, value]) => ({
    key,
    label: similarityFactorLabel(key),
    value,
  })),
)

const clubProfileCoverage = computed(() => Object.entries(clubProfile.value?.coverage ?? {}))

const signature = computed(() =>
  JSON.stringify({
    filters: transfers.filters,
    page: transfers.page,
    pageSize: transfers.pageSize,
    saveId: session.activeSaveId,
    revision: session.dataRevision,
  }),
)

let reloadTimer: ReturnType<typeof setTimeout> | null = null
let firstRun = true

/** Debounced list + statistics reload for filter changes. */
function scheduleReload(): void {
  if (reloadTimer) clearTimeout(reloadTimer)
  const delay = firstRun ? 0 : 220
  firstRun = false
  reloadTimer = setTimeout(() => {
    void transfers.loadList(session.activeSaveId)
    void transfers.loadStats(session.activeSaveId)
  }, delay)
}

/** Load club options once. */
async function loadClubs(): Promise<void> {
  clubsLoading.value = true
  clubsError.value = null
  try {
    const response = await listClubs()
    clubs.value = response.items
  } catch (caught) {
    clubsError.value = asApiError(caught)
    clubs.value = []
  } finally {
    clubsLoading.value = false
  }
}

/** Sync fee inputs (万) with the base-unit filters. */
function applyFeeRange(): void {
  transfers.setFilter(
    'min_fee',
    minFeeWan.value === undefined ? undefined : Math.round(minFeeWan.value * 10_000),
  )
  transfers.setFilter(
    'max_fee',
    maxFeeWan.value === undefined ? undefined : Math.round(maxFeeWan.value * 10_000),
  )
}

/** Sync the date range picker with the filter fields. */
function applyDateRange(value: [string, string] | null): void {
  dateRange.value = value
  transfers.setFilter('from_date', value?.[0] || undefined)
  transfers.setFilter('to_date', value?.[1] || undefined)
}

/** Reset every filter and local input. */
function resetFilters(): void {
  minFeeWan.value = undefined
  maxFeeWan.value = undefined
  dateRange.value = null
  transfers.reset()
}

/** Run the comparable-transfer query. */
async function runSimilar(): Promise<void> {
  if (similarForm.instanceId === undefined) return
  similarLoading.value = true
  similarError.value = null
  similarSearched.value = true
  try {
    similar.value = await getSimilarTransfers(similarForm.instanceId, similarForm.limit)
    session.markSources(similar.value.items.map((item) => item.transfer.source))
  } catch (caught) {
    similarError.value = asApiError(caught)
    similar.value = null
  } finally {
    similarLoading.value = false
  }
}

/** Load the selected club's transfer profile. */
async function loadClubProfile(): Promise<void> {
  if (clubProfileId.value === undefined) return
  clubProfileLoading.value = true
  clubProfileError.value = null
  try {
    clubProfile.value = await getClubTransferProfile(clubProfileId.value)
    session.markSources(clubProfile.value.top_transfers.map((row) => row.source))
  } catch (caught) {
    clubProfileError.value = asApiError(caught)
    clubProfile.value = null
  } finally {
    clubProfileLoading.value = false
  }
}

/** Run the deal decision report for one player. */
async function runDealReport(): Promise<void> {
  if (dealForm.instanceId === undefined) return
  dealLoading.value = true
  dealError.value = null
  dealSearched.value = true
  try {
    dealReport.value = await postDealReport({
      instance_id: dealForm.instanceId,
      save_id: session.activeSaveId ?? undefined,
      fee: dealForm.feeWan === undefined ? undefined : Math.round(dealForm.feeWan * 10_000),
      budget: dealForm.budgetWan === undefined ? undefined : Math.round(dealForm.budgetWan * 10_000),
    })
  } catch (caught) {
    dealError.value = asApiError(caught)
    dealReport.value = null
  } finally {
    dealLoading.value = false
  }
}

/** 确认一个快照对比发现的俱乐部变化：生成或关联一笔交易。 */
async function confirmCandidate(row: CandidateRow): Promise<void> {
  candidateBusy.value = true
  candidateError.value = null
  try {
    const result = await confirmTransferCandidate(row.id, {})
    ElMessage.success(`已确认：${row.player.name ?? '球员'} → ${displayText(row.to_club)}`)
    candidates.value = candidates.value.filter((item) => item.id !== row.id)
    if (candidateCount.value !== null) candidateCount.value = Math.max(0, candidateCount.value - 1)
    await loadDealsOverview()
    void result
  } catch (caught) {
    candidateError.value = asApiError(caught)
    ElMessage.error(`确认失败：${candidateError.value.message}`)
  } finally {
    candidateBusy.value = false
  }
}

/** 把候选标记为误报（租借回归、退役、数据错乱等）。 */
async function dismissCandidate(row: CandidateRow): Promise<void> {
  candidateBusy.value = true
  candidateError.value = null
  try {
    await dismissTransferCandidate(row.id, '人工确认为误报')
    candidates.value = candidates.value.filter((item) => item.id !== row.id)
    if (candidateCount.value !== null) candidateCount.value = Math.max(0, candidateCount.value - 1)
    ElMessage.success('已标记为误报')
  } catch (caught) {
    candidateError.value = asApiError(caught)
    ElMessage.error(`标记失败：${candidateError.value.message}`)
  } finally {
    candidateBusy.value = false
  }
}

/** Load only the candidate count for the summary; failures leave the value unknown. */
async function loadCandidateCount(): Promise<void> {
  try {
    const result = await listTransferCandidates({ save_id: session.activeSaveId ?? undefined, status: 'candidate' })
    candidateCount.value = typeof result.total === 'number' ? result.total : (result.items?.length ?? null)
  } catch {
    candidateCount.value = null
  }
}

/** Load the transaction taxonomy, the own-club review and the unconfirmed club-change candidates. */
async function loadDealsOverview(): Promise<void> {
  reviewLoading.value = true
  reviewError.value = null
  taxonomyError.value = null
  candidateError.value = null
  try {
    const [summary, reviewed, candidateList] = await Promise.all([
      getTransactionSummary(session.activeSaveId ?? undefined),
      getTransferReview(session.activeSaveId ?? undefined),
      listTransferCandidates({ save_id: session.activeSaveId ?? undefined, status: 'candidate' }),
    ])
    taxonomy.value = summary
    review.value = reviewed
    candidates.value = candidateList.items ?? []
    candidateCount.value = typeof candidateList.total === 'number' ? candidateList.total : candidates.value.length
  } catch (caught) {
    const apiError = asApiError(caught)
    reviewError.value = apiError
    taxonomyError.value = apiError
    taxonomy.value = null
    review.value = null
  } finally {
    reviewLoading.value = false
  }
}

watch(activeTab, (tab) => {
  if (tab === 'deals' && review.value === null && !reviewLoading.value) void loadDealsOverview()
})

/** Status tab helper for the status select. */
function setStatus(value: string): void {
  transfers.setStatus(value as TransferStatus | 'all')
}
/** Transfer-type select options, in enum order. */
const transferTypeOptions = Object.entries(TRANSFER_TYPE_LABELS).map(([value, label]) => ({ value, label }))

/** Set the transfer type filter from the select value. */
function setTransferType(value: string | undefined): void {
  transfers.setFilter('transfer_type', value ? (value as TransferType) : undefined)
}

function onPageChange(value: number): void {
  transfers.setPage(value)
}

function onPageSizeChange(value: number): void {
  transfers.setPageSize(value)
}

/** Label of a fee component type. */
function feeTypeLabel(component: FeeComponent): string {
  return FEE_COMPONENT_LABELS[component.type] ?? component.type
}

/** Label of a fee component status. */
function feeStatusLabel(component: FeeComponent): string {
  return FEE_STATUS_LABELS[component.status] ?? component.status
}

watch(signature, scheduleReload, { immediate: true })

onBeforeUnmount(() => {
  if (reloadTimer) clearTimeout(reloadTimer)
})

void loadClubs()
void loadCandidateCount()
// A deep link straight into the deals tab still needs its own data; the tab watcher only fires on change.
if (activeTab.value === 'deals') void loadDealsOverview()
</script>

<template>
  <div class="sm-page">
    <PageHeader
      title="转会情报"
      description="清楚查看每笔交易的状态、类型与费用。只有已完成且有金额来源的交易进入统计，缺失字段不填默认值。"
    >
      <template #meta>
        <span class="sm-text-xs sm-text-faint">
          样本 {{ formatInt(transfers.stats?.sample_size ?? null) }} 笔 · 币种 {{ currency }} ·
          算法 {{ displayText(transfers.stats?.algorithm_version) }}
        </span>
      </template>
      <template #actions>
        <el-button size="small" :loading="transfers.loading" @click="scheduleReload">刷新</el-button>
      </template>
    </PageHeader>

    <InsightPanel
      title="转会情报摘要"
      subtitle="只统计已完成交易；不包含传闻或谈判事件，缺失字段不填默认值。"
      :tone="insightTone"
      badge="数据事实"
      :items="insightItems"
      footnote="样本、分位与覆盖字段来自统计接口；可观测成交与候选数量来自当前存档。"
    />

    <StatStrip :items="statStripItems" dense />

    <el-tabs v-model="activeTab" class="tabs">
      <el-tab-pane label="成交列表" name="list">
        <div class="sm-stack">
          <section class="timeline sm-glass" aria-label="最近可观测交易">
            <header class="timeline__head">
              <span class="sm-section-label">可观测事件</span>
              <h2 class="timeline__title">最近可观测交易</h2>
              <p class="timeline__hint">
                当前页成交按日期倒序，最多 8 条；金额为记录自带币种，缺失显示 —，完整明细以下方表格为准。
              </p>
            </header>
            <ol v-if="recentTrades.length > 0" class="timeline__rail">
              <li v-for="row in recentTrades" :key="row.id" class="timeline__item">
                <span class="timeline__date sm-num">{{ formatDate(row.transfer_date) }}</span>
                <span class="timeline__dot" aria-hidden="true" />
                <div class="timeline__body">
                  <div class="timeline__row">
                    <span class="timeline__player">{{ displayText(row.player_name) }}</span>
                    <span class="timeline__meta">
                      <AppTag :tag="row.status" :label="transferStatusLabel(row.status)" />
                      <span class="timeline__fee sm-num">{{ formatMoney(row.effective_fee) }}</span>
                    </span>
                  </div>
                  <p class="timeline__clubs">
                    {{ displayText(row.from_club) }} → {{ displayText(row.to_club) }} ·
                    {{ transferTypeLabel(row.transfer_type) }}
                  </p>
                  <span v-if="row.effective_fee !== null" class="timeline__bar" aria-hidden="true">
                    <i
                      :style="{
                        width: `${timelineMaxFee > 0 ? Math.max(4, (row.effective_fee / timelineMaxFee) * 100) : 0}%`,
                      }"
                    />
                  </span>
                </div>
              </li>
            </ol>
            <EmptyState
              v-else
              title="暂无可观测交易"
              description="当前筛选还没有成交记录。到「游戏数据」同步游戏数据或导入转会记录后再查看。"
              compact
            >
              <el-button size="small" @click="router.push('/data')">去游戏数据</el-button>
            </EmptyState>
          </section>

          <section class="console sm-glass" aria-label="转会筛选控制台">
            <header class="console__head">
              <div class="console__titles">
                <span class="sm-section-label">筛选交易</span>
                <p class="console__hint">
                  条件变更后自动查询；统计头使用位置组、年龄、日期、俱乐部，费用与类型只影响列表（契约未提供对应统计参数）。
                </p>
              </div>
            </header>
            <div class="filter-grid">
              <label class="filter-field">
                <span class="sm-label">状态</span>
                <el-select
                  :model-value="transfers.filters.status ?? 'completed'"
                  size="small"
                  aria-label="交易状态"
                  @update:model-value="(value) => setStatus(String(value))"
                >
                  <el-option value="completed" label="已完成" />
                  <el-option value="pending" label="待完成" />
                  <el-option value="all" label="全部" />
                </el-select>
              </label>

              <label class="filter-field">
                <span class="sm-label">转会类型</span>
                <el-select
                  :model-value="transfers.filters.transfer_type"
                  size="small"
                  clearable
                  placeholder="全部类型"
                  @update:model-value="(value) => setTransferType(value === '' ? undefined : String(value))"
                >
                  <el-option v-for="option in transferTypeOptions" :key="option.value" :label="option.label" :value="option.value" />
                </el-select>
              </label>

              <label class="filter-field">
                <span class="sm-label">位置组</span>
                <el-select
                  :model-value="transfers.filters.position_group"
                  size="small"
                  clearable
                  placeholder="全部位置组"
                  @update:model-value="(value) => transfers.setFilter('position_group', value === '' ? undefined : String(value))"
                >
                  <el-option v-for="group in POSITION_GROUPS" :key="group.value" :label="group.label" :value="group.value" />
                </el-select>
              </label>

              <label class="filter-field filter-field--wide">
                <span class="sm-label">成交日期</span>
                <el-date-picker
                  :model-value="dateRange"
                  type="daterange"
                  size="small"
                  value-format="YYYY-MM-DD"
                  range-separator="至"
                  start-placeholder="开始日期"
                  end-placeholder="结束日期"
                  unlink-panels
                  @update:model-value="applyDateRange"
                />
              </label>

              <div class="filter-field filter-field--pair">
                <span class="sm-label">费用区间（万 €）</span>
                <div class="filter-pair">
                  <el-input-number
                    v-model="minFeeWan"
                    size="small"
                    :min="0"
                    :step="100"
                    :controls="false"
                    placeholder="最小"
                    @update:model-value="applyFeeRange"
                  />
                  <span class="filter-pair__dash">–</span>
                  <el-input-number
                    v-model="maxFeeWan"
                    size="small"
                    :min="0"
                    :step="100"
                    :controls="false"
                    placeholder="最大"
                    @update:model-value="applyFeeRange"
                  />
                </div>
              </div>

              <div class="filter-field filter-field--pair">
                <span class="sm-label">成交时年龄</span>
                <div class="filter-pair">
                  <el-input-number
                    :model-value="transfers.filters.min_age"
                    size="small"
                    :min="14"
                    :max="60"
                    :controls="false"
                    placeholder="最小"
                    @update:model-value="(value) => transfers.setFilter('min_age', typeof value === 'number' ? value : undefined)"
                  />
                  <span class="filter-pair__dash">–</span>
                  <el-input-number
                    :model-value="transfers.filters.max_age"
                    size="small"
                    :min="14"
                    :max="60"
                    :controls="false"
                    placeholder="最大"
                    @update:model-value="(value) => transfers.setFilter('max_age', typeof value === 'number' ? value : undefined)"
                  />
                </div>
              </div>

              <label class="filter-field">
                <span class="sm-label">俱乐部</span>
                <el-select
                  :model-value="transfers.filters.club_id"
                  size="small"
                  clearable
                  filterable
                  :loading="clubsLoading"
                  placeholder="全部俱乐部"
                  @update:model-value="(value) => transfers.setFilter('club_id', typeof value === 'number' ? value : undefined)"
                >
                  <el-option v-for="club in clubs" :key="club.club_id" :label="club.name" :value="club.club_id" />
                </el-select>
              </label>

              <div class="filter-field filter-field--actions">
                <el-button size="small" @click="resetFilters">重置</el-button>
              </div>
            </div>
            <p class="console__foot">
              <span v-if="clubsError">俱乐部选项加载失败：{{ clubsError.message }}</span>
              <span v-else>成交时 CA、合同剩余月数等字段按记录返回值展示；缺失显示 —，不参与分位数校正。</span>
            </p>
          </section>

          <SectionCard title="成交明细" subtitle="展开行可查看费用构成（基础、分期、附加条款等）" flush>
            <DataTable
              :columns="transferColumns"
              :rows="transfers.items"
              :loading="transfers.loading"
              :error="transfers.error"
              :total="transfers.total"
              :page="transfers.page"
              :page-size="transfers.pageSize"
              :page-sizes="[25, 50, 100, 200]"
              row-key="id"
              expandable
              show-pagination
              :empty-title="transfers.items.length === 0 ? '没有符合筛选条件的成交' : '暂无数据'"
              empty-description="放宽日期、费用或年龄筛选后重试；如果全部为空，说明当前存档还没有已完成的交易记录。"
              @update:page="onPageChange"
              @update:page-size="onPageSizeChange"
              @retry="transfers.loadList(session.activeSaveId)"
            >
              <template #expand="{ row }">
                <div class="components">
                  <div v-if="(row.fee_components ?? []).length === 0" class="sm-text-2xs sm-text-faint">
                    该交易没有费用构成明细；已支付费用字段为 {{ formatMoney(row.fee_paid) }}。
                  </div>
                  <div v-else class="components__table">
                    <div class="components__head">
                      <span>构成</span>
                      <span>状态</span>
                      <span>金额（原币种）</span>
                      <span>到期日</span>
                      <span>触发条件</span>
                    </div>
                    <div v-for="(component, index) in row.fee_components ?? []" :key="`${component.type}-${index}`" class="components__row">
                      <span>{{ feeTypeLabel(component) }}</span>
                      <span>{{ feeStatusLabel(component) }}</span>
                      <span class="sm-num">{{ formatMoney(component.amount) }}</span>
                      <span class="sm-num">{{ formatDate(component.due_date) }}</span>
                      <span class="sm-text-2xs">{{ displayText(component.condition ?? null) }}</span>
                    </div>
                  </div>
                  <div class="components__meta">
                    <span>基础费用 {{ formatMoney(row.base_fee) }}</span>
                    <span>附加条款上限 {{ formatMoney(row.addons_potential) }}（不计入已支付）</span>
                    <span>来源 {{ sourceLabel(row.source) }} · 记录置信度 {{ formatDecimal(row.confidence, 2) }} · 币种 {{ row.currency }}</span>
                  </div>
                </div>
              </template>

              <template #cell="{ row, column }">
                <template v-if="column.prop === 'base_fee'">
                  <NumberCell :value="row.base_fee" kind="money" :currency="row.currency" />
                </template>
                <template v-else-if="column.prop === 'addons_potential'">
                  <NumberCell :value="row.addons_potential" kind="money" :currency="row.currency" />
                </template>
                <template v-else-if="column.prop === 'effective_fee'">
                  <NumberCell :value="row.effective_fee" kind="money" :currency="row.currency" />
                </template>
                <template v-else-if="column.prop === 'player_ca_at_transfer'">
                  <NumberCell :value="row.player_ca_at_transfer" />
                </template>
                <template v-else-if="column.prop === 'contract_remaining_months'">
                  <span class="sm-num" :title="formatMonths(row.contract_remaining_months)">
                    {{ row.contract_remaining_months === null ? EMPTY : row.contract_remaining_months }}
                  </span>
                </template>
                <template v-else-if="column.prop === 'confidence'">
                  <NumberCell :value="row.confidence" kind="decimal" :digits="2" />
                </template>
                <template v-else>
                  {{ column.formatter ? column.formatter(row) : EMPTY }}
                </template>
              </template>

              <template #toolbar>
                <div class="coverage-chips">
                  <span class="sm-text-2xs sm-text-faint">列表覆盖：</span>
                  <AppTag
                    v-for="[key, value] in Object.entries(transfers.coverage)"
                    :key="key"
                    tag="source"
                    :label="`${coverageLabel(key)} ${formatPercent(value)}`"
                    tone="neutral"
                    allow-internal
                  />
                </div>
              </template>
            </DataTable>
          </SectionCard>
        </div>
      </el-tab-pane>

      <el-tab-pane label="费用结构" name="cost">
        <div class="sm-stack">
          <StatStrip :items="costStatItems" dense />
          <ErrorState
            v-if="transfers.statsError && !transfers.stats"
            :error="transfers.statsError"
            compact
            @retry="transfers.loadStats(session.activeSaveId)"
          />
          <div v-if="transfers.stats && transfers.stats.warnings.length > 0" class="warnings">
            <el-alert type="warning" :closable="false" show-icon>
              <template #title>
                <span class="sm-text-xs">{{ transfers.stats.warnings.join(' ') }}</span>
              </template>
            </el-alert>
          </div>
          <ChartCard
            title="成交费用分布"
            subtitle="按后端给定区间统计的已完成交易笔数"
            :loading="transfers.statsLoading && !transfers.stats"
            :empty="!transfers.statsLoading && (transfers.stats === null || statsEmpty || (transfers.stats?.distribution.length ?? 0) === 0)"
            empty-title="暂无成交样本"
            empty-variant="insufficient"
            :empty-description="statsEmptyDescription"
            :footnote="statsFootnote"
          >
            <EChart :option="histogramOption" height="236px" aria-label="成交费用直方图" />
          </ChartCard>
        </div>
      </el-tab-pane>

      <el-tab-pane label="俱乐部画像" name="clubs">
        <div class="sm-stack">
          <section class="club-cards" aria-label="重点俱乐部">
            <header class="club-cards__head">
              <span class="sm-section-label">重点俱乐部</span>
              <h2 class="club-cards__title">当前页交易最活跃的俱乐部</h2>
              <p class="club-cards__hint">由当前页成交聚合，点击卡片按该俱乐部筛选成交并加载完整画像。</p>
            </header>
            <div v-if="clubSignals.length > 0" class="club-cards__grid">
              <button
                v-for="signal in clubSignals.slice(0, 6)"
                :key="signal.name"
                type="button"
                class="club-card"
                @click="filterByClub(signal)"
              >
                <span class="club-card__name">{{ signal.name }}</span>
                <span class="club-card__league">{{ displayText(signal.league) }}</span>
                <span class="club-card__line">
                  {{ formatInt(signal.deals) }} 笔交易 · 已知净支出（{{ currency }}）
                  {{ signal.knownFees > 0 ? formatMoney(signal.netSpend) : EMPTY }}
                </span>
                <span class="club-card__line">偏好：{{ clubPreference(signal) }}</span>
                <span class="club-card__hint">
                  最近 {{ formatDate(signal.latest) }} · {{ signal.clubId === null ? '无法按俱乐部筛选' : '点击筛选' }}
                </span>
              </button>
            </div>
            <EmptyState
              v-else
              title="暂无可画像俱乐部"
              description="当前筛选还没有成交记录；同步游戏数据或放宽筛选后重试。"
              compact
            />
          </section>

          <SectionCard title="选择俱乐部" subtitle="画像基于该俱乐部的已完成交易" dense>
            <div class="similar-form">
              <label class="filter-field filter-field--wide">
                <span class="sm-label">俱乐部</span>
                <el-select
                  v-model="clubProfileId"
                  size="small"
                  filterable
                  clearable
                  :loading="clubsLoading"
                  placeholder="选择俱乐部"
                  aria-label="俱乐部"
                  @update:model-value="loadClubProfile"
                >
                  <el-option v-for="club in clubs" :key="club.club_id" :label="club.name" :value="club.club_id" />
                </el-select>
              </label>
              <el-button size="small" :loading="clubProfileLoading" @click="loadClubProfile">刷新画像</el-button>
            </div>
            <template #footer>
              <span v-if="clubsError">俱乐部列表加载失败：{{ clubsError.message }}</span>
              <span v-else>净支出、每笔出售利润等均由后端聚合；字段为 null 时显示 —。</span>
            </template>
          </SectionCard>

          <ErrorState v-if="clubProfileError" :error="clubProfileError" @retry="loadClubProfile" />

          <EmptyState
            v-else-if="clubProfileId === undefined"
            title="选择俱乐部查看画像"
            description="画像包含买入/卖出笔数与中位数、净支出、年轻球员比例、租借数量与重点交易。"
            compact
          />

          <template v-else-if="clubProfile">
            <SectionCard
              :title="`${displayText(clubProfile.name)} · 俱乐部画像`"
              :subtitle="`${displayText(clubProfile.league)} · ${displayText(clubProfile.nation)} · 声望 ${formatInt(clubProfile.reputation)}`"
            >
              <template #actions>
                <AppTag v-if="clubProfile.is_user_club" tag="user_club" />
              </template>

              <div class="club-kpis">
                <div class="club-kpi">
                  <span class="sm-label">买入</span>
                  <span class="club-kpi__value sm-num">{{ formatInt(clubProfile.bought.count) }} 笔</span>
                  <span class="club-kpi__hint">
                    合计 {{ formatMoney(clubProfile.bought.total) }} · 中位
                    {{ formatMoney(clubProfile.bought.median) }}
                  </span>
                </div>
                <div class="club-kpi">
                  <span class="sm-label">卖出</span>
                  <span class="club-kpi__value sm-num">{{ formatInt(clubProfile.sold.count) }} 笔</span>
                  <span class="club-kpi__hint">
                    合计 {{ formatMoney(clubProfile.sold.total) }} · 中位
                    {{ formatMoney(clubProfile.sold.median) }}
                  </span>
                </div>
                <div class="club-kpi">
                  <span class="sm-label">净支出</span>
                  <span class="club-kpi__value sm-num">{{ formatMoney(clubProfile.net_spend) }}</span>
                  <span class="club-kpi__hint">买入 − 卖出</span>
                </div>
                <div class="club-kpi">
                  <span class="sm-label">每笔出售平均利润</span>
                  <span class="club-kpi__value sm-num">
                    {{ formatMoney(clubProfile.avg_profit_per_sale) }}
                  </span>
                  <span class="club-kpi__hint">后端口径，非逐笔核算</span>
                </div>
                <div class="club-kpi">
                  <span class="sm-label">年轻球员签约比例</span>
                  <span class="club-kpi__value sm-num">{{ formatPercent(clubProfile.young_signing_ratio) }}</span>
                  <span class="club-kpi__hint">年轻阈值由后端规则决定</span>
                </div>
                <div class="club-kpi">
                  <span class="sm-label">租借</span>
                  <span class="club-kpi__value sm-num">
                    入 {{ formatInt(clubProfile.loan_in_count) }} / 出 {{ formatInt(clubProfile.loan_out_count) }}
                  </span>
                  <span class="club-kpi__hint">租入 / 租出笔数</span>
                </div>
              </div>

              <div class="club-coverage">
                <CoverageBar
                  v-for="[key, value] in clubProfileCoverage"
                  :key="key"
                  :label="coverageLabel(key)"
                  :value="value"
                  dense
                />
              </div>

              <template #footer>
                样本 {{ formatInt(clubProfile.sample_size) }} 笔 · 币种 {{ clubProfile.currency }} · 覆盖度见上
              </template>
            </SectionCard>

            <SectionCard title="重点交易" subtitle="按后端返回顺序展示" flush>
              <DataTable
                :columns="clubTransferColumns"
                :rows="clubProfile.top_transfers"
                row-key="id"
                dense
                :empty-title="clubProfile.top_transfers.length === 0 ? '该俱乐部没有重点交易' : '暂无数据'"
              >
                <template #cell="{ row, column }">
                  <template v-if="column.prop === 'effective_fee'">
                    <NumberCell :value="row.effective_fee" kind="money" :currency="row.currency" />
                  </template>
                  <template v-else>
                    {{ column.formatter ? column.formatter(row) : EMPTY }}
                  </template>
                </template>
              </DataTable>
            </SectionCard>
          </template>
        </div>
      </el-tab-pane>

      <el-tab-pane label="相似成交" name="similar">
        <div class="sm-stack">
          <SectionCard title="查询相似成交" subtitle="输入球员实例 ID，后端按年龄、CA、PA、位置与合同加权匹配" dense>
            <div class="similar-form">
              <label class="filter-field">
                <span class="sm-label">球员实例 ID</span>
                <el-input-number v-model="similarForm.instanceId" size="small" :min="1" :controls="false" placeholder="例如 11" />
              </label>
              <label class="filter-field">
                <span class="sm-label">返回数量</span>
                <el-select v-model="similarForm.limit" size="small" aria-label="返回数量">
                  <el-option :value="10" label="10" />
                  <el-option :value="20" label="20" />
                  <el-option :value="50" label="50" />
                </el-select>
              </label>
              <el-button size="small" type="primary" :loading="similarLoading" @click="runSimilar">查询</el-button>
            </div>
          </SectionCard>

          <ErrorState v-if="similarError" :error="similarError" @retry="runSimilar" />

          <EmptyState
            v-else-if="!similarSearched"
            title="尚未查询"
            description="相似成交依赖同存档内条件相近的已完成交易；样本不足时后端会返回空列表并给出原因，前端不会补造对比。"
            compact
          />

          <template v-else-if="similar">
            <SectionCard title="目标与权重" subtitle="权重由后端在缺失字段上重新分配">
              <div class="similar-target">
                <div>
                  <p class="similar-target__name">{{ displayText(similar.target.name) }}</p>
                  <p class="sm-text-xs sm-text-muted">
                    年龄 {{ formatInt(similar.target.age) }} · {{ displayText(similar.target.position_group) }} · CA
                    {{ formatInt(similar.target.ca) }} / PA {{ formatInt(similar.target.pa) }} · 样本
                    {{ formatInt(similar.sample_size) }} 笔
                  </p>
                </div>
                <div class="chips">
                  <span v-for="weight in similarWeights" :key="weight.key" class="chip">
                    {{ weight.label }} {{ formatDecimal(weight.value, 2) }}
                  </span>
                </div>
              </div>
              <ul v-if="similar.data_gaps.length > 0" class="warnings-list">
                <li v-for="gap in similar.data_gaps" :key="gap">{{ gap }}</li>
              </ul>
              <p v-if="similar.missing_fields.length > 0" class="sm-text-2xs sm-text-faint">
                目标缺失字段：{{ similar.missing_fields.map((field) => similarityFactorLabel(field)).join('、') }}
              </p>
              <EmptyState
                v-if="similar.items.length === 0"
                title="没有相似成交样本"
                description="条件相近的已完成交易不足。样本不足时不做估值，也不会用球员身价顶替成交价。"
                variant="insufficient"
                compact
              />
              <DataTable
                v-else
                :columns="similarColumns"
                :rows="similar.items"
                row-key="transfer_id"
                expandable
                dense
                empty-title="暂无数据"
              >
                <template #expand="{ row }">
                  <div class="components__table">
                    <div class="components__head components__head--factors">
                      <span>因子</span>
                      <span>目标值</span>
                      <span>该笔成交</span>
                      <span>距离</span>
                      <span>权重</span>
                    </div>
                    <div v-for="factor in row.factors" :key="factor.key" class="components__row components__row--factors">
                      <span>{{ similarityFactorLabel(factor.key) }}</span>
                      <span class="sm-num">{{ displayText(factor.target) }}</span>
                      <span class="sm-num">{{ displayText(factor.value) }}</span>
                      <span class="sm-num">{{ formatDecimal(factor.distance, 3) }}</span>
                      <span class="sm-num">{{ formatDecimal(factor.weight, 3) }}</span>
                    </div>
                    <p v-if="row.factors.length === 0" class="sm-text-2xs sm-text-faint">该样本没有因子明细。</p>
                  </div>
                </template>
                <template #cell="{ row, column }">
                  <template v-if="column.prop === 'similarity'">
                    <NumberCell :value="row.similarity" kind="decimal" :digits="3" />
                  </template>
                  <template v-else-if="column.prop === 'fee'">
                    <NumberCell :value="row.transfer.effective_fee" kind="money" :currency="row.transfer.currency" />
                  </template>
                  <template v-else-if="column.prop === 'ca'">
                    <NumberCell :value="row.transfer.player_ca_at_transfer" />
                  </template>
                  <template v-else>
                    {{ column.formatter ? column.formatter(row) : EMPTY }}
                  </template>
                </template>
              </DataTable>
            </SectionCard>
          </template>
        </div>
      </el-tab-pane>

      <el-tab-pane label="交易决策与复盘" name="deals">
        <div class="sm-stack">
          <SectionCard
            title="交易决策报告"
            subtitle="总成本 = 转会费 + 签字费 + 经纪人费用 + 合同期内工资 + 奖金；每个成本项都标注是存档观测值还是模型假设"
            dense
          >
            <div class="filter-grid">
              <label class="filter-field">
                <span class="sm-label">球员实例 ID</span>
                <el-input-number
                  v-model="dealForm.instanceId"
                  :min="1"
                  size="small"
                  controls-position="right"
                  placeholder="必填"
                />
              </label>
              <label class="filter-field">
                <span class="sm-label">报价（万 €）</span>
                <el-input-number v-model="dealForm.feeWan" :min="0" :step="500" size="small" controls-position="right" />
              </label>
              <label class="filter-field">
                <span class="sm-label">预算（万 €）</span>
                <el-input-number v-model="dealForm.budgetWan" :min="0" :step="500" size="small" controls-position="right" />
              </label>
              <div class="filter-actions">
                <el-button size="small" type="primary" :loading="dealLoading" :disabled="dealForm.instanceId === undefined" @click="runDealReport">
                  生成报告
                </el-button>
              </div>
            </div>

            <ErrorState v-if="dealError" :error="dealError" title="决策报告生成失败" @retry="runDealReport" />
            <template v-else-if="dealReport">
              <div class="deal-grid">
                <div class="deal-block">
                  <p class="sm-label">总成本模型（{{ dealReport.cost.label }}）</p>
                  <ul class="deal-list">
                    <li v-for="component in dealReport.cost.components" :key="component.key">
                      <span>{{ component.label }}</span>
                      <span class="sm-num">{{ formatMoney(component.amount) }}</span>
                      <AppTag
                        :tag="component.status"
                        :label="component.status === 'observed' ? '已观测' : component.status === 'assumed' ? '推定' : '推断'"
                      />
                    </li>
                  </ul>
                  <p class="sm-text-2xs sm-text-faint">
                    已知成本合计 {{ formatMoney(dealReport.cost.total_known) }}
                    <template v-if="dealReport.cost.missing_components.length > 0">
                      · 缺少 {{ dealReport.cost.missing_components.join('、') }}
                    </template>
                  </p>
                </div>
                <div class="deal-block">
                  <p class="sm-label">决策要素</p>
                  <ul class="deal-list">
                    <li v-for="row in dealReport.rows" :key="row.key">
                      <span>{{ row.label }}</span>
                      <strong>{{ row.value }}</strong>
                    </li>
                  </ul>
                </div>
                <div class="deal-block">
                  <p class="sm-label">投资效率</p>
                  <p class="deal-verdict">{{ dealReport.recommendation.verdict }}</p>
                  <ul class="deal-list">
                    <li v-for="reason in dealReport.recommendation.reasons" :key="reason" class="sm-text-xs sm-text-2">
                      {{ reason }}
                    </li>
                  </ul>
                  <p v-if="dealReport.investment.available" class="sm-text-2xs sm-text-faint">
                    投资效率 {{ formatDecimal(dealReport.investment.score, 2) }} · 未来价值
                    {{ formatMoney(dealReport.investment.expected_future_value) }}
                  </p>
                  <p v-else class="sm-text-2xs sm-text-faint">{{ dealReport.investment.reason }}</p>
                </div>
              </div>
              <el-alert
                v-if="dealReport.data_gaps.length > 0"
                class="deal-gaps"
                type="warning"
                :closable="false"
                show-icon
                title="数据缺口"
              >
                <ul class="deal-list">
                  <li v-for="gap in dealReport.data_gaps" :key="gap" class="sm-text-xs">{{ gap }}</li>
                </ul>
              </el-alert>
            </template>
            <EmptyState
              v-else-if="dealSearched && !dealLoading"
              title="没有生成报告"
              description="确认球员实例 ID 存在后重试"
            />
          </SectionCard>

          <SectionCard
            title="交易类型体系"
            subtitle="正式转会、租借、租借附买断、自由转会、分期、附加条款、未完成与取消各自的口径；只有正式转会进入价格统计"
            flush
          >
            <ErrorState v-if="taxonomyError" :error="taxonomyError" title="交易类型加载失败" @retry="loadDealsOverview" />
            <DataTable
              v-else
              :columns="taxonomyColumns"
              :rows="taxonomy?.categories ?? []"
              row-key="key"
              dense
              :show-pagination="false"
              empty-title="没有交易记录"
              empty-description="导入带 transfers 的扫描报文后可查看"
            />
          </SectionCard>

          <SectionCard
            title="待确认的俱乐部变化"
            subtitle="由两次快照的俱乐部差异发现；确认后才会生成交易记录，误报可直接标记"
            flush
          >
            <ErrorState v-if="candidateError" :error="candidateError" title="候选事件加载失败" @retry="loadDealsOverview" />
            <template v-else>
              <div v-if="candidates.length > 0" class="candidate-list">
                <div v-for="row in candidates" :key="row.id" class="candidate">
                  <div class="candidate__main">
                    <span class="candidate__name">{{ displayText(row.player.name) }}</span>
                    <span class="sm-text-xs sm-text-2">
                      {{ displayText(row.from_club) }} → {{ displayText(row.to_club) }}
                      · {{ formatDate(row.detected_at) }}
                      · 类型 {{ row.kind === 'loan' ? '租借' : '未知（未提供租借信息）' }}
                    </span>
                  </div>
                  <div class="candidate__actions">
                    <el-button size="small" type="primary" :loading="candidateBusy" @click="confirmCandidate(row)">确认</el-button>
                    <el-button size="small" :loading="candidateBusy" @click="dismissCandidate(row)">误报</el-button>
                  </div>
                </div>
              </div>
              <EmptyState
                v-else
                title="没有待确认的变化"
                description="两次快照之间没有发现球员换俱乐部；候选不会自动计入任何统计"
              />
            </template>
          </SectionCard>

          <SectionCard
            title="本队交易复盘"
            subtitle="成交价在同类样本中的分位、转会后的能力与身价变化，以及逐笔结论"
            flush
          >
            <ErrorState v-if="reviewError" :error="reviewError" title="复盘加载失败" @retry="loadDealsOverview" />
            <template v-else>
              <div v-if="review?.summary" class="review-summary">
                <StatHeader :items="reviewStats" />
              </div>
              <DataTable
                :columns="reviewColumns"
                :rows="review?.items ?? []"
                row-key="transfer_id"
                dense
                :show-pagination="false"
                empty-title="没有可复盘的交易"
                empty-description="本队还没有已完成的交易记录"
              />
              <p v-if="review?.note" class="sm-text-2xs sm-text-faint review-note">{{ review.note }}</p>
            </template>
          </SectionCard>
        </div>
      </el-tab-pane>
    </el-tabs>

    <TransferFlowCard :save-id="session.activeSaveId" />
  </div>
</template>

<style scoped>
.tabs :deep(.el-tabs__header) {
  margin-bottom: var(--sm-space-3);
}

/* 当前标签页使用品牌渐变下划线，其余保持 Element Plus 行为。 */
.tabs :deep(.el-tabs__active-bar) {
  background: var(--sm-gradient-accent);
}

.tabs :deep(.el-tabs__item.is-active) {
  color: var(--sm-text-primary);
  font-weight: var(--sm-fw-semibold);
}

/* ---------- 市场筛选控制台 ---------- */

.console {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-3);
  padding: var(--sm-space-3) var(--sm-space-4);
  border-radius: var(--sm-radius-lg);
  box-shadow: var(--sm-shadow-1);
}

.console__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--sm-space-3);
  flex-wrap: wrap;
}

.console__titles {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-1);
  min-width: 0;
}

.console__hint {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-xs);
  line-height: 1.6;
}

.console__foot {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
  line-height: 1.5;
}

/* ---------- 本页成交时间轴 ---------- */

.timeline {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-3);
  padding: var(--sm-space-3) var(--sm-space-4);
  border-radius: var(--sm-radius-lg);
  box-shadow: var(--sm-shadow-1);
}

.timeline__head {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-1);
}

.timeline__title {
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-md);
  font-weight: var(--sm-fw-semibold);
}

.timeline__hint {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-xs);
  line-height: 1.55;
}

.timeline__rail {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.timeline__item {
  position: relative;
  display: grid;
  grid-template-columns: 82px 12px minmax(0, 1fr);
  align-items: start;
  gap: var(--sm-space-2);
}

/* 连接线只画到下一项，最后一项自然结束。 */
.timeline__item::before {
  content: '';
  position: absolute;
  top: 14px;
  bottom: calc(-1 * var(--sm-space-2));
  left: 96px;
  width: 1px;
  background: linear-gradient(180deg, rgba(34, 211, 238, 0.35), rgba(167, 139, 250, 0.08));
}

.timeline__item:last-child::before {
  display: none;
}

.timeline__date {
  padding-top: 2px;
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}

.timeline__dot {
  width: 7px;
  height: 7px;
  margin: 6px auto 0;
  border-radius: 50%;
  background: var(--sm-accent-cyan);
  box-shadow: 0 0 0 3px rgba(34, 211, 238, 0.12);
}

.timeline__body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.timeline__row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--sm-space-2);
}

.timeline__meta {
  display: flex;
  align-items: center;
  gap: var(--sm-space-2);
  flex: 0 0 auto;
}

.timeline__player {
  overflow: hidden;
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-sm);
  font-weight: var(--sm-fw-medium);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.timeline__fee {
  color: var(--sm-text);
  font-size: var(--sm-fs-sm);
  font-weight: var(--sm-fw-semibold);
}

.timeline__clubs {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
  overflow-wrap: anywhere;
}

.timeline__bar {
  height: 2px;
  border-radius: 2px;
  background: rgba(22, 37, 59, 0.9);
  overflow: hidden;
}

.timeline__bar i {
  display: block;
  height: 100%;
  border-radius: 2px;
  background: linear-gradient(90deg, rgba(34, 211, 238, 0.6), rgba(167, 139, 250, 0.75));
}

@media (max-width: 640px) {
  .console,
  .timeline {
    padding: var(--sm-space-3);
  }

  /* 单列布局下取消跨列，避免隐式网格列造成横向溢出。 */
  .filter-field--wide {
    grid-column: auto;
  }

  .timeline__item {
    grid-template-columns: 64px 10px minmax(0, 1fr);
  }

  .timeline__item::before {
    left: 79px;
  }
}

.deal-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: var(--sm-space-4);
  margin-top: var(--sm-space-3);
}

.deal-block {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-2);
  padding: var(--sm-space-3);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-md);
  background: var(--sm-surface-2);
}

.deal-list {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-1);
  margin: 0;
  padding-left: 0;
  list-style: none;
  font-size: var(--sm-fs-xs);
  color: var(--sm-text-2);
}

.deal-list li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sm-space-2);
}

.deal-verdict {
  font-size: var(--sm-fs-md);
  font-weight: var(--sm-fw-semibold);
  color: var(--sm-text);
}

.deal-gaps {
  margin-top: var(--sm-space-3);
}

.review-summary {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: var(--sm-space-3);
  padding: var(--sm-space-3) var(--sm-space-4);
  border-bottom: 1px solid var(--sm-border);
}

.candidate-list {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-2);
  padding: var(--sm-space-3) var(--sm-space-4);
}

.candidate {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sm-space-3);
  padding: var(--sm-space-2) var(--sm-space-3);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-md);
  background: var(--sm-surface-2);
}

.candidate__main {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.candidate__name {
  font-size: var(--sm-fs-sm);
  font-weight: var(--sm-fw-medium);
  color: var(--sm-text);
}

.candidate__actions {
  display: flex;
  gap: var(--sm-space-2);
}

.review-note {
  padding: var(--sm-space-2) var(--sm-space-4);
  border-top: 1px solid var(--sm-border);
}

.filter-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(164px, 1fr));
  gap: var(--sm-space-3);
  align-items: end;
}

.filter-field {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-1);
  min-width: 0;
}

.filter-field--wide {
  grid-column: span 2;
}

.filter-field--pair {
  min-width: 208px;
}

.filter-field--actions {
  flex-direction: row;
  justify-content: flex-end;
}

.filter-pair {
  display: flex;
  align-items: center;
  gap: var(--sm-space-1);
}

.filter-pair :deep(.el-input-number) {
  width: 88px;
}

.filter-pair__dash {
  color: var(--sm-text-3);
}

.filter-field :deep(.el-input-number),
.filter-field :deep(.el-date-editor) {
  width: 100%;
}

.coverage-chips {
  display: flex;
  align-items: center;
  gap: var(--sm-space-1);
  flex-wrap: wrap;
}

.warnings {
  margin-top: var(--sm-space-3);
}

.components {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-2);
}

.components__table {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: var(--sm-fs-xs);
}

.components__head,
.components__row {
  display: grid;
  grid-template-columns: 1fr 0.8fr 1fr 0.9fr 1.4fr;
  gap: var(--sm-space-2);
  align-items: baseline;
}

.components__head--factors,
.components__row--factors {
  grid-template-columns: 1.2fr 1fr 1fr 0.8fr 0.8fr;
}

.components__head {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}

.components__row {
  padding-top: 2px;
  border-top: 1px solid var(--sm-border);
  color: var(--sm-text-2);
}

.components__meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sm-space-3);
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}

.similar-form {
  display: flex;
  flex-wrap: wrap;
  align-items: end;
  gap: var(--sm-space-3);
}

.similar-target {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--sm-space-3);
  margin-bottom: var(--sm-space-2);
}

.similar-target__name {
  color: var(--sm-text);
  font-size: var(--sm-fs-lg);
  font-weight: var(--sm-fw-semibold);
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sm-space-1);
}

.chip {
  padding: 1px 6px;
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-sm);
  background: var(--sm-surface-2);
  color: var(--sm-text-2);
  font-size: var(--sm-fs-2xs);
  font-variant-numeric: tabular-nums;
}

.warnings-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin: 0 0 var(--sm-space-2);
  padding-left: var(--sm-space-4);
  color: var(--sm-warn);
  font-size: var(--sm-fs-2xs);
}

/* ---------- 重点俱乐部卡片 ---------- */

.club-cards {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-3);
}

.club-cards__head {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.club-cards__title {
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-md);
  font-weight: var(--sm-fw-semibold);
}

.club-cards__hint {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-xs);
  line-height: 1.55;
}

.club-cards__grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--sm-space-3);
}

.club-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  min-width: 0;
  padding: var(--sm-space-3);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-md);
  background: var(--sm-surface-2);
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.15s ease, transform 0.15s ease;
}

.club-card:hover {
  border-color: var(--sm-border-strong);
  transform: translateY(-1px);
}

.club-card:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--sm-accent-cyan) 55%, transparent);
  outline-offset: 1px;
}

.club-card__name {
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-sm);
  font-weight: var(--sm-fw-semibold);
}

.club-card__league {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}

.club-card__line {
  color: var(--sm-text-2);
  font-size: var(--sm-fs-xs);
  line-height: 1.5;
}

.club-card__hint {
  margin-top: var(--sm-space-1);
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}

.club-kpis {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: var(--sm-space-3);
  margin-bottom: var(--sm-space-3);
}

.club-kpi {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--sm-space-3);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-md);
  background: var(--sm-surface-2);
}

.club-kpi__value {
  color: var(--sm-text);
  font-size: var(--sm-fs-lg);
  font-weight: var(--sm-fw-semibold);
  text-align: right;
}

.club-kpi__hint {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
  text-align: right;
}

.club-coverage {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: var(--sm-space-2);
}
</style>



