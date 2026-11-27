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
  createNegotiation,
  generateLoanOffers,
  generatePurchaseOffers,
  generateSaleOffers,
  getClubTransferSummary,
  getDirectorOverview,
  getNegotiation,
  getOpportunityDetail,
  getOpportunitySummary,
  getPlayerTransferAnalysis,
  getSimilarStrategyCases,
  getStrategyInsights,
  listNegotiations,
  listOpportunities,
  listStrategyCases,
  listTransferAlerts,
  markTransferAlertRead,
  refreshOpportunities,
  reviewNegotiation,
  saveOffer,
} from '../api/transferDirector'
import type {
  ContractInfo,
  DirectorOverview,
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
import { listTransfers } from '../api/transfers'
import type { PlayerSummary } from '../types/players'
import type { TransferListResponse } from '../types/transfers'
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
  ageMin: null as number | null,
  ageMax: null as number | null,
  sort: 'score',
  page: 1,
  pageSize: 20,
})
const oppDetail = ref<{ opportunity: Opportunity; context: PlayerTransferAnalysis | null } | null>(null)
const detailVisible = ref(false)
const alerts = ref<TransferAlert[]>([])
const alertsVisible = ref(false)

const strategyCases = ref<StrategyCase[]>([])
const strategyInsights = ref<{ available: boolean; patterns: StrategyInsight[]; totals?: Record<string, number>; message: string | null } | null>(null)
const strategyLoading = ref(false)
const similarCases = ref<StrategyCase[]>([])
const similarMessage = ref<string | null>(null)

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

async function refreshRadar() {
  oppLoading.value = true
  try {
    const result = await refreshOpportunities()
    ElMessage.success(
      `扫描完成：新增 ${result.created ?? 0}，撤销 ${result.deactivated ?? 0}，提醒 ${result.alerts_created ?? 0}`,
    )
    await loadRadar()
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    oppLoading.value = false
  }
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
  await Promise.all([loadOverview(), loadTransfers(), loadClubSummary(), loadNegotiations()])
  loading.value = false
  const instanceId = Number(route.query.instance_id)
  if (Number.isFinite(instanceId) && instanceId > 0) {
    await selectedAndLoad(instanceId)
  }
  if (section.value === 'strategy') await loadStrategy()
  else await loadRadar()
})

watch([transferStatus, transferType], () => {
  loadTransfers()
})

watch(section, (value) => {
  router.replace({ query: { ...route.query, section: value } })
  if (value === 'strategy' && !strategyCases.value.length) loadStrategy()
  if (value === 'radar' && !oppItems.value.length) loadRadar()
})

watch(
  () => [oppFilters.type, oppFilters.group, oppFilters.sort],
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
            <el-button type="primary" :loading="oppLoading" @click="refreshRadar">重新扫描</el-button>
          </div>
        </div>

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
          <el-select v-model="oppFilters.sort" class="filter">
            <el-option label="综合评分" value="score" />
            <el-option label="合同到期" value="contract" />
            <el-option label="年龄" value="age" />
            <el-option label="身价" value="value" />
            <el-option label="最新发现" value="newest" />
          </el-select>
          <el-button @click="loadRadar">筛选</el-button>
        </div>

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
              </dl>
              <p class="rationale">{{ String(offer.rationale.reason ?? '') }}</p>
              <p class="muted" v-if="offer.budget_feasible === false">立即支付超过预算，需要调整结构</p>
              <div class="offer-actions">
                <el-button size="small" @click="saveDraft(offer, 'purchase')">保存草稿</el-button>
                <el-button size="small" type="primary" plain @click="startNegotiation(offer, 'purchase')">
                  记录谈判
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
              </dl>
              <p class="rationale">{{ String(offer.rationale.reason ?? '') }}</p>
              <div class="offer-actions">
                <el-button size="small" @click="saveDraft(offer, 'sale')">保存草稿</el-button>
                <el-button size="small" type="primary" plain @click="startNegotiation(offer, 'sale')">
                  记录谈判
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
              </dl>
              <p class="rationale">{{ String(offer.rationale.reason ?? '') }}</p>
              <div class="offer-actions">
                <el-button size="small" @click="saveDraft(offer, 'loan')">保存草稿</el-button>
                <el-button size="small" type="primary" plain @click="startNegotiation(offer, 'loan')">
                  记录谈判
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
@media (max-width: 1100px) {
  .intel-grid,
  .negotiation-layout {
    grid-template-columns: 1fr;
  }
}
</style>
