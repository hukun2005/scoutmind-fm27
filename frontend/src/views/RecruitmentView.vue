/**
 * 智能球探引擎：位置模板 + 六维球员评分、候选排序、雷达对比、隐藏价值发现与候选名单。
 */

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { asApiError, type ApiError } from '../api/client'
import { addWatchlistItem } from '../api/watchlist'
import {
  createShortlist,
  getHiddenValue,
  getShortlist,
  listShortlists,
  searchRecruitment,
} from '../api/recruitment'
import DataTable from '../components/DataTable.vue'
import EChart from '../components/EChart.vue'
import EmptyState from '../components/EmptyState.vue'
import ErrorState from '../components/ErrorState.vue'
import InsightPanel from '../components/InsightPanel.vue'
import LoadingBlock from '../components/LoadingBlock.vue'
import PageHeader from '../components/PageHeader.vue'
import ScoreBadge from '../components/ScoreBadge.vue'
import SectionCard from '../components/SectionCard.vue'
import StatStrip from '../components/StatStrip.vue'
import { useSessionStore } from '../stores/session'
import type {
  HiddenValueHit,
  HiddenValueResponse,
  PlayerScore,
  Shortlist,
  ShortlistSummary,
} from '../types/recruitment'
import type { TableColumn } from '../types/table'
import type { InsightItem, InsightTone, StatItem } from '../types/ui'
import { buildRadarChart, type RadarSeries } from '../utils/chart'
import { EMPTY, displayText, formatDecimal, formatInt, formatMoney, formatPercent } from '../utils/format'
import { positionLabel } from '../utils/labels'

const session = useSessionStore()
const router = useRouter()
const route = useRoute()

const SLOT_OPTIONS = [
  { value: 'GK', label: '门将' },
  { value: 'CB', label: '中后卫' },
  { value: 'LB', label: '左后卫' },
  { value: 'RB', label: '右后卫' },
  { value: 'DM', label: '后腰' },
  { value: 'CM', label: '中前卫' },
  { value: 'AM', label: '前腰' },
  { value: 'LW', label: '左边锋' },
  { value: 'RW', label: '右边锋' },
  { value: 'ST', label: '中锋' },
]

const form = reactive<{
  slot: string
  minAge: number | undefined
  maxAge: number | undefined
  budgetWan: number | undefined
  minScore: number | undefined
  limit: number
}>({ slot: 'ST', minAge: undefined, maxAge: undefined, budgetWan: undefined, minScore: undefined, limit: 20 })

const shortlistName = ref('')

const candidates = ref<PlayerScore[]>([])
const total = ref(0)
const dataGaps = ref<string[]>([])
const gradeRules = ref('')
const loading = ref(false)
const error = ref<ApiError | null>(null)
const searched = ref(false)

const hidden = ref<HiddenValueResponse | null>(null)
const hiddenLoading = ref(false)
const hiddenError = ref<ApiError | null>(null)

const shortlists = ref<ShortlistSummary[]>([])
const shortlistsLoading = ref(false)
const openedShortlist = ref<Shortlist | null>(null)
const generating = ref(false)

/** Candidates selected for the radar comparison (maximum three). */
const selected = ref<number[]>([])

const selectedPlayers = computed(() => candidates.value.filter((item) => selected.value.includes(item.player.instance_id)))

/** Scores actually returned by the search; drives the summary tiles only. */
const scoreValues = computed(() =>
  candidates.value.map((item) => item.score).filter((value): value is number => value !== null),
)

/** Highest returned score, or `null` when no candidate carries one. */
const topScore = computed(() => (scoreValues.value.length > 0 ? Math.max(...scoreValues.value) : null))

/** Mean of the returned scores, or `null` when no candidate carries one. */
const averageScore = computed(() => {
  const values = scoreValues.value
  if (values.length === 0) return null
  return values.reduce((sum, value) => sum + value, 0) / values.length
})

/** Candidates ordered by the returned score; presentation order only. */
const rankedCandidates = computed(() => candidates.value.slice().sort((a, b) => (b.score ?? -1) - (a.score ?? -1)))

/** Highest-scoring candidate, or `null` when the search returned nothing. */
const topCandidate = computed<PlayerScore | null>(() => rankedCandidates.value[0] ?? null)

/** Why the current filters produced no candidate; used by the conclusion panel. */
const emptyReason = computed(() => {
  if (!searched.value) return '尚未执行搜索。'
  const filters: string[] = []
  if (form.minScore !== undefined) filters.push(`最低评分 ${form.minScore}`)
  if (typeof form.budgetWan === 'number' && form.budgetWan > 0) filters.push(`预算 ${formatMoney(form.budgetWan * 10_000)}`)
  if (form.minAge !== undefined || form.maxAge !== undefined) filters.push('年龄区间')
  return filters.length > 0
    ? `当前条件（${filters.join('、')}）没有命中候选。`
    : '当前位置与数据源没有命中候选。'
})

/** Budget check between the form budget and the top candidate's market value. */
const budgetFit = computed<{ text: string; tone: InsightTone }>(() => {
  const target = topCandidate.value
  const budget = typeof form.budgetWan === 'number' ? form.budgetWan * 10_000 : null
  if (budget === null) {
    return { text: '未设置预算（预算上限留空），结果未按身价过滤。', tone: 'neutral' }
  }
  if (!target) {
    return { text: `预算上限 ${formatMoney(budget)}，但没有候选可比较身价。`, tone: 'neutral' }
  }
  const value = target.cost_estimate.market_value
  if (value === null) {
    return { text: `预算上限 ${formatMoney(budget)}；${target.player.name} 身价缺失，无法判断适配。`, tone: 'warning' }
  }
  if (value <= budget) {
    return {
      text: `预算上限 ${formatMoney(budget)}，${target.player.name} 身价 ${formatMoney(value)}，在预算内。`,
      tone: 'success',
    }
  }
  return {
    text: `预算上限 ${formatMoney(budget)}，${target.player.name} 身价 ${formatMoney(value)}，超出 ${formatMoney(value - budget)}。`,
    tone: 'warning',
  }
})

/** Overall tone of the conclusion panel, derived from the returned grades only. */
const insightTone = computed<InsightTone>(() => {
  if (!searched.value) return 'neutral'
  if (candidates.value.length === 0) return 'warning'
  const grade = topCandidate.value?.grade
  return grade === 'S' || grade === 'A' ? 'success' : 'info'
})

/** Conclusion items; every sentence maps to a returned field or the current form. */
const insightItems = computed<InsightItem[]>(() => {
  const target = topCandidate.value
  const items: InsightItem[] = [
    {
      label: '命中',
      text: `本次命中 ${formatInt(total.value)} 名，当前返回 ${formatInt(candidates.value.length)} 名候选。`,
    },
  ]
  if (target) {
    items.push({
      label: '最高评分',
      text: `${target.player.name} · ${formatDecimal(target.score, 1)} 分 · ${target.grade_label ?? '等级数据不足'}`,
    })
    items.push({ label: '最强项', text: target.strengths[0] ?? '属性数据不足，无法判断强项' })
    items.push({
      label: '主要风险',
      text: target.risks[0] ?? '暂无显著风险',
      tone: target.risks.length > 0 ? 'warning' : 'neutral',
    })
  } else {
    items.push({ label: '最高评分', text: '返回结果中没有可评估的候选（评分字段缺失）。' })
  }
  items.push({ label: '预算适配', text: budgetFit.value.text, tone: budgetFit.value.tone })
  if (searched.value && candidates.value.length === 0) {
    items.push({
      label: '下一步',
      text: `${emptyReason.value}放宽位置、年龄或预算，或降低最低评分后重新搜索。`,
      tone: 'warning',
    })
  }
  return items
})

/** Compact metrics replacing the former KPI card stack. */
const statItems = computed<StatItem[]>(() => [
  { label: '命中候选', value: formatInt(total.value), hint: '后端匹配总数' },
  { label: '本次返回', value: formatInt(candidates.value.length), hint: '当前结果条数' },
  {
    label: '最高评分',
    value: topScore.value === null ? EMPTY : formatDecimal(topScore.value, 1),
    hint: '返回结果中的最高分',
    tone: 'accent',
  },
  {
    label: '平均评分',
    value: averageScore.value === null ? EMPTY : formatDecimal(averageScore.value, 1),
    hint: `参与均值 ${formatInt(scoreValues.value.length)} 名`,
  },
  {
    label: '已评估规则',
    value: hidden.value ? formatInt(hidden.value.rules.evaluated.length) : EMPTY,
    hint: '隐藏价值规则',
  },
  {
    label: '无法评估规则',
    value: hidden.value ? formatInt(hidden.value.rules.unavailable.length) : EMPTY,
    hint: '缺少字段，悬停查看原因',
  },
])

/** Empty-state copy for the priority section. */
const emptyOppsDescription = computed(() => `${emptyReason.value}放宽筛选条件，或先运行隐藏价值扫描。`)

/** Radar axes: the six score dimensions, shared by every compared player. */
const radarOption = computed(() => {
  if (selectedPlayers.value.length === 0) return null
  const dimensions = selectedPlayers.value[0]?.dimensions ?? []
  const labels = dimensions.map((dimension) => dimension.label.replace(/（.*?）/, ''))
  const series: RadarSeries[] = selectedPlayers.value.map((item) => ({
    name: item.player.name,
    values: item.dimensions.map((dimension) => dimension.value),
  }))
  return buildRadarChart(labels, series)
})

const columns: TableColumn<PlayerScore>[] = [
  { prop: 'name', label: '球员', minWidth: 150, formatter: (row) => row.player.name },
  { prop: 'age', label: '年龄', width: 64, align: 'right', formatter: (row) => displayText(row.player.age) },
  { prop: 'position', label: '位置', width: 92, formatter: (row) => positionLabel(row.player.position) },
  { prop: 'club', label: '俱乐部', width: 140, formatter: (row) => displayText(row.player.club) },
  { prop: 'grade', label: '推荐等级', width: 112, formatter: (row) => row.grade_label ?? '数据不足' },
  { prop: 'score', label: '综合评分', width: 96, align: 'right', formatter: (row) => formatDecimal(row.score, 1) },
  { prop: 'ability', label: 'A 能力', width: 84, align: 'right', formatter: (row) => formatDecimal(dimension(row, 'ability'), 0) },
  { prop: 'potential', label: 'P 潜力', width: 84, align: 'right', formatter: (row) => formatDecimal(dimension(row, 'potential'), 0) },
  { prop: 'fit', label: 'T 适配', width: 84, align: 'right', formatter: (row) => formatDecimal(dimension(row, 'fit'), 0) },
  { prop: 'form', label: 'F 表现', width: 84, align: 'right', formatter: (row) => formatDecimal(dimension(row, 'form'), 0) },
  { prop: 'value', label: 'V 价值', width: 84, align: 'right', formatter: (row) => formatDecimal(dimension(row, 'value'), 0) },
  { prop: 'room', label: 'R 空间', width: 84, align: 'right', formatter: (row) => formatDecimal(dimension(row, 'room'), 0) },
  { prop: 'market_value', label: '身价', width: 110, align: 'right', formatter: (row) => formatMoney(row.player.market_value) },
  { prop: 'actions', label: '操作', width: 132, align: 'right' },
]

const hiddenColumns: TableColumn<HiddenValueHit>[] = [
  { prop: 'rule', label: '规则', width: 168, formatter: (row) => row.rule_label },
  { prop: 'name', label: '球员', minWidth: 150, formatter: (row) => row.player.name },
  { prop: 'age', label: '年龄', width: 64, align: 'right', formatter: (row) => displayText(row.player.age) },
  { prop: 'club', label: '俱乐部', width: 150, formatter: (row) => displayText(row.player.club) },
  { prop: 'value', label: '身价', width: 110, align: 'right', formatter: (row) => formatMoney(row.player.market_value) },
  { prop: 'signal', label: '信号强度', width: 96, align: 'right', formatter: (row) => formatDecimal(row.signal, 1) },
  { prop: 'evidence', label: '依据', minWidth: 320, formatter: (row) => row.evidence.join('；') },
]

/** One dimension value of a scored player. */
function dimension(row: PlayerScore, key: string): number | null {
  return row.dimensions.find((item) => item.key === key)?.value ?? null
}

/** Run the recruitment search. */
async function search(): Promise<void> {
  loading.value = true
  error.value = null
  searched.value = true
  selected.value = []
  try {
    const result = await searchRecruitment({
      save_id: session.activeSaveId ?? undefined,
      slot: form.slot || undefined,
      min_age: form.minAge,
      max_age: form.maxAge,
      max_value: form.budgetWan === undefined ? undefined : Math.round(form.budgetWan * 10_000),
      min_score: form.minScore,
      limit: form.limit,
    })
    candidates.value = result.items ?? []
    total.value = result.total ?? 0
    dataGaps.value = result.data_gaps ?? []
    gradeRules.value = result.grade_rules ?? ''
  } catch (caught) {
    error.value = asApiError(caught)
    candidates.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

/** Toggle one candidate in the radar comparison. */
function toggleCompare(instanceId: number): void {
  if (selected.value.includes(instanceId)) {
    selected.value = selected.value.filter((id) => id !== instanceId)
    return
  }
  if (selected.value.length >= 3) {
    ElMessage.warning('最多同时比较 3 名球员')
    return
  }
  selected.value = [...selected.value, instanceId]
}

/** Load the hidden-value rules and hits. */
async function loadHidden(): Promise<void> {
  hiddenLoading.value = true
  hiddenError.value = null
  try {
    hidden.value = await getHiddenValue(form.slot || undefined, 12)
  } catch (caught) {
    hiddenError.value = asApiError(caught)
    hidden.value = null
  } finally {
    hiddenLoading.value = false
  }
}

/** Load stored shortlists. */
async function loadShortlists(): Promise<void> {
  shortlistsLoading.value = true
  try {
    const result = await listShortlists()
    shortlists.value = result.items ?? []
  } catch {
    shortlists.value = []
  } finally {
    shortlistsLoading.value = false
  }
}

/** Generate and store a shortlist from the current filters. */
async function generate(): Promise<void> {
  const name = shortlistName.value.trim() || `${form.slot} 引援方案`
  generating.value = true
  try {
    const result = await createShortlist({
      save_id: session.activeSaveId ?? undefined,
      name,
      slot: form.slot || undefined,
      budget: form.budgetWan === undefined ? undefined : Math.round(form.budgetWan * 10_000),
      min_age: form.minAge,
      max_age: form.maxAge,
      limit: 8,
    })
    openedShortlist.value = result
    shortlistName.value = ''
    ElMessage.success('候选名单已生成并保存')
    await loadShortlists()
  } catch (caught) {
    ElMessage.error(asApiError(caught).message)
  } finally {
    generating.value = false
  }
}

/** Open one stored shortlist. */
async function openShortlist(id: number): Promise<void> {
  try {
    openedShortlist.value = await getShortlist(id)
  } catch (caught) {
    ElMessage.error(asApiError(caught).message)
  }
}

/** Follow one candidate; the backend keeps the item in the default list. */
async function followCandidate(row: PlayerScore): Promise<void> {
  try {
    await addWatchlistItem({ instance_id: row.player.instance_id })
    ElMessage.success(`已关注 ${row.player.name}`)
  } catch (caught) {
    ElMessage.warning(asApiError(caught).message)
  }
}

/** Open the player detail page of one candidate. */
function openCandidate(row: PlayerScore): void {
  void router.push(`/players/${row.player.instance_id}`)
}

/** Element tag type of a recommendation grade. */
function gradeTagType(grade: string | undefined): 'success' | 'primary' | 'warning' | 'danger' | 'info' {
  if (grade === 'S' || grade === 'A') return 'success'
  if (grade === 'B') return 'primary'
  if (grade === 'C') return 'warning'
  if (grade === 'D') return 'danger'
  return 'info'
}

onMounted(() => {
  const slot = route.query.slot
  if (typeof slot === 'string' && SLOT_OPTIONS.some((option) => option.value === slot)) {
    form.slot = slot
  }
  void search()
  void loadHidden()
  void loadShortlists()
})
</script>

<template>
  <div class="sm-page">
    <PageHeader
      title="引援机会"
      description="寻找最适合当前阵容、预算与发展计划的球员，而不是能力最高的人。推荐理由、适配位置与主要风险会一起给出。"
    />

    <InsightPanel
      title="引援结论"
      subtitle="只使用本次搜索结果与隐藏价值规则字段，不新增评分或预测。"
      :tone="insightTone"
      badge="规则生成"
      :items="insightItems"
      footnote="评分覆盖率低于 60% 时推荐等级记为「数据不足」；未设置预算时不做预算过滤。"
    />

    <StatStrip :items="statItems" dense />

    <section class="opps" aria-label="优先机会">
      <header class="opps__head">
        <span class="sm-section-label">优先机会</span>
        <h2 class="opps__title">优先机会</h2>
        <p class="opps__hint">按后端评分排序的前 3 名候选，仅重排现有字段；完整能力维度见下方候选球员表。</p>
      </header>
      <div v-if="rankedCandidates.length > 0" class="opps__grid">
        <article v-for="(item, index) in rankedCandidates.slice(0, 3)" :key="item.player.instance_id" class="opp-card">
          <header class="opp-card__head">
            <div class="opp-card__titles">
              <p class="opp-card__name">{{ displayText(item.player.name) }} <span class="opp-card__rank">#{{ index + 1 }}</span></p>
              <p class="opp-card__meta">
                {{ item.player.age === null ? EMPTY : `${item.player.age} 岁` }} ·
                {{ positionLabel(item.player.position) }} · {{ displayText(item.player.club) }}
              </p>
            </div>
            <ScoreBadge :score="item.score" size="sm" />
          </header>
          <div class="opp-card__tags">
            <el-tag size="small" :type="gradeTagType(item.grade)" disable-transitions>
              {{ item.grade_label ?? '数据不足' }}
            </el-tag>
            <span class="opp-card__coverage">评分覆盖率 {{ formatPercent(item.score_coverage, 0) }}</span>
          </div>
          <dl class="opp-card__facts">
            <div>
              <dt>强项</dt>
              <dd>{{ item.strengths.slice(0, 2).join('；') || '属性数据不足，无法判断强项' }}</dd>
            </div>
            <div>
              <dt>风险</dt>
              <dd>{{ item.risks[0] ?? '暂无显著风险' }}</dd>
            </div>
            <div>
              <dt>成本</dt>
              <dd>
                身价 {{ formatMoney(item.cost_estimate?.market_value) }} · 工资
                {{ formatMoney(item.cost_estimate?.wage) }} · 合同 {{ item.cost_estimate?.contract_end ?? EMPTY }}
              </dd>
            </div>
          </dl>
          <footer class="opp-card__actions">
            <el-button link size="small" @click="openCandidate(item)">详情</el-button>
            <el-button link size="small" type="primary" @click="followCandidate(item)">关注</el-button>
          </footer>
        </article>
      </div>
      <LoadingBlock v-else-if="loading" :rows="2" />
      <EmptyState v-else-if="searched" title="暂无可推荐机会" :description="emptyOppsDescription" compact />
      <EmptyState v-else title="尚未搜索" description="设置位置、预算后点击开始搜索" compact />
    </section>

    <section class="console sm-glass" aria-label="球探筛选控制台">
      <header class="console__head">
        <div class="console__titles">
          <span class="sm-section-label">筛选目标</span>
          <p class="console__hint">按位置、年龄与预算筛选，条件由后端执行，不做隐式猜测。</p>
        </div>
        <el-button size="small" type="primary" :loading="loading" @click="search">开始搜索</el-button>
      </header>
      <div class="console__grid">
        <label class="console__field">
          <span class="sm-label">位置</span>
          <el-select v-model="form.slot" size="small" aria-label="位置">
            <el-option v-for="item in SLOT_OPTIONS" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </label>
        <label class="console__field">
          <span class="sm-label">最小年龄</span>
          <el-input-number
            v-model="form.minAge"
            :min="14"
            :max="45"
            size="small"
            placeholder="不限"
            controls-position="right"
          />
        </label>
        <label class="console__field">
          <span class="sm-label">最大年龄</span>
          <el-input-number
            v-model="form.maxAge"
            :min="14"
            :max="45"
            size="small"
            placeholder="不限"
            controls-position="right"
          />
        </label>
        <label class="console__field">
          <span class="sm-label">预算上限（万 €）</span>
          <el-input-number
            v-model="form.budgetWan"
            :min="0"
            :step="500"
            size="small"
            placeholder="不限"
            controls-position="right"
          />
        </label>
        <label class="console__field">
          <span class="sm-label">最低综合评分</span>
          <el-input-number
            v-model="form.minScore"
            :min="0"
            :max="100"
            :step="5"
            size="small"
            placeholder="不限"
            controls-position="right"
          />
        </label>
      </div>
      <p v-if="gradeRules" class="sm-text-2xs sm-text-faint">{{ gradeRules }}</p>
      <el-alert
        v-if="dataGaps.length > 0"
        class="recruit__gaps"
        type="warning"
        :closable="false"
        show-icon
        title="评分缺口"
      >
        <ul class="recruit__list">
          <li v-for="gap in dataGaps" :key="gap">{{ gap }}</li>
        </ul>
      </el-alert>
    </section>

    <ErrorState v-if="error" :error="error" title="候选搜索失败" @retry="search" />
    <SectionCard v-else title="候选球员" :subtitle="`命中 ${formatInt(total)} 名，勾选最多 3 人做雷达对比`">
      <LoadingBlock v-if="loading && candidates.length === 0" :rows="3" />
      <DataTable
        v-else
        :columns="columns"
        :rows="candidates"
        :row-key="(row) => String(row.player.instance_id)"
        clickable
        :empty-title="searched ? '没有符合条件的候选' : '尚未搜索'"
        empty-description="放宽年龄、预算或位置后再试"
        @row-click="(row) => toggleCompare(row.player.instance_id)"
      >
        <template #expand="{ row }">
          <div class="recruit__detail">
            <div>
              <p class="sm-label">强项</p>
              <ul class="recruit__list">
                <li v-for="item in row.strengths" :key="item">{{ item }}</li>
                <li v-if="row.strengths.length === 0">没有足够属性判断强项</li>
              </ul>
            </div>
            <div>
              <p class="sm-label">风险</p>
              <ul class="recruit__list">
                <li v-for="item in row.risks" :key="item">{{ item }}</li>
                <li v-if="row.risks.length === 0">暂无显著风险</li>
              </ul>
            </div>
            <div>
              <p class="sm-label">成本估算</p>
              <ul class="recruit__list">
                <li>身价 {{ formatMoney(row.cost_estimate.market_value) }}</li>
                <li>工资 {{ formatMoney(row.cost_estimate.wage) }}</li>
                <li>合同到期 {{ row.cost_estimate.contract_end ?? EMPTY }}</li>
                <li>来源：{{ row.cost_estimate.basis ? row.cost_estimate.basis : '数据源未标注' }}</li>
              </ul>
            </div>
            <div>
              <p class="sm-label">位置模板</p>
              <ul class="recruit__list">
                <li>属性评分 {{ formatDecimal(row.position_template.attribute_score, 1) }}</li>
                <li>属性覆盖 {{ row.position_template.coverage === null ? EMPTY : formatPercent(row.position_template.coverage, 0) }}</li>
              </ul>
            </div>
          </div>
        </template>

        <template #cell="{ row, column, value }">
          <ScoreBadge v-if="column.prop === 'score'" :score="row.score" size="sm" />
          <el-tag
            v-else-if="column.prop === 'grade'"
            size="small"
            :type="gradeTagType(row.grade)"
            disable-transitions
          >
            {{ row.grade ?? 'insufficient' }} · {{ row.grade_label ?? '数据不足' }}
          </el-tag>
          <template v-else-if="column.prop === 'actions'">
            <el-button link size="small" @click.stop="openCandidate(row)">详情</el-button>
            <el-button link size="small" type="primary" @click.stop="followCandidate(row)">关注</el-button>
          </template>
          <template v-else>{{ value }}</template>
        </template>
      </DataTable>
    </SectionCard>

    <SectionCard
      v-if="radarOption"
      title="雷达对比"
      :subtitle="`${selectedPlayers.length} 名球员按同一套六维权重对比；缺失维度记 0，需要看展开行的缺口说明`"
    >
      <div class="recruit__radar">
        <EChart :option="radarOption" height="320px" />
      </div>
      <div class="sm-row sm-row--wrap recruit__chips">
        <span class="sm-label">对比中</span>
        <el-tag
          v-for="item in selectedPlayers"
          :key="item.player.instance_id"
          closable
          size="small"
          @close="toggleCompare(item.player.instance_id)"
        >
          {{ item.player.name }} · {{ formatDecimal(item.score, 1) }}
        </el-tag>
        <el-button size="small" text @click="selected = []">清空</el-button>
      </div>
    </SectionCard>

    <SectionCard title="隐藏价值发现" subtitle="低成本高价值候选；数据源缺少的规则会被明确标出">
      <template #actions>
        <el-button size="small" :loading="hiddenLoading" @click="loadHidden">重新扫描</el-button>
      </template>
      <ErrorState v-if="hiddenError" :error="hiddenError" title="隐藏价值扫描失败" @retry="loadHidden" />
      <template v-else-if="hidden">
        <div class="recruit__rules">
          <span class="sm-label">已评估规则</span>
          <el-tag v-for="rule in hidden.rules.evaluated" :key="rule.key" size="small" type="success">
            {{ rule.label }}
          </el-tag>
          <span class="sm-label">无法评估</span>
          <el-tooltip
            v-for="rule in hidden.rules.unavailable"
            :key="rule.key"
            :content="`缺少字段：${rule.missing_fields.join('、')}。${rule.description}`"
            placement="top"
          >
            <el-tag size="small" type="info">{{ rule.label }}</el-tag>
          </el-tooltip>
        </div>
        <DataTable
          :columns="hiddenColumns"
          :rows="hidden.items"
          :row-key="(row) => `${row.rule}-${row.player.instance_id}`"
          dense
          empty-title="没有命中隐藏价值规则"
          empty-description="当前存档没有满足条件的球员"
        />
      </template>
      <EmptyState v-else title="尚未扫描" description="点击重新扫描以运行隐藏价值规则" />
    </SectionCard>

    <SectionCard title="候选名单" subtitle="生成后可保存，供后续复盘与报价参考">
      <template #actions>
        <el-input v-model="shortlistName" size="small" placeholder="名单名称（可选）" class="recruit__name" />
        <el-button size="small" type="primary" :loading="generating" @click="generate">生成名单</el-button>
      </template>
      <div class="recruit__shortlists">
        <el-button
          v-for="item in shortlists"
          :key="item.id"
          size="small"
          :loading="shortlistsLoading"
          @click="openShortlist(item.id)"
        >
          {{ item.name }} · {{ item.candidates }} 人
        </el-button>
        <span v-if="shortlists.length === 0" class="sm-text-2xs sm-text-faint">还没有保存过的候选名单</span>
      </div>

      <div v-if="openedShortlist" class="recruit__shortlist">
        <header class="sm-row sm-row--between">
          <h3 class="recruit__shortlist-title">{{ openedShortlist.name ?? '候选名单' }}</h3>
          <span class="sm-text-2xs sm-text-faint">
            位置 {{ openedShortlist.slot ?? '不限' }} · 预算 {{ formatMoney(openedShortlist.budget) }}
          </span>
        </header>
        <ol class="recruit__shortlist-items">
          <li v-for="item in openedShortlist.items" :key="item.rank">
            <div class="sm-row sm-row--between">
              <strong>{{ item.rank }}. {{ item.player.name }}</strong>
              <span class="sm-num">{{ formatDecimal(item.score, 1) }}</span>
            </div>
            <p class="sm-text-xs sm-text-2">{{ item.reason }}</p>
            <p class="sm-text-2xs sm-text-faint">
              身价 {{ formatMoney(item.cost_estimate.market_value) }} · 风险
              {{ item.risks.length > 0 ? item.risks.join('；') : '无明显风险' }}
            </p>
          </li>
        </ol>
      </div>
    </SectionCard>
  </div>
</template>

<style scoped>
/* ---------- 球探控制台 ---------- */

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
}

.console__grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(168px, 1fr));
  gap: var(--sm-space-3);
  align-items: end;
}

.console__field {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-1);
  min-width: 0;
}

.console__field :deep(.el-select),
.console__field :deep(.el-input-number) {
  width: 100%;
}

/* ---------- 优先机会 ---------- */

.opps {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-3);
}

.opps__head {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.opps__title {
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-md);
  font-weight: var(--sm-fw-semibold);
}

.opps__hint {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-xs);
  line-height: 1.55;
}

.opps__grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: var(--sm-space-3);
}

.opp-card {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-2);
  min-width: 0;
  padding: var(--sm-space-3) var(--sm-space-4);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-lg);
  background:
    linear-gradient(170deg, rgba(20, 35, 56, 0.5), rgba(9, 18, 32, 0.92)),
    var(--sm-surface);
  box-shadow: var(--sm-shadow-1);
}

.opp-card__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--sm-space-2);
}

.opp-card__titles {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.opp-card__name {
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-md);
  font-weight: var(--sm-fw-semibold);
}

.opp-card__rank {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
  font-weight: var(--sm-fw-medium);
}

.opp-card__meta {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
  line-height: 1.5;
}

.opp-card__tags {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--sm-space-2);
}

.opp-card__coverage {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}

.opp-card__facts {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-1);
  margin: 0;
}

.opp-card__facts div {
  display: grid;
  grid-template-columns: 40px minmax(0, 1fr);
  gap: var(--sm-space-2);
}

.opp-card__facts dt {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}

.opp-card__facts dd {
  margin: 0;
  color: var(--sm-text-2);
  font-size: var(--sm-fs-xs);
  line-height: 1.55;
  overflow-wrap: anywhere;
}

.opp-card__actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--sm-space-1);
  padding-top: var(--sm-space-1);
  border-top: 1px solid var(--sm-border);
}

.recruit__radar {
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-md);
  background:
    radial-gradient(520px 220px at 50% 0%, rgba(34, 211, 238, 0.06), transparent 70%),
    rgba(8, 17, 30, 0.5);
}

.recruit__gaps {
  margin-top: var(--sm-space-1);
}

.recruit__list {
  margin: 0;
  padding-left: var(--sm-space-4);
  font-size: var(--sm-fs-xs);
  line-height: 1.65;
  color: var(--sm-text-2);
}

.recruit__detail {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: var(--sm-space-3);
}

.recruit__chips {
  margin-top: var(--sm-space-3);
  padding-top: var(--sm-space-3);
  border-top: 1px solid var(--sm-border);
}

.recruit__rules {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--sm-space-2);
  margin-bottom: var(--sm-space-3);
  padding: var(--sm-space-3);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-md);
  background: rgba(12, 23, 39, 0.55);
}

.recruit__name {
  width: 180px;
}

.recruit__shortlists {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--sm-space-2);
}

.recruit__shortlist {
  margin-top: var(--sm-space-4);
  padding-top: var(--sm-space-3);
  border-top: 1px solid var(--sm-border);
}

.recruit__shortlist-title {
  font-size: var(--sm-fs-md);
  font-weight: var(--sm-fw-semibold);
  color: var(--sm-text);
}

.recruit__shortlist-items {
  margin: var(--sm-space-2) 0 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-2);
}

.recruit__shortlist-items li {
  padding: var(--sm-space-2) var(--sm-space-3);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-md);
  background: var(--sm-surface-2);
}

@media (max-width: 640px) {
  .console {
    padding: var(--sm-space-3);
  }
}
</style>
