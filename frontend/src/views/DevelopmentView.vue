/**
 * 球员发展：成长曲线、成长速率、发展建议与潜力区间（区间与等级，不是精确 CA 预测）。
 */

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import type { EChartsOption } from 'echarts'
import { asApiError, type ApiError } from '../api/client'
import { getDevelopmentBoard, getGrowthProfile } from '../api/development'
import DataTable from '../components/DataTable.vue'
import EChart from '../components/EChart.vue'
import EmptyState from '../components/EmptyState.vue'
import ErrorState from '../components/ErrorState.vue'
import KpiCard from '../components/KpiCard.vue'
import LoadingBlock from '../components/LoadingBlock.vue'
import PageHeader from '../components/PageHeader.vue'
import SectionCard from '../components/SectionCard.vue'
import { useSessionStore } from '../stores/session'
import type { DevelopmentBoardRow, GrowthPoint, GrowthProfile } from '../types/development'
import type { TableColumn } from '../types/table'
import { CHART_COLORS } from '../utils/chart'
import { EMPTY, displayText, formatDecimal, formatInt, formatMoney } from '../utils/format'
import { positionLabel } from '../utils/labels'

const session = useSessionStore()

const board = ref<DevelopmentBoardRow[]>([])
const boardLoading = ref(false)
const boardError = ref<ApiError | null>(null)
const minAge = ref(23)

const profile = ref<GrowthProfile | null>(null)
const profileLoading = ref(false)
const profileError = ref<ApiError | null>(null)
const selectedId = ref<number | null>(null)

/** Growth chart: CA and PA over the observed snapshots. */
const growthOption = computed<EChartsOption | null>(() => {
  const points = profile.value?.points ?? []
  if (points.length === 0) return null
  const labels = points.map((point) => point.date)
  return {
    animationDuration: 240,
    grid: { left: 8, right: 16, top: 28, bottom: 24, containLabel: true },
    legend: {
      bottom: 0,
      icon: 'roundRect',
      itemWidth: 10,
      itemHeight: 10,
      textStyle: { color: '#a6b2c4', fontSize: 11 },
    },
    tooltip: { trigger: 'axis', confine: true },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: { color: '#7a8698', fontSize: 11 },
      axisLine: { lineStyle: { color: '#232d3c' } },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      name: 'CA / PA',
      nameTextStyle: { color: '#7a8698', fontSize: 11 },
      axisLabel: { color: '#7a8698', fontSize: 11 },
      splitLine: { lineStyle: { color: '#1d2632' } },
    },
    series: [
      {
        name: 'CA',
        type: 'line',
        symbolSize: 5,
        connectNulls: true,
        data: points.map((point) => point.ca),
        lineStyle: { width: 2, color: CHART_COLORS.ca },
        itemStyle: { color: CHART_COLORS.ca },
      },
      {
        name: 'PA',
        type: 'line',
        symbolSize: 4,
        connectNulls: true,
        data: points.map((point) => point.pa),
        lineStyle: { width: 2, color: CHART_COLORS.pa, type: 'dashed' },
        itemStyle: { color: CHART_COLORS.pa },
      },
    ],
  }
})

const boardColumns: TableColumn<DevelopmentBoardRow>[] = [
  { prop: 'name', label: '球员', minWidth: 150, formatter: (row) => row.player.name },
  { prop: 'age', label: '年龄', width: 64, align: 'right', formatter: (row) => displayText(row.player.age) },
  { prop: 'position', label: '位置', width: 92, formatter: (row) => positionLabel(row.player.position) },
  {
    prop: 'overall',
    label: '月均成长',
    width: 104,
    align: 'right',
    formatter: (row) => (row.overall_per_month === null ? EMPTY : formatDecimal(row.overall_per_month, 2)),
  },
  {
    prop: 'recent',
    label: '最近区间',
    width: 104,
    align: 'right',
    formatter: (row) => (row.recent_per_month === null ? EMPTY : formatDecimal(row.recent_per_month, 2)),
  },
  { prop: 'ca_delta', label: 'CA 变化', width: 92, align: 'right', formatter: (row) => displayText(row.ca_delta) },
  { prop: 'outlook', label: '潜力判断', width: 148, formatter: (row) => row.outlook.label },
  { prop: 'advice', label: '建议', minWidth: 180, formatter: (row) => row.advice_top?.action ?? EMPTY },
]

const pointColumns: TableColumn<GrowthPoint>[] = [
  { prop: 'date', label: '日期', width: 104 },
  { prop: 'age', label: '年龄', width: 64, align: 'right', formatter: (row) => displayText(row.age) },
  { prop: 'ca', label: 'CA', width: 64, align: 'right', formatter: (row) => displayText(row.ca) },
  { prop: 'pa', label: 'PA', width: 64, align: 'right', formatter: (row) => displayText(row.pa) },
  { prop: 'market_value', label: '身价', width: 110, align: 'right', formatter: (row) => formatMoney(row.market_value) },
  { prop: 'minutes_played', label: '出场分钟', width: 96, align: 'right', formatter: (row) => displayText(row.minutes_played) },
  { prop: 'ca_delta', label: 'CA 变化', width: 92, align: 'right', formatter: (row) => displayText(row.ca_delta) },
  { prop: 'change_label', label: '主要变化', minWidth: 140 },
]

/** Load the development board. */
async function loadBoard(): Promise<void> {
  boardLoading.value = true
  boardError.value = null
  try {
    const result = await getDevelopmentBoard(session.activeSaveId ?? undefined, 30, minAge.value)
    board.value = result.items ?? []
    if (selectedId.value === null && board.value.length > 0) {
      await select(board.value[0].player.instance_id)
    } else if (selectedId.value !== null) {
      await loadProfile(selectedId.value)
    }
  } catch (caught) {
    boardError.value = asApiError(caught)
    board.value = []
  } finally {
    boardLoading.value = false
  }
}

/** Load one player's growth profile. */
async function loadProfile(instanceId: number): Promise<void> {
  profileLoading.value = true
  profileError.value = null
  try {
    profile.value = await getGrowthProfile(instanceId)
  } catch (caught) {
    profileError.value = asApiError(caught)
    profile.value = null
  } finally {
    profileLoading.value = false
  }
}

/** Select a board row and load its profile. */
async function select(instanceId: number): Promise<void> {
  selectedId.value = instanceId
  await loadProfile(instanceId)
}

/** Confidence label of one piece of advice. */
function confidenceLabel(value: string): string {
  return { high: '高置信', medium: '中等', low: '参考', none: '无' }[value] ?? value
}

onMounted(() => void loadBoard())
</script>

<template>
  <div class="sm-page">
    <PageHeader
      title="Player Development · 球员发展"
      description="成长速率来自快照之间的真实变化；潜力判断是区间与等级，产品不承诺精确预测未来 CA。"
    >
      <template #actions>
        <el-input-number v-model="minAge" :min="14" :max="45" size="small" controls-position="right" />
        <span class="sm-text-2xs sm-text-faint">年龄上限</span>
        <el-button size="small" :loading="boardLoading" @click="loadBoard">刷新</el-button>
      </template>
    </PageHeader>

    <ErrorState v-if="boardError" :error="boardError" title="成长数据加载失败" @retry="loadBoard" />
    <SectionCard v-else title="成长排行" :subtitle="`只统计至少两个快照的球员，共 ${formatInt(board.length)} 人`">
      <LoadingBlock v-if="boardLoading && board.length === 0" :rows="3" />
      <DataTable
        v-else
        :columns="boardColumns"
        :rows="board"
        :row-key="(row) => String(row.player.instance_id)"
        clickable
        empty-title="没有可分析的球员"
        empty-description="需要至少两次扫描才能计算成长速率"
        @row-click="(row) => select(row.player.instance_id)"
      />
    </SectionCard>

    <template v-if="profile">
      <section class="sm-grid sm-grid--kpi">
        <KpiCard
          label="月均成长"
          :value="profile.rates.overall_per_month === null ? EMPTY : formatDecimal(profile.rates.overall_per_month, 2)"
          :hint="`分类 ${profile.rates.classification} · 样本 ${profile.rates.sample_size ?? 0} 个区间`"
          :tone="(profile.rates.overall_per_month ?? 0) > 0 ? 'accent' : 'warn'"
        />
        <KpiCard
          label="最近区间"
          :value="profile.rates.recent_per_month === null ? EMPTY : formatDecimal(profile.rates.recent_per_month, 2)"
          hint="最后一次快照之间的变化"
        />
        <KpiCard label="潜力判断" :value="profile.outlook.label" :hint="`概率 ${profile.outlook.probability ?? EMPTY}`" />
        <KpiCard
          label="外推区间"
          :value="
            profile.outlook.projected_low === null
              ? EMPTY
              : `${formatDecimal(profile.outlook.projected_low, 0)} – ${formatDecimal(profile.outlook.projected_high, 0)}`
          "
          :hint="`到 ${profile.outlook.horizon_age ?? 24} 岁的 CA 区间`"
        />
      </section>

      <div class="sm-grid sm-grid--wide-left">
        <SectionCard :title="`${profile.player.name} 成长曲线`" subtitle="CA 与 PA 随快照的变化">
          <ErrorState v-if="profileError" :error="profileError" title="球员成长加载失败" @retry="loadProfile(selectedId as number)" />
          <LoadingBlock v-else-if="profileLoading" :rows="3" />
          <EChart v-else-if="growthOption" :option="growthOption" height="300px" />
          <EmptyState v-else title="没有快照" description="该球员没有任何历史快照" />
        </SectionCard>

        <SectionCard title="发展建议" subtitle="每条建议都给出依据与置信度">
          <ul class="dev__advice">
            <li v-for="item in profile.advice" :key="item.action">
              <div class="sm-row sm-row--between">
                <strong>{{ item.action }}</strong>
                <el-tag size="small" type="info">{{ confidenceLabel(item.confidence) }}</el-tag>
              </div>
              <p class="sm-text-xs sm-text-2">{{ item.reason }}</p>
              <p class="sm-text-2xs sm-text-faint">{{ item.evidence.join('；') }}</p>
            </li>
          </ul>
          <p class="sm-text-2xs sm-text-faint dev__rationale">{{ profile.outlook.rationale }}</p>
        </SectionCard>
      </div>

      <SectionCard title="成长记录" subtitle="每次快照的年龄、能力、身价与主要变化">
        <DataTable :columns="pointColumns" :rows="profile.points" row-key="snapshot_id" dense :show-pagination="false" />
        <el-alert
          v-if="profile.data_gaps.length > 0"
          class="dev__gaps"
          type="warning"
          :closable="false"
          show-icon
          title="数据缺口"
        >
          <ul class="dev__list">
            <li v-for="gap in profile.data_gaps" :key="gap">{{ gap }}</li>
          </ul>
        </el-alert>
      </SectionCard>
    </template>

    <EmptyState
      v-else-if="!boardLoading"
      title="选择一名球员"
      description="点击上方表格中的球员查看成长曲线、建议与潜力区间"
    />
  </div>
</template>

<style scoped>
.dev__advice {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-3);
}

.dev__advice li {
  padding: var(--sm-space-2) var(--sm-space-3);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-md);
  background: var(--sm-surface-2);
}

.dev__rationale {
  margin-top: var(--sm-space-3);
  line-height: 1.7;
}

.dev__gaps {
  margin-top: var(--sm-space-3);
}

.dev__list {
  margin: 0;
  padding-left: var(--sm-space-4);
  font-size: var(--sm-fs-xs);
  line-height: 1.6;
}
</style>
