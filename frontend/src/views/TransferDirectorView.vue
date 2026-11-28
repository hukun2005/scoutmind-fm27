<script setup lang="ts">
/**
 * AI 转会总监工作台：转会情报、AI 买入/出售报价、合同与条款、谈判记录。
 * 所有数字来自后端确定性引擎；页面只负责展示与记录，不计算金额。
 */

import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  appendNegotiationEvent,
  cancelScan,
  createNegotiation,
  createScan,
  generateLoanOffers,
  generatePurchaseOffers,
  generateSaleOffers,
  getClubHabits,
  getClubLinkHealth,
  getClubTransferSummary,
  getDirectorOverview,
  getLearningStatus,
  getNegotiation,
  getOpportunityDetail,
  getOpportunitySummary,
  getPlayerTransferAnalysis,
  getScan,
  getSimilarStrategyCases,
  getStrategyInsights,
  listClubPlayers,
  listDirectorClubs,
  listNegotiations,
  listOpportunities,
  listScans,
  listStrategyCases,
  listTransferAlerts,
  markTransferAlertRead,
  repairClubLinks,
  reviewNegotiation,
  saveOffer,
  submitFeedback,
} from '../api/transferDirector'
import type {
  BackgroundTask,
  ClubHabits,
  ClubLinkHealth,
  ClubPlayerRow,
  ContractInfo,
  DirectorClub,
  DirectorOverview,
  FeedbackOutcome,
  LearningStatus,
  Negotiation,
  NegotiationReview,
  Offer,
  OfferBundle,
  Opportunity,
  OpportunitySummary,
  PlayerTransferAnalysis,
  StrategyCase,
  StrategyInsight,
  TransferAlert,
  TransferClause,
} from '../api/transferDirector'
import { listPlayers } from '../api/players'
import {
  getOnlineLearningStatus,
  listFocusClubs,
  listLearningActivity,
  pauseOnlineLearning,
  resumeOnlineLearning,
} from '../api/transferLearning'
import type {
  LearningActivity,
  LearningClub,
  OnlineLearningStatus,
} from '../api/transferLearning'
import { listTransfers } from '../api/transfers'
import InsightPanel from '../components/InsightPanel.vue'
import StatStrip from '../components/StatStrip.vue'
import type { PlayerSummary } from '../types/players'
import type { TransferListResponse } from '../types/transfers'
import type { InsightItem, StatItem } from '../types/ui'
import { formatDate, formatDateTime, formatMoney, formatPercent } from '../utils/format'

const route = useRoute()
const router = useRouter()

const section = ref(String(route.query.section ?? (route.query.tab ? 'workbench' : 'radar')))
const activeTab = ref(String(route.query.tab ?? 'intel'))
const overview = ref<DirectorOverview | null>(null)
const loading = ref(false)

const oppSummary = ref<OpportunitySummary | null>(null)
const oppItems = ref<Opportunity[]>([])
const oppTotal = ref(0)
const oppLoading = ref(false)
const oppFilters = reactive({
  type: '',
  group: '',
  search: '',
  position: '',
  clubId: null as number | null,
  ageMin: null as number | null,
  ageMax: null as number | null,
  sort: 'score',
  page: 1,
  pageSize: 20,
})

// V3.3.2-05.2：后台扫描任务与俱乐部关联健康度
const scanTask = ref<BackgroundTask | null>(null)
const scanTimer = ref<number | null>(null)
const clubLinkHealth = ref<ClubLinkHealth | null>(null)
const repairLoading = ref(false)
const clubOptions = ref<DirectorClub[]>([])
const clubs = ref<DirectorClub[]>([])
const clubsTotal = ref(0)
const clubsLoading = ref(false)
const clubSearch = ref('')
const clubPage = ref(1)
const clubPageSize = 10
const clubDetailVisible = ref(false)
const activeClub = ref<DirectorClub | null>(null)
const clubPlayers = ref<ClubPlayerRow[]>([])
const clubPlayersTotal = ref(0)
const clubPlayersLoading = ref(false)
const clubPlayerState = ref('all')
const clubPlayerSort = ref('score')
const clubPlayerPage = ref(1)
const CLUB_PLAYER_PAGE_SIZE = 12
const ACTIVE_SCAN_STATUSES = ['PENDING', 'RUNNING', 'CANCELLING']
const scanRunning = computed(() => !!scanTask.value && ACTIVE_SCAN_STATUSES.includes(scanTask.value.status))
const scanPercent = computed(() => Math.min(100, Math.max(0, Math.round(Number(scanTask.value?.progress ?? 0)))))
/** Remaining minutes, only when the backend can estimate an ETA. */
const scanEtaMinutes = computed(() => {
  const seconds = scanTask.value?.eta_seconds
  if (seconds === null || seconds === undefined) return null
  return Math.ceil(seconds / 60)
})
const healthMissingCount = computed(
  () => clubLinkHealth.value?.states?.MISSING_SOURCE_FIELD ?? 0,
)
const oppDetail = ref<{ opportunity: Opportunity; context: PlayerTransferAnalysis | null } | null>(null)
const detailVisible = ref(false)
const alerts = ref<TransferAlert[]>([])
const alertsVisible = ref(false)

const strategyCases = ref<StrategyCase[]>([])
const strategyInsights = ref<{ available: boolean; patterns: StrategyInsight[]; totals?: Record<string, number>; message: string | null } | null>(null)
const strategyLoading = ref(false)
const similarCases = ref<StrategyCase[]>([])
const similarMessage = ref<string | null>(null)

// V3.3.2-07：交易策略学习、俱乐部画像与交易结果反馈
const learning = ref<LearningStatus | null>(null)
const learningLoading = ref(false)
const learningError = ref<string | null>(null)
const learningTypes = computed(() => Object.entries(learning.value?.by_type ?? {}))

// V3.3.2-08：在线持续学习状态、重点俱乐部与最近动态
const onlineStatus = ref<OnlineLearningStatus | null>(null)
const onlineFocus = ref<LearningClub[]>([])
const onlineActivity = ref<LearningActivity[]>([])
const onlineLoading = ref(false)
const onlineError = ref<string | null>(null)
const onlineBusy = ref(false)

async function loadOnlineLearning() {
  onlineLoading.value = true
  onlineError.value = null
  try {
    const [status, focus, activity] = await Promise.all([
      getOnlineLearningStatus(),
      listFocusClubs(6),
      listLearningActivity(6),
    ])
    if (!status || !status.counts || !status.coverage) {
      throw new Error('学习状态数据不完整')
    }
    onlineStatus.value = status
    onlineFocus.value = focus.items ?? []
    onlineActivity.value = activity.items ?? []
  } catch (error) {
    onlineError.value = (error as Error).message
  } finally {
    onlineLoading.value = false
  }
}

async function toggleOnlineLearning(pause: boolean) {
  onlineBusy.value = true
  try {
    if (pause) await pauseOnlineLearning()
    else await resumeOnlineLearning()
    await loadOnlineLearning()
    ElMessage.success(pause ? '已暂停自动学习' : '已恢复自动学习')
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    onlineBusy.value = false
  }
}

const clubHabitsVisible = ref(false)
const clubHabits = ref<ClubHabits | null>(null)
const clubHabitsLoading = ref(false)

const feedbackVisible = ref(false)
const feedbackSubmitting = ref(false)
const feedbackBundle = ref<OfferBundle | null>(null)
const feedbackOffer = ref<Offer | null>(null)
const feedbackOutcome = ref<FeedbackOutcome>('completed')
const feedbackAmount = ref<number | null>(null)
const feedbackNote = ref('')
const feedbackAmountValid = computed(
  () => feedbackOutcome.value !== 'completed' || (feedbackAmount.value !== null && feedbackAmount.value > 0),
)

const CLUB_OBSERVATION_LABELS: Record<string, string> = {
  completed: '完成交易',
  loans: '租借',
  free: '自由转会',
  installments: '分期',
  addons: '附加条款',
  buyout: '买断',
}

const loan = ref<OfferBundle | null>(null)
const loanLoading = ref(false)

const OPPORTUNITY_LABELS: Record<string, string> = {
  listed: '已挂牌',
  loan_listed: '可租借',
  release_listed: '解约挂牌',
  contract_expiring: '合同到期',
  ai_inferred: 'AI 推测机会',
}

const keyword = ref('')
const candidates = ref<PlayerSummary[]>([])
const selectedId = ref<number | null>(null)
const analysis = ref<PlayerTransferAnalysis | null>(null)
const analysisLoading = ref(false)

const purchase = ref<OfferBundle | null>(null)
const sale = ref<OfferBundle | null>(null)
const budget = ref<number | null>(null)
const offerLoading = ref(false)

const transfers = ref<TransferListResponse | null>(null)
const transferStatus = ref('completed')
const transferType = ref('')
const clubSummary = ref<Record<string, unknown> | null>(null)

const negotiations = ref<Negotiation[]>([])
const activeNegotiation = ref<Negotiation | null>(null)
const review = ref<NegotiationReview | null>(null)
const eventType = ref('offer_submitted')
const eventAmount = ref<number | null>(null)
const eventNote = ref('')

const EVENT_LABELS: Record<string, string> = {
  draft_created: '创建草稿',
  offer_generated: 'AI 生成报价',
  offer_submitted: '已提交报价',
  counter_received: '收到反报价',
  offer_revised: '修改报价',
  accepted: '对方接受',
  rejected: '被拒绝',
  withdrawn: '撤回',
  completed: '完成交易',
  cancelled: '取消',
  note: '备注',
}

const TYPE_LABELS: Record<string, string> = {
  permanent: '正式转会',
  loan: '租借',
  loan_with_option: '租借+买断',
  free: '自由转会',
  end_of_contract: '合同到期',
  clause_release: '解约金',
  swap: '互换',
  youth_promotion: '青训上调',
  other: '其他',
}

const STATUS_LABELS: Record<string, string> = {
  completed: '已完成',
  pending: '进行中',
  future: '未来生效',
  agreed: '已达成',
  bid_rejected: '报价被拒',
  cancelled: '已取消',
  failed: '失败',
  unknown: '未知',
}

const selectedPlayerName = computed(() => {
  const found = candidates.value.find((item) => item.instance_id === selectedId.value)
  return found?.name ?? analysis.value?.player.name ?? '未选择球员'
})

const contract = computed<ContractInfo | null>(() => analysis.value?.contract ?? null)
const clauses = computed<TransferClause[]>(() => analysis.value?.clauses ?? [])

const contractCoverage = computed(() => {
  if (!overview.value || !overview.value.player_count) return '—'
  return formatPercent(overview.value.players_with_contract / overview.value.player_count)
})

/** 工作台关键指标：全部来自 overview 与机会雷达摘要，缺失显示 —。 */
const workbenchStats = computed<StatItem[]>(() => {
  const data = overview.value
  if (!data) return []
  const counts = oppSummary.value?.counts
  return [
    { label: '存档球员', value: String(data.player_count) },
    { label: '合同覆盖', value: contractCoverage.value },
    { label: '转会记录', value: String(data.transfer_count) },
    { label: '谈判', value: String(data.negotiations_total) },
    {
      label: '已挂牌机会',
      value: counts ? String(counts.listed) : '—',
    },
  ]
})

/** 工作台结论：只复述后端 overview 与当前选择状态。 */
const workbenchItems = computed<InsightItem[]>(() => {
  const data = overview.value
  const items: InsightItem[] = [
    { label: '当前目标', text: selectedPlayerName.value },
    { label: '报价口径', text: '报价金额由确定性报价引擎计算；AI 只解释逻辑与风险，不决定金额。' },
  ]
  if (data) {
    items.push({
      label: '存档规模',
      text: `${data.player_count} 名球员 · 合同覆盖 ${contractCoverage.value} · 转会记录 ${data.transfer_count} 条`,
    })
  }
  if (data && !data.capabilities.auto_transfer_history) {
    items.push({
      label: '数据边界',
      text: '历史转会与成交金额需手动导入，自动采集不可用。',
      tone: 'warning',
    })
  }
  return items
})

/** 主分区导航：与 el-tabs 共用同一个 section 状态。 */
const sections = [
  { name: 'radar', label: '机会雷达' },
  { name: 'strategy', label: '成交策略' },
  { name: 'workbench', label: '报价工作台' },
  { name: 'intel', label: '转会情报' },
  { name: 'purchase', label: '买入报价' },
  { name: 'sale', label: '出售报价' },
  { name: 'loan', label: '租借报价' },
  { name: 'contract', label: '合同条款' },
  { name: 'negotiation', label: '谈判记录' },
]

async function loadOverview() {
  try {
    overview.value = await getDirectorOverview()
  } catch (error) {
    ElMessage.error((error as Error).message)
  }
}

async function loadRadar() {
  oppLoading.value = true
  try {
    const params: Record<string, unknown> = {
      sort: oppFilters.sort,
      limit: oppFilters.pageSize,
      offset: (oppFilters.page - 1) * oppFilters.pageSize,
    }
    if (oppFilters.type) params.type = oppFilters.type
    if (oppFilters.group) params.group = oppFilters.group
    if (oppFilters.clubId) params.club_id = oppFilters.clubId
    if (oppFilters.search.trim()) params.search = oppFilters.search.trim()
    if (oppFilters.position.trim()) params.position = oppFilters.position.trim()
    if (oppFilters.ageMin !== null) params.age_min = oppFilters.ageMin
    if (oppFilters.ageMax !== null) params.age_max = oppFilters.ageMax
    const [summary, listing] = await Promise.all([getOpportunitySummary(), listOpportunities(params as never)])
    oppSummary.value = summary
    oppItems.value = listing.items
    oppTotal.value = listing.total
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    oppLoading.value = false
  }
}

function stopScanPolling() {
  if (scanTimer.value !== null) {
    window.clearInterval(scanTimer.value)
    scanTimer.value = null
  }
}

async function pollScan(taskId: string) {
  try {
    const task = await getScan(taskId)
    scanTask.value = task
    if (!ACTIVE_SCAN_STATUSES.includes(task.status)) {
      stopScanPolling()
      if (task.status === 'COMPLETED') {
        ElMessage.success(
          `扫描完成：新增 ${Number(task.result?.created ?? 0)}，更新 ${Number(task.result?.updated ?? 0)}，撤销 ${Number(task.result?.deactivated ?? 0)}`,
        )
        await Promise.all([loadRadar(), loadClubLinkHealth(), loadClubs()])
      } else if (task.status === 'PARTIAL') {
        ElMessage.warning(task.error_message ?? task.message)
      } else if (task.status === 'FAILED') {
        ElMessage.error(task.message)
      } else if (task.status === 'CANCELLED') {
        ElMessage.info('扫描已取消，已完成的批次已保留')
      }
    }
  } catch (error) {
    stopScanPolling()
    ElMessage.error((error as Error).message)
  }
}

function startScanPolling(taskId: string) {
  stopScanPolling()
  scanTimer.value = window.setInterval(() => pollScan(taskId), 1200)
}

async function startScan(taskType = 'FULL_SCAN') {
  if (scanRunning.value) return
  oppLoading.value = true
  try {
    const response = await createScan(taskType)
    if (!response?.task) throw new Error('扫描任务创建失败')
    scanTask.value = response.task
    if (response.reused) ElMessage.info('已有扫描任务在运行，已接入该任务的进度')
    if (ACTIVE_SCAN_STATUSES.includes(response.task.status)) startScanPolling(response.task.task_id)
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    oppLoading.value = false
  }
}

async function cancelRunningScan() {
  if (!scanTask.value) return
  try {
    scanTask.value = await cancelScan(scanTask.value.task_id)
  } catch (error) {
    ElMessage.error((error as Error).message)
  }
}

async function resumeActiveScan() {
  try {
    const response = await listScans(true)
    const active = (response.items ?? []).find((task) => task.task_type !== 'CLUB_LINK_REPAIR')
    if (active) {
      scanTask.value = active
      startScanPolling(active.task_id)
    }
  } catch {
    // 恢复失败不应阻塞页面其他数据加载。
  }
}

async function loadClubLinkHealth() {
  try {
    clubLinkHealth.value = await getClubLinkHealth()
  } catch {
    clubLinkHealth.value = null
  }
}

async function runClubLinkRepair() {
  repairLoading.value = true
  try {
    const result = await repairClubLinks(false)
    ElMessage.success(
      `俱乐部关联修复完成：新增关联 ${result.linked}，已正确关联 ${result.already_linked}，仍无法验证 ${result.unresolved}`,
    )
    await Promise.all([loadClubLinkHealth(), loadRadar(), loadClubs()])
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    repairLoading.value = false
  }
}

async function loadClubOptions() {
  try {
    const response = await listDirectorClubs({ limit: 200 })
    clubOptions.value = response.items ?? []
  } catch {
    clubOptions.value = []
  }
}

async function loadClubs() {
  clubsLoading.value = true
  try {
    const response = await listDirectorClubs({
      search: clubSearch.value.trim() || undefined,
      limit: clubPageSize,
      offset: (clubPage.value - 1) * clubPageSize,
    })
    clubs.value = response.items ?? []
    clubsTotal.value = response.total ?? 0
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    clubsLoading.value = false
  }
}

function changeClubPage(page: number) {
  clubPage.value = page
  loadClubs()
}

async function openClub(club: DirectorClub) {
  activeClub.value = club
  clubPlayerState.value = 'all'
  clubPlayerSort.value = 'score'
  clubPlayerPage.value = 1
  clubDetailVisible.value = true
  await loadClubPlayers()
}

async function loadClubPlayers() {
  if (!activeClub.value) return
  clubPlayersLoading.value = true
  try {
    const response = await listClubPlayers(activeClub.value.club_id, {
      state: clubPlayerState.value,
      sort: clubPlayerSort.value,
      limit: CLUB_PLAYER_PAGE_SIZE,
      offset: (clubPlayerPage.value - 1) * CLUB_PLAYER_PAGE_SIZE,
    })
    clubPlayers.value = response.items ?? []
    clubPlayersTotal.value = response.total ?? 0
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    clubPlayersLoading.value = false
  }
}

function changeClubPlayerPage(page: number) {
  clubPlayerPage.value = page
  loadClubPlayers()
}

async function openOpportunity(row: Opportunity) {
  try {
    oppDetail.value = await getOpportunityDetail(row.instance_id)
    detailVisible.value = true
  } catch (error) {
    ElMessage.error((error as Error).message)
  }
}

async function workbenchFromOpportunity(instanceId: number) {
  detailVisible.value = false
  section.value = 'workbench'
  selectedId.value = instanceId
  await selectedAndLoad(instanceId)
}

async function loadAlerts() {
  try {
    const response = await listTransferAlerts({ limit: 50 })
    alerts.value = response.items
    alertsVisible.value = true
  } catch (error) {
    ElMessage.error((error as Error).message)
  }
}

async function readAlert(alert: TransferAlert) {
  if (alert.read_at) return
  try {
    await markTransferAlertRead(alert.alert_id)
    alert.read_at = new Date().toISOString()
    if (oppSummary.value) oppSummary.value.alerts_unread = Math.max(0, oppSummary.value.alerts_unread - 1)
  } catch (error) {
    ElMessage.error((error as Error).message)
  }
}

async function loadStrategy() {
  strategyLoading.value = true
  try {
    const [cases, insights] = await Promise.all([listStrategyCases({ limit: 30 }), getStrategyInsights()])
    strategyCases.value = cases.items
    strategyInsights.value = insights
    await loadSimilar()
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    strategyLoading.value = false
  }
}

async function loadSimilar() {
  if (!selectedId.value) {
    similarCases.value = []
    similarMessage.value = null
    return
  }
  try {
    const response = await getSimilarStrategyCases(selectedId.value)
    similarCases.value = response.items
    similarMessage.value = response.message
  } catch (error) {
    ElMessage.error((error as Error).message)
  }
}

/** Learning status: how many real cases the strategy engine can learn from. */
async function loadLearningStatus() {
  learningLoading.value = true
  learningError.value = null
  try {
    const data = await getLearningStatus()
    // 防御未实现该接口的旧后端/测试桩：返回空对象时按“暂无学习数据”处理，避免整页渲染失败。
    learning.value = data && data.totals && data.confidence ? data : null
  } catch (error) {
    learningError.value = (error as Error).message
    learning.value = null
  } finally {
    learningLoading.value = false
  }
}

/** Club habits: selling/buying patterns for the selected player's club. */
async function openClubHabits() {
  const clubId = analysis.value?.player.club_id
  if (!clubId) return
  clubHabits.value = null
  clubHabitsVisible.value = true
  clubHabitsLoading.value = true
  try {
    const data = await getClubHabits(clubId)
    if (!data || !data.observations) {
      clubHabitsVisible.value = false
      ElMessage.warning('暂无足够数据')
      return
    }
    clubHabits.value = data
  } catch (error) {
    ElMessage.error((error as Error).message)
    clubHabitsVisible.value = false
  } finally {
    clubHabitsLoading.value = false
  }
}

function observationEntries(value: object | undefined): Array<[string, number]> {
  return Object.entries(value ?? {}) as Array<[string, number]>
}

/** Never imply a currency when the backend says it is unknown. */
function currencyLabel(currency: string | null | undefined): string {
  return currency ? currency : '货币单位未知'
}

/** Open the feedback dialog for one offer, remembering its bundle direction. */
function openFeedback(offer: Offer, bundle: OfferBundle | null) {
  if (!bundle) return
  feedbackBundle.value = bundle
  feedbackOffer.value = offer
  feedbackOutcome.value = 'completed'
  feedbackAmount.value = offer.total_committed ?? offer.base_fee ?? null
  feedbackNote.value = ''
  feedbackVisible.value = true
}

/** Record the real-world outcome so the strategy engine can learn from it. */
async function submitOfferFeedback() {
  if (!selectedId.value || !feedbackBundle.value) return
  if (!feedbackAmountValid.value) {
    ElMessage.warning('成交金额必须大于 0')
    return
  }
  feedbackSubmitting.value = true
  try {
    const result = await submitFeedback({
      instance_id: selectedId.value,
      direction: feedbackBundle.value.direction,
      outcome: feedbackOutcome.value,
      amount: feedbackAmount.value ?? null,
      offer_id: feedbackOffer.value?.offer_id ?? null,
      note: feedbackNote.value.trim() || null,
    })
    if (result.duplicate) ElMessage.info('该反馈已记录')
    else ElMessage.success(result.message)
    feedbackVisible.value = false
    await loadLearningStatus()
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    feedbackSubmitting.value = false
  }
}

async function refreshLoan() {
  if (!selectedId.value) return
  loanLoading.value = true
  try {
    loan.value = await generateLoanOffers(selectedId.value)
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    loanLoading.value = false
  }
}

function contractTagType(value: number | null): 'success' | 'warning' | 'danger' | 'info' {
  if (value == null) return 'info'
  if (value <= 6) return 'danger'
  if (value <= 12) return 'warning'
  return 'success'
}

async function searchPlayers() {
  if (!keyword.value.trim()) {
    candidates.value = []
    return
  }
  try {
    const response = await listPlayers({ query: keyword.value.trim(), limit: 8 } as never)
    candidates.value = response.items
  } catch (error) {
    ElMessage.error((error as Error).message)
  }
}

async function selectPlayer(instanceId: number) {
  selectedId.value = instanceId
  selectedAndLoad(instanceId)
}

async function selectedAndLoad(instanceId: number) {
  selectedId.value = instanceId
  analysisLoading.value = true
  purchase.value = null
  sale.value = null
  loan.value = null
  review.value = null
  try {
    analysis.value = await getPlayerTransferAnalysis(instanceId)
    purchase.value = analysis.value.purchase_preview
    sale.value = analysis.value.sale_preview
    loan.value = analysis.value.loan_preview ?? null
    await loadSimilar()
    router.replace({ query: { ...route.query, instance_id: String(instanceId) } })
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    analysisLoading.value = false
  }
}

async function refreshPurchase() {
  if (!selectedId.value) return
  offerLoading.value = true
  try {
    purchase.value = await generatePurchaseOffers(selectedId.value, budget.value)
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    offerLoading.value = false
  }
}

async function refreshSale() {
  if (!selectedId.value) return
  offerLoading.value = true
  try {
    sale.value = await generateSaleOffers(selectedId.value)
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    offerLoading.value = false
  }
}

async function saveDraft(offer: Offer, direction: 'purchase' | 'sale' | 'loan') {  if (!selectedId.value) return
  try {
    await saveOffer(selectedId.value, { ...offer, direction, status: 'saved' })
    ElMessage.success('报价草稿已保存')
  } catch (error) {
    ElMessage.error((error as Error).message)
  }
}

async function startNegotiation(offer: Offer, direction: 'purchase' | 'sale' | 'loan') {
  if (!selectedId.value) return
  try {
    const negotiation = await createNegotiation({
      instance_id: selectedId.value,
      direction,
      initial_ask: offer.total_committed,
      note: offer.offer_type,
    })
    ElMessage.success('谈判记录已创建')
    await loadNegotiations()
    activeTab.value = 'negotiation'
    await openNegotiation(negotiation.negotiation_id)
  } catch (error) {
    ElMessage.error((error as Error).message)
  }
}

async function loadTransfers() {
  try {
    transfers.value = await listTransfers({
      status: transferStatus.value as never,
      transfer_type: (transferType.value || undefined) as never,
      limit: 30,
    } as never)
  } catch (error) {
    ElMessage.error((error as Error).message)
  }
}

async function loadClubSummary() {
  try {
    clubSummary.value = await getClubTransferSummary()
  } catch {
    clubSummary.value = null
  }
}

async function loadNegotiations() {
  try {
    const response = await listNegotiations()
    negotiations.value = response.items
  } catch (error) {
    ElMessage.error((error as Error).message)
  }
}

async function openNegotiation(id: number) {
  try {
    activeNegotiation.value = await getNegotiation(id)
    review.value = null
  } catch (error) {
    ElMessage.error((error as Error).message)
  }
}

async function submitEvent() {
  if (!activeNegotiation.value) return
  try {
    const payload: Record<string, unknown> = { event_type: eventType.value }
    if (eventAmount.value !== null) payload.amount = eventAmount.value
    if (eventNote.value.trim()) payload.data = { note: eventNote.value.trim() }
    const result = await appendNegotiationEvent(activeNegotiation.value.negotiation_id, payload as never)
    if (result.duplicate) {
      ElMessage.info('相同事件已存在，未重复写入')
    } else {
      ElMessage.success('已记录')
    }
    eventAmount.value = null
    eventNote.value = ''
    await openNegotiation(activeNegotiation.value.negotiation_id)
    await loadNegotiations()
    await loadOverview()
  } catch (error) {
    ElMessage.error((error as Error).message)
  }
}

async function loadReview() {
  if (!activeNegotiation.value) return
  try {
    review.value = await reviewNegotiation(activeNegotiation.value.negotiation_id)
  } catch (error) {
    ElMessage.error((error as Error).message)
  }
}

function offerTitle(type: string): string {
  return (
    {
      conservative: '保守方案',
      competitive: '竞争性方案',
      fast_close: '快速成交方案',
      quick_sale: '快速出售',
      fair_sale: '合理出售',
      max_value: '价值最大化',
      low_cost_loan: '低成本租借',
      development_loan: '发展型租借',
      loan_to_buy: '租借后买断',
    }[type] ?? type
  )
}

function riskTag(level: string): 'success' | 'warning' | 'danger' {
  if (level === 'low') return 'success'
  if (level === 'high') return 'danger'
  return 'warning'
}

onMounted(async () => {
  loading.value = true
  await Promise.all([
    loadOverview(),
    loadTransfers(),
    loadClubSummary(),
    loadNegotiations(),
    loadClubLinkHealth(),
    loadClubs(),
    loadClubOptions(),
    loadLearningStatus(),
    loadOnlineLearning(),
  ])
  loading.value = false
  const instanceId = Number(route.query.instance_id)
  if (Number.isFinite(instanceId) && instanceId > 0) {
    await selectedAndLoad(instanceId)
  }
  if (section.value === 'strategy') await loadStrategy()
  else await loadRadar()
  await resumeActiveScan()
})

watch([transferStatus, transferType], () => {
  loadTransfers()
})

watch(section, (value) => {
  router.replace({ query: { ...route.query, section: value } })
  if (value === 'strategy' && !strategyCases.value.length) loadStrategy()
  if (value === 'strategy' && !learning.value) loadLearningStatus()
  if (value === 'strategy' && !onlineStatus.value) loadOnlineLearning()
  if (value === 'radar' && !oppItems.value.length) loadRadar()
})

watch(
  () => [oppFilters.type, oppFilters.group, oppFilters.clubId, oppFilters.sort],
  () => {
    oppFilters.page = 1
    loadRadar()
  },
)

watch(
  () => oppFilters.search,
  () => {
    oppFilters.page = 1
    loadRadar()
  },
)

function changePage(page: number) {
  oppFilters.page = page
  loadRadar()
}

function formatScore(value: number | null | undefined): string {
  return value == null ? '—' : value.toFixed(1)
}

function signalsOf(detail: Record<string, unknown> | undefined): string[] {
  const value = detail?.signals
  return Array.isArray(value) ? value.map((item) => String(item)) : []
}

const GROUP_LABELS: Record<string, string> = {
  strong: '强烈推荐关注',
  watch: '值得考察',
  loan: '可租借机会',
  long_term: '长期潜力目标',
  not_recommended: '暂不推荐',
}

function directionLabel(direction: string): string {
  return ({ purchase: '买入', sale: '出售', loan: '租借' } as Record<string, string>)[direction] ?? direction
}
</script>

<template>
  <div class="director" v-loading="loading">
    <header class="page-head">
      <div>
        <p class="eyebrow">AI TRANSFER DIRECTOR</p>
        <h1>AI 转会总监</h1>
        <p class="subtitle">合同、条款、买卖报价与真实谈判记录，全部以当前存档为准。</p>
      </div>
      <div class="head-stats" v-if="overview">
        <div class="stat">
          <span>存档球员</span>
          <strong>{{ overview.player_count }}</strong>
        </div>
        <div class="stat">
          <span>合同覆盖</span>
          <strong>{{ contractCoverage }}</strong>
        </div>
        <div class="stat">
          <span>转会记录</span>
          <strong>{{ overview.transfer_count }}</strong>
        </div>
        <div class="stat">
          <span>谈判</span>
          <strong>{{ overview.negotiations_total }}</strong>
        </div>
      </div>
    </header>

    <el-alert
      v-if="overview"
      :title="overview.message"
      type="info"
      :closable="false"
      show-icon
      class="notice"
    />
    <el-alert
      v-if="overview && !overview.capabilities.auto_transfer_history"
      title="当前数据源不提供自动历史转会与成交金额：转会情报依赖手动导入的 CSV/JSON；合同与周薪来自游戏读取。"
      type="warning"
      :closable="false"
      show-icon
    />

    <InsightPanel title="当前任务与结论" :tone="analysis ? 'info' : 'neutral'" badge="数据事实" :items="workbenchItems">
      <template #actions>
        <div class="section-nav" aria-label="工作区分区">
          <button
            v-for="item in sections"
            :key="item.name"
            type="button"
            class="section-nav__item"
            :class="{ 'section-nav__item--active': section === item.name }"
            @click="section = item.name"
          >
            {{ item.label }}
          </button>
        </div>
      </template>
    </InsightPanel>

    <StatStrip :items="workbenchStats" dense />

    <section class="player-picker">
      <el-input
        v-model="keyword"
        placeholder="搜索球员姓名后选择目标"
        clearable
        class="picker-input"
        @keyup.enter="searchPlayers"
        @clear="candidates = []"
      />
      <el-button type="primary" plain @click="searchPlayers">搜索</el-button>
      <el-select
        v-if="candidates.length"
        :model-value="selectedId ?? undefined"
        placeholder="选择球员"
        class="picker-select"
        filterable
        @change="(value: number) => selectPlayer(value)"
      >
        <el-option
          v-for="item in candidates"
          :key="item.instance_id"
          :label="`${item.name} · ${item.club ?? '自由'} · ${item.position ?? '—'}`"
          :value="item.instance_id"
        />
      </el-select>
      <span v-if="analysis" class="picked">已选：{{ selectedPlayerName }}</span>
      <el-button
        v-if="analysis?.player.club_id"
        size="small"
        data-testid="club-habits-open"
        @click="openClubHabits"
      >
        查看俱乐部交易画像
      </el-button>
    </section>

    <el-tabs v-model="section" class="section-tabs">
      <el-tab-pane label="机会雷达" name="radar">
        <div class="radar-head">
          <div class="radar-stats" v-if="oppSummary">
            <div class="radar-stat"><span>已挂牌</span><strong>{{ oppSummary.counts.listed }}</strong></div>
            <div class="radar-stat"><span>可租借</span><strong>{{ oppSummary.counts.loan_listed }}</strong></div>
            <div class="radar-stat"><span>合同到期</span><strong>{{ oppSummary.counts.contract_expiring }}</strong></div>
            <div class="radar-stat"><span>24h 新发现</span><strong>{{ oppSummary.counts.new_24h }}</strong></div>
            <div class="radar-stat"><span>AI 推测</span><strong>{{ oppSummary.counts.ai_inferred }}</strong></div>
          </div>
          <div class="radar-actions">
            <el-badge :value="oppSummary?.alerts_unread ?? 0" :hidden="!oppSummary?.alerts_unread">
              <el-button @click="loadAlerts">提醒</el-button>
            </el-badge>
            <el-button v-if="!scanRunning" type="primary" :loading="oppLoading" @click="startScan('FULL_SCAN')">
              刷新转会情报
            </el-button>
            <template v-else>
              <el-button :disabled="scanTask?.status === 'CANCELLING'" @click="cancelRunningScan">取消扫描</el-button>
              <el-tag type="warning">{{ scanTask?.message ?? '正在扫描' }}</el-tag>
            </template>
          </div>
        </div>

        <div v-if="scanRunning || scanTask?.status === 'FAILED'" class="scan-progress">
          <el-progress
            :percentage="scanPercent"
            :status="scanTask?.status === 'FAILED' ? 'exception' : undefined"
            :stroke-width="10"
          />
          <span v-if="scanTask?.current_stage" class="scan-progress-text">
            当前阶段：{{ scanTask.current_stage }}
          </span>
          <span class="scan-progress-text">
            已处理 {{ scanTask?.processed ?? 0 }} / {{ scanTask?.total || '…' }} 名球员
            <template v-if="scanTask?.failed">（失败 {{ scanTask.failed }}）</template>
          </span>
          <span v-if="scanEtaMinutes !== null" class="scan-progress-text">
            预计剩余约 {{ scanEtaMinutes }} 分钟
          </span>
          <el-tag v-if="scanTask?.resumable" type="info" size="small">可继续</el-tag>
          <span v-if="scanTask?.status === 'CANCELLING'" class="scan-progress-text">正在安全取消…</span>
          <span v-else-if="scanTask?.status === 'FAILED'" class="scan-progress-text">{{ scanTask?.message }}</span>
        </div>

        <el-alert
          v-if="healthMissingCount > 0"
          type="warning"
          :closable="false"
          show-icon
          class="notice"
          title="当前存档有大量球员缺少俱乐部字段，因此俱乐部关联覆盖率偏低。这不代表这些球员没有俱乐部，而是数据源没有提供该字段。系统不会按姓名猜测俱乐部，以免产生错误关联。"
        >
          <template #default>
            <div class="health-actions">
              <span>
                已关联 {{ clubLinkHealth?.linked ?? 0 }} / {{ clubLinkHealth?.total_players ?? 0 }} 名球员；
                来源未提供字段 {{ healthMissingCount }} 人，引用无法解析 {{ clubLinkHealth?.states?.UNRESOLVED ?? 0 }} 人。
              </span>
              <el-button size="small" :loading="repairLoading" @click="runClubLinkRepair">修复俱乐部关联</el-button>
            </div>
          </template>
        </el-alert>

        <el-alert
          v-if="oppSummary"
          title="当前数据源不提供离队意愿字段，雷达不会把推测包装成“想离队”；AI 推测机会单独标注。真实存档中多数球员没有俱乐部归属，俱乐部信息可能为未知。"
          type="info"
          :closable="false"
          show-icon
          class="notice"
        />

        <div class="filters">
          <el-input
            v-model="oppFilters.search"
            placeholder="搜索球员 / 俱乐部"
            clearable
            class="filter-wide"
            @keyup.enter="loadRadar"
            @clear="loadRadar"
          />
          <el-select v-model="oppFilters.type" placeholder="机会类型" clearable class="filter">
            <el-option v-for="(label, key) in OPPORTUNITY_LABELS" :key="key" :label="label" :value="key" />
          </el-select>
          <el-select v-model="oppFilters.group" placeholder="推荐分组" clearable class="filter">
            <el-option v-for="(label, key) in GROUP_LABELS" :key="key" :label="label" :value="key" />
          </el-select>
          <el-select
            v-model="oppFilters.clubId"
            placeholder="俱乐部"
            clearable
            filterable
            class="filter-wide club-filter"
          >
            <el-option
              v-for="club in clubOptions"
              :key="club.club_id"
              :label="`${club.name}（${club.players}）`"
              :value="club.club_id"
            />
          </el-select>
          <el-select v-model="oppFilters.sort" class="filter">
            <el-option label="综合评分" value="score" />
            <el-option label="合同到期" value="contract" />
            <el-option label="年龄" value="age" />
            <el-option label="身价" value="value" />
            <el-option label="最新发现" value="newest" />
          </el-select>
          <el-button @click="loadRadar">筛选</el-button>
        </div>

        <el-card shadow="never" class="club-panel">
          <template #header>
            <div class="club-panel-head">
              <span>俱乐部概览</span>
              <el-input
                v-model="clubSearch"
                placeholder="搜索俱乐部"
                clearable
                size="small"
                class="club-search"
                @keyup.enter="loadClubs"
                @clear="loadClubs"
              />
            </div>
          </template>
          <el-table
            :data="clubs"
            size="small"
            v-loading="clubsLoading"
            class="clickable-rows"
            @row-click="openClub"
          >
            <el-table-column prop="name" label="俱乐部" min-width="160" />
            <el-table-column prop="players" label="当前球员" width="100" />
            <el-table-column label="机会" min-width="220">
              <template #default="{ row }">
                <el-tag
                  v-for="(count, type) in row.opportunities"
                  :key="type"
                  size="small"
                  class="tag-gap"
                >
                  {{ OPPORTUNITY_LABELS[type] ?? type }} {{ count }}
                </el-tag>
                <span v-if="!row.opportunities_total">—</span>
              </template>
            </el-table-column>
          </el-table>
          <el-pagination
            v-if="clubsTotal > clubPageSize"
            layout="prev, pager, next"
            :total="clubsTotal"
            :page-size="clubPageSize"
            :current-page="clubPage"
            class="pager"
            @current-change="changeClubPage"
          />
        </el-card>

        <el-dialog v-model="clubDetailVisible" :title="activeClub?.name ?? '俱乐部'" width="760px">
          <div class="filters">
            <el-select v-model="clubPlayerState" class="filter club-state-select" @change="changeClubPlayerPage(1)">
              <el-option label="全部球员" value="all" />
              <el-option label="已挂牌" value="listed" />
              <el-option label="可租借" value="loan_listed" />
              <el-option label="解约挂牌" value="release_listed" />
              <el-option label="合同到期" value="contract_expiring" />
              <el-option label="AI 推测" value="ai_inferred" />
            </el-select>
            <el-select v-model="clubPlayerSort" class="filter club-sort-select" @change="changeClubPlayerPage(1)">
              <el-option label="综合评分" value="score" />
              <el-option label="年龄" value="age" />
              <el-option label="合同到期" value="contract" />
              <el-option label="姓名" value="name" />
            </el-select>
          </div>
          <el-table :data="clubPlayers" size="small" v-loading="clubPlayersLoading">
            <el-table-column prop="player_name" label="球员" min-width="160" />
            <el-table-column prop="position" label="位置" width="80" />
            <el-table-column prop="age" label="年龄" width="70" />
            <el-table-column label="合同到期" width="110">
              <template #default="{ row }">{{ formatDate(row.contract_end) }}</template>
            </el-table-column>
            <el-table-column label="评分" width="80">
              <template #default="{ row }">{{ formatScore(row.overall_score) }}</template>
            </el-table-column>
            <el-table-column label="机会" min-width="140">
              <template #default="{ row }">
                <el-tag v-for="type in row.opportunity_types" :key="type" size="small" class="tag-gap">
                  {{ OPPORTUNITY_LABELS[type] ?? type }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>
          <el-pagination
            v-if="clubPlayersTotal > CLUB_PLAYER_PAGE_SIZE"
            layout="prev, pager, next"
            :total="clubPlayersTotal"
            :page-size="CLUB_PLAYER_PAGE_SIZE"
            :current-page="clubPlayerPage"
            class="pager"
            @current-change="changeClubPlayerPage"
          />
        </el-dialog>

        <el-table
          :data="oppItems"
          v-loading="oppLoading"
          size="small"
          class="table clickable-rows"
          @row-click="openOpportunity"
        >
          <el-table-column label="球员" min-width="180">
            <template #default="{ row }">
              <strong>{{ row.player_name ?? '未知' }}</strong>
              <el-tag
                v-for="type in row.types"
                :key="type"
                size="small"
                class="tag-gap"
                :type="row.verified_status === 'inferred' ? 'info' : 'warning'"
              >
                {{ OPPORTUNITY_LABELS[type] ?? type }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="俱乐部" min-width="150">
            <template #default="{ row }">{{ row.club_name ?? '未知' }}</template>
          </el-table-column>
          <el-table-column label="位置" width="100">
            <template #default="{ row }">{{ row.position ?? '—' }}</template>
          </el-table-column>
          <el-table-column label="年龄" width="70">
            <template #default="{ row }">{{ row.age ?? '—' }}</template>
          </el-table-column>
          <el-table-column label="身价" width="130" align="right">
            <template #default="{ row }">{{ row.market_value != null ? formatMoney(row.market_value) : '未知' }}</template>
          </el-table-column>
          <el-table-column label="合同" width="150">
            <template #default="{ row }">
              <el-tag :type="contractTagType(row.contract_remaining_months)" size="small">
                {{ row.contract_remaining_months != null ? `剩 ${row.contract_remaining_months} 个月` : '未知' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="综合评分" width="100" align="right">
            <template #default="{ row }">{{ formatScore(row.scores.overall) }}</template>
          </el-table-column>
          <el-table-column label="推荐" width="120">
            <template #default="{ row }">{{ GROUP_LABELS[row.recommendation_group] ?? '—' }}</template>
          </el-table-column>
        </el-table>
        <el-empty
          v-if="!oppLoading && !oppItems.length"
          description="没有符合条件的机会；可点击「重新扫描」重新读取当前存档。"
        />
        <div class="pager">
          <el-pagination
            layout="total, prev, pager, next"
            :total="oppTotal"
            :page-size="oppFilters.pageSize"
            :current-page="oppFilters.page"
            @current-change="changePage"
          />
        </div>

        <el-drawer v-model="detailVisible" title="机会详情" size="480px">
          <template v-if="oppDetail">
            <h3 class="drawer-title">
              {{ oppDetail.opportunity.player_name ?? '未知球员' }}
              <el-tag :type="oppDetail.opportunity.verified_status === 'inferred' ? 'info' : 'warning'" size="small">
                {{ OPPORTUNITY_LABELS[oppDetail.opportunity.opportunity_type] ?? oppDetail.opportunity.opportunity_type }}
              </el-tag>
            </h3>
            <el-descriptions :column="2" border size="small">
              <el-descriptions-item label="俱乐部">{{ oppDetail.opportunity.club_name ?? '未知' }}</el-descriptions-item>
              <el-descriptions-item label="位置">{{ oppDetail.opportunity.position ?? '—' }}</el-descriptions-item>
              <el-descriptions-item label="年龄">{{ oppDetail.opportunity.age ?? '—' }}</el-descriptions-item>
              <el-descriptions-item label="身价">
                {{ oppDetail.opportunity.market_value != null ? formatMoney(oppDetail.opportunity.market_value) : '未知' }}
              </el-descriptions-item>
              <el-descriptions-item label="合同到期">{{ formatDate(oppDetail.opportunity.contract_end) }}</el-descriptions-item>
              <el-descriptions-item label="剩余月数">
                {{ oppDetail.opportunity.contract_remaining_months ?? '未知' }}
              </el-descriptions-item>
              <el-descriptions-item label="已挂牌">
                {{ oppDetail.opportunity.listed == null ? '来源未提供' : oppDetail.opportunity.listed ? '是' : '否' }}
              </el-descriptions-item>
              <el-descriptions-item label="可租借">
                {{ oppDetail.opportunity.loan_listed == null ? '来源未提供' : oppDetail.opportunity.loan_listed ? '是' : '否' }}
              </el-descriptions-item>
              <el-descriptions-item label="数据来源">{{ oppDetail.opportunity.source }}</el-descriptions-item>
              <el-descriptions-item label="更新时间">{{ formatDateTime(oppDetail.opportunity.last_seen_at) }}</el-descriptions-item>
            </el-descriptions>

            <h4 class="section-title">评分维度</h4>
            <el-descriptions :column="2" border size="small">
              <el-descriptions-item label="球员实力">{{ formatScore(oppDetail.opportunity.scores.ability) }}</el-descriptions-item>
              <el-descriptions-item label="阵容适配">{{ formatScore(oppDetail.opportunity.scores.squad_fit) }}</el-descriptions-item>
              <el-descriptions-item label="机会强度">{{ formatScore(oppDetail.opportunity.scores.opportunity) }}</el-descriptions-item>
              <el-descriptions-item label="财务可行">{{ formatScore(oppDetail.opportunity.scores.financial) }}</el-descriptions-item>
              <el-descriptions-item label="综合推荐">{{ formatScore(oppDetail.opportunity.scores.overall) }}</el-descriptions-item>
              <el-descriptions-item label="评分置信">{{ formatScore(oppDetail.opportunity.scores.confidence) }}</el-descriptions-item>
            </el-descriptions>
            <el-alert
              v-if="oppDetail.opportunity.scores.financial == null"
              title="当前没有可靠预算来源，财务可行性未计算；报价不会声称符合预算。"
              type="info"
              :closable="false"
              show-icon
              class="warning-line"
            />
            <template v-if="signalsOf(oppDetail.opportunity.detail).length">
              <h4 class="section-title">AI 推测依据</h4>
              <ul class="caps">
                <li v-for="(signal, index) in signalsOf(oppDetail.opportunity.detail)" :key="index">{{ signal }}</li>
              </ul>
            </template>
            <div class="offer-actions">
              <el-button type="primary" @click="workbenchFromOpportunity(oppDetail.opportunity.instance_id)">
                在报价工作台打开
              </el-button>
            </div>
          </template>
        </el-drawer>

        <el-drawer v-model="alertsVisible" title="转会提醒" size="420px">
          <el-empty v-if="!alerts.length" description="暂无提醒" :image-size="60" />
          <div
            v-for="alert in alerts"
            :key="alert.alert_id"
            class="alert-item"
            :class="{ 'alert-item--read': alert.read_at }"
            @click="readAlert(alert)"
          >
            <div class="alert-head">
              <strong>{{ alert.title }}</strong>
              <el-tag v-if="!alert.read_at" type="danger" size="small">未读</el-tag>
            </div>
            <p class="muted">{{ alert.message }}</p>
            <span class="muted">{{ formatDateTime(alert.created_at) }}</span>
          </div>
        </el-drawer>
      </el-tab-pane>

      <el-tab-pane label="成交策略" name="strategy">
        <el-card shadow="never" class="learning-card" data-testid="online-learning-status">
          <template #header>
            <div class="offer-head">
              <strong>在线持续学习</strong>
              <div class="tag-gap">
                <el-tag size="small" :type="onlineStatus?.enabled ? 'success' : 'info'">
                  {{ onlineStatus?.status_label ?? '加载中' }}
                </el-tag>
                <el-button size="small" text :loading="onlineLoading" @click="loadOnlineLearning">刷新</el-button>
                <el-button
                  v-if="onlineStatus?.enabled"
                  size="small"
                  text
                  :loading="onlineBusy"
                  @click="toggleOnlineLearning(true)"
                >暂停</el-button>
                <el-button
                  v-else
                  size="small"
                  text
                  :loading="onlineBusy"
                  @click="toggleOnlineLearning(false)"
                >恢复</el-button>
              </div>
            </div>
          </template>
          <el-skeleton v-if="onlineLoading && !onlineStatus" :rows="3" animated />
          <el-alert
            v-else-if="onlineError"
            :title="onlineError"
            type="warning"
            :closable="false"
            show-icon
          />
          <template v-else-if="onlineStatus">
            <div class="learning-stats">
              <div><span>已观察事件</span><strong>{{ onlineStatus.counts.events_observed ?? 0 }}</strong></div>
              <div><span>已确认交易</span><strong>{{ onlineStatus.counts.confirmed_transfers ?? 0 }}</strong></div>
              <div><span>全球俱乐部</span><strong>{{ onlineStatus.counts.global_clubs ?? 0 }}</strong></div>
              <div><span>重点俱乐部</span><strong>{{ onlineStatus.counts.focus_clubs ?? 0 }}</strong></div>
            </div>
            <p class="muted">
              最近监控 {{ formatDateTime(onlineStatus.last_monitor_at) }}
              <span v-if="onlineStatus.last_learning_at"> · 最近学习 {{ formatDateTime(onlineStatus.last_learning_at) }}</span>
            </p>
            <el-alert
              v-if="!onlineStatus.coverage?.transfer_history_available"
              :title="onlineStatus.coverage?.note ?? '原生读取器不提供转会历史；只有导入的成交记录会计入学习'"
              type="info"
              :closable="false"
              show-icon
              class="notice"
            />
            <div v-if="onlineFocus.length" class="online-block">
              <strong>重点学习俱乐部</strong>
              <ul class="learning-patterns">
                <li v-for="club in onlineFocus" :key="club.club_id">
                  <div class="offer-head">
                    <strong>{{ club.club_name ?? `俱乐部 ${club.club_id}` }}</strong>
                    <el-tag size="small" type="info">{{ club.confidence.label }} · 样本 {{ club.sample_size }}</el-tag>
                  </div>
                  <p class="rationale">
                    买入 {{ club.trade_counts?.buying ?? club.buying.completed }}
                    · 卖出 {{ club.trade_counts?.selling ?? club.selling.completed }}
                    · 租借 {{ club.trade_counts?.loans ?? 0 }}
                  </p>
                </li>
              </ul>
            </div>
            <div v-if="onlineActivity.length" class="online-block">
              <strong>最近学习动态</strong>
              <ul class="learning-patterns">
                <li v-for="item in onlineActivity" :key="item.activity_id">
                  <div class="offer-head">
                    <span>{{ item.title }}</span>
                    <span class="muted">{{ formatDateTime(item.created_at) }}</span>
                  </div>
                </li>
              </ul>
            </div>
            <p v-if="onlineStatus.latest_error" class="muted">最近一次学习未完成：{{ onlineStatus.latest_error }}</p>
          </template>
        </el-card>

        <el-card shadow="never" class="learning-card" data-testid="learning-status">
          <template #header>
            <div class="offer-head">
              <strong>交易策略学习</strong>
              <el-button size="small" text :loading="learningLoading" @click="loadLearningStatus">刷新</el-button>
            </div>
          </template>
          <el-skeleton v-if="learningLoading && !learning" :rows="3" animated />
          <el-alert
            v-else-if="learningError"
            :title="learningError"
            type="warning"
            :closable="false"
            show-icon
          />
          <template v-else-if="learning">
            <div class="learning-stats">
              <div><span>有效案例</span><strong>{{ learning.totals.cases }}</strong></div>
              <div><span>成交案例</span><strong>{{ learning.totals.completed_transfers }}</strong></div>
              <div>
                <span>置信度</span>
                <strong>{{ learning.confidence.label }}（样本 {{ learning.confidence.sample_size }}）</strong>
              </div>
            </div>
            <div v-if="learningTypes.length" class="learning-types">
              <el-tag v-for="[type, count] in learningTypes" :key="type" size="small" class="tag-gap">
                {{ TYPE_LABELS[type] ?? type }} {{ count }}
              </el-tag>
            </div>
            <el-alert
              v-if="!learning.available || learning.totals.cases === 0"
              :title="learning.message ?? '当前存档没有真实成交案例，学习暂不可用'"
              type="info"
              :closable="false"
              show-icon
              class="notice"
            />
            <ul v-if="learning.patterns.length" class="learning-patterns">
              <li v-for="pattern in learning.patterns" :key="pattern.key">
                <div class="offer-head">
                  <strong>{{ TYPE_LABELS[pattern.key] ?? pattern.key }}</strong>
                  <el-tag size="small" type="info">{{ pattern.sample_size }} 例 · {{ pattern.confidence.label }}</el-tag>
                </div>
                <p class="rationale">{{ pattern.summary }}</p>
              </li>
            </ul>
            <p class="muted learning-version">数据版本 {{ learning.data_version }}</p>
          </template>
        </el-card>

        <div v-loading="strategyLoading">
          <el-alert
            v-if="strategyInsights?.message"
            :title="strategyInsights.message"
            type="warning"
            :closable="false"
            show-icon
            class="notice"
          />
          <div class="pattern-grid" v-if="strategyInsights?.patterns?.length">
            <el-card v-for="pattern in strategyInsights.patterns" :key="pattern.key" shadow="never" class="pattern-card">
              <div class="offer-head">
                <strong>{{ pattern.label }}</strong>
                <el-tag :type="pattern.sufficient_sample ? 'success' : 'info'" size="small">
                  {{ pattern.sample_size }} 例
                </el-tag>
              </div>
              <p class="rationale">{{ pattern.summary }}</p>
              <p class="muted" v-if="pattern.case_ids.length">案例：{{ pattern.case_ids.join('、') }}</p>
            </el-card>
          </div>

          <h3 class="section-title">最近成交案例（{{ strategyCases.length }}）</h3>
          <el-table v-if="strategyCases.length" :data="strategyCases" size="small" class="table">
            <el-table-column label="球员" min-width="150">
              <template #default="{ row }">{{ row.player_name ?? row.case_id }}</template>
            </el-table-column>
            <el-table-column label="类型" width="100">
              <template #default="{ row }">{{ TYPE_LABELS[row.transfer_type] ?? row.transfer_type }}</template>
            </el-table-column>
            <el-table-column label="成交费用" width="140" align="right">
              <template #default="{ row }">{{ row.actual_fee != null ? formatMoney(row.actual_fee) : '未知' }}</template>
            </el-table-column>
            <el-table-column label="分期" width="110">
              <template #default="{ row }">
                {{ row.installments?.count ? `${row.installments.count} 期` : '无/未知' }}
              </template>
            </el-table-column>
            <el-table-column label="附加" width="120">
              <template #default="{ row }">
                {{ row.addons_potential != null ? formatMoney(row.addons_potential) : row.addons?.count ? `${row.addons.count} 条` : '未知' }}
              </template>
            </el-table-column>
            <el-table-column label="二转分成" width="100">
              <template #default="{ row }">{{ row.sell_on_clause != null ? `${row.sell_on_clause}%` : '无/未知' }}</template>
            </el-table-column>
            <el-table-column label="数据" width="110">
              <template #default="{ row }">
                <el-tag :type="row.case_origin === 'demo' ? 'info' : 'success'" size="small">
                  {{ row.case_origin === 'demo' ? '演示数据' : row.case_origin === 'negotiation' ? '谈判结果' : '导入数据' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="日期" width="110">
              <template #default="{ row }">{{ formatDateTime(row.observed_at) }}</template>
            </el-table-column>
          </el-table>
          <el-empty
            v-else
            description="当前存档没有真实成交案例（数据源不提供历史转会）；可在数据中心导入 CSV/JSON。"
          />

          <h3 class="section-title">
            当前目标相似案例
            <el-button size="small" text @click="loadSimilar">刷新</el-button>
          </h3>
          <el-alert v-if="similarMessage" :title="similarMessage" type="info" :closable="false" show-icon />
          <el-table v-if="similarCases.length" :data="similarCases" size="small" class="table">
            <el-table-column label="球员" min-width="140">
              <template #default="{ row }">{{ row.player_name ?? row.case_id }}</template>
            </el-table-column>
            <el-table-column label="匹配度" width="100" align="right">
              <template #default="{ row }">{{ row.match_pct != null ? `${row.match_pct}%` : '—' }}</template>
            </el-table-column>
            <el-table-column label="共同特征" min-width="200">
              <template #default="{ row }">{{ (row.matched_features ?? []).join('、') || '—' }}</template>
            </el-table-column>
            <el-table-column label="关键差异" min-width="180">
              <template #default="{ row }">{{ (row.differences ?? []).join('、') || '—' }}</template>
            </el-table-column>
            <el-table-column label="成交方式" width="110">
              <template #default="{ row }">{{ TYPE_LABELS[row.transfer_type] ?? row.transfer_type }}</template>
            </el-table-column>
            <el-table-column label="成交费用" width="140" align="right">
              <template #default="{ row }">{{ row.actual_fee != null ? formatMoney(row.actual_fee) : '未知' }}</template>
            </el-table-column>
          </el-table>
          <el-empty v-else description="在报价工作台选择一名球员后，这里会显示相似成交案例" :image-size="60" />
        </div>
      </el-tab-pane>

      <el-tab-pane label="报价工作台" name="workbench">
        <el-tabs v-model="activeTab" class="director-tabs">
      <el-tab-pane label="转会情报" name="intel">
        <div class="intel-grid">
          <el-card shadow="never" class="panel">
            <template #header>我的俱乐部</template>
            <template v-if="clubSummary">
              <div class="summary-row">
                <div><span>买入</span><strong>{{ clubSummary.purchases ?? 0 }}</strong></div>
                <div><span>卖出</span><strong>{{ clubSummary.sales ?? 0 }}</strong></div>
                <div><span>已达成</span><strong>{{ clubSummary.agreed ?? 0 }}</strong></div>
                <div><span>未完成</span><strong>{{ clubSummary.pending ?? 0 }}</strong></div>
                <div><span>取消</span><strong>{{ clubSummary.cancelled ?? 0 }}</strong></div>
              </div>
              <p class="muted" v-if="clubSummary.warning">{{ clubSummary.warning }}</p>
            </template>
            <el-empty v-else description="当前存档还没有识别出执教俱乐部" :image-size="60" />
          </el-card>
          <el-card shadow="never" class="panel">
            <template #header>数据能力</template>
            <ul class="caps" v-if="overview">
              <li>自动合同：{{ overview.capabilities.auto_contract ? '可用（周薪/到期日）' : '不可用' }}</li>
              <li>自动租借条款：{{ overview.capabilities.auto_loan_terms ? '有真实记录' : '无来源' }}</li>
              <li>自动转会历史：{{ overview.capabilities.auto_transfer_history ? '可用' : '不可用（需导入）' }}</li>
              <li>预算数据：{{ overview.capabilities.auto_budget ? '可用' : '不可用' }}</li>
              <li>未知合同字段：{{ overview.unknown_contract_fields }}</li>
              <li>数据冲突：{{ overview.identity_conflicts }}</li>
            </ul>
          </el-card>
        </div>

        <div class="filters">
          <el-select v-model="transferStatus" class="filter">
            <el-option label="已完成" value="completed" />
            <el-option label="已达成" value="agreed" />
            <el-option label="进行中" value="pending" />
            <el-option label="已取消" value="cancelled" />
            <el-option label="全部" value="all" />
          </el-select>
          <el-select v-model="transferType" clearable placeholder="交易类型" class="filter">
            <el-option v-for="(label, key) in TYPE_LABELS" :key="key" :label="label" :value="key" />
          </el-select>
        </div>

        <el-table v-if="transfers?.items.length" :data="transfers.items" class="table" size="small">
          <el-table-column prop="player_name" label="球员" min-width="150" />
          <el-table-column label="从 → 到" min-width="220">
            <template #default="{ row }">
              {{ row.from_club_name ?? '—' }} → {{ row.to_club_name ?? '—' }}
            </template>
          </el-table-column>
          <el-table-column label="类型" width="110">
            <template #default="{ row }">{{ TYPE_LABELS[row.transfer_type] ?? row.transfer_type }}</template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">{{ STATUS_LABELS[row.status] ?? row.status }}</template>
          </el-table-column>
          <el-table-column label="日期" width="110">
            <template #default="{ row }">{{ formatDate(row.transfer_date) }}</template>
          </el-table-column>
          <el-table-column label="费用" width="140" align="right">
            <template #default="{ row }">{{ row.effective_fee != null ? formatMoney(row.effective_fee) : '未知' }}</template>
          </el-table-column>
        </el-table>
        <el-empty v-else description="没有符合条件的转会记录。当前数据源不提供自动历史转会，可在数据中心导入 CSV/JSON。" />
      </el-tab-pane>

      <el-tab-pane label="AI 买入报价" name="purchase">
        <el-empty v-if="!analysis" description="请先在上方搜索并选择一名球员" />
        <template v-else>
          <div class="contract-strip">
            <span>周薪：{{ contract?.wage != null ? formatMoney(contract.wage) : '未知' }}</span>
            <span>合同到期：{{ contract?.contract_end ? formatDate(contract.contract_end) : '未知' }}</span>
            <span>剩余：{{ contract?.remaining_months != null ? `${contract.remaining_months} 个月` : '未知' }}</span>
            <span>身价：{{ analysis.player.market_value != null ? formatMoney(analysis.player.market_value) : '未知' }}</span>
            <el-tag v-if="contract?.listed" type="warning" size="small">已挂牌</el-tag>
            <el-tag v-if="contract?.not_for_sale" type="danger" size="small">非卖品</el-tag>
          </div>

          <el-alert
            v-if="analysis.valuation.insufficient_sample"
            :title="`可比成交仅 ${analysis.valuation.sample_size} 笔，估值区间不可用；报价以身价为基准。`"
            type="warning"
            :closable="false"
            show-icon
          />

          <div class="budget-row">
            <span>可用预算（可选）</span>
            <el-input-number v-model="budget" :min="0" :step="100000" controls-position="right" />
            <el-button @click="refreshPurchase">重新生成</el-button>
          </div>
          <div v-if="purchase" class="currency-row">
            <span class="sm-label">报价币种</span>
            <el-tag size="small" :type="purchase.currency ? 'info' : 'warning'">
              {{ currencyLabel(purchase.currency) }}
            </el-tag>
            <span v-if="!purchase.currency" class="muted">货币单位未知，金额不能按默认币种理解</span>
          </div>
          <p v-if="purchase?.learning_adjustment" class="muted" data-testid="purchase-learning-basis">
            学习依据：{{
              purchase.learning_adjustment.applied
                ? `已参考 ${purchase.learning_adjustment.sample_size} 条真实成交样本调整报价`
                : purchase.learning_adjustment.basis
            }}
          </p>
          <el-alert
            v-for="(warning, index) in purchase?.warnings ?? []"
            :key="index"
            :title="warning"
            type="warning"
            :closable="false"
            show-icon
            class="warning-line"
          />

          <div class="offer-grid" v-loading="offerLoading">
            <el-card v-for="offer in purchase?.offers ?? []" :key="offer.offer_type" shadow="hover" class="offer-card">
              <template #header>
                <div class="offer-head">
                  <strong>{{ offerTitle(offer.offer_type) }}</strong>
                  <el-tag :type="riskTag(offer.risk_level)" size="small">风险 {{ offer.risk_level }}</el-tag>
                </div>
              </template>
              <dl class="offer-facts">
                <div><dt>基础报价</dt><dd>{{ formatMoney(offer.base_fee) }}</dd></div>
                <div><dt>立即支付</dt><dd>{{ formatMoney(offer.immediate_payment) }}</dd></div>
                <div><dt>分期</dt><dd>{{ offer.installments_total != null ? formatMoney(offer.installments_total) : '无' }}</dd></div>
                <div><dt>附加费用</dt><dd>{{ offer.addons_potential != null ? formatMoney(offer.addons_potential) : '未知' }}</dd></div>
                <div><dt>固定承诺</dt><dd>{{ formatMoney(offer.total_committed) }}</dd></div>
                <div><dt>潜在总成本</dt><dd>{{ formatMoney(offer.potential_total) }}</dd></div>
                <div><dt>工资影响</dt><dd>{{ offer.wage_impact != null ? `${formatMoney(offer.wage_impact)}/年` : '未知' }}</dd></div>
                <div><dt>货币</dt><dd>{{ currencyLabel(offer.currency) }}</dd></div>
              </dl>
              <p class="rationale">{{ String(offer.rationale.reason ?? '') }}</p>
              <p class="muted" v-if="offer.budget_feasible === false">立即支付超过预算，需要调整结构</p>
              <div class="offer-actions">
                <el-button size="small" @click="saveDraft(offer, 'purchase')">保存草稿</el-button>
                <el-button size="small" type="primary" plain @click="startNegotiation(offer, 'purchase')">
                  记录谈判
                </el-button>
                <el-button size="small" data-testid="feedback-open" @click="openFeedback(offer, purchase)">
                  记录结果
                </el-button>
              </div>
            </el-card>
            <el-empty v-if="purchase && !purchase.offers.length" description="没有足够数据生成报价（不编造金额）" />
          </div>
        </template>
      </el-tab-pane>

      <el-tab-pane label="AI 出售报价" name="sale">
        <el-empty v-if="!analysis" description="请先在上方搜索并选择一名球员" />
        <template v-else>
          <div class="contract-strip">
            <span>同位置队友：{{ analysis.sale_preview.squad_impact?.same_position_peers ?? '未知' }}</span>
            <span>缺口风险：{{ analysis.sale_preview.squad_impact?.squad_gap_risk ?? '未知' }}</span>
            <span>工资释放：{{ analysis.contract.annual_wage != null ? formatMoney(analysis.contract.annual_wage) : '未知' }}</span>
            <el-button size="small" @click="refreshSale">重新生成</el-button>
          </div>
          <div v-if="sale" class="currency-row">
            <span class="sm-label">报价币种</span>
            <el-tag size="small" :type="sale.currency ? 'info' : 'warning'">{{ currencyLabel(sale.currency) }}</el-tag>
            <span v-if="!sale.currency" class="muted">货币单位未知，金额不能按默认币种理解</span>
          </div>
          <p v-if="sale?.learning_adjustment" class="muted" data-testid="sale-learning-basis">
            学习依据：{{
              sale.learning_adjustment.applied
                ? `已参考 ${sale.learning_adjustment.sample_size} 条真实出售样本调整报价`
                : sale.learning_adjustment.basis
            }}
          </p>
          <el-alert
            v-for="(warning, index) in sale?.warnings ?? []"
            :key="index"
            :title="warning"
            type="warning"
            :closable="false"
            show-icon
            class="warning-line"
          />
          <div class="offer-grid" v-loading="offerLoading">
            <el-card v-for="offer in sale?.offers ?? []" :key="offer.offer_type" shadow="hover" class="offer-card">
              <template #header>
                <div class="offer-head">
                  <strong>{{ offerTitle(offer.offer_type) }}</strong>
                  <el-tag :type="riskTag(offer.risk_level)" size="small">风险 {{ offer.risk_level }}</el-tag>
                </div>
              </template>
              <dl class="offer-facts">
                <div><dt>基础报价</dt><dd>{{ formatMoney(offer.base_fee) }}</dd></div>
                <div><dt>即时收款</dt><dd>{{ formatMoney(offer.immediate_payment) }}</dd></div>
                <div><dt>分期收款</dt><dd>{{ offer.installments_total != null ? formatMoney(offer.installments_total) : '无' }}</dd></div>
                <div><dt>浮动条款</dt><dd>{{ offer.addons_potential != null ? formatMoney(offer.addons_potential) : '未知' }}</dd></div>
                <div><dt>潜在总额</dt><dd>{{ formatMoney(offer.potential_total) }}</dd></div>
                <div><dt>二转分成</dt><dd>{{ offer.sell_on_pct != null ? `${offer.sell_on_pct}%` : '无' }}</dd></div>
                <div><dt>货币</dt><dd>{{ currencyLabel(offer.currency) }}</dd></div>
              </dl>
              <p class="rationale">{{ String(offer.rationale.reason ?? '') }}</p>
              <div class="offer-actions">
                <el-button size="small" @click="saveDraft(offer, 'sale')">保存草稿</el-button>
                <el-button size="small" type="primary" plain @click="startNegotiation(offer, 'sale')">
                  记录谈判
                </el-button>
                <el-button size="small" data-testid="feedback-open" @click="openFeedback(offer, sale)">
                  记录结果
                </el-button>
              </div>
            </el-card>
            <el-empty v-if="sale && !sale.offers.length" description="没有足够数据生成出售方案（不编造金额）" />
          </div>
        </template>
      </el-tab-pane>

      <el-tab-pane label="AI 租借报价" name="loan">
        <el-empty v-if="!analysis" description="请先在上方搜索并选择一名球员" />
        <template v-else>
          <div class="contract-strip">
            <span>可租借标记：{{ analysis.availability.loan_listed == null ? '来源未提供' : analysis.availability.loan_listed ? '可租借' : '未标记' }}</span>
            <span>周薪：{{ contract?.wage != null ? formatMoney(contract.wage) : '未知' }}</span>
            <span>合同剩余：{{ contract?.remaining_months != null ? `${contract.remaining_months} 个月` : '未知' }}</span>
            <el-button size="small" @click="refreshLoan">重新生成</el-button>
          </div>
          <div v-if="loan" class="currency-row">
            <span class="sm-label">报价币种</span>
            <el-tag size="small" :type="loan.currency ? 'info' : 'warning'">{{ currencyLabel(loan.currency) }}</el-tag>
            <span v-if="!loan.currency" class="muted">货币单位未知，金额不能按默认币种理解</span>
          </div>
          <p v-if="loan?.learning_adjustment" class="muted" data-testid="loan-learning-basis">
            学习依据：{{
              loan.learning_adjustment.applied
                ? `已参考 ${loan.learning_adjustment.sample_size} 条真实租借样本调整报价`
                : loan.learning_adjustment.basis
            }}
          </p>
          <el-alert
            v-for="(warning, index) in loan?.warnings ?? []"
            :key="index"
            :title="warning"
            type="warning"
            :closable="false"
            show-icon
            class="warning-line"
          />
          <div class="offer-grid" v-loading="loanLoading">
            <el-card v-for="offer in loan?.offers ?? []" :key="offer.offer_type" shadow="hover" class="offer-card">
              <template #header>
                <div class="offer-head">
                  <strong>{{ offerTitle(offer.offer_type) }}</strong>
                  <el-tag :type="riskTag(offer.risk_level)" size="small">风险 {{ offer.risk_level }}</el-tag>
                </div>
              </template>
              <dl class="offer-facts">
                <div><dt>租借费</dt><dd>{{ offer.loan_fee != null ? formatMoney(offer.loan_fee) : '未知' }}</dd></div>
                <div><dt>工资承担</dt><dd>{{ offer.wage_contribution_pct != null ? `${offer.wage_contribution_pct}%` : '未知' }}</dd></div>
                <div><dt>租期</dt><dd>{{ offer.loan_months != null ? `${offer.loan_months} 个月` : '未知' }}</dd></div>
                <div><dt>买断选择权</dt><dd>{{ offer.buy_option_fee != null ? formatMoney(offer.buy_option_fee) : '无' }}</dd></div>
                <div><dt>强制买断</dt><dd>{{ offer.buy_obligation_fee != null ? formatMoney(offer.buy_obligation_fee) : '无' }}</dd></div>
                <div><dt>潜在总成本</dt><dd>{{ formatMoney(offer.potential_total) }}</dd></div>
                <div><dt>货币</dt><dd>{{ currencyLabel(offer.currency) }}</dd></div>
              </dl>
              <p class="rationale">{{ String(offer.rationale.reason ?? '') }}</p>
              <div class="offer-actions">
                <el-button size="small" @click="saveDraft(offer, 'loan')">保存草稿</el-button>
                <el-button size="small" type="primary" plain @click="startNegotiation(offer, 'loan')">
                  记录谈判
                </el-button>
                <el-button size="small" data-testid="feedback-open" @click="openFeedback(offer, loan)">
                  记录结果
                </el-button>
              </div>
            </el-card>
            <el-empty v-if="loan && !loan.offers.length" description="没有足够数据生成租借方案（不编造金额）" />
          </div>
        </template>
      </el-tab-pane>

      <el-tab-pane label="合同与条款" name="contract">
        <el-empty v-if="!analysis" description="请先选择球员" />
        <template v-else>
          <el-descriptions :column="3" border class="desc">
            <el-descriptions-item label="合同到期">{{ contract?.contract_end ? formatDate(contract.contract_end) : '未知' }}</el-descriptions-item>
            <el-descriptions-item label="剩余月数">{{ contract?.remaining_months ?? '未知' }}</el-descriptions-item>
            <el-descriptions-item label="周薪">{{ contract?.wage != null ? formatMoney(contract.wage) : '未知' }}</el-descriptions-item>
            <el-descriptions-item label="合同开始">{{ contract?.contract_start ? formatDate(contract.contract_start) : '数据源不提供' }}</el-descriptions-item>
            <el-descriptions-item label="合同类型">{{ contract?.contract_type ?? '数据源不提供' }}</el-descriptions-item>
            <el-descriptions-item label="解约条款">{{ contract?.release_clause != null ? formatMoney(contract.release_clause) : '数据源不提供' }}</el-descriptions-item>
            <el-descriptions-item label="来源">{{ contract?.source ?? '未知' }}</el-descriptions-item>
            <el-descriptions-item label="观测时间">{{ contract?.observed_at ? formatDateTime(contract.observed_at) : '未知' }}</el-descriptions-item>
            <el-descriptions-item label="合同状态">{{ contract?.contract_status ?? '未知' }}</el-descriptions-item>
          </el-descriptions>
          <el-alert
            v-for="(warning, index) in contract?.warnings ?? []"
            :key="index"
            :title="warning"
            type="info"
            :closable="false"
            show-icon
            class="warning-line"
          />

          <h3 class="section-title">租借与买断</h3>
          <el-descriptions v-if="analysis.loan.available" :column="3" border class="desc">
            <el-descriptions-item label="母队">{{ analysis.loan.parent_club_name ?? '未知' }}</el-descriptions-item>
            <el-descriptions-item label="租借队">{{ analysis.loan.loan_club_name ?? '未知' }}</el-descriptions-item>
            <el-descriptions-item label="租借期">{{ formatDate(analysis.loan.start_date ?? null) }} → {{ formatDate(analysis.loan.end_date ?? null) }}</el-descriptions-item>
            <el-descriptions-item label="租借费用">{{ analysis.loan.loan_fee != null ? formatMoney(analysis.loan.loan_fee) : '未知' }}</el-descriptions-item>
            <el-descriptions-item label="买断选择权">{{ analysis.loan.has_option == null ? '未知' : analysis.loan.has_option ? '有' : '无' }}</el-descriptions-item>
            <el-descriptions-item label="强制买断">{{ analysis.loan.has_obligation == null ? '未知' : analysis.loan.has_obligation ? '有' : '无' }}</el-descriptions-item>
          </el-descriptions>
          <el-alert v-else :title="analysis.loan.note ?? '当前数据源没有租借记录'" type="info" :closable="false" show-icon />

          <h3 class="section-title">已确认条款</h3>
          <el-table v-if="clauses.length" :data="clauses" size="small" class="table">
            <el-table-column label="类型" width="120">
              <template #default="{ row }">{{ row.clause_type }}</template>
            </el-table-column>
            <el-table-column label="金额" width="130" align="right">
              <template #default="{ row }">{{ row.clause_value != null ? formatMoney(row.clause_value) : '未知' }}</template>
            </el-table-column>
            <el-table-column prop="clause_status" label="状态" width="140" />
            <el-table-column prop="trigger_condition" label="触发条件" min-width="160" />
            <el-table-column prop="payment_schedule" label="付款计划" min-width="160" />
            <el-table-column prop="source" label="来源" width="120" />
          </el-table>
          <el-empty v-else description="没有可验证的条款记录；未知条款不等于不存在" :image-size="60" />

          <h3 class="section-title">历史转会</h3>
          <el-table v-if="analysis.transfer_history.length" :data="analysis.transfer_history" size="small" class="table">
            <el-table-column label="从 → 到" min-width="220">
              <template #default="{ row }">{{ row.from_club_name ?? '—' }} → {{ row.to_club_name ?? '—' }}</template>
            </el-table-column>
            <el-table-column label="类型" width="110">
              <template #default="{ row }">{{ TYPE_LABELS[row.transfer_type] ?? row.transfer_type }}</template>
            </el-table-column>
            <el-table-column label="日期" width="110">
              <template #default="{ row }">{{ formatDate(row.transfer_date) }}</template>
            </el-table-column>
            <el-table-column label="费用" width="130" align="right">
              <template #default="{ row }">{{ row.effective_fee != null ? formatMoney(row.effective_fee) : '未知' }}</template>
            </el-table-column>
          </el-table>
          <el-empty v-else description="当前存档没有该球员的转会记录" :image-size="60" />
        </template>
      </el-tab-pane>

      <el-tab-pane label="谈判记录" name="negotiation">
        <div class="negotiation-layout">
          <el-card shadow="never" class="neg-list">
            <template #header>全部谈判（{{ negotiations.length }}）</template>
            <el-empty v-if="!negotiations.length" description="还没有谈判记录。在买入/出售方案里点击「记录谈判」。" :image-size="60" />
            <button
              v-for="item in negotiations"
              :key="item.negotiation_id"
              class="neg-item"
              :class="{ 'neg-item--active': activeNegotiation?.negotiation_id === item.negotiation_id }"
              @click="openNegotiation(item.negotiation_id)"
            >
              <span>#{{ item.negotiation_id }} · {{ directionLabel(item.direction) }}</span>
              <el-tag size="small">{{ item.status }}</el-tag>
            </button>
          </el-card>

          <el-card shadow="never" class="neg-detail">
            <template #header>谈判详情</template>
            <el-empty v-if="!activeNegotiation" description="选择左侧一条谈判记录" :image-size="60" />
            <template v-else>
              <dl class="offer-facts">
                <div><dt>状态</dt><dd>{{ activeNegotiation.status }}</dd></div>
                <div><dt>轮次</dt><dd>{{ activeNegotiation.round_count }}</dd></div>
                <div><dt>初始要价</dt><dd>{{ activeNegotiation.initial_ask != null ? formatMoney(activeNegotiation.initial_ask) : '未知' }}</dd></div>
                <div><dt>用户报价</dt><dd>{{ activeNegotiation.user_offer != null ? formatMoney(activeNegotiation.user_offer) : '未记录' }}</dd></div>
                <div><dt>对方反报价</dt><dd>{{ activeNegotiation.counter_offer != null ? formatMoney(activeNegotiation.counter_offer) : '未记录' }}</dd></div>
                <div><dt>最终费用</dt><dd>{{ activeNegotiation.final_fee != null ? formatMoney(activeNegotiation.final_fee) : '未完成' }}</dd></div>
              </dl>

              <div class="event-form">
                <el-select v-model="eventType" class="filter">
                  <el-option v-for="(label, key) in EVENT_LABELS" :key="key" :label="label" :value="key" />
                </el-select>
                <el-input-number v-model="eventAmount" :min="0" :step="100000" controls-position="right" placeholder="金额" />
                <el-input v-model="eventNote" placeholder="备注（可选）" class="note-input" />
                <el-button type="primary" @click="submitEvent">记录事件</el-button>
              </div>

              <el-timeline v-if="activeNegotiation.events?.length" class="timeline">
                <el-timeline-item
                  v-for="event in activeNegotiation.events"
                  :key="event.event_id"
                  :timestamp="formatDateTime(event.occurred_at)"
                >
                  {{ EVENT_LABELS[event.event_type] ?? event.event_type }}
                  <span v-if="event.amount != null"> · {{ formatMoney(event.amount) }}</span>
                  <span v-if="event.data?.note" class="muted"> · {{ event.data.note }}</span>
                </el-timeline-item>
              </el-timeline>

              <div class="review-block">
                <el-button size="small" @click="loadReview">生成复盘</el-button>
                <template v-if="review">
                  <el-descriptions :column="2" border class="desc review">
                    <el-descriptions-item label="结果">{{ review.outcome }}</el-descriptions-item>
                    <el-descriptions-item label="轮次">{{ review.round_count }}</el-descriptions-item>
                    <el-descriptions-item label="初始报价">{{ review.initial_offer != null ? formatMoney(review.initial_offer) : '未记录' }}</el-descriptions-item>
                    <el-descriptions-item label="最终成交">{{ review.final_fee != null ? formatMoney(review.final_fee) : '未完成' }}</el-descriptions-item>
                    <el-descriptions-item label="差异">{{ review.delta != null ? formatMoney(review.delta) : '—' }}</el-descriptions-item>
                    <el-descriptions-item label="差异比例">{{ review.delta_pct != null ? `${review.delta_pct}%` : '—' }}</el-descriptions-item>
                  </el-descriptions>
                  <el-alert
                    v-for="(warning, index) in review.warnings"
                    :key="index"
                    :title="warning"
                    type="info"
                    :closable="false"
                    show-icon
                    class="warning-line"
                  />
                </template>
              </div>
            </template>
          </el-card>
        </div>
      </el-tab-pane>
        </el-tabs>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="feedbackVisible" title="记录交易结果" width="480px">
      <div class="feedback-form">
        <p class="muted" v-if="feedbackBundle">
          方向：{{ directionLabel(feedbackBundle.direction) }} · 方案：{{ feedbackOffer ? offerTitle(feedbackOffer.offer_type) : '—' }}
        </p>
        <div class="feedback-row">
          <span class="sm-label">结果</span>
          <el-select v-model="feedbackOutcome" class="feedback-field">
            <el-option label="已成交" value="completed" />
            <el-option label="被拒绝" value="rejected" />
            <el-option label="用户取消" value="cancelled" />
            <el-option label="谈判中" value="negotiating" />
            <el-option label="未知结果" value="unknown" />
          </el-select>
        </div>
        <div class="feedback-row">
          <span class="sm-label">成交金额</span>
          <el-input-number
            v-model="feedbackAmount"
            :min="0"
            :step="100000"
            controls-position="right"
            class="feedback-field"
          />
        </div>
        <p v-if="!feedbackAmountValid" class="feedback-hint">成交时金额必填且必须大于 0</p>
        <div class="feedback-row">
          <span class="sm-label">备注</span>
          <el-input v-model="feedbackNote" type="textarea" :rows="3" class="feedback-field" placeholder="可选" />
        </div>
      </div>
      <template #footer>
        <el-button @click="feedbackVisible = false">取消</el-button>
        <el-button
          type="primary"
          :disabled="!feedbackAmountValid"
          :loading="feedbackSubmitting"
          @click="submitOfferFeedback"
        >
          提交
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="clubHabitsVisible" title="俱乐部交易画像" width="560px">
      <el-skeleton v-if="clubHabitsLoading" :rows="4" animated />
      <template v-else-if="clubHabits">
        <h3 class="drawer-title">{{ clubHabits.club_name }}</h3>
        <p class="muted">
          方向：{{ clubHabits.direction === 'selling' ? '卖方' : '买方' }} · 置信度
          {{ clubHabits.confidence.label }}（样本 {{ clubHabits.confidence.sample_size }}）
        </p>
        <template v-if="clubHabits.available">
          <el-descriptions :column="3" border size="small" class="desc">
            <el-descriptions-item
              v-for="[key, count] in observationEntries(clubHabits.observations)"
              :key="key"
              :label="CLUB_OBSERVATION_LABELS[key] ?? key"
            >
              {{ count }}
            </el-descriptions-item>
          </el-descriptions>
          <ul v-if="clubHabits.patterns.length" class="learning-patterns">
            <li v-for="pattern in clubHabits.patterns" :key="pattern.key">
              <div class="offer-head">
                <strong>{{ pattern.label }}</strong>
                <el-tag size="small" type="info">{{ pattern.sample_size }} 例</el-tag>
              </div>
              <p class="rationale">{{ pattern.summary }}</p>
            </li>
          </ul>
        </template>
        <template v-else>
          <el-empty description="暂无足够数据" :image-size="60" />
          <p v-if="clubHabits.message" class="muted">{{ clubHabits.message }}</p>
        </template>
      </template>
      <el-empty v-else description="暂无数据" :image-size="60" />
    </el-dialog>
  </div>
</template>

<style scoped>
.director {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.page-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 24px;
  flex-wrap: wrap;
}
.eyebrow {
  font-size: 11px;
  letter-spacing: 0.18em;
  color: var(--sm-text-muted);
  margin: 0 0 4px;
}
.page-head h1 {
  margin: 0;
  font-size: 26px;
}
.subtitle {
  margin: 6px 0 0;
  color: var(--sm-text-muted);
}
.head-stats {
  display: flex;
  gap: 18px;
}
.stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.stat span {
  font-size: 12px;
  color: var(--sm-text-muted);
}
.stat strong {
  font-size: 20px;
}
.notice {
  margin-bottom: 4px;
}
.player-picker {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.picker-input {
  max-width: 300px;
}
.picker-select {
  width: 300px;
}
.picked {
  color: var(--sm-text-muted);
  font-size: 13px;
}
.intel-grid {
  display: grid;
  grid-template-columns: 1.4fr 1fr;
  gap: 14px;
}
.summary-row {
  display: flex;
  gap: 26px;
  flex-wrap: wrap;
}
.summary-row div {
  display: flex;
  flex-direction: column;
}
.summary-row span {
  font-size: 12px;
  color: var(--sm-text-muted);
}
.summary-row strong {
  font-size: 20px;
}
.caps {
  margin: 0;
  padding-left: 18px;
  line-height: 1.9;
  font-size: 13px;
}
.filters {
  display: flex;
  gap: 10px;
  margin: 14px 0 8px;
}
.filter {
  width: 150px;
}
.table {
  width: 100%;
}
.contract-strip {
  display: flex;
  gap: 22px;
  align-items: center;
  flex-wrap: wrap;
  padding: 10px 0 14px;
  font-size: 13px;
  color: var(--sm-text-muted);
}
.budget-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 10px 0;
  font-size: 13px;
}
.warning-line {
  margin: 8px 0;
}
.offer-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 14px;
  align-items: start;
}
.offer-card {
  display: flex;
  flex-direction: column;
}
.offer-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.offer-facts {
  display: grid;
  gap: 6px;
  margin: 0 0 10px;
}
.offer-facts div {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
}
.offer-facts dt {
  color: var(--sm-text-muted);
}
.offer-facts dd {
  margin: 0;
  font-weight: 600;
}
.rationale {
  font-size: 12px;
  color: var(--sm-text-muted);
  line-height: 1.6;
  margin: 0 0 10px;
}
.offer-actions {
  display: flex;
  gap: 8px;
  margin-top: auto;
}
.desc {
  margin-bottom: 12px;
}
.section-title {
  margin: 18px 0 10px;
  font-size: 15px;
}
.negotiation-layout {
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: 14px;
}
.section-tabs {
  margin-top: 4px;
}
.section-nav {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 4px;
}
.section-nav__item {
  padding: 4px 10px;
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-pill);
  background: transparent;
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
  cursor: pointer;
}
.section-nav__item:hover {
  border-color: var(--sm-border-glow);
  color: var(--sm-text-primary);
}
.section-nav__item--active {
  border-color: var(--sm-accent-cyan);
  color: var(--sm-accent-cyan);
}

.radar-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 20px;
  flex-wrap: wrap;
}
.radar-stats {
  display: flex;
  gap: 28px;
  flex-wrap: wrap;
  padding: 12px 0;
}
.radar-stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.radar-stat span {
  font-size: 12px;
  color: var(--sm-text-muted);
}
.radar-stat strong {
  font-size: 22px;
}
.radar-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}
.filter-wide {
  width: 220px;
}
.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
.clickable-rows :deep(tr) {
  cursor: pointer;
}
.tag-gap {
  margin-left: 6px;
}
.scan-progress {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 10px 0;
}
.scan-progress :deep(.el-progress) {
  flex: 1;
}
.scan-progress-text {
  font-size: 12px;
  color: var(--sm-text-muted, #909399);
  white-space: nowrap;
}
.health-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-size: 12px;
}
.club-panel {
  margin: 12px 0;
}
.club-panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.club-search {
  width: 220px;
}
.alert-item {
  border-bottom: 1px solid var(--sm-border, #ebeef5);
  padding: 10px 0;
  cursor: pointer;
}
.alert-item--read {
  opacity: 0.55;
}
.alert-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}
.alert-item p {
  margin: 4px 0;
  font-size: 12px;
}
.pattern-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 12px;
  margin-top: 12px;
}
.pattern-card {
  min-height: 120px;
}
.drawer-title {
  margin: 0 0 12px;
  font-size: 17px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.neg-item {
  width: 100%;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  margin-bottom: 6px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: inherit;
  cursor: pointer;
  font-size: 13px;
}
.neg-item:hover {
  background: rgba(127, 127, 127, 0.08);
}
.neg-item--active {
  border-color: var(--el-color-primary);
  background: rgba(64, 158, 255, 0.08);
}
.event-form {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  align-items: center;
  margin: 12px 0;
}
.note-input {
  max-width: 220px;
}
.timeline {
  margin-top: 12px;
}
.review-block {
  margin-top: 14px;
}
.review {
  margin-top: 10px;
}
.muted {
  color: var(--sm-text-muted);
  font-size: 12px;
}
.learning-card {
  margin-bottom: 12px;
}
.learning-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 24px;
  margin-bottom: 8px;
}
.learning-stats div {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.learning-stats span {
  font-size: 12px;
  color: var(--sm-text-muted);
}
.learning-stats strong {
  font-size: 18px;
}
.learning-types {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 8px;
}
.learning-patterns {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 8px 0 0;
  padding: 0;
  list-style: none;
}
.learning-patterns li {
  padding: 8px 10px;
  border: 1px solid var(--sm-border, #ebeef5);
  border-radius: 8px;
}
.learning-version {
  margin: 8px 0 0;
}
.online-block {
  margin-top: 12px;
}
.online-block > strong {
  display: block;
  margin-bottom: 6px;
}
.currency-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin: 8px 0;
}
.feedback-form {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.feedback-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}
.feedback-row .sm-label {
  width: 76px;
  flex: 0 0 auto;
  padding-top: 6px;
}
.feedback-field {
  flex: 1 1 auto;
  min-width: 0;
}
.feedback-hint {
  margin: 0 0 0 86px;
  color: var(--el-color-danger, #f56c6c);
  font-size: 12px;
}
@media (max-width: 1100px) {
  .intel-grid,
  .negotiation-layout {
    grid-template-columns: 1fr;
  }
}
</style>
