/**
 * 比赛表现分析：分位置统计、每 90 分钟产出、同位置百分位、趋势，以及能力与表现对比。
 * 缺失字段显示为「数据缺失」，不用 0 代替。
 */

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { asApiError, type ApiError } from '../api/client'
import { getPerformanceBoard, getPerformanceMetrics, getPerformanceProfile } from '../api/performance'
import CoverageBar from '../components/CoverageBar.vue'
import DataTable from '../components/DataTable.vue'
import EmptyState from '../components/EmptyState.vue'
import ErrorState from '../components/ErrorState.vue'
import KpiCard from '../components/KpiCard.vue'
import LoadingBlock from '../components/LoadingBlock.vue'
import PageHeader from '../components/PageHeader.vue'
import SectionCard from '../components/SectionCard.vue'
import StatHeader from '../components/StatHeader.vue'
import { useSessionStore } from '../stores/session'
import type { PerformanceBoardRow, PerformanceMetric, PerformanceMetricSpec, PerformanceProfile } from '../types/performance'
import type { TableColumn } from '../types/table'
import { EMPTY, displayText, formatDecimal, formatInt, formatPercent } from '../utils/format'
import { positionLabel } from '../utils/labels'

const session = useSessionStore()

const SLOT_OPTIONS = [
  { value: 'ALL', label: '全部位置' },
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

const board = ref<PerformanceBoardRow[]>([])
const boardLoading = ref(false)
const boardError = ref<ApiError | null>(null)
const slot = ref('ALL')
const minMinutes = ref(300)
const excluded = ref(0)

const spec = ref<PerformanceMetricSpec | null>(null)
const profile = ref<PerformanceProfile | null>(null)
const profileLoading = ref(false)
const profileError = ref<ApiError | null>(null)
const selectedId = ref<number | null>(null)

const boardColumns: TableColumn<PerformanceBoardRow>[] = [
  { prop: 'name', label: '球员', minWidth: 150 },
  { prop: 'club', label: '俱乐部', width: 150, formatter: (row) => displayText(row.club) },
  { prop: 'position', label: '位置', width: 92, formatter: (row) => positionLabel(row.position) },
  { prop: 'age', label: '年龄', width: 64, align: 'right', formatter: (row) => displayText(row.age) },
  { prop: 'ca', label: 'CA', width: 60, align: 'right', formatter: (row) => displayText(row.ca) },
  { prop: 'minutes', label: '出场分钟', width: 96, align: 'right', formatter: (row) => displayText(row.minutes_played) },
  {
    prop: 'output',
    label: '产出百分位',
    width: 104,
    align: 'right',
    formatter: (row) => (row.output_percentile === null ? EMPTY : formatPercent(row.output_percentile, 0)),
  },
  {
    prop: 'ability',
    label: '能力百分位',
    width: 112,
    align: 'right',
    formatter: (row) => (row.ability_percentile === null ? EMPTY : formatPercent(row.ability_percentile, 0)),
  },
  { prop: 'verdict', label: '结论', width: 140 },
]

const metricColumns: TableColumn<PerformanceMetric>[] = [
  { prop: 'label', label: '指标', minWidth: 130 },
  { prop: 'total', label: '累计', width: 88, align: 'right', formatter: (row) => displayText(row.total) },
  { prop: 'per90', label: '每 90 分钟', width: 104, align: 'right', formatter: (row) => formatDecimal(row.per90, 2) },
  {
    prop: 'percentile',
    label: '同位置百分位',
    width: 118,
    align: 'right',
    formatter: (row) => (row.percentile === null ? EMPTY : formatPercent(row.percentile, 0)),
  },
  { prop: 'peer_sample', label: '样本', width: 72, align: 'right' },
]

/** Whether the tracked metrics carry any percentile, i.e. whether a ranking is meaningful. */
const hasPercentiles = computed(() => (profile.value?.metrics ?? []).some((metric) => metric.percentile !== null))

/** 分位置产出概况：只汇总后端字段，不重新计算百分位。 */
const metricStats = computed(() => {
  const metrics = profile.value?.metrics ?? []
  const available = metrics.filter((metric) => metric.percentile !== null).length
  const samples = metrics.map((metric) => metric.peer_sample)
  return [
    { label: '跟踪指标', value: formatInt(metrics.length) },
    { label: '有百分位', value: formatInt(available) },
    {
      label: '最小同位置样本',
      value: samples.length === 0 ? EMPTY : formatInt(Math.min(...samples)),
      hint: 'peer_sample 最小值',
    },
  ]
})

/** Load the performance board. */
async function loadBoard(): Promise<void> {
  boardLoading.value = true
  boardError.value = null
  try {
    const result = await getPerformanceBoard(
      session.activeSaveId ?? undefined,
      slot.value === 'ALL' ? undefined : slot.value,
      minMinutes.value,
      60,
    )
    board.value = result.items ?? []
    excluded.value = result.excluded_below_minutes ?? 0
    if (selectedId.value === null && board.value.length > 0) {
      await select(board.value[0].instance_id)
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

/** Load one player's performance profile. */
async function loadProfile(instanceId: number): Promise<void> {
  profileLoading.value = true
  profileError.value = null
  try {
    profile.value = await getPerformanceProfile(instanceId)
  } catch (caught) {
    profileError.value = asApiError(caught)
    profile.value = null
  } finally {
    profileLoading.value = false
  }
}

/** Select a board row. */
async function select(instanceId: number): Promise<void> {
  selectedId.value = instanceId
  await loadProfile(instanceId)
}

onMounted(async () => {
  try {
    spec.value = await getPerformanceMetrics()
  } catch {
    spec.value = null
  }
  await loadBoard()
})
</script>

<template>
  <div class="sm-page">
    <PageHeader
      eyebrow="PERFORMANCE ANALYTICS"
      title="比赛表现分析"
      description="属性强不等于表现出色：按位置比较每 90 分钟产出与同位置百分位，再把产出和能力放在一起看。缺失的统计字段会明确标注。"
    >
      <template #actions>
        <el-select v-model="slot" size="small" class="perf__slot" aria-label="位置" @change="loadBoard">
          <el-option v-for="item in SLOT_OPTIONS" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
        <el-input-number v-model="minMinutes" :min="0" :step="90" size="small" controls-position="right" />
        <span class="sm-text-2xs sm-text-faint">最低分钟</span>
        <el-button size="small" :loading="boardLoading" @click="loadBoard">刷新</el-button>
      </template>
    </PageHeader>

    <ErrorState v-if="boardError" :error="boardError" title="表现数据加载失败" @retry="loadBoard" />

    <SectionCard
      v-else
      title="表现排行"
      :subtitle="`${formatInt(board.length)} 名球员达到出场门槛${excluded > 0 ? `，另有 ${excluded} 人因出场时间不足未参与排名` : ''}`"
    >
      <LoadingBlock v-if="boardLoading && board.length === 0" :rows="3" />
      <DataTable
        v-else
        :columns="boardColumns"
        :rows="board"
        :row-key="(row) => String(row.instance_id)"
        clickable
        empty-title="没有可用的赛季统计"
        empty-description="导入带有 statistics 块的扫描数据后即可分析"
        @row-click="(row) => select(row.instance_id)"
      />
    </SectionCard>

    <template v-if="profile">
      <section class="sm-grid sm-grid--kpi">
        <KpiCard
          label="赛季"
          :value="profile.season?.period ?? EMPTY"
          :hint="profile.season?.competition ?? '未知赛事'"
        />
        <KpiCard
          label="出场 / 分钟"
          :value="`${formatInt(profile.season?.appearances ?? null)} / ${formatInt(profile.season?.minutes_played ?? null)}`"
          hint="来自赛季统计块"
        />
        <KpiCard
          label="产出百分位"
          :value="
            profile.ability_vs_output.output_percentile === null
              ? EMPTY
              : formatPercent(profile.ability_vs_output.output_percentile, 0)
          "
          hint="同位置球员之间的相对位置"
        />
        <KpiCard
          label="能力 vs 表现"
          :value="profile.ability_vs_output.verdict ?? '不可比较'"
          :hint="profile.ability_vs_output.available ? `差距 ${formatPercent(profile.ability_vs_output.gap ?? null, 0)}` : profile.ability_vs_output.reason ?? ''"
          :tone="profile.ability_vs_output.available ? 'accent' : 'warn'"
        />
      </section>

      <div class="sm-grid sm-grid--wide-left">
        <SectionCard :title="`${profile.player.name} 分位置产出`" subtitle="每 90 分钟与同位置百分位；百分位为空表示样本不足">
          <ErrorState v-if="profileError" :error="profileError" title="球员表现加载失败" @retry="loadProfile(selectedId as number)" />
          <LoadingBlock v-else-if="profileLoading" :rows="3" />
          <template v-else>
            <StatHeader
              class="perf__stats"
              :items="metricStats"
              footnote="同位置样本取各指标 peer_sample 的最小值；百分位为空表示样本不足。"
            />
            <DataTable :columns="metricColumns" :rows="profile.metrics" row-key="key" dense :show-pagination="false" />
            <p v-if="!hasPercentiles" class="sm-text-2xs sm-text-faint perf__note">
              当前没有可用的同位置百分位：需要至少 5 名同位置且有统计的球员。
            </p>
          </template>
        </SectionCard>

        <SectionCard title="趋势" subtitle="赛季之间可以直接比较；逐场窗口需要逐场统计">
          <template v-if="profile.trend.available && profile.trend.season_over_season">
            <p class="sm-text-xs sm-text-2">
              {{ profile.trend.season_over_season.previous_period }} → {{ profile.trend.season_over_season.current_period }}
            </p>
            <ul class="perf__trend">
              <li v-for="change in profile.trend.season_over_season.changes" :key="change.key">
                <span>{{ change.label }}</span>
                <span class="sm-num">
                  {{ displayText(change.previous) }} → {{ displayText(change.current) }}
                  <em :class="(change.delta ?? 0) >= 0 ? 'perf__up' : 'perf__down'">
                    ({{ change.delta === null ? EMPTY : change.delta > 0 ? `+${change.delta}` : change.delta }})
                  </em>
                </span>
              </li>
            </ul>
          </template>
          <EmptyState v-else title="趋势不可用" :description="profile.trend.reason" />
          <ul v-if="profile.trend.unavailable_windows" class="perf__gaps">
            <li v-for="(reason, key) in profile.trend.unavailable_windows" :key="key">{{ key }}：{{ reason }}</li>
          </ul>
        </SectionCard>
      </div>

      <SectionCard title="能力与表现" subtitle="属性预期与实际产出的差距">
        <div class="perf__bars">
          <CoverageBar label="能力百分位" :value="profile.ability_vs_output.ability_percentile" />
          <CoverageBar label="产出百分位" :value="profile.ability_vs_output.output_percentile" />
        </div>
        <ul v-if="(profile.ability_vs_output.evidence ?? []).length > 0" class="perf__evidence">
          <li v-for="line in profile.ability_vs_output.evidence ?? []" :key="line">{{ line }}</li>
        </ul>
        <el-alert
          v-if="profile.data_gaps.length > 0"
          class="perf__alert"
          type="warning"
          :closable="false"
          show-icon
          title="数据缺口"
        >
          <ul class="perf__gaps">
            <li v-for="gap in profile.data_gaps" :key="gap">{{ gap }}</li>
          </ul>
        </el-alert>
      </SectionCard>
    </template>

    <EmptyState
      v-else-if="!boardLoading"
      title="选择一名球员"
      description="点击表格中的球员查看分位置产出、趋势与能力对比"
    />

    <SectionCard v-if="spec" title="统计口径" subtitle="每个位置关注的指标，以及缺失数据的处理规则">
      <div class="perf__spec">
        <div v-for="(metrics, group) in spec.position_metrics" :key="group" class="perf__spec-group">
          <p class="sm-label">{{ group }}</p>
          <p class="sm-text-xs sm-text-2">{{ metrics.map((metric) => metric.label).join('、') }}</p>
        </div>
      </div>
      <p class="sm-text-2xs sm-text-faint">{{ spec.note }}</p>
    </SectionCard>
  </div>
</template>

<style scoped>
.perf__slot {
  width: 132px;
}

.perf__note {
  margin-top: var(--sm-space-2);
}

.perf__trend {
  margin: var(--sm-space-2) 0 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-1);
  font-size: var(--sm-fs-xs);
  color: var(--sm-text-2);
}

.perf__trend li {
  display: flex;
  justify-content: space-between;
  gap: var(--sm-space-2);
  padding-bottom: var(--sm-space-1);
  border-bottom: 1px solid var(--sm-border);
}

.perf__trend li:last-child {
  padding-bottom: 0;
  border-bottom: 0;
}

.perf__up {
  color: var(--sm-success);
  font-style: normal;
}

.perf__down {
  color: var(--sm-danger);
  font-style: normal;
}

.perf__gaps {
  margin: var(--sm-space-2) 0 0;
  padding-left: var(--sm-space-4);
  font-size: var(--sm-fs-xs);
  line-height: 1.6;
  color: var(--sm-text-2);
}

.perf__stats {
  margin-bottom: var(--sm-space-3);
}

.perf__bars {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: var(--sm-space-4);
}

.perf__evidence {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-1);
  margin: var(--sm-space-3) 0 0;
  padding-left: var(--sm-space-4);
  color: var(--sm-text-2);
  font-size: var(--sm-fs-xs);
  line-height: 1.7;
}

.perf__alert {
  margin-top: var(--sm-space-3);
}

.perf__spec {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: var(--sm-space-3);
  margin-bottom: var(--sm-space-2);
}
</style>
