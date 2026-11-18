/** 概览：KPI、数据覆盖度、身价趋势、成交分布、最近导入与快捷入口。 */

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { asApiError, type ApiError } from '../api/client'
import { getOverview } from '../api/analytics'
import { listImports } from '../api/imports'
import { getTransferStats } from '../api/transfers'
import ChartCard from '../components/ChartCard.vue'
import CoverageBar from '../components/CoverageBar.vue'
import DataTable from '../components/DataTable.vue'
import EmptyState from '../components/EmptyState.vue'
import ErrorState from '../components/ErrorState.vue'
import KpiCard from '../components/KpiCard.vue'
import PageHeader from '../components/PageHeader.vue'
import SectionCard from '../components/SectionCard.vue'
import EChart from '../components/EChart.vue'
import type { OverviewResponse } from '../types/analytics'
import type { ImportJob } from '../types/imports'
import type { TransferStatsResponse } from '../types/transfers'
import type { TableColumn } from '../types/table'
import { useSessionStore } from '../stores/session'
import { buildFeeHistogram, buildTrendChart } from '../utils/chart'
import {
  EMPTY,
  formatDateTime,
  formatInt,
  formatMoney,
  formatPercent,
  displayText,
} from '../utils/format'
import { coverageLabel, importStatusLabel, sourceLabel } from '../utils/labels'

const session = useSessionStore()
const router = useRouter()

const overview = ref<OverviewResponse | null>(null)
const overviewLoading = ref(false)
const overviewError = ref<ApiError | null>(null)

const imports = ref<ImportJob[]>([])
const importsLoading = ref(false)
const importsError = ref<ApiError | null>(null)

const stats = ref<TransferStatsResponse | null>(null)
const statsLoading = ref(false)
const statsError = ref<ApiError | null>(null)

/** Coverage entries in the order the API returned them. */
const coverageEntries = computed(() => Object.entries(overview.value?.coverage ?? {}))

/** Currency reported by the statistics endpoint; the API default is EUR. */
const currency = computed(() => stats.value?.currency ?? 'EUR')

/** Fee histogram option built from the statistics distribution. */
const feeChartOption = computed(() => buildFeeHistogram(stats.value?.distribution ?? []))

/** Trend option; empty series are handled by the chart card state. */
const trendOption = computed(() => buildTrendChart(overview.value?.trend ?? []))

const trendFootnote = computed(() => {
  const points = overview.value?.trend ?? []
  if (points.length === 0) return ''
  const last = points[points.length - 1]
  return `趋势点 ${points.length} 个（最近 ${last?.date ?? EMPTY}）· 由每日快照聚合，CA 均值与总身价各取当期快照`
})

const feeFootnote = computed(() => {
  const value = stats.value
  if (!value) return ''
  return `样本 ${formatInt(value.sample_size)} 笔 · 算法 ${displayText(value.algorithm_version)} · 中位数 ${formatMoney(value.median)} · P25 ${formatMoney(value.p25)} · P75 ${formatMoney(value.p75)} · 币种 ${value.currency}`
})

const feeEmpty = computed(() => {
  const value = stats.value
  if (!value) return false
  return value.sample_size === 0 || value.distribution.length === 0
})

const feeEmptyDescription = computed(() => {
  const value = stats.value
  if (!value) return ''
  const excluded = value.excluded
  const warning = value.warnings.length > 0 ? value.warnings[0] : ''
  return `当前筛选窗口内没有可统计的已完成交易（排除不完整 ${formatInt(excluded.incomplete)} 笔、非完成 ${formatInt(excluded.non_completed)} 笔）。${warning}`
})

const importsColumns: TableColumn<ImportJob>[] = [
  { prop: 'received_at', label: '接收时间', width: 150, formatter: (row) => formatDateTime(row.received_at) },
  { prop: 'source', label: '来源', width: 110, formatter: (row) => sourceLabel(row.source) },
  { prop: 'status', label: '状态', width: 96, formatter: (row) => importStatusLabel(row.status) },
  { prop: 'player_count', label: '球员', width: 80, align: 'right', formatter: (row) => formatInt(row.player_count) },
  { prop: 'transfer_count', label: '交易', width: 80, align: 'right', formatter: (row) => formatInt(row.transfer_count) },
  {
    prop: 'warnings',
    label: '警告',
    minWidth: 120,
    align: 'right',
    formatter: (row) => (row.warnings.length === 0 ? '0' : String(row.warnings.length)),
    title: '导入过程中记录的非致命警告数量',
  },
]

const quickLinks = [
  { to: '/squad', title: '阵容智能', description: '六维阵容评分、位置深度、短板与接班规划' },
  { to: '/recruitment', title: '智能球探引擎', description: '位置模板 + 六维评分 + 隐藏价值 + 候选名单' },
  { to: '/transfers', title: '转会情报', description: '成交分位、总成本模型、投资效率与复盘' },
  { to: '/development', title: '球员发展', description: '成长速率、发展建议与潜力区间' },
  { to: '/performance', title: '表现分析', description: '分位置每 90 分钟产出与同位置百分位' },
  { to: '/agent', title: 'AI 体育总监', description: '自然语言提问，回答带可靠性分类与工具引用' },
  { to: '/players', title: '球员中心', description: '按位置、年龄、CA/PA 与身价筛选全部球员实例' },
  { to: '/scouting', title: '角色球探', description: '选择战术角色模板，按加权评分排序候选人' },
  { to: '/watchlist', title: '关注名单', description: '关注球员、标签与规则生成的提醒' },
  { to: '/data', title: '数据中心', description: '扫描导入、覆盖度与客户端兼容性' },
]

/** Load overview, recent imports and fee statistics for the active save. */
async function loadAll(): Promise<void> {
  const saveId = session.activeSaveId
  overviewLoading.value = true
  overviewError.value = null
  importsLoading.value = true
  importsError.value = null
  statsLoading.value = true
  statsError.value = null

  await Promise.all([
    (async () => {
      try {
        overview.value = await getOverview(saveId ?? undefined)
      } catch (caught) {
        overviewError.value = asApiError(caught)
        overview.value = null
      } finally {
        overviewLoading.value = false
      }
    })(),
    (async () => {
      try {
        const response = await listImports({ save_id: saveId ?? undefined, limit: 6 })
        imports.value = response.items ?? []
        session.markSources(imports.value.map((job) => job.source))
      } catch (caught) {
        importsError.value = asApiError(caught)
        imports.value = []
      } finally {
        importsLoading.value = false
      }
    })(),
    (async () => {
      try {
        stats.value = await getTransferStats({ save_id: saveId ?? undefined })
      } catch (caught) {
        statsError.value = asApiError(caught)
        stats.value = null
      } finally {
        statsLoading.value = false
      }
    })(),
  ])
}

/** Open the diagnostics screen from a recent-import row. */
function openImport(): void {
  void router.push('/data')
}

watch([() => session.activeSaveId, () => session.dataRevision], () => void loadAll(), { immediate: true })
</script>

<template>
  <div class="sm-page">
    <PageHeader
      title="概览"
      description="当前存档的数据规模、覆盖度与成交统计口径。所有数值来自后端接口，缺失值显示为 —。"
    >
      <template #meta>
        <el-tag v-if="session.activeSave" size="small" type="info" disable-transitions>
          存档：{{ session.activeSave.name }}
        </el-tag>
        <span class="sm-text-xs sm-text-faint">
          游戏版本 {{ displayText(session.activeSave?.game_version) }} ·
          最近导入 {{ formatDateTime(overview?.last_import?.finished_at ?? null) }}
        </span>
      </template>
      <template #actions>
        <el-button size="small" :loading="overviewLoading || importsLoading" @click="loadAll">刷新</el-button>
        <el-button size="small" type="primary" @click="router.push('/data')">导入扫描数据</el-button>
      </template>
    </PageHeader>

    <ErrorState
      v-if="overviewError && !overview"
      :error="overviewError"
      title="概览指标加载失败"
      @retry="loadAll"
    />

    <template v-else>
      <div class="sm-grid sm-grid--kpi">
        <KpiCard
          label="球员数"
          :value="overview ? formatInt(overview.players) : EMPTY"
          :hint="overview ? `俱乐部 ${formatInt(overview.clubs)} 个` : ''"
          :loading="overviewLoading && !overview"
          to="/players"
        />
        <KpiCard
          label="快照数"
          :value="overview ? formatInt(overview.snapshots) : EMPTY"
          hint="每次观测一条快照"
          :loading="overviewLoading && !overview"
        />
        <KpiCard
          label="成交数"
          :value="overview ? formatInt(overview.transfers) : EMPTY"
          :hint="`仅统计 status=completed 且含金额来源的交易`"
          :loading="overviewLoading && !overview"
          to="/transfers"
        />
        <KpiCard
          :label="`已完成转会总额（${currency}）`"
          :value="formatMoney(overview?.completed_transfer_value ?? null)"
          hint="按记录币种汇总，不做汇率换算"
          :loading="overviewLoading && !overview"
          tone="accent"
        />
        <KpiCard
          label="关注数"
          :value="overview ? formatInt(overview.watchlist) : EMPTY"
          hint="来源：手工添加与规则刷新"
          :loading="overviewLoading && !overview"
          to="/watchlist"
        />
        <KpiCard
          label="未读提醒"
          :value="overview ? formatInt(overview.alerts) : EMPTY"
          hint="由关注规则生成"
          :loading="overviewLoading && !overview"
          :tone="(overview?.alerts ?? 0) > 0 ? 'warn' : 'default'"
          to="/watchlist"
        />
      </div>

      <div class="sm-grid sm-grid--wide-left">
        <ChartCard
          title="身价与 CA 趋势"
          subtitle="总身价（亿 €）与阵容 CA 均值随时间变化"
          :loading="overviewLoading && !overview"
          :empty="!overviewLoading && (overview?.trend.length ?? 0) === 0"
          empty-title="暂无趋势数据"
          empty-description="后端还没有可聚合的快照序列。导入至少两次扫描后，趋势才会出现。"
          :footnote="trendFootnote"
        >
          <EChart :option="trendOption" height="248px" aria-label="总身价与 CA 均值时间序列" />
        </ChartCard>

        <SectionCard title="数据覆盖度" subtitle="各字段在样本中的非空比例">
          <div v-if="overviewLoading && !overview" class="sm-stack">
            <el-skeleton :rows="4" animated />
          </div>
          <EmptyState
            v-else-if="coverageEntries.length === 0"
            title="覆盖度未提供"
            description="后端未返回 coverage 字段，无法判断缺失情况；这通常意味着当前存档尚未导入任何扫描数据。"
            compact
          />
          <div v-else class="coverage-list">
            <CoverageBar
              v-for="[key, value] in coverageEntries"
              :key="key"
              :label="coverageLabel(key)"
              :value="value"
              :hint="value === null ? '后端未提供该字段的覆盖度' : ''"
            />
          </div>
          <template #footer>
            覆盖度 = 非空记录数 / 样本记录数。低于 60% 时相关统计（分位数、估值）会不稳定。
          </template>
        </SectionCard>
      </div>

      <div class="sm-grid sm-grid--wide-left">
        <SectionCard title="最近导入" subtitle="按接收时间倒序的前 6 条导入任务" flush>
          <DataTable
            :columns="importsColumns"
            :rows="imports"
            :loading="importsLoading"
            :error="importsError"
            row-key="id"
            clickable
            :empty-title="imports.length === 0 ? '还没有导入记录' : '暂无数据'"
            empty-description="在「数据与诊断」中拖入扫描 JSON/NDJSON，或先运行 ScoutMind.LiveReader.exe scan 生成真实数据。"
            @row-click="openImport"
            @retry="loadAll"
          />
        </SectionCard>

        <ChartCard
          title="成交费用分布"
          subtitle="已完成交易的费用直方图"
          :loading="statsLoading && !stats"
          :empty="!statsLoading && feeEmpty"
          empty-title="暂无成交样本"
          :empty-description="feeEmptyDescription"
          :footnote="feeFootnote"
        >
          <EChart :option="feeChartOption" height="216px" aria-label="成交费用直方图" />
        </ChartCard>
      </div>

      <ErrorState v-if="statsError && !stats" :error="statsError" compact @retry="loadAll" />

      <SectionCard title="快速入口" subtitle="按工作流进入对应模块">
        <div class="quick-links">
          <router-link v-for="link in quickLinks" :key="link.to" :to="link.to" class="quick-link">
            <span class="quick-link__title">{{ link.title }}</span>
            <span class="quick-link__desc">{{ link.description }}</span>
          </router-link>
        </div>
      </SectionCard>

      <SectionCard title="口径说明" dense>
        <ul class="notes">
          <li>所有比率（覆盖度、置信度）来自后端字段；页面不做二次估算，也不补默认值。</li>
          <li>金额单位为记录自带币种，默认 EUR；页面只做 万/亿 显示换算，不做汇率转换。</li>
          <li>
            成交统计只包含 <code>status=completed</code> 且至少有一个金额来源的交易；
            <code>untriggered</code> 附加条款不计入已支付金额。
          </li>
          <li>
            当前统计算法版本：费用分布 {{ displayText(stats?.algorithm_version) }}；估值算法见球员详情。
          </li>
          <li>
            覆盖度：{{ coverageEntries.map(([key, value]) => `${coverageLabel(key)} ${formatPercent(value)}`).join(' · ') || EMPTY }}
          </li>
        </ul>
      </SectionCard>
    </template>
  </div>
</template>

<style scoped>
.coverage-list {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-3);
}

.quick-links {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--sm-space-3);
}

.quick-link {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--sm-space-3);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-md);
  background: var(--sm-surface-2);
  color: inherit;
}

.quick-link:hover {
  border-color: var(--sm-accent);
  background: var(--sm-accent-weak);
  text-decoration: none;
}

.quick-link__title {
  color: var(--sm-text);
  font-size: var(--sm-fs-sm);
  font-weight: var(--sm-fw-medium);
}

.quick-link__desc {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
  line-height: 1.6;
}

.notes {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-1);
  padding-left: var(--sm-space-4);
  color: var(--sm-text-2);
  font-size: var(--sm-fs-xs);
  line-height: 1.7;
}

.notes code {
  padding: 0 3px;
  border-radius: 3px;
  background: var(--sm-surface-3);
  font-family: var(--sm-font-mono);
}
</style>
