/**
 * 智能球探引擎：位置模板 + 六维球员评分、候选排序、雷达对比、隐藏价值发现与候选名单。
 */

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { asApiError, type ApiError } from '../api/client'
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
import LoadingBlock from '../components/LoadingBlock.vue'
import PageHeader from '../components/PageHeader.vue'
import SectionCard from '../components/SectionCard.vue'
import { useSessionStore } from '../stores/session'
import type {
  HiddenValueHit,
  HiddenValueResponse,
  PlayerScore,
  Shortlist,
  ShortlistSummary,
} from '../types/recruitment'
import type { TableColumn } from '../types/table'
import { buildRadarChart, type RadarSeries } from '../utils/chart'
import { EMPTY, displayText, formatDecimal, formatInt, formatMoney, formatPercent } from '../utils/format'
import { positionLabel } from '../utils/labels'

const session = useSessionStore()

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
  limit: number
}>({ slot: 'ST', minAge: undefined, maxAge: undefined, budgetWan: undefined, limit: 20 })

const shortlistName = ref('')

const candidates = ref<PlayerScore[]>([])
const total = ref(0)
const dataGaps = ref<string[]>([])
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
  { prop: 'club', label: '俱乐部', width: 150, formatter: (row) => displayText(row.player.club) },
  { prop: 'score', label: '综合评分', width: 96, align: 'right', formatter: (row) => formatDecimal(row.score, 1) },
  { prop: 'ability', label: 'A 能力', width: 84, align: 'right', formatter: (row) => formatDecimal(dimension(row, 'ability'), 0) },
  { prop: 'potential', label: 'P 潜力', width: 84, align: 'right', formatter: (row) => formatDecimal(dimension(row, 'potential'), 0) },
  { prop: 'fit', label: 'T 适配', width: 84, align: 'right', formatter: (row) => formatDecimal(dimension(row, 'fit'), 0) },
  { prop: 'form', label: 'F 表现', width: 84, align: 'right', formatter: (row) => formatDecimal(dimension(row, 'form'), 0) },
  { prop: 'value', label: 'V 价值', width: 84, align: 'right', formatter: (row) => formatDecimal(dimension(row, 'value'), 0) },
  { prop: 'room', label: 'R 空间', width: 84, align: 'right', formatter: (row) => formatDecimal(dimension(row, 'room'), 0) },
  { prop: 'market_value', label: '身价', width: 110, align: 'right', formatter: (row) => formatMoney(row.player.market_value) },
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
      limit: form.limit,
    })
    candidates.value = result.items ?? []
    total.value = result.total ?? 0
    dataGaps.value = result.data_gaps ?? []
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

onMounted(() => {
  void search()
  void loadHidden()
  void loadShortlists()
})
</script>

<template>
  <div class="sm-page">
    <PageHeader
      title="Recruitment Engine · 智能球探引擎"
      description="不是寻找能力最高的球员，而是寻找最合适当前阵容、预算与发展计划的球员：六维评分、位置模板、隐藏价值与可执行候选名单。"
    />

    <SectionCard title="筛选条件" subtitle="位置、年龄与预算来自请求本身，不做隐式猜测">
      <template #actions>
        <el-button size="small" type="primary" :loading="loading" @click="search">开始搜索</el-button>
      </template>
      <div class="recruit__filters">
        <el-select v-model="form.slot" size="small" class="recruit__field" aria-label="位置">
          <el-option v-for="item in SLOT_OPTIONS" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
        <el-input-number v-model="form.minAge" :min="14" :max="45" size="small" placeholder="最小年龄" controls-position="right" />
        <el-input-number v-model="form.maxAge" :min="14" :max="45" size="small" placeholder="最大年龄" controls-position="right" />
        <el-input-number
          v-model="form.budgetWan"
          :min="0"
          :step="500"
          size="small"
          placeholder="预算（万）"
          controls-position="right"
        />
        <span class="sm-text-2xs sm-text-faint">预算单位：万 €</span>
      </div>
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
    </SectionCard>

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
      </DataTable>
    </SectionCard>

    <SectionCard
      v-if="radarOption"
      title="雷达对比"
      :subtitle="`${selectedPlayers.length} 名球员按同一套六维权重对比；缺失维度记 0，需要看展开行的缺口说明`"
    >
      <EChart :option="radarOption" height="320px" />
      <div class="sm-row sm-row--wrap recruit__chips">
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
.recruit__filters {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--sm-space-2);
}

.recruit__field {
  width: 140px;
}

.recruit__gaps {
  margin-top: var(--sm-space-3);
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
  margin-top: var(--sm-space-2);
}

.recruit__rules {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--sm-space-2);
  margin-bottom: var(--sm-space-3);
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
</style>
