/**
 * 球员详情：档案、属性分组、成长曲线、发展归因、估值、相似成交与角色评分。
 */

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { asApiError, type ApiError } from '../api/client'
import { getPlayer, getPlayerDevelopment, getPlayerHistory } from '../api/players'
import { getPlayerStatus } from '../api/status'
import { evaluateRole, listRoles } from '../api/scouting'
import { getSimilarTransfers, getValuation } from '../api/transfers'
import {
  addWatchlistItem,
  deleteWatchlistItem,
  listWatchlist,
  patchWatchlistItem,
} from '../api/watchlist'
import AttributeBar from '../components/AttributeBar.vue'
import ChartCard from '../components/ChartCard.vue'
import ConfidenceTag from '../components/ConfidenceTag.vue'
import DataTable from '../components/DataTable.vue'
import EChart from '../components/EChart.vue'
import EmptyState from '../components/EmptyState.vue'
import ErrorState from '../components/ErrorState.vue'
import InsightPanel from '../components/InsightPanel.vue'
import LoadingBlock from '../components/LoadingBlock.vue'
import NumberCell from '../components/NumberCell.vue'
import PageHeader from '../components/PageHeader.vue'
import ScoreBadge from '../components/ScoreBadge.vue'
import SectionCard from '../components/SectionCard.vue'
import StatHeader from '../components/StatHeader.vue'
import StatStrip from '../components/StatStrip.vue'
import type {
  DevelopmentPeriod,
  PlayerAttribute,
  PlayerDetail,
  PlayerDevelopmentResponse,
  PlayerHistoryResponse,
  Valuation,
} from '../types/players'
import type { RoleEvaluation, RoleTemplate } from '../types/scouting'
import type { SimilarTransferItem, SimilarTransfersResponse } from '../types/transfers'
import type { WatchlistItem } from '../types/watchlist'
import type { PlayerStatus } from '../types/status'
import type { TableColumn } from '../types/table'
import type { InsightItem, InsightTone, StatItem } from '../types/ui'
import { useCompareStore } from '../stores/compare'
import { useSessionStore } from '../stores/session'
import { buildAppearanceChart, buildGrowthChart, buildRadarChart } from '../utils/chart'
import { rememberRecent } from '../utils/recent'
import {
  EMPTY,
  displayText,
  formatDate,
  formatDateTime,
  formatDecimal,
  formatInt,
  formatMoney,
  formatPercent,
  formatSignedInt,
  formatSignedMoney,
  toFiniteNumber,
} from '../utils/format'
import {
  attributionHint,
  attributionTitle,
  attributeCategoryLabel,
  positionGroupLabel,
  positionLabel,
  similarityFactorLabel,
  sourceLabel,
  transferStatusLabel,
  valuationAdjustmentLabel,
  valuationMethodLabel,
} from '../utils/labels'

const route = useRoute()
const session = useSessionStore()

const detail = ref<PlayerDetail | null>(null)
const detailLoading = ref(false)
const detailError = ref<ApiError | null>(null)

const history = ref<PlayerHistoryResponse | null>(null)
const historyLoading = ref(false)
const historyError = ref<ApiError | null>(null)

const development = ref<PlayerDevelopmentResponse | null>(null)
const developmentLoading = ref(false)
const developmentError = ref<ApiError | null>(null)

const status = ref<PlayerStatus | null>(null)
const statusLoading = ref(false)
const statusError = ref<ApiError | null>(null)

const valuation = ref<Valuation | null>(null)
const valuationLoading = ref(false)
const valuationError = ref<ApiError | null>(null)

const similar = ref<SimilarTransfersResponse | null>(null)
const similarLoading = ref(false)
const similarError = ref<ApiError | null>(null)

const roles = ref<RoleTemplate[]>([])
const rolesLoading = ref(false)
const rolesError = ref<ApiError | null>(null)
const selectedRoleKey = ref('')
const evaluation = ref<RoleEvaluation | null>(null)
const evaluationLoading = ref(false)
const evaluationError = ref<ApiError | null>(null)

const watchItem = ref<WatchlistItem | null>(null)
const watchLoading = ref(false)
const watchError = ref<ApiError | null>(null)
/** Last instance id loaded, used to clear stale panels when the route changes. */
let loadedInstanceId: number | null = null
/** Monotonic token: responses from an older player/reload never write into the current page. */
let activeToken = 0

/** Instance id from the route; `null` for a malformed URL. */
const instanceId = computed(() => {
  const raw = route.params.id
  const parsed = Number.parseInt(Array.isArray(raw) ? (raw[0] ?? '') : (raw ?? ''), 10)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null
})

const summary = computed(() => detail.value?.summary ?? null)

const pageTitle = computed(() => (summary.value ? displayText(summary.value.name) : '球员详情'))

/** 头像缩写：仅由姓名派生，不引入额外字段。 */
const initials = computed(() => {
  const name = summary.value?.name?.trim() ?? ''
  if (!name) return EMPTY
  const parts = name.split(/\s+/).filter(Boolean)
  if (parts.length >= 2) return `${parts[0]!.charAt(0)}${parts[1]!.charAt(0)}`.toUpperCase()
  return name.slice(0, 2).toUpperCase()
})

/** 档案速览：全部复用 detail / summary 中已有字段。 */
const profileFacts = computed(() => [
  { label: '生日', value: formatDate(summary.value?.birth_date) },
  { label: '入档', value: formatDate(detail.value?.first_seen) },
  { label: '最近观测', value: formatDate(detail.value?.last_seen) },
  { label: '快照次数', value: formatInt(detail.value?.snapshot_count) },
  { label: '合同到期', value: formatDate(summary.value?.contract_end) },
  { label: '周薪（€）', value: formatMoney(summary.value?.wage) },
])

/** Currency used by valuation and comparable transfers. */
const currency = computed(() => valuation.value?.currency ?? 'EUR')

/** Attributes grouped by category, preserving the API order inside each group. */
const attributeGroups = computed(() => {
  const groups = new Map<string, PlayerAttribute[]>()
  for (const attribute of detail.value?.attributes ?? []) {
    const key = attribute.category || 'other'
    const bucket = groups.get(key)
    if (bucket) bucket.push(attribute)
    else groups.set(key, [attribute])
  }
  return Array.from(groups.entries()).map(([category, items]) => ({
    category,
    label: attributeCategoryLabel(category),
    items,
  }))
})

/** 能力结构雷达：类别均值（1–20），只绘制有数据的类别，不是 CA/PA。 */
const attributeRadarOption = computed(() => {
  const dimensions = attributeGroups.value
    .map((group) => {
      const values = group.items.map((item) => item.value).filter((value): value is number => value !== null)
      return {
        label: group.label,
        value: values.length > 0 ? Number((values.reduce((sum, value) => sum + value, 0) / values.length).toFixed(1)) : null,
      }
    })
    .filter((entry): entry is { label: string; value: number } => entry.value !== null)
  if (dimensions.length < 3) return null
  return buildRadarChart(
    dimensions.map((entry) => entry.label),
    [{ name: summary.value?.name ?? '当前球员', values: dimensions.map((entry) => entry.value) }],
    20,
  )
})

const historyPoints = computed(() => history.value?.points ?? [])

const growthOption = computed(() => buildGrowthChart(historyPoints.value))
const appearanceOption = computed(() => buildAppearanceChart(historyPoints.value))

const historyFootnote = computed(() => {
  const coverage = history.value?.coverage
  if (!coverage) return ''
  return `快照点 ${formatInt(coverage.points)} 个 · 属性覆盖 ${formatPercent(coverage.attributes)} · 缺失点以断线显示，不做插值`
})

/** Attribution rows split into 事实 / 相关性 / 推测, each rendered separately. */
const attributionGroups = computed(() =>
  ['fact', 'correlation', 'speculation'].map((kind) => ({
    kind,
    title: attributionTitle(kind),
    hint: attributionHint(kind),
    items: (development.value?.attributions ?? []).filter((item) => item.kind === kind),
  })),
)

const developmentColumns: TableColumn<DevelopmentPeriod>[] = [
  {
    prop: 'period_start',
    label: '区间',
    minWidth: 190,
    formatter: (row) => `${formatDate(row.period_start)} → ${formatDate(row.period_end)}`,
  },
  { prop: 'ca_delta', label: 'CA Δ', width: 84, align: 'right' },
  { prop: 'market_value_delta', label: '身价 Δ', width: 118, align: 'right' },
  { prop: 'minutes', label: '分钟', width: 88, align: 'right' },
  { prop: 'appearances', label: '出场', width: 76, align: 'right' },
  { prop: 'goals', label: '进球', width: 72, align: 'right' },
  { prop: 'assists', label: '助攻', width: 72, align: 'right' },
]

const evaluationColumns: TableColumn<{ key: string; name: string; weight: number; value: number | null; contribution: number | null }>[] = [
  { prop: 'name', label: '属性', minWidth: 130 },
  { prop: 'weight', label: '权重', width: 88, align: 'right' },
  { prop: 'value', label: '数值', width: 76, align: 'right' },
  { prop: 'contribution', label: '贡献', width: 88, align: 'right' },
]

const similarColumns: TableColumn<SimilarTransferItem>[] = [
  {
    prop: 'transfer',
    label: '球员',
    minWidth: 150,
    formatter: (row) => displayText(row.transfer.player_name),
  },
  { prop: 'similarity', label: '相似度', width: 92, align: 'right' },
  {
    prop: 'transfer_date',
    label: '日期',
    width: 108,
    formatter: (row) => formatDate(row.transfer.transfer_date),
  },
  {
    prop: 'clubs',
    label: '俱乐部',
    minWidth: 190,
    formatter: (row) => `${displayText(row.transfer.from_club)} → ${displayText(row.transfer.to_club)}`,
  },
  {
    prop: 'fee',
    label: '费用',
    width: 116,
    align: 'right',
    formatter: (row) => formatMoney(row.transfer.effective_fee),
  },
  {
    prop: 'ca',
    label: '成交时 CA',
    width: 96,
    align: 'right',
    formatter: (row) => formatInt(row.transfer.player_ca_at_transfer),
  },
  {
    prop: 'status',
    label: '状态',
    width: 88,
    formatter: (row) => transferStatusLabel(row.transfer.status),
  },
]

/** Effective similarity weights as a readable list. */
const effectiveWeights = computed(() =>
  Object.entries(similar.value?.effective_weights ?? {}).map(([key, value]) => ({
    key,
    label: similarityFactorLabel(key),
    value,
  })),
)

/** Valuation basis adjustments; the backend mixes numeric factors and text notes. */
const valuationAdjustments = computed(() =>
  Object.entries(valuation.value?.basis?.adjustment ?? {}).map(([key, value]) => ({
    key,
    label: valuationAdjustmentLabel(key),
    numeric: toFiniteNumber(value),
    text: typeof value === 'string' ? value : null,
  })),
)

/** Numeric adjustment factors rendered as multipliers. */
const valuationAdjustmentFactors = computed(() =>
  valuationAdjustments.value.filter((item) => item.numeric !== null),
)

/** Textual adjustment notes rendered as explanation lines. */
const valuationAdjustmentNotes = computed(() =>
  valuationAdjustments.value.filter((item) => item.numeric === null && item.text !== null),
)

const valuationWarnings = computed(() => valuation.value?.warnings ?? [])

/** True when the backend refuses a precise range because the sample is too small. */
const valuationInsufficient = computed(() => valuation.value?.insufficient_sample === true)

/** 合同剩余月数折算口径：30.44 天/月，仅用于摘要中的到期提醒。 */
const CONTRACT_MONTH_MS = 1000 * 60 * 60 * 24 * 30.44

/** 合同剩余月数（向下取整，不足一个月按 0 个月计）；无到期日或日期不可解析时为 null。 */
const contractMonthsLeft = computed<number | null>(() => {
  const end = summary.value?.contract_end
  if (!end) return null
  const endAt = new Date(end).getTime()
  if (Number.isNaN(endAt)) return null
  return Math.floor((endAt - Date.now()) / CONTRACT_MONTH_MS)
})

/** 合同摘要文案：缺失、已到期、12 个月内与窗口外分开说明。 */
const contractText = computed(() => {
  const months = contractMonthsLeft.value
  if (!summary.value?.contract_end || months === null) return '合同数据缺失'
  const date = formatDate(summary.value.contract_end)
  if (months < 0) return `合同已于 ${date} 到期`
  if (months < 12) return `合同 ${date} 到期（约 ${months} 个月），不足 12 个月`
  return `合同 ${date} 到期（约 ${months} 个月），未进入 12 个月窗口`
})

/** 估值偏离口径：可比成交中位与当前身价相差 ±10% 以内视为接近。 */
const VALUATION_BAND = 0.1

/**
 * 决策摘要：只使用已加载的合同、状态、估值、成长与角色评分字段，最多 4 条。
 * 合同与状态合并为一条，避免挤掉其余维度；缺失字段明确写出，不当作否或 0。
 */
const decisionSummary = computed<{ tone: InsightTone; items: InsightItem[] }>(() => {
  const items: InsightItem[] = []
  const months = contractMonthsLeft.value
  const snapshot = status.value?.current ?? null

  const statusRisk =
    snapshot !== null &&
    (snapshot.flags.listed === true || snapshot.flags.loan_listed === true || snapshot.injury.injured === true)
  const statusText = snapshot
    ? `挂牌出售 ${triState(snapshot.flags.listed)} · 挂牌出租 ${triState(snapshot.flags.loan_listed)} · 伤病 ${triState(snapshot.injury.injured)}`
    : statusLoading.value && !status.value
      ? '状态数据加载中'
      : '状态数据未返回，挂牌与伤病未知'
  items.push({
    label: '合同与状态',
    text: `${contractText.value}；${statusText}。`,
    tone: statusRisk || (months !== null && months < 12) ? 'warning' : 'neutral',
  })

  const val = valuation.value
  const marketValue = toFiniteNumber(summary.value?.market_value)
  const mid = val ? toFiniteNumber(val.mid) : null
  if (!val && valuationLoading.value) {
    items.push({ label: '估值', text: '估值加载中。', tone: 'neutral' })
  } else if (!val) {
    items.push({ label: '估值', text: '无估值数据，样本不足，未估值。', tone: 'neutral' })
  } else if (val.insufficient_sample) {
    items.push({ label: '估值', text: '样本不足，未估值。', tone: 'neutral' })
  } else if (mid === null) {
    items.push({ label: '估值', text: '估值中位缺失，无法与身价比较。', tone: 'neutral' })
  } else if (marketValue === null || marketValue <= 0) {
    items.push({
      label: '估值',
      text: `相似成交中位 ${formatMoney(mid)} ${currency.value}，当前身价缺失，无法比较。`,
      tone: 'neutral',
    })
  } else {
    const deviation = (mid - marketValue) / marketValue
    const percent = formatPercent(Math.abs(deviation), 0)
    if (Math.abs(deviation) <= VALUATION_BAND) {
      items.push({
        label: '估值',
        text: `相似成交中位 ${formatMoney(mid)} ${currency.value}，与身价 ${formatMoney(marketValue)} 接近（偏差 ${percent}，阈值 ±10%）。`,
        tone: 'neutral',
      })
    } else if (deviation > 0) {
      items.push({
        label: '估值',
        text: `相似成交中位 ${formatMoney(mid)} ${currency.value}，高于身价 ${formatMoney(marketValue)} ${percent}（阈值 ±10%），身价偏低。`,
        tone: 'success',
      })
    } else {
      items.push({
        label: '估值',
        text: `相似成交中位 ${formatMoney(mid)} ${currency.value}，低于身价 ${formatMoney(marketValue)} ${percent}（阈值 ±10%），身价偏高。`,
        tone: 'warning',
      })
    }
  }

  const dev = development.value
  const caDelta = dev ? toFiniteNumber(dev.summary.ca_delta) : null
  const valueDelta = dev ? toFiniteNumber(dev.summary.market_value_delta) : null
  if (!dev && developmentLoading.value) {
    items.push({ label: '成长', text: '成长数据加载中。', tone: 'neutral' })
  } else if (!dev || (caDelta === null && valueDelta === null)) {
    items.push({ label: '成长', text: '快照不足，无法计算 CA 与身价变化。', tone: 'neutral' })
  } else {
    const growthTone: InsightTone = caDelta === null ? 'neutral' : caDelta > 0 ? 'success' : caDelta < 0 ? 'warning' : 'neutral'
    items.push({
      label: '成长',
      text: `CA 变化 ${formatSignedInt(caDelta)}；身价变化 ${formatSignedMoney(valueDelta)}（窗口 ${formatDate(dev.summary.window_start)} → ${formatDate(dev.summary.window_end)}）。`,
      tone: growthTone,
    })
  }

  const score = evaluation.value?.score ?? null
  const evaluationCoverage = evaluation.value?.coverage ?? null
  if (score !== null) {
    const coverageTone: InsightTone =
      evaluationCoverage !== null && evaluationCoverage < 0.6 ? 'warning' : 'neutral'
    items.push({
      label: '角色评分',
      text: `${displayText(evaluation.value?.role_name)} ${formatDecimal(score, 1)} 分，属性覆盖 ${formatPercent(evaluationCoverage)}。`,
      tone: coverageTone,
    })
  }

  const tone: InsightTone = items.some((item) => item.tone === 'warning' || item.tone === 'danger') ? 'warning' : 'info'
  return { tone, items: items.slice(0, 4) }
})

/** 顶部关键事实：替代原事实卡片网格，缺失值保持 —。 */
const keyStats = computed<StatItem[]>(() => {
  const months = contractMonthsLeft.value
  const contractTone: StatItem['tone'] = months !== null && months < 12 ? 'warning' : 'default'
  const contractHint =
    months === null ? '无合同日期' : months < 0 ? '已到期' : `剩余约 ${months} 个月`
  return [
    { label: 'CA', value: formatInt(summary.value?.ca), hint: '当前能力' },
    { label: 'PA', value: formatInt(summary.value?.pa), hint: '潜力上限' },
    { label: '身价', value: formatMoney(summary.value?.market_value), hint: '币种默认 EUR' },
    { label: '周薪', value: formatMoney(summary.value?.wage), hint: '每周 · EUR' },
    { label: '合同到期', value: formatDate(summary.value?.contract_end), hint: contractHint, tone: contractTone },
    { label: '数据完整度', value: formatPercent(summary.value?.data_completeness), hint: '非空字段比例' },
  ]
})

/** Load the profile, history and development panels. */
async function loadCore(id: number, token: number = activeToken): Promise<void> {
  detailLoading.value = true
  detailError.value = null
  historyLoading.value = true
  historyError.value = null
  developmentLoading.value = true
  developmentError.value = null

  await Promise.all([
    (async () => {
      try {
        const next = await getPlayer(id)
        if (token !== activeToken) return
        detail.value = next
        session.markSources([next.summary.source])
        rememberRecent({
          entity_type: 'player',
          entity_id: next.summary.instance_id,
          display_name: next.summary.name,
          subtitle: [next.summary.position, next.summary.club].filter(Boolean).join(' · '),
          navigation_target: `/players/${next.summary.instance_id}`,
          save_id: session.activeSaveId,
        })
      } catch (caught) {
        if (token !== activeToken) return
        detailError.value = asApiError(caught)
        detail.value = null
      } finally {
        if (token === activeToken) detailLoading.value = false
      }
    })(),
    (async () => {
      try {
        const next = await getPlayerHistory(id)
        if (token !== activeToken) return
        history.value = next
      } catch (caught) {
        if (token !== activeToken) return
        historyError.value = asApiError(caught)
        history.value = null
      } finally {
        if (token === activeToken) historyLoading.value = false
      }
    })(),
    (async () => {
      try {
        const next = await getPlayerDevelopment(id)
        if (token !== activeToken) return
        development.value = next
      } catch (caught) {
        if (token !== activeToken) return
        developmentError.value = asApiError(caught)
        development.value = null
      } finally {
        if (token === activeToken) developmentLoading.value = false
      }
    })(),
  ])
}

/** Load the comparable-transfer valuation. */
async function loadValuation(id: number, token: number = activeToken): Promise<void> {
  valuationLoading.value = true
  valuationError.value = null
  try {
    const next = await getValuation(id)
    if (token !== activeToken) return
    valuation.value = next
  } catch (caught) {
    if (token !== activeToken) return
    valuationError.value = asApiError(caught)
    valuation.value = null
  } finally {
    if (token === activeToken) valuationLoading.value = false
  }
}

/** Load comparable transfers. */
async function loadSimilar(id: number, token: number = activeToken): Promise<void> {
  similarLoading.value = true
  similarError.value = null
  try {
    const next = await getSimilarTransfers(id, 20)
    if (token !== activeToken) return
    similar.value = next
  } catch (caught) {
    if (token !== activeToken) return
    similarError.value = asApiError(caught)
    similar.value = null
  } finally {
    if (token === activeToken) similarLoading.value = false
  }
}

/** Load role templates once per session. */
async function loadRoles(): Promise<void> {
  rolesLoading.value = true
  rolesError.value = null
  try {
    const response = await listRoles()
    roles.value = response.items ?? []
    if (!selectedRoleKey.value && roles.value.length > 0) {
      selectedRoleKey.value = roles.value[0]?.key ?? ''
    }
  } catch (caught) {
    rolesError.value = asApiError(caught)
    roles.value = []
  } finally {
    rolesLoading.value = false
  }
}

/** Score the player against the selected role. */
async function runEvaluation(): Promise<void> {
  const id = instanceId.value
  const roleKey = selectedRoleKey.value
  if (id === null || !roleKey) return
  evaluationLoading.value = true
  evaluationError.value = null
  try {
    const next = await evaluateRole({ instance_id: id, role_key: roleKey })
    if (instanceId.value !== id || selectedRoleKey.value !== roleKey) return
    evaluation.value = next
  } catch (caught) {
    if (instanceId.value !== id || selectedRoleKey.value !== roleKey) return
    evaluationError.value = asApiError(caught)
    evaluation.value = null
  } finally {
    if (instanceId.value === id && selectedRoleKey.value === roleKey) evaluationLoading.value = false
  }
}

/** Read whether the player is already tracked. */
async function loadWatchState(token: number = activeToken): Promise<void> {
  watchLoading.value = true
  watchError.value = null
  try {
    const response = await listWatchlist({ saveId: session.activeSaveId ?? undefined })
    if (token !== activeToken) return
    watchItem.value = (response.items ?? []).find((item) => item.instance_id === instanceId.value) ?? null
  } catch (caught) {
    if (token !== activeToken) return
    watchError.value = asApiError(caught)
    watchItem.value = null
  } finally {
    if (token === activeToken) watchLoading.value = false
  }
}

/** Add or remove the player from the watchlist. */
async function toggleWatch(next: boolean): Promise<void> {
  const id = instanceId.value
  if (id === null) return
  watchLoading.value = true
  watchError.value = null
  try {
    if (next) {
      watchItem.value = await addWatchlistItem({ instance_id: id })
      ElMessage.success('已加入关注名单')
    } else if (watchItem.value) {
      await deleteWatchlistItem(watchItem.value.id)
      watchItem.value = null
      ElMessage.success('已从关注名单移除')
    }
  } catch (caught) {
    const error = asApiError(caught)
    watchError.value = error
    ElMessage.error(`关注状态更新失败：${error.message}`)
  } finally {
    watchLoading.value = false
  }
}

const router = useRouter()
const compare = useCompareStore()
const noteOpen = ref(false)
const noteSaving = ref(false)
const noteText = ref('')

/** Open the personal note editor of the watched player. */
function openNote(): void {
  noteText.value = watchItem.value?.note ?? ''
  noteOpen.value = true
}

/** Persist the personal note; empty text clears it without touching tags or list. */
async function saveNote(): Promise<void> {
  const id = instanceId.value
  if (id === null) return
  noteSaving.value = true
  try {
    // 备注属于关注名单；未关注时先自动关注，再写入备注。
    if (!watchItem.value) {
      await addWatchlistItem({ instance_id: id })
      await loadWatchState()
    }
    const item = watchItem.value
    if (!item) throw new Error('关注失败，无法保存备注')
    const updated = await patchWatchlistItem(item.id, { note: noteText.value.trim() })
    watchItem.value = { ...item, ...updated }
    noteOpen.value = false
    ElMessage.success('备注已保存')
  } catch (caught) {
    ElMessage.error(`备注保存失败：${asApiError(caught).message}`)
  } finally {
    noteSaving.value = false
  }
}

/** Add the player to the local comparison selection. */
function addToCompare(): void {
  const id = instanceId.value
  if (id === null) return
  compare.ensureSave(session.activeSaveId)
  const result = compare.add(id)
  if (result === 'added') ElMessage.success(`已加入对比（${compare.count}/4）`)
  else if (result === 'exists') ElMessage.info('该球员已在对比中')
  else ElMessage.warning('对比最多 4 名球员，请先在对比页移除一名')
}

/** Ask the AI scout assistant for a report grounded in this player's data. */
function generateReport(): void {
  const id = instanceId.value
  if (id === null) return
  const name = summary.value?.name ?? '该球员'
  void router.push({ path: '/agent', query: { instance_id: String(id), q: `分析 ${name} 的能力、成长与估值` } })
}

/** Placing, injury, loan and pending-move status (P0-2/P0-4). */
async function loadStatus(id: number, token: number = activeToken): Promise<void> {
  statusLoading.value = true
  statusError.value = null
  try {
    const next = await getPlayerStatus(id)
    if (token !== activeToken) return
    status.value = next
  } catch (caught) {
    if (token !== activeToken) return
    statusError.value = asApiError(caught)
    status.value = null
  } finally {
    if (token === activeToken) statusLoading.value = false
  }
}

/** Render an arbitrary recorded change value; booleans become 是/否, null becomes 未知. */
function changeValue(value: unknown): string {
  if (value === null || value === undefined) return '未知'
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value === 'number') return String(value)
  if (typeof value === 'string') return displayText(value)
  return '未知'
}

/** Render a three-valued flag: unknown is "未知", never "否". */
function triState(value: boolean | null | undefined): string {
  if (value === null || value === undefined) return '未知'
  return value ? '是' : '否'
}

/** Reload every panel of this player. */
function reloadAll(): void {
  const id = instanceId.value
  if (id === null) return
  const token = ++activeToken
  void loadCore(id, token)
  void loadValuation(id, token)
  void loadSimilar(id, token)
  void loadStatus(id, token)
  void loadWatchState(token)
  if (selectedRoleKey.value) void runEvaluation()
}

watch(
  [() => instanceId.value, () => session.dataRevision],
  () => {
    const id = instanceId.value
    evaluation.value = null
    if (id === null) {
      detail.value = null
      history.value = null
      development.value = null
      valuation.value = null
      similar.value = null
      loadedInstanceId = null
      return
    }
    if (id !== loadedInstanceId) {
      detail.value = null
      history.value = null
      development.value = null
      valuation.value = null
      similar.value = null
      loadedInstanceId = id
    }
    reloadAll()
  },
  { immediate: true },
)

watch(selectedRoleKey, () => {
  if (selectedRoleKey.value) void runEvaluation()
})

void loadRoles()
</script>

<template>
  <div class="sm-page">
    <PageHeader
      :title="pageTitle"
      :description="summary ? `${positionLabel(summary.position)} · ${positionGroupLabel(summary.position_group)} · ${displayText(summary.club)}` : '读取球员档案、成长曲线与估值依据'"
      back-to="/players"
      back-label="返回球员中心"
    >
      <template #meta>
        <el-tag v-if="summary" size="small" type="info" disable-transitions>来源：{{ sourceLabel(summary.source) }}</el-tag>
        <span v-if="summary" class="sm-text-xs sm-text-faint">
          实例 ID {{ summary.instance_id }} · 最近观测 {{ formatDateTime(summary.observed_at) }}
        </span>
        <el-tag v-if="watchItem" size="small" type="success" disable-transitions>关注：{{ displayText(watchItem.tag) }}</el-tag>
      </template>
      <template #actions>
        <el-tooltip
          :disabled="session.capabilities.watchlist"
          content="后端未启用 watchlist 能力"
          placement="top"
        >
          <span class="watch-toggle">
            <span class="sm-text-xs sm-text-muted">关注名单</span>
            <el-switch
              :model-value="watchItem !== null"
              :loading="watchLoading"
              :disabled="!session.capabilities.watchlist"
              size="small"
              @update:model-value="(value) => toggleWatch(value === true)"
            />
          </span>
        </el-tooltip>
        <el-button size="small" @click="openNote">编辑备注</el-button>
        <el-button size="small" @click="addToCompare">加入对比</el-button>
        <el-button size="small" @click="generateReport">生成球员报告</el-button>
        <el-button size="small" :loading="detailLoading" @click="reloadAll">刷新</el-button>
      </template>
    </PageHeader>

    <el-dialog v-model="noteOpen" title="个人备注" width="460px">
      <el-input
        v-model="noteText"
        type="textarea"
        :rows="4"
        maxlength="512"
        show-word-limit
        placeholder="记录观察结论、谈判计划或需要复核的问题"
      />
      <p class="sm-text-2xs sm-text-faint">备注只保存到本存档的关注名单，不会被后续导入覆盖。</p>
      <template #footer>
        <el-button size="small" @click="noteOpen = false">取消</el-button>
        <el-button size="small" type="primary" :loading="noteSaving" @click="saveNote">保存</el-button>
      </template>
    </el-dialog>

    <EmptyState
      v-if="instanceId === null"
      title="无效的球员 ID"
      description="路由参数必须是正整数实例 ID，例如 /players/11。"
    >
      <router-link to="/players"><el-button size="small">返回球员中心</el-button></router-link>
    </EmptyState>

    <template v-else>
      <ErrorState
        v-if="detailError && !detail"
        :error="detailError"
        :title="detailError.isNotFound ? '球员不存在' : '球员档案加载失败'"
        @retry="reloadAll"
      />

      <LoadingBlock v-else-if="detailLoading && !detail" :rows="8" label="正在加载球员档案" />

      <template v-else-if="detail && summary">
        <section class="player-hero" aria-label="球员档案概览">
          <div class="player-hero__glow" aria-hidden="true" />

          <div class="player-hero__identity">
            <div class="player-hero__avatar" aria-hidden="true">{{ initials }}</div>
            <div class="player-hero__id">
              <h2 class="player-hero__name">{{ displayText(summary.name) }}</h2>
              <p class="player-hero__sub">
                {{ positionLabel(summary.position) }} · {{ positionGroupLabel(summary.position_group) }} ·
                {{ displayText(summary.club) }}
              </p>
              <div class="player-hero__chips">
                <span class="player-chip">
                  年龄 <strong>{{ summary.age === null ? EMPTY : `${summary.age} 岁` }}</strong>
                </span>
                <span class="player-chip">国籍 <strong>{{ displayText(summary.nationality) }}</strong></span>
                <span class="player-chip">合同到期 <strong>{{ formatDate(summary.contract_end) }}</strong></span>
                <ConfidenceTag :confidence="valuation?.confidence ?? null" />
              </div>
              <p class="player-hero__note">「—」表示该字段暂无数据，不会用 0 代替。</p>
              <router-link
                class="player-hero__transfer"
                :to="`/transfer-director?instance_id=${summary.instance_id}&tab=purchase`"
              >
                AI 交易分析：合同 · 条款 · 买入/出售报价 · 谈判
              </router-link>
              <div v-if="detail.tags.length > 0" class="player-hero__tags">
                <el-tag v-for="tag in detail.tags" :key="tag" size="small" type="info" disable-transitions>{{ tag }}</el-tag>
              </div>
            </div>
          </div>
        </section>

        <InsightPanel
          title="决策摘要"
          badge="规则生成"
          :tone="decisionSummary.tone"
          :items="decisionSummary.items"
          footnote="以上为规则生成摘要，不替代球探判断；缺失字段不参与计算"
        />

        <StatStrip :items="keyStats" />

        <nav class="player-sections" aria-label="球员详情区块">
          <a class="player-sections__link" href="#player-ability">能力</a>
          <a class="player-sections__link" href="#player-growth">表现与成长</a>
          <a class="player-sections__link" href="#player-transfer">转会与估值</a>
          <a class="player-sections__link" href="#player-status">状态与合同</a>
        </nav>

        <section id="player-ability" class="player-group" aria-labelledby="player-ability-title">
          <header class="player-group__head">
            <h2 id="player-ability-title" class="player-group__title">能力</h2>
            <p class="player-group__hint">属性与结构只描述当前快照，不代表潜力上限。</p>
          </header>

          <div class="sm-grid sm-grid--wide-left">
            <SectionCard title="球员属性" :subtitle="`按类别分组的 1–20 属性值（共 ${formatInt(detail.attributes.length)} 项）`">
              <EmptyState
                v-if="attributeGroups.length === 0"
                title="没有属性数据"
                description="当前快照没有记录任何属性键，常见于扫描器未启用 attributes 覆盖。"
                compact
              />
              <div v-else class="attribute-groups">
                <section v-for="group in attributeGroups" :key="group.category" class="attribute-card">
                  <header class="attribute-card__head">
                    <h3 class="attribute-card__title">{{ group.label }}</h3>
                    <span class="attribute-card__count">{{ group.items.length }} 项</span>
                  </header>
                  <div class="attribute-card__grid">
                    <AttributeBar
                      v-for="attribute in group.items"
                      :key="attribute.key"
                      :label="attribute.name"
                      :value="attribute.value"
                      :code="attribute.key"
                    />
                  </div>
                </section>
              </div>
              <template #footer>
                属性为 1–20 整数刻度；null 表示该属性未被扫描到，不按 0 处理。
              </template>
            </SectionCard>

            <ChartCard
              v-if="attributeRadarOption"
              title="能力结构雷达"
              subtitle="按属性类别汇总的 1–20 均值，用于观察结构差异"
              footnote="类别均值为该类属性的算术平均，仅用于查看能力结构，不代表 CA/PA，也不是综合评分。"
            >
              <EChart :option="attributeRadarOption" height="280px" aria-label="球员能力结构雷达" />
            </ChartCard>
          </div>
        </section>

        <section id="player-growth" class="player-group" aria-labelledby="player-growth-title">
          <header class="player-group__head">
            <h2 id="player-growth-title" class="player-group__title">表现与成长</h2>
            <p class="player-group__hint">走势、出场与发展归因均来自历史快照；缺失点不做插值。</p>
          </header>

          <div class="sm-grid sm-grid--2">
            <ChartCard
              title="能力与身价走势"
              subtitle="CA/PA（左轴）与身价（右轴，万 €）"
              :loading="historyLoading && !history"
              :empty="!historyLoading && historyPoints.length === 0"
              empty-title="暂无历史快照"
              empty-description="该球员只有一次观测，或历史接口没有返回数据，因此无法绘制成长曲线。导入后续扫描后会补齐。"
              :footnote="historyFootnote"
            >
              <EChart :option="growthOption" height="268px" aria-label="CA、PA 与身价的时间序列" />
            </ChartCard>

            <ChartCard
              title="出场时间与出场次数"
              subtitle="出场分钟（左轴，柱）与出场次数（右轴，线）"
              :loading="historyLoading && !history"
              :empty="!historyLoading && historyPoints.length === 0"
              empty-title="暂无出场数据"
              empty-description="历史快照中没有 minutes_played / appearances 字段，或还没有第二次扫描。"
            >
              <EChart :option="appearanceOption" height="236px" aria-label="出场分钟与出场次数的时间序列" />
            </ChartCard>
          </div>

          <SectionCard
            title="发展归因"
            subtitle="事实、相关性与推测分开展示；无法验证的指标不会被写成因果"
          >
            <LoadingBlock v-if="developmentLoading && !development" :rows="4" compact label="正在加载归因" />
            <ErrorState
              v-else-if="developmentError && !development"
              :error="developmentError"
              compact
              @retry="instanceId !== null && loadCore(instanceId)"
            />
            <template v-else-if="development">
              <div class="development__summary">
                <div class="development__stat">
                  <span class="sm-label">快照</span>
                  <span class="sm-num">{{ formatInt(development.summary.snapshots) }}</span>
                </div>
                <div class="development__stat">
                  <span class="sm-label">CA 变化</span>
                  <span class="sm-num">{{ formatSignedInt(development.summary.ca_delta) }}</span>
                </div>
                <div class="development__stat">
                  <span class="sm-label">身价变化</span>
                  <span class="sm-num">{{ formatSignedMoney(development.summary.market_value_delta) }}</span>
                </div>
                <div class="development__stat">
                  <span class="sm-label">分钟变化</span>
                  <span class="sm-num">{{ formatSignedInt(development.summary.minutes_delta) }}</span>
                </div>
                <div class="development__stat development__stat--wide">
                  <span class="sm-label">窗口</span>
                  <span class="sm-num">
                    {{ formatDate(development.summary.window_start) }} → {{ formatDate(development.summary.window_end) }}
                  </span>
                </div>
              </div>

              <div class="attribution-grid">
                <div
                  v-for="group in attributionGroups"
                  :key="group.kind"
                  class="attribution"
                  :class="`attribution--${group.kind}`"
                >
                  <div class="attribution__head">
                    <span class="attribution__title">{{ group.title }}</span>
                    <span class="attribution__hint">{{ group.hint }}</span>
                  </div>
                  <ul v-if="group.items.length > 0" class="attribution__list">
                    <li v-for="item in group.items" :key="`${item.factor}-${item.evidence}`">
                      <span class="attribution__factor">{{ item.factor }}</span>
                      <span class="attribution__evidence">{{ item.evidence }}</span>
                    </li>
                  </ul>
                  <p v-else class="sm-text-faint sm-text-2xs">后端未返回该类归因。</p>
                </div>
              </div>

              <div v-if="development.data_gaps.length > 0" class="data-gaps">
                <span class="sm-label">数据缺口</span>
                <ul>
                  <li v-for="gap in development.data_gaps" :key="gap">{{ gap }}</li>
                </ul>
              </div>

              <DataTable
                :columns="developmentColumns"
                :rows="development.records"
                dense
                row-key="period_start"
                :empty-title="development.records.length === 0 ? '没有区间记录' : '暂无数据'"
                empty-description="至少需要两次快照才能计算区间变化。"
              >
                <template #cell="{ row, column }">
                  <template v-if="column.prop === 'ca_delta'">
                    <NumberCell :value="row.ca_delta" />
                  </template>
                  <template v-else-if="column.prop === 'market_value_delta'">
                    <span class="sm-num">{{ formatSignedMoney(row.market_value_delta) }}</span>
                  </template>
                  <template v-else-if="column.prop === 'minutes'">
                    <NumberCell :value="row.minutes" />
                  </template>
                  <template v-else-if="column.prop === 'appearances'">
                    <NumberCell :value="row.appearances" />
                  </template>
                  <template v-else-if="column.prop === 'goals'">
                    <NumberCell :value="row.goals" />
                  </template>
                  <template v-else-if="column.prop === 'assists'">
                    <NumberCell :value="row.assists" />
                  </template>
                  <template v-else>
                    {{ column.formatter ? column.formatter(row) : EMPTY }}
                  </template>
                </template>
              </DataTable>
            </template>
          </SectionCard>
        </section>

        <section id="player-transfer" class="player-group" aria-labelledby="player-transfer-title">
          <header class="player-group__head">
            <h2 id="player-transfer-title" class="player-group__title">转会与估值</h2>
            <p class="player-group__hint">估值与相似成交来自可比交易；角色评分按模板权重计算。</p>
          </header>

          <SectionCard title="估值（相似成交）" subtitle="区间来自可比成交的分位数，样本不足时不给区间">
              <header class="sm-row sm-row--between valuation__head">
                <span class="sm-label">相似成交区间</span>
                <span class="sm-text-2xs sm-text-faint">
                  样本 {{ valuation ? formatInt(valuation.sample_size) : EMPTY }} · 币种 {{ currency }} · 算法
                  {{ displayText(valuation?.algorithm_version) }}
                </span>
              </header>

              <LoadingBlock v-if="valuationLoading && !valuation" :rows="4" compact label="正在加载估值" />
              <ErrorState
                v-else-if="valuationError && !valuation"
                :error="valuationError"
                compact
                @retry="instanceId !== null && loadValuation(instanceId)"
              />
              <template v-else-if="valuation">
                <EmptyState
                  v-if="valuationInsufficient"
                  variant="insufficient"
                  title="样本不足，拒绝精确估值"
                  :description="valuationWarnings.length > 0 ? valuationWarnings.join(' ') : '样本量低于方法要求，后端返回 insufficient_sample=true，区间字段为 null。'"
                  compact
                />
                <div v-else class="valuation__range">
                  <div class="valuation__cell">
                    <span class="sm-label">下限</span>
                    <span class="valuation__amount sm-num">{{ formatMoney(valuation.low) }}</span>
                  </div>
                  <div class="valuation__cell valuation__cell--mid">
                    <span class="sm-label">中位</span>
                    <span class="valuation__amount sm-num">{{ formatMoney(valuation.mid) }}</span>
                  </div>
                  <div class="valuation__cell">
                    <span class="sm-label">上限</span>
                    <span class="valuation__amount sm-num">{{ formatMoney(valuation.high) }}</span>
                  </div>
                </div>

                <dl class="facts">
                  <div class="facts__row">
                    <dt>方法</dt>
                    <dd>{{ valuationMethodLabel(valuation.method) }}</dd>
                  </div>
                  <div class="facts__row">
                    <dt>样本量</dt>
                    <dd class="sm-num">{{ formatInt(valuation.sample_size) }}</dd>
                  </div>
                  <div class="facts__row">
                    <dt>费用覆盖</dt>
                    <dd class="sm-num">{{ formatPercent(valuation.coverage?.fee) }}</dd>
                  </div>
                  <div v-if="valuation.basis" class="facts__row">
                    <dt>基准分位</dt>
                    <dd class="sm-num">
                      P25 {{ formatMoney(valuation.basis.p25) }} · 中位
                      {{ formatMoney(valuation.basis.median) }} · P75
                      {{ formatMoney(valuation.basis.p75) }}
                    </dd>
                  </div>
                  <div v-for="item in valuationAdjustmentFactors" :key="item.key" class="facts__row">
                    <dt>{{ item.label }}</dt>
                    <dd class="sm-num">×{{ formatDecimal(item.numeric, 2) }}</dd>
                  </div>
                </dl>

                <ul v-if="valuationAdjustmentNotes.length > 0" class="valuation-notes">
                  <li v-for="note in valuationAdjustmentNotes" :key="note.key">
                    <span class="sm-label">{{ note.label }}</span>
                    <span>{{ note.text }}</span>
                  </li>
                </ul>

                <ul v-if="valuationWarnings.length > 0" class="warnings">
                  <li v-for="warning in valuationWarnings" :key="warning">{{ warning }}</li>
                </ul>
              </template>
              <EmptyState
                v-else
                title="估值不可用"
                description="后端未返回估值字段；通常是因为相似成交样本不足或当前存档没有成交记录。"
                compact
              />
          </SectionCard>

          <SectionCard
            title="相似成交"
            subtitle="按年龄、CA、PA、位置与合同的加权相似度排序"
          >
            <LoadingBlock v-if="similarLoading && !similar" :rows="4" compact label="正在加载相似成交" />
            <ErrorState
              v-else-if="similarError && !similar"
              :error="similarError"
              compact
              @retry="instanceId !== null && loadSimilar(instanceId)"
            />
            <template v-else-if="similar">
              <div class="similar__head">
                <div class="sm-text-xs sm-text-muted">
                  目标：{{ displayText(similar.target.name) }} · 年龄 {{ formatInt(similar.target.age) }} ·
                  {{ positionGroupLabel(similar.target.position_group) }} · CA {{ formatInt(similar.target.ca) }} / PA
                  {{ formatInt(similar.target.pa) }}
                </div>
                <div class="chips">
                  <span v-for="weight in effectiveWeights" :key="weight.key" class="chip">
                    {{ weight.label }} {{ formatDecimal(weight.value, 2) }}
                  </span>
                </div>
              </div>
              <ul v-if="similar.data_gaps.length > 0" class="warnings">
                <li v-for="gap in similar.data_gaps" :key="gap">{{ gap }}</li>
              </ul>
              <p v-if="similar.missing_fields.length > 0" class="sm-text-2xs sm-text-faint">
                目标缺失字段：{{ similar.missing_fields.map((field) => similarityFactorLabel(field)).join('、') }}
                （权重已按后端策略重新分配）
              </p>
              <DataTable
                :columns="similarColumns"
                :rows="similar.items"
                row-key="transfer_id"
                expandable
                dense
                :empty-title="similar.items.length === 0 ? '没有相似成交样本' : '暂无数据'"
                empty-description="相似成交需要同一存档内、条件相近的已完成交易。样本不足时不做估值，也不会用身价顶替成交价。"
              >
                <template #expand="{ row }">
                  <div class="factor-table">
                    <div class="factor-table__head">
                      <span>因子</span>
                      <span>目标值</span>
                      <span>该笔成交</span>
                      <span>距离</span>
                      <span>权重</span>
                    </div>
                    <div v-for="factor in row.factors" :key="factor.key" class="factor-table__row">
                      <span>{{ similarityFactorLabel(factor.key) }}</span>
                      <span class="sm-num">{{ displayText(factor.target) }}</span>
                      <span class="sm-num">{{ displayText(factor.value) }}</span>
                      <span class="sm-num">{{ formatDecimal(factor.distance, 3) }}</span>
                      <span class="sm-num">{{ formatDecimal(factor.weight, 3) }}</span>
                    </div>
                    <p v-if="row.factors.length === 0" class="sm-text-faint sm-text-2xs">该样本没有因子明细。</p>
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
            </template>
            <template #footer>
              <span v-if="similar">样本 {{ formatInt(similar.sample_size) }} 笔 · 相似度与权重均由后端计算，前端不做重排。</span>
              <span v-else>相似成交样本不可用。</span>
            </template>
          </SectionCard>

          <SectionCard title="角色评分" subtitle="按角色模板加权计算，覆盖率不足时结果会标注">
            <div class="role-select">
              <el-select
                v-model="selectedRoleKey"
                size="small"
                filterable
                :loading="rolesLoading"
                placeholder="选择角色模板"
                aria-label="角色模板"
              >
                <el-option
                  v-for="role in roles"
                  :key="role.key"
                  :label="`${role.name} · ${positionGroupLabel(role.position_group)}`"
                  :value="role.key"
                />
              </el-select>
              <el-button size="small" :loading="evaluationLoading" @click="runEvaluation">重新评估</el-button>
            </div>

            <ErrorState v-if="rolesError" :error="rolesError" compact @retry="loadRoles" />
            <EmptyState
              v-else-if="!rolesLoading && roles.length === 0"
              title="没有可用的角色模板"
              description="后端 /scouting/roles 返回为空，无法进行角色评分。"
              compact
            />

            <LoadingBlock v-else-if="evaluationLoading && !evaluation" :rows="3" compact label="正在评分" />
            <ErrorState v-else-if="evaluationError" :error="evaluationError" compact @retry="runEvaluation" />
            <template v-else-if="evaluation">
              <div class="evaluation__head">
                <ScoreBadge :score="evaluation.score" :coverage="evaluation.coverage" />
                <span class="sm-text-xs sm-text-muted">{{ evaluation.role_name }}</span>
                <span class="sm-text-2xs sm-text-faint">模板 v{{ evaluation.template_version }}</span>
              </div>
              <div class="evaluation__lists">
                <div>
                  <p class="sm-label">优势</p>
                  <ul class="chips">
                    <li v-for="item in evaluation.strengths" :key="item" class="chip chip--good">{{ item }}</li>
                    <li v-if="evaluation.strengths.length === 0" class="sm-text-faint sm-text-2xs">无</li>
                  </ul>
                </div>
                <div>
                  <p class="sm-label">短板</p>
                  <ul class="chips">
                    <li v-for="item in evaluation.weaknesses" :key="item" class="chip chip--weak">{{ item }}</li>
                    <li v-if="evaluation.weaknesses.length === 0" class="sm-text-faint sm-text-2xs">无</li>
                  </ul>
                </div>
              </div>
              <DataTable
                :columns="evaluationColumns"
                :rows="evaluation.components"
                row-key="key"
                dense
                max-height="220"
                :empty-title="evaluation.components.length === 0 ? '没有参与计算的属性' : '暂无数据'"
              >
                <template #cell="{ row, column }">
                  <template v-if="column.prop === 'weight'">
                    <NumberCell :value="row.weight" kind="percent" :digits="0" />
                  </template>
                  <template v-else-if="column.prop === 'value'">
                    <NumberCell :value="row.value" />
                  </template>
                  <template v-else-if="column.prop === 'contribution'">
                    <NumberCell :value="row.contribution" kind="decimal" :digits="1" />
                  </template>
                  <template v-else>{{ displayText(row.name) }}</template>
                </template>
              </DataTable>
            </template>
            <EmptyState v-else title="尚未评分" description="选择一个角色模板后会自动评分。" compact />
          </SectionCard>
        </section>

        <section id="player-status" class="player-group" aria-labelledby="player-status-title">
          <header class="player-group__head">
            <h2 id="player-status-title" class="player-group__title">状态与合同</h2>
            <p class="player-group__hint">挂牌、伤病、租借与合同均以数据源为准，缺失标注未知。</p>
          </header>

          <div class="sm-grid sm-grid--wide-left">
            <SectionCard
              title="状态与租借"
              subtitle="挂牌、伤病、所有权与待生效转会；来源没有的字段标为未知，不做推断"
            >
            <ErrorState v-if="statusError" :error="statusError" compact title="状态加载失败" @retry="instanceId !== null && loadStatus(instanceId)" />
            <LoadingBlock v-else-if="statusLoading && !status" :rows="3" label="正在加载状态" />
            <EmptyState
              v-else-if="!status || !status.current"
              title="没有状态记录"
              description="数据源未提供挂牌/伤病字段，或该球员还没有状态快照"
            />
            <template v-else>
              <div class="status-grid">
                <div class="status-block">
                  <p class="sm-label">挂牌</p>
                  <ul class="status-list">
                    <li>
                      <span>挂牌出售</span>
                      <strong>{{ triState(status.current.flags.listed) }}</strong>
                    </li>
                    <li>
                      <span>挂牌出租</span>
                      <strong>{{ triState(status.current.flags.loan_listed) }}</strong>
                    </li>
                    <li>
                      <span>非卖品</span>
                      <strong>{{ triState(status.current.flags.not_for_sale) }}</strong>
                    </li>
                    <li>
                      <span>已设置解约</span>
                      <strong>{{ triState(status.current.flags.set_for_release) }}</strong>
                    </li>
                  </ul>
                </div>
                <div class="status-block">
                  <p class="sm-label">伤病</p>
                  <ul class="status-list">
                    <li>
                      <span>当前受伤</span>
                      <strong>{{ triState(status.current.injury.injured) }}</strong>
                    </li>
                    <li>
                      <span>伤病倾向</span>
                      <strong>{{ status.current.injury.proneness === null ? EMPTY : `${status.current.injury.proneness}/20` }}</strong>
                    </li>
                    <li>
                      <span>开始日期</span>
                      <strong>{{ formatDate(status.current.injury.start_date) }}</strong>
                    </li>
                    <li>
                      <span>预计复出</span>
                      <strong>{{ formatDate(status.current.injury.expected_return) }}</strong>
                    </li>
                  </ul>
                </div>
                <div class="status-block">
                  <p class="sm-label">注册与所有权</p>
                  <ul class="status-list">
                    <li>
                      <span>原属俱乐部</span>
                      <strong>{{ displayText(status.current.registration.parent_club) }}</strong>
                    </li>
                    <li>
                      <span>当前效力</span>
                      <strong>{{ displayText(status.current.registration.loan_club ?? summary.club) }}</strong>
                    </li>
                    <li>
                      <span>梯队</span>
                      <strong>{{ displayText(status.current.registration.team_type) }}</strong>
                    </li>
                    <li>
                      <span>已达成转会</span>
                      <strong>
                        {{ status.current.agreed_transfer
                          ? `${displayText(status.current.agreed_transfer.to_club)} · ${formatDate(status.current.agreed_transfer.date)}`
                          : EMPTY }}
                      </strong>
                    </li>
                  </ul>
                </div>
              </div>

              <div v-if="status.loans.length > 0" class="status-loans">
                <p class="sm-label">租借关系</p>
                <ul class="status-list">
                  <li v-for="loan in status.loans" :key="loan.id">
                    <span>{{ displayText(loan.parent_club) }} → {{ displayText(loan.loan_club) }}</span>
                    <strong>
                      买断条款 {{ triState(loan.has_option) }}
                      · 强制买断 {{ triState(loan.has_obligation) }}
                      · 结束 {{ formatDate(loan.end_date) }}
                    </strong>
                  </li>
                </ul>
              </div>

              <div v-if="status.changes.length > 0" class="status-changes">
                <p class="sm-label">状态变化</p>
                <ul class="status-list">
                  <li v-for="change in status.changes" :key="`${change.field}-${change.observed_at}`">
                    <span>{{ change.label }}</span>
                    <strong>{{ changeValue(change.from) }} → {{ changeValue(change.to) }} · {{ formatDate(change.observed_at) }}</strong>
                  </li>
                </ul>
              </div>

              <div v-if="status.data_gaps.length > 0" class="status-gaps">
                <p class="sm-label">数据缺口</p>
                <ul class="status-list">
                  <li v-for="gap in status.data_gaps" :key="gap">
                    <span>{{ gap }}</span>
                  </li>
                </ul>
              </div>
            </template>
            </SectionCard>

            <div class="sm-stack">
              <SectionCard
                v-if="summary.contract_end"
                title="合同与身份"
                dense
              >
                <dl class="facts">
                  <div class="facts__row">
                    <dt>合同到期</dt>
                    <dd>{{ formatDate(summary.contract_end) }}</dd>
                  </div>
                  <div class="facts__row">
                    <dt>周薪</dt>
                    <dd class="sm-num">{{ formatMoney(summary.wage) }}</dd>
                  </div>
                  <div class="facts__row">
                    <dt>最近一次快照</dt>
                    <dd>{{ formatDateTime(summary.observed_at) }} · snapshot #{{ displayText(detail.latest_snapshot_id) }}</dd>
                  </div>
                </dl>
              </SectionCard>

              <SectionCard title="档案" subtitle="字段全部来自后端，缺失显示为 —">
                <StatHeader :items="profileFacts" />
                <template #footer>
                  <span v-if="watchItem?.note">备注：{{ watchItem.note }}</span>
                  <span v-else>备注：暂无，可在「编辑备注」中添加。</span>
                </template>
              </SectionCard>
            </div>
          </div>
        </section>

      </template>

      <div v-if="watchError" class="sm-text-2xs sm-text-faint">
        关注名单状态读取失败：{{ watchError.message }}
      </div>
    </template>
  </div>
</template>

<style scoped>
.status-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--sm-space-3);
}

.status-block {
  padding: var(--sm-space-3);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-md);
  background: var(--sm-surface-2);
}

.status-list {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-1);
  margin: var(--sm-space-2) 0 0;
  padding: 0;
  list-style: none;
  font-size: var(--sm-fs-xs);
  color: var(--sm-text-2);
}

.status-list li {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--sm-space-2);
}

.status-loans,
.status-changes,
.status-gaps {
  margin-top: var(--sm-space-3);
  padding-top: var(--sm-space-2);
  border-top: 1px solid var(--sm-border);
}
.watch-toggle {
  display: inline-flex;
  align-items: center;
  gap: var(--sm-space-2);
}

/* ---------- 球员档案指挥条 ---------- */

.player-hero {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  align-items: center;
  gap: var(--sm-space-5);
  padding: var(--sm-space-5);
  overflow: hidden;
  border: 1px solid var(--sm-border-strong);
  border-radius: var(--sm-radius-xl);
  background:
    linear-gradient(120deg, rgba(10, 34, 54, 0.92) 0%, rgba(9, 18, 34, 0.94) 50%, rgba(24, 16, 46, 0.9) 100%),
    var(--sm-surface);
  box-shadow: var(--sm-shadow-2);
}

.player-hero__glow {
  position: absolute;
  top: -110px;
  left: -40px;
  width: 340px;
  height: 280px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(167, 139, 250, 0.2), transparent 70%);
  filter: blur(4px);
  pointer-events: none;
}

.player-hero__identity {
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--sm-space-4);
  min-width: 0;
}

/* 渐变描边头像：用 padding + 渐变背景形成 2px 边框。 */
.player-hero__avatar {
  display: grid;
  place-items: center;
  width: 76px;
  height: 76px;
  flex: 0 0 auto;
  border-radius: var(--sm-radius-lg);
  background: var(--sm-gradient-accent);
  color: var(--sm-text-inverse);
  font-size: var(--sm-fs-xl);
  font-weight: var(--sm-fw-semibold);
  letter-spacing: 0.02em;
  box-shadow: var(--sm-glow-cyan);
}

.player-hero__id {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-1);
  min-width: 0;
}

.player-hero__name {
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-2xl);
  font-weight: var(--sm-fw-semibold);
  letter-spacing: -0.015em;
  line-height: var(--sm-lh-tight);
  overflow-wrap: anywhere;
}

.player-hero__sub {
  color: var(--sm-text-2);
  font-size: var(--sm-fs-sm);
}

.player-hero__chips {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sm-space-2);
  margin-top: var(--sm-space-1);
}

.player-hero__note {
  margin-top: var(--sm-space-1);
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}

.player-hero__transfer {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-top: var(--sm-space-2);
  padding: 6px 12px;
  border: 1px solid rgba(64, 158, 255, 0.4);
  border-radius: 999px;
  color: var(--el-color-primary);
  font-size: var(--sm-fs-2xs);
  text-decoration: none;
}

.player-hero__transfer:hover {
  background: rgba(64, 158, 255, 0.1);
}

.player-chip {
  display: inline-flex;
  align-items: baseline;
  gap: 6px;
  padding: 3px var(--sm-space-2);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-pill);
  background: rgba(8, 17, 30, 0.72);
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
  white-space: nowrap;
}

.player-chip strong {
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-xs);
  font-weight: var(--sm-fw-semibold);
  font-variant-numeric: tabular-nums;
}

.player-hero__tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sm-space-1);
  margin-top: var(--sm-space-1);
}

/* ---------- 决策导航与分组 ---------- */

.player-sections {
  position: sticky;
  top: 0;
  z-index: 3;
  display: flex;
  flex-wrap: wrap;
  gap: var(--sm-space-1);
  padding: var(--sm-space-2) 0;
  border-bottom: 1px solid var(--sm-border);
  background: var(--sm-bg-primary);
}

.player-sections__link {
  padding: 3px var(--sm-space-3);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-pill);
  color: var(--sm-text-2);
  font-size: var(--sm-fs-xs);
  text-decoration: none;
  transition:
    border-color var(--sm-dur-2) var(--sm-ease-out),
    color var(--sm-dur-2) var(--sm-ease-out);
}

.player-sections__link:hover,
.player-sections__link:focus-visible {
  border-color: var(--sm-accent-cyan);
  color: var(--sm-accent-cyan);
}

.player-group {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-4);
  scroll-margin-top: 64px;
}

.player-group__head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--sm-space-1) var(--sm-space-3);
  padding-bottom: var(--sm-space-2);
  border-bottom: 1px solid var(--sm-border);
}

.player-group__title {
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-md);
  font-weight: var(--sm-fw-semibold);
  letter-spacing: 0.02em;
}

.player-group__hint {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}

.valuation__head {
  margin-bottom: var(--sm-space-3);
}

.valuation__range {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--sm-space-2);
  padding-bottom: var(--sm-space-3);
  border-bottom: 1px solid var(--sm-border);
  margin-bottom: var(--sm-space-3);
}

.valuation__cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.valuation__cell--mid .valuation__amount {
  color: var(--sm-accent);
}

.valuation__amount {
  color: var(--sm-text);
  font-size: var(--sm-fs-lg);
  font-weight: var(--sm-fw-semibold);
  text-align: right;
}

.facts {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-1);
  margin: 0;
}

.facts__row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--sm-space-3);
  font-size: var(--sm-fs-xs);
}

.facts__row dt {
  color: var(--sm-text-3);
  white-space: nowrap;
}

.facts__row dd {
  margin: 0;
  color: var(--sm-text);
  text-align: right;
}

.warnings {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin: var(--sm-space-2) 0 0;
  padding-left: var(--sm-space-4);
  color: var(--sm-warn);
  font-size: var(--sm-fs-2xs);
  line-height: 1.6;
}

.valuation-notes {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin: var(--sm-space-2) 0 0;
  padding: 0;
  color: var(--sm-text-2);
  font-size: var(--sm-fs-2xs);
  list-style: none;
}
.role-select {
  display: flex;
  align-items: center;
  gap: var(--sm-space-2);
  margin-bottom: var(--sm-space-3);
}

.role-select :deep(.el-select) {
  flex: 1 1 auto;
}

.evaluation__head {
  display: flex;
  align-items: baseline;
  gap: var(--sm-space-2);
  margin-bottom: var(--sm-space-2);
}

.evaluation__lists {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--sm-space-3);
  margin-bottom: var(--sm-space-3);
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sm-space-1);
  margin: 2px 0 0;
  padding: 0;
  list-style: none;
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

.chip--good {
  border-color: rgba(53, 201, 138, 0.35);
  background: var(--sm-success-weak);
  color: var(--sm-success);
}

.chip--weak {
  border-color: rgba(240, 106, 99, 0.35);
  background: var(--sm-danger-weak);
  color: var(--sm-danger);
}

.development__summary {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sm-space-4);
  padding-bottom: var(--sm-space-3);
  margin-bottom: var(--sm-space-3);
  border-bottom: 1px solid var(--sm-border);
}

.development__stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 96px;
  font-size: var(--sm-fs-md);
  font-weight: var(--sm-fw-semibold);
}

.development__stat--wide {
  min-width: 220px;
  font-size: var(--sm-fs-sm);
}

.attribution-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--sm-space-3);
  margin-bottom: var(--sm-space-3);
}

.attribution {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-2);
  padding: var(--sm-space-3);
  border: 1px solid var(--sm-border);
  border-left: 3px solid var(--sm-border-strong);
  border-radius: var(--sm-radius-md);
  background: var(--sm-surface-2);
}

.attribution--fact {
  border-left-color: var(--sm-success);
  background: var(--sm-success-weak);
}

.attribution--correlation {
  border-left-color: var(--sm-warn);
  background: var(--sm-warn-weak);
}

.attribution--speculation {
  border-left-color: var(--sm-text-3);
  background: var(--sm-surface-3);
}

.attribution__head {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.attribution__title {
  color: var(--sm-text);
  font-size: var(--sm-fs-sm);
  font-weight: var(--sm-fw-semibold);
}

.attribution__hint {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}

.attribution__list {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.attribution__list li {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.attribution__factor {
  color: var(--sm-text);
  font-size: var(--sm-fs-xs);
  font-weight: var(--sm-fw-medium);
}

.attribution__evidence {
  color: var(--sm-text-2);
  font-size: var(--sm-fs-2xs);
  line-height: 1.6;
}

.data-gaps {
  margin-bottom: var(--sm-space-3);
  font-size: var(--sm-fs-xs);
  color: var(--sm-text-2);
}

.data-gaps ul {
  margin: 2px 0 0;
  padding-left: var(--sm-space-4);
}

.attribute-groups {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: var(--sm-space-3);
}

/* 每个属性类别是一张独立玻璃卡，避免长表格失去分组。 */
.attribute-card {
  min-width: 0;
  padding: var(--sm-space-3);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-md);
  background:
    linear-gradient(160deg, rgba(22, 37, 59, 0.45) 0%, rgba(11, 21, 36, 0.85) 100%),
    var(--sm-surface-2);
}

.attribute-card__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--sm-space-2);
  padding-bottom: var(--sm-space-2);
  margin-bottom: var(--sm-space-2);
  border-bottom: 1px solid var(--sm-border);
}

.attribute-card__title {
  color: var(--sm-text);
  font-size: var(--sm-fs-sm);
  font-weight: var(--sm-fw-semibold);
}

.attribute-card__count {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
  font-variant-numeric: tabular-nums;
}

.attribute-card__grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(132px, 1fr));
  gap: var(--sm-space-3) var(--sm-space-4);
}

.similar__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--sm-space-2);
  margin-bottom: var(--sm-space-2);
}

.factor-table {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: var(--sm-fs-xs);
}

.factor-table__head,
.factor-table__row {
  display: grid;
  grid-template-columns: 1.2fr repeat(4, 1fr);
  gap: var(--sm-space-2);
}

.factor-table__head {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}

.factor-table__row {
  color: var(--sm-text-2);
  padding-top: 2px;
  border-top: 1px solid var(--sm-border);
}

@media (max-width: 1180px) {
  .attribution-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 768px) {
  .player-hero {
    gap: var(--sm-space-4);
    padding: var(--sm-space-4);
  }

  .player-hero__identity {
    align-items: flex-start;
  }
}

@media (max-width: 420px) {
  .player-hero__identity {
    flex-direction: column;
    gap: var(--sm-space-3);
  }
}
</style>




