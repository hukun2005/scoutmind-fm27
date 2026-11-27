<script setup lang="ts">
/**
 * AI 转会总监工作台：转会情报、AI 买入/出售报价、合同与条款、谈判记录。
 * 所有数字来自后端确定性引擎；页面只负责展示与记录，不计算金额。
 */

import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  appendNegotiationEvent,
  createNegotiation,
  generatePurchaseOffers,
  generateSaleOffers,
  getClubTransferSummary,
  getDirectorOverview,
  getNegotiation,
  getPlayerTransferAnalysis,
  listNegotiations,
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
  PlayerTransferAnalysis,
  TransferClause,
} from '../api/transferDirector'
import { listPlayers } from '../api/players'
import { listTransfers } from '../api/transfers'
import type { PlayerSummary } from '../types/players'
import type { TransferListResponse } from '../types/transfers'
import { formatDate, formatDateTime, formatMoney, formatPercent } from '../utils/format'

const route = useRoute()
const router = useRouter()

const activeTab = ref(String(route.query.tab ?? 'intel'))
const overview = ref<DirectorOverview | null>(null)
const loading = ref(false)

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
  analysisLoading.value = true
  purchase.value = null
  sale.value = null
  review.value = null
  try {
    analysis.value = await getPlayerTransferAnalysis(instanceId)
    purchase.value = analysis.value.purchase_preview
    sale.value = analysis.value.sale_preview
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

async function saveDraft(offer: Offer, direction: 'purchase' | 'sale') {  if (!selectedId.value) return
  try {
    await saveOffer(selectedId.value, { ...offer, direction, status: 'saved' })
    ElMessage.success('报价草稿已保存')
  } catch (error) {
    ElMessage.error((error as Error).message)
  }
}

async function startNegotiation(offer: Offer, direction: 'purchase' | 'sale') {
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
})

watch([transferStatus, transferType], () => {
  loadTransfers()
})
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
              <span>#{{ item.negotiation_id }} · {{ item.direction === 'purchase' ? '买入' : '出售' }}</span>
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
