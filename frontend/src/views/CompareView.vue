/**
 * 球员对比：2–4 名球员的基本资料、能力属性、身价合同与确定性摘要。
 *
 * 数据只来自 `GET /players/{id}`；不新增评分模型，不把属性均值当作 CA/PA。
 */

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { asApiError, type ApiError } from '../api/client'
import { getPlayer } from '../api/players'
import { searchAll } from '../api/search'
import ChartCard from '../components/ChartCard.vue'
import EChart from '../components/EChart.vue'
import EmptyState from '../components/EmptyState.vue'
import ErrorState from '../components/ErrorState.vue'
import InsightPanel from '../components/InsightPanel.vue'
import LoadingBlock from '../components/LoadingBlock.vue'
import PageHeader from '../components/PageHeader.vue'
import SectionCard from '../components/SectionCard.vue'
import StatStrip from '../components/StatStrip.vue'
import { MAX_COMPARE, useCompareStore } from '../stores/compare'
import { useSessionStore } from '../stores/session'
import type { PlayerDetail } from '../types/players'
import type { SearchResultItem } from '../types/search'
import type { InsightItem, InsightTone, StatItem } from '../types/ui'
import { buildRadarChart, type RadarSeries } from '../utils/chart'
import {
  EMPTY,
  displayText,
  formatDate,
  formatInt,
  formatMoney,
  formatPercent,
  formatSignedInt,
  formatSignedMoney,
} from '../utils/format'
import { attributeCategoryLabel, positionLabel } from '../utils/labels'

const route = useRoute()
const router = useRouter()
const session = useSessionStore()
const compare = useCompareStore()

const selectorQuery = ref('')
const selectorLoading = ref(false)
const selectorError = ref<ApiError | null>(null)
const selectorResults = ref<SearchResultItem[]>([])
const replaceTarget = ref<number | null>(null)

const details = ref<Record<number, PlayerDetail>>({})
const loading = ref(false)
const errors = ref<Record<number, ApiError>>({})

let selectorTimer: ReturnType<typeof setTimeout> | null = null
let detailSeq = 0

/** 已选球员详情，保持选择顺序。 */
const selected = computed(() =>
  compare.ids.map((id) => details.value[id]).filter((detail): detail is PlayerDetail => Boolean(detail)),
)

/** 已加载但失败的数量。 */
const failedCount = computed(() => Object.keys(errors.value).length)

/**
 * 属性类别均值：只保留所有已选球员都有数据的类别；缺失类别不绘制，避免伪造。
 * 均值为 1–20 刻度，仅用于横向对比，不是 CA/PA。
 */
function categoryAverages(detail: PlayerDetail): Record<string, number | null> {
  const buckets = new Map<string, number[]>()
  for (const attribute of detail.attributes) {
    if (attribute.value === null) continue
    const key = attribute.category || 'other'
    const values = buckets.get(key) ?? []
    values.push(attribute.value)
    buckets.set(key, values)
  }
  const result: Record<string, number | null> = {}
  for (const [key, values] of buckets) {
    result[key] = values.length > 0 ? Number((values.reduce((sum, value) => sum + value, 0) / values.length).toFixed(1)) : null
  }
  return result
}

const radar = computed(() => {
  const items = selected.value
  if (items.length < 2) return null
  const averages = items.map((detail) => categoryAverages(detail))
  const keys = new Set<string>()
  for (const entry of averages) {
    for (const key of Object.keys(entry)) keys.add(key)
  }
  const dimensions = Array.from(keys).filter((key) => averages.every((entry) => typeof entry[key] === 'number'))
  if (dimensions.length < 3) return null
  const series: RadarSeries[] = items.map((detail, index) => ({
    name: detail.summary.name,
    values: dimensions.map((key) => averages[index][key] ?? null),
  }))
  return {
    dimensions: dimensions.map((key) => attributeCategoryLabel(key)),
    series,
    option: buildRadarChart(
      dimensions.map((key) => attributeCategoryLabel(key)),
      series,
      20,
    ),
  }
})

/** 数值行的比较口径：`max` 表示越大越领先，`min` 表示越小越领先。 */
interface RowMetric {
  pick: (detail: PlayerDetail) => number | null
  better: 'max' | 'min'
  /** 与领先值的差值文案；省略时只高亮、不显示差值。 */
  formatDelta?: (delta: number) => string
}

/** 对比表的行定义。 */
interface CompareRow {
  label: string
  hint?: string
  value: (detail: PlayerDetail) => string
  /** 只有可比较的数值行才参与领先值计算。 */
  metric?: RowMetric
}

/** 合同日期转为时间戳；无法解析时视为缺失。 */
function contractTimestamp(detail: PlayerDetail): number | null {
  if (!detail.summary.contract_end) return null
  const timestamp = Date.parse(detail.summary.contract_end)
  return Number.isFinite(timestamp) ? timestamp : null
}

const rows: CompareRow[] = [
  {
    label: '年龄',
    value: (d) => (d.summary.age === null ? EMPTY : `${d.summary.age} 岁`),
    metric: { pick: (d) => d.summary.age, better: 'min', formatDelta: (delta) => `${formatSignedInt(delta)} 岁` },
  },
  { label: '国籍', value: (d) => displayText(d.summary.nationality) },
  { label: '位置', value: (d) => positionLabel(d.summary.position) },
  { label: '俱乐部', value: (d) => displayText(d.summary.club) },
  {
    label: '身高',
    value: (d) => (d.summary.height_cm === null || d.summary.height_cm === undefined ? EMPTY : `${d.summary.height_cm} cm`),
    metric: { pick: (d) => d.summary.height_cm ?? null, better: 'max', formatDelta: (delta) => `${formatSignedInt(delta)} cm` },
  },
  { label: '惯用脚', value: (d) => footLabel(d.summary.foot) },
  {
    label: '当前能力（CA）',
    value: (d) => formatInt(d.summary.ca),
    metric: { pick: (d) => d.summary.ca, better: 'max', formatDelta: (delta) => formatSignedInt(delta) },
  },
  {
    label: '潜力（PA）',
    value: (d) => formatInt(d.summary.pa),
    metric: { pick: (d) => d.summary.pa, better: 'max', formatDelta: (delta) => formatSignedInt(delta) },
  },
  {
    label: '身价',
    value: (d) => formatMoney(d.summary.market_value),
    metric: { pick: (d) => d.summary.market_value, better: 'max', formatDelta: (delta) => formatSignedMoney(delta) },
  },
  {
    label: '周薪',
    value: (d) => formatMoney(d.summary.wage),
    metric: { pick: (d) => d.summary.wage, better: 'min', formatDelta: (delta) => formatSignedMoney(delta) },
  },
  {
    label: '合同到期',
    value: (d) => formatDate(d.summary.contract_end),
    metric: { pick: contractTimestamp, better: 'min' },
  },
  {
    label: '数据完整度',
    value: (d) => formatPercent(d.summary.data_completeness),
    metric: {
      pick: (d) => d.summary.data_completeness,
      better: 'max',
      formatDelta: (delta) => `${formatSignedInt(Math.round(delta * 100))} 个百分点`,
    },
  },
]

/** 惯用脚中文；未知保持「暂无数据」。 */
function footLabel(foot: string | null | undefined): string {
  if (!foot) return EMPTY
  const map: Record<string, string> = { left: '左脚', right: '右脚', both: '双脚' }
  return map[foot.toLowerCase()] ?? foot
}

/** 一条可直接验证的差异事实：摘要页与顶部结论共用同一份推导结果。 */
interface CompareFact {
  label: string
  summary: string
  insight: string
}

/**
 * 确定性事实：只陈述可验证字段，不做综合评分。
 * `summary` 用于「确定性摘要」列表，`insight` 用于顶部「差异结论」。
 */
const facts = computed<CompareFact[]>(() => {
  const items = selected.value
  if (items.length < 2) return []
  const collected: CompareFact[] = []
  const bestBy = (label: string, pick: (d: PlayerDetail) => number | null, format: (value: number) => string): void => {
    const entries = items
      .map((detail) => ({ name: detail.summary.name, value: pick(detail) }))
      .filter((entry): entry is { name: string; value: number } => entry.value !== null)
    if (entries.length < 2) return
    const max = Math.max(...entries.map((entry) => entry.value))
    const winners = entries.filter((entry) => entry.value === max).map((entry) => entry.name)
    collected.push({
      label,
      summary: `${winners.join('、')} 的${label}最高（${format(max)}）`,
      insight: `${winners.join('、')} 最高（${format(max)}）`,
    })
  }
  bestBy('当前能力', (d) => d.summary.ca, (value) => String(value))
  bestBy('潜力', (d) => d.summary.pa, (value) => String(value))
  bestBy('身价', (d) => d.summary.market_value, (value) => formatMoney(value))

  const ages = items
    .map((detail) => ({ name: detail.summary.name, value: detail.summary.age }))
    .filter((entry): entry is { name: string; value: number } => entry.value !== null)
  if (ages.length >= 2) {
    const min = Math.min(...ages.map((entry) => entry.value))
    const winners = ages.filter((entry) => entry.value === min).map((entry) => entry.name)
    collected.push({
      label: '年龄',
      summary: `${winners.join('、')} 年龄最小（${min} 岁）`,
      insight: `${winners.join('、')} 最小（${min} 岁）`,
    })
  }

  const contracts = items
    .map((detail) => ({ name: detail.summary.name, value: detail.summary.contract_end }))
    .filter((entry): entry is { name: string; value: string } => Boolean(entry.value))
  if (contracts.length >= 2) {
    const earliest = contracts.map((entry) => entry.value).sort()[0]
    const winners = contracts.filter((entry) => entry.value === earliest).map((entry) => entry.name)
    collected.push({
      label: '合同到期',
      summary: `${winners.join('、')} 合同最早到期（${formatDate(earliest)}）`,
      insight: `${winners.join('、')} 最早到期（${formatDate(earliest)}）`,
    })
  }
  return collected
})

/** 「确定性摘要」列表只读取事实文本。 */
const summary = computed(() => facts.value.map((fact) => fact.summary))

/** 至少一名已选球员缺失的可比较字段；用于结论中的缺失项说明。 */
const missingFields = computed<string[]>(() => {
  const items = selected.value
  if (items.length === 0) return []
  const checks: Array<{ label: string; present: (detail: PlayerDetail) => boolean }> = [
    { label: '年龄', present: (d) => d.summary.age !== null },
    { label: '身高', present: (d) => d.summary.height_cm !== null && d.summary.height_cm !== undefined },
    { label: 'CA', present: (d) => d.summary.ca !== null },
    { label: 'PA', present: (d) => d.summary.pa !== null },
    { label: '身价', present: (d) => d.summary.market_value !== null },
    { label: '周薪', present: (d) => d.summary.wage !== null },
    { label: '合同到期', present: (d) => Boolean(d.summary.contract_end) },
    { label: '数据完整度', present: (d) => d.summary.data_completeness !== null },
  ]
  return checks.filter((check) => items.some((detail) => !check.present(detail))).map((check) => check.label)
})

/** 顶部「差异结论」：由事实与缺失项组成，无足够数据时明确写「数据不足」。 */
const differenceInsight = computed<{ tone: InsightTone; items: InsightItem[] }>(() => {
  const chosen = selected.value
  if (compare.ids.length < 2) {
    return {
      tone: 'neutral',
      items: [{ label: '数据不足', text: '选择至少 2 名球员后，才能按现有字段比较差异。' }],
    }
  }
  if (chosen.length < 2) {
    return {
      tone: 'neutral',
      items: [
        {
          label: '数据不足',
          text: loading.value ? '正在加载所选球员资料，稍后给出差异结论。' : '所选球员资料不可用，无法给出差异结论。',
        },
      ],
    }
  }
  if (facts.value.length === 0) {
    return {
      tone: 'warning',
      items: [{ label: '数据不足', text: '所选球员缺少 CA、PA、年龄、身价或合同数据，无法给出差异结论。', tone: 'warning' }],
    }
  }
  const missing = missingFields.value
  const insightItems: InsightItem[] = facts.value.map((fact) => ({ label: fact.label, text: fact.insight }))
  insightItems.push({
    label: '缺失项',
    text:
      missing.length > 0
        ? `部分球员缺少${missing.join('、')}，未参与对应项的领先比较。`
        : '关键字段齐全，所有可比较数值都已参与比较。',
    tone: missing.length > 0 ? 'warning' : 'success',
  })
  return { tone: 'info', items: insightItems }
})

/** 有身价数据的已选球员数量；无选择时为 null，避免把未知显示成 0。 */
const valueCoverage = computed<number | null>(() => {
  const items = selected.value
  if (items.length === 0) return null
  return items.filter((detail) => detail.summary.market_value !== null).length
})

/** 已选球员数据完整度均值；全部缺失时为 null。 */
const averageCompleteness = computed<number | null>(() => {
  const values = selected.value
    .map((detail) => detail.summary.data_completeness)
    .filter((value): value is number => value !== null)
  if (values.length === 0) return null
  return values.reduce((sum, value) => sum + value, 0) / values.length
})

/** 页面顶部关键指标：数量、可比性与数据覆盖，全部来自已加载详情。 */
const metrics = computed<StatItem[]>(() => {
  const selectedCount = selected.value.length
  const covered = valueCoverage.value
  const completeness = averageCompleteness.value
  return [
    {
      label: '已选人数',
      value: `${compare.count} / ${MAX_COMPARE}`,
      hint: compare.count >= 2 ? '可生成差异结论' : '至少 2 名才能对比',
      tone: 'accent',
    },
    {
      label: '可比人数',
      value: formatInt(selectedCount),
      hint: failedCount.value > 0 ? `${formatInt(failedCount.value)} 名资料加载失败` : '资料已加载',
      tone: failedCount.value > 0 ? 'warning' : 'default',
    },
    {
      label: '身价覆盖',
      value: covered === null ? '—' : `${formatInt(covered)} / ${formatInt(selectedCount)}`,
      hint: covered === null ? '还没有选择球员' : '有身价数据的球员',
      tone: covered === null ? 'default' : covered === selectedCount ? 'success' : 'warning',
    },
    {
      label: '数据完整度均值',
      value: completeness === null ? '—' : formatPercent(completeness),
      hint: completeness === null ? '接口未返回完整度' : '所选球员均值',
    },
  ]
})

/** 对比表单元格：文本 + 领先标记 + 与领先值的差值。 */
interface CompareCell {
  id: number
  text: string
  lead: boolean
  delta: string
}

interface CompareTableRow {
  label: string
  cells: CompareCell[]
}

/** 预先计算领先值与差值；缺失值不参与比较，少于 2 个已知值时不标记。 */
const tableRows = computed<CompareTableRow[]>(() => {
  const items = selected.value
  return rows.map((row) => {
    const picks = items.map((detail) => (row.metric ? row.metric.pick(detail) : null))
    const known = picks.filter((value): value is number => value !== null)
    let best: number | null = null
    if (row.metric && known.length >= 2) {
      best = row.metric.better === 'min' ? Math.min(...known) : Math.max(...known)
    }
    const cells: CompareCell[] = items.map((detail, index) => {
      const pick = picks[index]
      const lead = best !== null && pick !== null && pick === best
      const delta =
        best !== null && pick !== null && !lead && row.metric?.formatDelta
          ? row.metric.formatDelta(pick - best)
          : ''
      return { id: detail.summary.instance_id, text: row.value(detail), lead, delta }
    })
    return { label: row.label, cells }
  })
})

/** 拉取已选球员详情；同一实例不重复请求。 */
async function loadDetails(): Promise<void> {
  compare.ensureSave(session.activeSaveId)
  const seq = ++detailSeq
  const missing = compare.ids.filter((id) => !details.value[id])
  if (missing.length === 0) {
    loading.value = false
    return
  }
  loading.value = true
  const outcome = await Promise.allSettled(missing.map((id) => getPlayer(id)))
  if (seq !== detailSeq) return
  outcome.forEach((result, index) => {
    const id = missing[index]
    if (result.status === 'fulfilled') {
      details.value = { ...details.value, [id]: result.value }
      const nextErrors = { ...errors.value }
      delete nextErrors[id]
      errors.value = nextErrors
    } else {
      const error = asApiError(result.reason)
      errors.value = { ...errors.value, [id]: error }
      // 404 表示该实例不属于当前存档：自动移出选择，避免跨存档混淆。
      if (error.isNotFound) compare.remove(id)
    }
  })
  loading.value = false
}

/** 选择器搜索（只搜球员）。 */
async function runSelectorSearch(): Promise<void> {
  const term = selectorQuery.value.trim()
  if (!term) {
    selectorResults.value = []
    selectorError.value = null
    return
  }
  selectorLoading.value = true
  selectorError.value = null
  try {
    const response = await searchAll(term, 'players', { saveId: session.activeSaveId, limit: 6 })
    selectorResults.value = response.categories.players
  } catch (caught) {
    selectorResults.value = []
    selectorError.value = asApiError(caught)
  } finally {
    selectorLoading.value = false
  }
}

function onSelectorInput(): void {
  if (selectorTimer) clearTimeout(selectorTimer)
  selectorTimer = setTimeout(() => {
    void runSelectorSearch()
  }, 260)
}

/** 添加或替换球员。 */
function choose(item: SearchResultItem): void {
  compare.ensureSave(session.activeSaveId)
  if (replaceTarget.value !== null) {
    if (compare.ids.includes(item.entity_id)) {
      ElMessage.info('该球员已在对比中')
      return
    }
    compare.replace(replaceTarget.value, item.entity_id)
    ElMessage.success(`已替换为 ${item.display_name}`)
    replaceTarget.value = null
  } else {
    const outcome = compare.add(item.entity_id)
    if (outcome === 'added') ElMessage.success(`已加入：${item.display_name}`)
    else if (outcome === 'exists') ElMessage.info('该球员已在对比中')
    else ElMessage.warning(`对比最多 ${MAX_COMPARE} 名球员`)
  }
  selectorQuery.value = ''
  selectorResults.value = []
}

/** 从球员中心返回时恢复状态。 */
function resetSelection(): void {
  compare.clear()
  details.value = {}
  errors.value = {}
  replaceTarget.value = null
}

/**
 * 用 URL 中的 ids 初始化选择；非整数或超限的 ID 直接忽略。
 */
function applyQueryIds(): void {
  const raw = route.query.ids
  const text = Array.isArray(raw) ? raw.join(',') : (raw ?? '')
  if (!text) return
  const ids = text
    .split(',')
    .map((value) => Number.parseInt(value, 10))
    .filter((value) => Number.isInteger(value) && value > 0)
    .slice(0, MAX_COMPARE)
  if (ids.length === 0) return
  compare.clear()
  for (const id of ids) compare.add(id)
}

watch(
  () => compare.ids,
  (ids) => {
    const next = ids.length > 0 ? ids.join(',') : undefined
    if ((route.query.ids ?? '') === (next ?? '')) {
      void loadDetails()
      return
    }
    void router.replace({ query: { ...route.query, ids: next } })
    void loadDetails()
  },
  { deep: true, immediate: true },
)

watch(
  () => session.activeSaveId,
  () => {
    compare.ensureSave(session.activeSaveId)
    details.value = {}
    errors.value = {}
    replaceTarget.value = null
    void loadDetails()
  },
)

watch(selectorQuery, onSelectorInput)

onMounted(() => {
  compare.ensureSave(session.activeSaveId)
  applyQueryIds()
})

onBeforeUnmount(() => {
  if (selectorTimer) clearTimeout(selectorTimer)
})
</script>

<template>
  <div class="sm-page">
    <PageHeader
      title="球员对比"
      description="选择 2–4 名球员，快速了解他们的能力、潜力和价值差异。"
    >
      <template #actions>
        <el-button size="small" @click="resetSelection">清空选择</el-button>
        <router-link to="/players"><el-button size="small" type="primary">去球员中心</el-button></router-link>
      </template>
    </PageHeader>

    <InsightPanel
      title="差异结论"
      badge="规则生成"
      :tone="differenceInsight.tone"
      :items="differenceInsight.items"
      footnote="结论由已选球员的现有字段直接比较得出，不包含综合评分或 AI 推断；缺失字段不参与比较。"
    />

    <StatStrip :items="metrics" />

    <SectionCard title="选择球员" :subtitle="`已选 ${compare.count} / ${MAX_COMPARE} 名；至少 2 名才能对比`">
      <div class="selector">
        <div class="selector__search">
          <el-input
            v-model="selectorQuery"
            size="large"
            clearable
            placeholder="搜索球员姓名"
            aria-label="搜索要对比的球员"
          >
            <template #prefix><span aria-hidden="true">⌕</span></template>
          </el-input>
          <p v-if="replaceTarget !== null" class="selector__hint">
            正在为第 {{ compare.ids.indexOf(replaceTarget) + 1 }} 名球员选择替换对象。
            <el-button size="small" text @click="replaceTarget = null">取消替换</el-button>
          </p>
        </div>

        <div class="chips">
          <span v-for="(id, index) in compare.ids" :key="id" class="chip">
            <span class="chip__index">{{ index + 1 }}</span>
            <span class="chip__name">{{ details[id]?.summary.name ?? `#${id}` }}</span>
            <button type="button" class="chip__action" @click="replaceTarget = id">替换</button>
            <button type="button" class="chip__remove" aria-label="移除" @click="compare.remove(id)">×</button>
          </span>
          <span v-if="compare.ids.length === 0" class="chips__empty">还没有选择球员</span>
        </div>

        <LoadingBlock v-if="selectorLoading" :rows="2" compact label="正在搜索球员" />
        <p v-else-if="selectorError" class="selector__error">搜索失败：{{ selectorError.message }}</p>
        <ul v-else-if="selectorResults.length > 0" class="candidates">
          <li v-for="item in selectorResults" :key="item.entity_id" class="candidate">
            <span class="candidate__main">
              <strong>{{ item.display_name }}</strong>
              <span>{{ item.subtitle }}</span>
            </span>
            <el-button size="small" @click="choose(item)">
              {{ replaceTarget !== null ? '替换' : '加入' }}
            </el-button>
          </li>
        </ul>
        <p v-else-if="selectorQuery.trim()" class="selector__error">没有找到匹配的球员。</p>
      </div>
    </SectionCard>

    <ErrorState
      v-if="failedCount > 0"
      :error="Object.values(errors)[0]"
      compact
      :title="`${failedCount} 名球员资料加载失败`"
      @retry="loadDetails"
    />

    <LoadingBlock v-if="loading && selected.length === 0" :rows="6" label="正在加载球员资料" />

    <EmptyState
      v-else-if="compare.ids.length < 2"
      title="至少选择 2 名球员"
      description="在球员中心、搜索结果或本页选择器中添加球员；最多 4 名，重复添加会被忽略。"
    >
      <router-link to="/players"><el-button size="small" type="primary">去球员中心选择</el-button></router-link>
    </EmptyState>

    <template v-else-if="selected.length >= 2">
      <SectionCard title="资料与能力对比" subtitle="缺失字段显示为「—」，不按 0 处理；高亮为该行的领先值">
        <div class="compare-table" role="table" aria-label="球员资料对比">
          <div class="compare-row compare-row--head" role="row">
            <span class="compare-cell compare-cell--label" role="columnheader">项目</span>
            <span v-for="detail in selected" :key="detail.summary.instance_id" class="compare-cell" role="columnheader">
              <router-link class="compare-name" :to="`/players/${detail.summary.instance_id}`">
                {{ detail.summary.name }}
              </router-link>
              <span class="compare-club">{{ displayText(detail.summary.club) }}</span>
            </span>
          </div>
          <div v-for="row in tableRows" :key="row.label" class="compare-row" role="row">
            <span class="compare-cell compare-cell--label" role="cell">{{ row.label }}</span>
            <span
              v-for="cell in row.cells"
              :key="cell.id"
              class="compare-cell compare-cell--value"
              :class="{ 'compare-cell--lead': cell.lead }"
              role="cell"
            >
              <span class="compare-cell__value">{{ cell.text }}</span>
              <span v-if="cell.lead" class="compare-cell__lead">领先</span>
              <span v-else-if="cell.delta" class="compare-cell__delta">{{ cell.delta }}</span>
            </span>
          </div>
        </div>
      </SectionCard>

      <ChartCard
        title="能力属性雷达"
        subtitle="技术 / 精神 / 身体等类别的属性均值（1–20）；雷达用于结构参考，差异以表格为准"
        :empty="radar === null"
        empty-title="暂无可共同对比的属性"
        empty-description="只有所有已选球员都具备数据的属性类别才会绘制；缺失类别不会被补成 0。"
        footnote="维度为该类属性的算术平均，仅用于横向查看，不代表 CA/PA，也不是综合评分。"
      >
        <EChart v-if="radar" :option="radar.option" height="320px" aria-label="多名球员的属性类别雷达对比" />
      </ChartCard>

      <SectionCard title="确定性摘要" subtitle="只陈述数据中可直接验证的事实">
        <EmptyState
          v-if="summary.length === 0"
          title="暂无可比较的结论"
          description="所选球员缺少 CA、PA、年龄、身价或合同数据，无法给出确定结论。"
          compact
        />
        <ul v-else class="facts">
          <li v-for="fact in summary" :key="fact" class="fact">{{ fact }}</li>
        </ul>
        <template #footer>
          以上结论由现有字段直接比较得出，不包含综合评分或 AI 推断。
        </template>
      </SectionCard>

      <SectionCard title="继续操作" dense>
        <div class="actions">
          <router-link to="/players"><el-button size="small">返回球员中心</el-button></router-link>
          <router-link to="/compare"><el-button size="small" text>重新选择</el-button></router-link>
          <el-button v-for="detail in selected" :key="detail.summary.instance_id" size="small" text @click="router.push(`/players/${detail.summary.instance_id}`)">
            {{ detail.summary.name }} 详情 →
          </el-button>
        </div>
      </SectionCard>
    </template>
  </div>
</template>

<style scoped>
.selector {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-3);
}

.selector__search {
  max-width: 460px;
}

.selector__hint {
  margin-top: var(--sm-space-1);
  color: var(--sm-text-2);
  font-size: var(--sm-fs-xs);
}

.selector__error {
  color: var(--sm-danger);
  font-size: var(--sm-fs-xs);
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sm-space-2);
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 6px 4px 10px;
  border: 1px solid rgba(53, 106, 230, 0.24);
  border-radius: var(--sm-radius-pill);
  background: var(--sm-accent-weak);
  font-size: var(--sm-fs-xs);
}

.chip__index {
  display: grid;
  place-items: center;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: rgba(53, 106, 230, 0.16);
  color: var(--sm-accent-blue);
  font-size: 9px;
}

.chip__action,
.chip__remove {
  border: 0;
  background: transparent;
  color: var(--sm-text-2);
  font-size: var(--sm-fs-2xs);
  cursor: pointer;
}

.chip__remove {
  font-size: 14px;
  line-height: 1;
}

.chips__empty {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-xs);
}

.candidates {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-1);
  max-width: 520px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.candidate {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sm-space-3);
  padding: 6px 10px;
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-sm);
  background: var(--sm-surface-2);
}

.candidate__main {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
  font-size: var(--sm-fs-xs);
}

.candidate__main span {
  color: var(--sm-text-3);
}

.compare-table {
  display: flex;
  flex-direction: column;
  overflow-x: auto;
}

.compare-row {
  display: grid;
  grid-template-columns: 140px repeat(auto-fit, minmax(150px, 1fr));
  min-width: 420px;
  border-bottom: 1px solid var(--sm-border);
}

.compare-row:last-child {
  border-bottom: 0;
}

.compare-row--head {
  border-bottom-color: var(--sm-border-strong);
  background: var(--sm-surface-2);
}

.compare-cell {
  padding: 8px 12px;
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-sm);
}

.compare-cell--label {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-xs);
}

.compare-row--head .compare-cell {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.compare-name {
  font-weight: 600;
}

.compare-club {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}

.compare-cell--value {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 8px;
}

.compare-cell__value {
  white-space: nowrap;
}

.compare-cell--lead {
  background: rgba(22, 163, 106, 0.07);
  box-shadow: inset 2px 0 0 rgba(22, 163, 106, 0.45);
}

.compare-cell__lead {
  color: var(--sm-status-success);
  font-size: var(--sm-fs-2xs);
  font-weight: var(--sm-fw-semibold);
}

.compare-cell__delta {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.facts {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-2);
  margin: 0;
  padding-left: 18px;
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-sm);
}

.actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sm-space-2);
}

@media (max-width: 900px) {
  .compare-row {
    grid-template-columns: 110px repeat(auto-fit, minmax(120px, 1fr));
  }
}
</style>
