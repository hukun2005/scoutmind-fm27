/**
 * 球员详情：档案、属性分组、成长曲线、发展归因、估值、相似成交与角色评分。
 */

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { asApiError, type ApiError } from '../api/client'
import { getPlayer, getPlayerDevelopment, getPlayerHistory } from '../api/players'
import { evaluateRole, listRoles } from '../api/scouting'
import { getSimilarTransfers, getValuation } from '../api/transfers'
import {
  addWatchlistItem,
  deleteWatchlistItem,
  listWatchlist,
} from '../api/watchlist'
import AttributeBar from '../components/AttributeBar.vue'
import ChartCard from '../components/ChartCard.vue'
import ConfidenceTag from '../components/ConfidenceTag.vue'
import CoverageBar from '../components/CoverageBar.vue'
import DataTable from '../components/DataTable.vue'
import EChart from '../components/EChart.vue'
import EmptyState from '../components/EmptyState.vue'
import ErrorState from '../components/ErrorState.vue'
import LoadingBlock from '../components/LoadingBlock.vue'
import NumberCell from '../components/NumberCell.vue'
import PageHeader from '../components/PageHeader.vue'
import ScoreBadge from '../components/ScoreBadge.vue'
import SectionCard from '../components/SectionCard.vue'
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
import type { TableColumn } from '../types/table'
import { useSessionStore } from '../stores/session'
import { buildAppearanceChart, buildGrowthChart } from '../utils/chart'
import {
  EMPTY,
  displayText,
  formatDate,
  formatDateTime,
  formatDecimal,
  formatInt,
  formatMoney,
  formatMoneyExact,
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

/** Instance id from the route; `null` for a malformed URL. */
const instanceId = computed(() => {
  const raw = route.params.id
  const parsed = Number.parseInt(Array.isArray(raw) ? (raw[0] ?? '') : (raw ?? ''), 10)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null
})

const summary = computed(() => detail.value?.summary ?? null)

const pageTitle = computed(() => (summary.value ? displayText(summary.value.name) : '球员详情'))

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

/** Load the profile, history and development panels. */
async function loadCore(id: number): Promise<void> {
  detailLoading.value = true
  detailError.value = null
  historyLoading.value = true
  historyError.value = null
  developmentLoading.value = true
  developmentError.value = null

  await Promise.all([
    (async () => {
      try {
        detail.value = await getPlayer(id)
        session.markSources([detail.value.summary.source])
      } catch (caught) {
        detailError.value = asApiError(caught)
        detail.value = null
      } finally {
        detailLoading.value = false
      }
    })(),
    (async () => {
      try {
        history.value = await getPlayerHistory(id)
      } catch (caught) {
        historyError.value = asApiError(caught)
        history.value = null
      } finally {
        historyLoading.value = false
      }
    })(),
    (async () => {
      try {
        development.value = await getPlayerDevelopment(id)
      } catch (caught) {
        developmentError.value = asApiError(caught)
        development.value = null
      } finally {
        developmentLoading.value = false
      }
    })(),
  ])
}

/** Load the comparable-transfer valuation. */
async function loadValuation(id: number): Promise<void> {
  valuationLoading.value = true
  valuationError.value = null
  try {
    valuation.value = await getValuation(id)
  } catch (caught) {
    valuationError.value = asApiError(caught)
    valuation.value = null
  } finally {
    valuationLoading.value = false
  }
}

/** Load comparable transfers. */
async function loadSimilar(id: number): Promise<void> {
  similarLoading.value = true
  similarError.value = null
  try {
    similar.value = await getSimilarTransfers(id, 20)
  } catch (caught) {
    similarError.value = asApiError(caught)
    similar.value = null
  } finally {
    similarLoading.value = false
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
    evaluation.value = await evaluateRole({ instance_id: id, role_key: roleKey })
  } catch (caught) {
    evaluationError.value = asApiError(caught)
    evaluation.value = null
  } finally {
    evaluationLoading.value = false
  }
}

/** Read whether the player is already tracked. */
async function loadWatchState(): Promise<void> {
  watchLoading.value = true
  watchError.value = null
  try {
    const response = await listWatchlist(session.activeSaveId ?? undefined)
    watchItem.value = (response.items ?? []).find((item) => item.instance_id === instanceId.value) ?? null
  } catch (caught) {
    watchError.value = asApiError(caught)
    watchItem.value = null
  } finally {
    watchLoading.value = false
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

/** Reload every panel of this player. */
function reloadAll(): void {
  const id = instanceId.value
  if (id === null) return
  void loadCore(id)
  void loadValuation(id)
  void loadSimilar(id)
  void loadWatchState()
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
        <el-button size="small" :loading="detailLoading" @click="reloadAll">刷新</el-button>
      </template>
    </PageHeader>

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
        <SectionCard title="档案" subtitle="字段全部来自后端，缺失显示为 —">
          <div class="profile">
            <div class="profile__identity">
              <div class="profile__name">{{ displayText(summary.name) }}</div>
              <div class="profile__sub">
                {{ positionLabel(summary.position) }} · {{ positionGroupLabel(summary.position_group) }} ·
                {{ displayText(summary.club) }}
              </div>
              <div class="profile__facts">
                <span>年龄 <strong>{{ summary.age === null ? EMPTY : `${summary.age} 岁` }}</strong></span>
                <span>生日 {{ formatDate(summary.birth_date) }}</span>
                <span>国籍 {{ displayText(summary.nationality) }}</span>
                <span>入档 {{ formatDate(detail.first_seen) }}</span>
                <span>最近 {{ formatDate(detail.last_seen) }}</span>
                <span>快照 {{ formatInt(detail.snapshot_count) }} 次</span>
              </div>
              <div v-if="detail.tags.length > 0" class="profile__tags">
                <el-tag v-for="tag in detail.tags" :key="tag" size="small" type="info" disable-transitions>{{ tag }}</el-tag>
              </div>
            </div>

            <div class="profile__metrics">
              <div class="metric">
                <span class="metric__label">CA</span>
                <span class="metric__value sm-num">{{ formatInt(summary.ca) }}</span>
              </div>
              <div class="metric">
                <span class="metric__label">PA</span>
                <span class="metric__value sm-num">{{ formatInt(summary.pa) }}</span>
              </div>
              <div class="metric">
                <span class="metric__label">身价（€）</span>
                <span class="metric__value sm-num" :title="formatMoneyExact(summary.market_value, 'EUR')">
                  {{ formatMoney(summary.market_value) }}
                </span>
                <span class="metric__hint">币种默认 EUR</span>
              </div>
              <div class="metric">
                <span class="metric__label">周薪（€）</span>
                <span class="metric__value sm-num" :title="formatMoneyExact(summary.wage, 'EUR')">
                  {{ formatMoney(summary.wage) }}
                </span>
              </div>
              <div class="metric">
                <span class="metric__label">合同到期</span>
                <span class="metric__value metric__value--text">{{ formatDate(summary.contract_end) }}</span>
              </div>
              <div class="metric">
                <span class="metric__label">数据完整度</span>
                <span class="metric__value sm-num">{{ formatPercent(summary.data_completeness) }}</span>
                <CoverageBar label="非空字段比例" :value="summary.data_completeness" dense />
              </div>
            </div>
          </div>
          <template #footer>
            <span v-if="detail.notes">备注：{{ detail.notes }}</span>
            <span v-else>备注：后端未提供备注字段。</span>
          </template>
        </SectionCard>

        <div class="sm-grid sm-grid--wide-left">
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

          <SectionCard title="估值（相似成交）" subtitle="区间来自可比成交的分位数，样本不足时不给区间">
            <header class="sm-row sm-row--between valuation__head">
              <ConfidenceTag :confidence="valuation?.confidence ?? null" />
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
        </div>

        <div class="sm-grid sm-grid--wide-left">
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

        <SectionCard title="球员属性" :subtitle="`按类别分组的 1–20 属性值（共 ${formatInt(detail.attributes.length)} 项）`">
          <EmptyState
            v-if="attributeGroups.length === 0"
            title="没有属性数据"
            description="当前快照没有记录任何属性键，常见于扫描器未启用 attributes 覆盖。"
            compact
          />
          <div v-else class="attribute-groups">
            <div v-for="group in attributeGroups" :key="group.category" class="attribute-group">
              <p class="attribute-group__title">{{ group.label }}</p>
              <div class="attribute-group__grid">
                <AttributeBar
                  v-for="attribute in group.items"
                  :key="attribute.key"
                  :label="attribute.name"
                  :value="attribute.value"
                  :code="attribute.key"
                />
              </div>
            </div>
          </div>
          <template #footer>
            属性为 1–20 整数刻度；null 表示该属性未被扫描到，不按 0 处理。
          </template>
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
      </template>

      <div v-if="watchError" class="sm-text-2xs sm-text-faint">
        关注名单状态读取失败：{{ watchError.message }}
      </div>
    </template>
  </div>
</template>

<style scoped>
.watch-toggle {
  display: inline-flex;
  align-items: center;
  gap: var(--sm-space-2);
}

.profile {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(320px, 1fr);
  gap: var(--sm-space-5);
}

.profile__identity {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-2);
  min-width: 0;
}

.profile__name {
  color: var(--sm-text);
  font-size: var(--sm-fs-2xl);
  font-weight: var(--sm-fw-semibold);
  line-height: var(--sm-lh-tight);
}

.profile__sub {
  color: var(--sm-text-2);
  font-size: var(--sm-fs-sm);
}

.profile__facts {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sm-space-3);
  color: var(--sm-text-2);
  font-size: var(--sm-fs-xs);
}

.profile__tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sm-space-1);
}

.profile__metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--sm-space-3);
}

.metric {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  padding: var(--sm-space-2) var(--sm-space-3);
  background: var(--sm-surface-2);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-md);
}

.metric__label {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}

.metric__value {
  color: var(--sm-text);
  font-size: var(--sm-fs-lg);
  font-weight: var(--sm-fw-semibold);
  text-align: right;
}

.metric__value--text {
  font-size: var(--sm-fs-sm);
}

.metric__hint {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
  text-align: right;
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
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-4);
}

.attribute-group__title {
  margin-bottom: var(--sm-space-2);
  color: var(--sm-text);
  font-size: var(--sm-fs-sm);
  font-weight: var(--sm-fw-semibold);
}

.attribute-group__grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(148px, 1fr));
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
  .profile,
  .attribution-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>




