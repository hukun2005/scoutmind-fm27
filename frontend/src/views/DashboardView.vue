/**
 * 指挥中心：存档状态、阵容关键指标、实力趋势、结构分析、AI 事实摘要与最近活动。
 * 所有数值来自后端接口；缺失值显示为 —，无本队时给出明确空状态。
 */

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { asApiError, type ApiError } from '../api/client'
import { getOverview } from '../api/analytics'
import { listImports } from '../api/imports'
import { getSquadOverview } from '../api/squad'
import { listPlayers } from '../api/players'
import { getTransferStats } from '../api/transfers'
import AppIcon from '../components/AppIcon.vue'
import ChartCard from '../components/ChartCard.vue'
import CoverageBar from '../components/CoverageBar.vue'
import DataTable from '../components/DataTable.vue'
import EmptyState from '../components/EmptyState.vue'
import ErrorState from '../components/ErrorState.vue'
import KpiCard from '../components/KpiCard.vue'
import SectionCard from '../components/SectionCard.vue'
import EChart from '../components/EChart.vue'
import type { OverviewResponse } from '../types/analytics'
import type { ImportJob } from '../types/imports'
import type { PlayerSummary } from '../types/players'
import type { SquadOverview } from '../types/squad'
import type { TransferStatsResponse } from '../types/transfers'
import type { TableColumn } from '../types/table'
import { useSessionStore } from '../stores/session'
import {
  buildAgeDistribution,
  buildFeeHistogram,
  buildPositionDistribution,
  buildSquadRadar,
  buildTrendChart,
} from '../utils/chart'
import {
  EMPTY,
  formatDateTime,
  formatDecimal,
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

const squad = ref<SquadOverview | null>(null)
const squadLoading = ref(false)
const squadError = ref<ApiError | null>(null)

const topPlayers = ref<PlayerSummary[]>([])
const topPlayersLoading = ref(false)
const topPlayersError = ref<ApiError | null>(null)

/** 覆盖度条目，按后端返回顺序。 */
const coverageEntries = computed(() => Object.entries(overview.value?.coverage ?? {}))

/** 统计接口返回的币种；API 默认 EUR。 */
const currency = computed(() => stats.value?.currency ?? 'EUR')

/** 费用直方图。 */
const feeChartOption = computed(() => buildFeeHistogram(stats.value?.distribution ?? []))

/** 强度趋势；空序列由图表卡的空状态处理。 */
const trendOption = computed(() => buildTrendChart(overview.value?.trend ?? []))

/** 最近一个趋势点：用于「阵容总身价」与「CA 均值」。 */
const lastTrend = computed(() => {
  const points = overview.value?.trend ?? []
  return points.length > 0 ? points[points.length - 1] : null
})

/** 本队是否可分析。 */
const squadAvailable = computed(() => (squad.value?.squad_size ?? 0) > 0)

/** 年龄结构图。 */
const ageOption = computed(() => buildAgeDistribution(squad.value?.age_structure.buckets ?? []))

/** 位置结构图。 */
const positionOption = computed(() => buildPositionDistribution(squad.value?.depth ?? []))

/** 六维能力雷达。 */
const squadRadarOption = computed(() => buildSquadRadar(squad.value?.components ?? []))

/** 雷达图脚注：说明哪些维度缺失。 */
const radarFootnote = computed(() => {
  const components = squad.value?.components ?? []
  if (components.length === 0) return ''
  const missing = components.filter((entry) => entry.value === null).map((entry) => entry.label)
  const base = '0–100 为六维加权前的归一化分值；权重可在阵容智能中调整。'
  return missing.length > 0 ? `${base} 缺失维度：${missing.join('、')}。` : base
})

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

/** 最近存档时间。 */
const lastImportLabel = computed(() => formatDateTime(overview.value?.last_import?.finished_at ?? null))

/** 数据来源状态。 */
const dataStatus = computed(() => {
  if (session.demoMode) return '演示数据'
  if (session.hasRealScanData) return '真实扫描数据'
  return '尚未导入扫描数据'
})

/** 顶部命令条：本队与数据缺口。 */
const squadMeta = computed(() => {
  const club = squad.value?.club
  if (!club) return '未指定本队'
  return club.league ? `${club.name} · ${club.league}` : club.name
})

/** Top 5 身价的最大值，用于列表条宽度（纯展示比例）。 */
const topValueMax = computed(() => Math.max(0, ...topPlayers.value.map((row) => row.market_value ?? 0)))

/** 规则推导的事实摘要：只使用后端字段，不生成结论。 */
const insights = computed<Array<{ tone: 'info' | 'warn' | 'danger'; title: string; detail: string; to?: string }>>(() => {
  const list: Array<{ tone: 'info' | 'warn' | 'danger'; title: string; detail: string; to?: string }> = []
  const current = squad.value
  if (!current) return list

  const weakest = current.weakness[0]
  if (weakest) {
    list.push({
      tone: weakest.severity >= 2 ? 'danger' : 'warn',
      title: `位置短板：${weakest.slot_name}`,
      detail: `现有 ${weakest.count} / 需求 ${weakest.required}。${weakest.suggestion}`,
      to: '/squad',
    })
  }

  if (current.contracts.at_risk_count > 0) {
    list.push({
      tone: 'warn',
      title: `合同风险：${formatInt(current.contracts.at_risk_count)} 名球员`,
      detail: current.contracts.at_risk_names.slice(0, 3).join('、') + (current.contracts.at_risk_names.length > 3 ? ' 等' : ''),
      to: '/squad',
    })
  }

  const gaps = Object.entries(overview.value?.coverage ?? {}).filter(
    ([, value]) => value !== null && value < 0.6,
  )
  if (gaps.length > 0) {
    list.push({
      tone: 'info',
      title: `数据缺口：${gaps.length} 个字段低于 60%`,
      detail: gaps.map(([key, value]) => `${coverageLabel(key)} ${formatPercent(value)}`).join(' · '),
      to: '/data',
    })
  }

  const succession = current.succession[0]
  if (succession) {
    list.push({
      tone: 'info',
      title: `接班规划：${succession.player.name}`,
      detail: succession.verdict,
      to: '/squad',
    })
  }

  if ((overview.value?.alerts ?? 0) > 0) {
    list.push({
      tone: 'warn',
      title: `未读提醒：${formatInt(overview.value?.alerts)}`,
      detail: '由关注名单规则生成，可在关注页逐条处理。',
      to: '/watchlist',
    })
  }

  return list.slice(0, 4)
})

/** 快捷入口。 */
const quickLinks = [
  { to: '/squad', icon: 'squad' as const, title: '阵容智能', description: '六维评分、位置深度、短板与接班规划' },
  { to: '/recruitment', icon: 'scouting' as const, title: '智能球探', description: '位置模板 + 六维评分 + 隐藏价值' },
  { to: '/transfers', icon: 'transfers' as const, title: '转会情报', description: '成交分位、成本模型与投资效率' },
  { to: '/development', icon: 'development' as const, title: '球员发展', description: '成长速率、发展建议与潜力区间' },
  { to: '/performance', icon: 'performance' as const, title: '表现分析', description: '分位置每 90 分钟产出与百分位' },
  { to: '/agent', icon: 'agent' as const, title: 'AI 体育总监', description: '自然语言提问，回答带可靠性分类' },
  { to: '/players', icon: 'players' as const, title: '球员中心', description: '按位置、年龄、CA/PA 与身价筛选' },
  { to: '/data', icon: 'data' as const, title: '数据中心', description: '扫描导入、覆盖度与客户端兼容性' },
]

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

/** 加载概览、最近导入、成交统计、阵容与身价前 5。 */
async function loadAll(): Promise<void> {
  const saveId = session.activeSaveId
  overviewLoading.value = true
  overviewError.value = null
  importsLoading.value = true
  importsError.value = null
  statsLoading.value = true
  statsError.value = null
  squadLoading.value = true
  squadError.value = null
  topPlayersLoading.value = true
  topPlayersError.value = null

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
    (async () => {
      try {
        squad.value = await getSquadOverview({ save_id: saveId ?? undefined })
      } catch (caught) {
        squadError.value = asApiError(caught)
        squad.value = null
      } finally {
        squadLoading.value = false
      }
    })(),
    (async () => {
      try {
        const response = await listPlayers({
          save_id: saveId ?? undefined,
          sort: '-market_value',
          limit: 5,
          offset: 0,
        })
        topPlayers.value = response.items ?? []
      } catch (caught) {
        topPlayersError.value = asApiError(caught)
        topPlayers.value = []
      } finally {
        topPlayersLoading.value = false
      }
    })(),
  ])
}

/** 从导入记录跳转到数据诊断页。 */
function openImport(): void {
  void router.push('/data')
}

watch([() => session.activeSaveId, () => session.dataRevision], () => void loadAll(), { immediate: true })
</script>

<template>
  <div class="sm-page dashboard">
    <ErrorState
      v-if="overviewError && !overview"
      :error="overviewError"
      title="概览指标加载失败"
      @retry="loadAll"
    />

    <template v-else>
      <!-- 指挥条：欢迎、存档、同步状态与主操作 -->
      <section class="command" aria-label="指挥中心概览">
        <div class="command__glow" aria-hidden="true" />
        <div class="command__grid" aria-hidden="true" />
        <div class="command__body">
          <span class="sm-eyebrow">Command Center</span>
          <h1 class="command__title">
            欢迎回来，<span class="sm-gradient-text">分析员</span>
          </h1>
          <p class="command__subtitle">
            当前存档的阵容结构、数据完整度与最近导入状态集中在这里。所有数值来自后端接口，缺失显示为 —。
          </p>
          <div class="command__chips">
            <span class="chip chip--accent">
              <i aria-hidden="true" />
              {{ displayText(session.activeSave?.name) }}
            </span>
            <span class="chip">游戏版本 {{ displayText(session.activeSave?.game_version) }}</span>
            <span class="chip" :class="{ 'chip--demo': session.demoMode }">{{ dataStatus }}</span>
            <span class="chip">最近导入 {{ lastImportLabel }}</span>
            <span class="chip">本队 {{ squadMeta }}</span>
          </div>
        </div>
        <div class="command__actions">
          <el-button size="small" type="primary" @click="router.push('/data')">导入扫描数据</el-button>
          <el-button size="small" @click="router.push('/agent')">打开 AI 体育总监</el-button>
          <el-button size="small" :loading="overviewLoading || squadLoading" @click="loadAll">刷新</el-button>
        </div>
      </section>

      <!-- 关键指标 -->
      <div class="sm-grid sm-grid--kpi">
        <KpiCard
          label="阵容规模"
          :value="squadAvailable ? formatInt(squad?.squad_size) : EMPTY"
          :hint="squadAvailable ? `全库球员 ${formatInt(overview?.players)}` : '未指定本队'"
          :loading="squadLoading && !squad"
          to="/squad"
        />
        <KpiCard
          label="阵容评分"
          :value="squad?.score === null || squad?.score === undefined ? EMPTY : formatDecimal(squad.score, 1)"
          hint="六维加权（0–100）"
          tone="accent"
          :loading="squadLoading && !squad"
          to="/squad"
        />
        <KpiCard
          label="平均年龄"
          :value="squad?.age_structure.average_age === null || squad?.age_structure.average_age === undefined ? EMPTY : formatDecimal(squad.age_structure.average_age, 1)"
          :hint="squad?.age_structure.median_age ? `中位 ${formatDecimal(squad.age_structure.median_age, 1)} 岁` : '需要阵容数据'"
          :loading="squadLoading && !squad"
        />
        <KpiCard
          label="CA 均值"
          :value="lastTrend?.ca_avg === null || lastTrend?.ca_avg === undefined ? EMPTY : formatDecimal(lastTrend.ca_avg, 1)"
          hint="最近一次快照"
          :loading="overviewLoading && !overview"
        />
        <KpiCard
          label="阵容总身价"
          :value="formatMoney(lastTrend?.value_total ?? null)"
          hint="按最近快照汇总，不做汇率换算"
          tone="accent"
          :loading="overviewLoading && !overview"
        />
        <KpiCard
          label="未读提醒"
          :value="overview ? formatInt(overview.alerts) : EMPTY"
          hint="由关注规则生成"
          :tone="(overview?.alerts ?? 0) > 0 ? 'warn' : 'default'"
          :loading="overviewLoading && !overview"
          to="/watchlist"
        />
      </div>

      <!-- 趋势 + 规则摘要 -->
      <div class="sm-grid sm-grid--wide-left">
        <ChartCard
          title="球队实力趋势"
          subtitle="总身价（亿 €）与阵容 CA 均值随时间变化"
          :loading="overviewLoading && !overview"
          :empty="!overviewLoading && (overview?.trend.length ?? 0) === 0"
          empty-title="暂无趋势数据"
          empty-description="后端还没有可聚合的快照序列。导入至少两次扫描后，趋势才会出现。"
          :footnote="trendFootnote"
        >
          <EChart :option="trendOption" height="260px" aria-label="总身价与 CA 均值时间序列" />
        </ChartCard>

        <SectionCard title="AI 体育总监 · 事实摘要" subtitle="规则推导，非 LLM 生成" accent>
          <div v-if="squadLoading && !squad" class="sm-stack">
            <el-skeleton :rows="4" animated />
          </div>
          <EmptyState
            v-else-if="insights.length === 0"
            title="暂无可推导的事实"
            description="需要本队阵容数据与覆盖度信息。先在「阵容智能」中指定本队，或导入更多扫描数据。"
            compact
          />
          <ul v-else class="insights">
            <li v-for="item in insights" :key="item.title" class="insight" :class="`insight--${item.tone}`">
              <span class="insight__dot" aria-hidden="true" />
              <div class="insight__body">
                <p class="insight__title">{{ item.title }}</p>
                <p class="insight__detail">{{ item.detail }}</p>
              </div>
              <router-link v-if="item.to" class="insight__link" :to="item.to" :aria-label="`查看 ${item.title}`">
                →
              </router-link>
            </li>
          </ul>
          <template #footer>
            以上条目由后端字段与固定规则推导，不包含模型生成内容。需要对话式分析请进入
            <router-link to="/agent">AI 体育总监</router-link>。
          </template>
        </SectionCard>
      </div>

      <!-- 结构分析 -->
      <div class="sm-grid sm-grid--wide-left">
        <ChartCard
          title="阵容年龄分布"
          subtitle="实际占比与后端给出的理想占比"
          :loading="squadLoading && !squad"
          :empty="!squadLoading && !squadAvailable"
          empty-title="未指定本队"
          empty-description="在阵容智能中选择「我的俱乐部」后，这里会显示年龄结构。"
          :footnote="squadAvailable ? `平均年龄 ${formatDecimal(squad?.age_structure.average_age, 1)} 岁 · 中位 ${formatDecimal(squad?.age_structure.median_age, 1)} 岁` : ''"
        >
          <template #actions>
            <el-button v-if="!squadAvailable && !squadLoading" size="small" @click="router.push('/squad')">
              去指定本队
            </el-button>
          </template>
          <EChart :option="ageOption" height="232px" aria-label="阵容年龄结构占比" />
        </ChartCard>

        <ChartCard
          title="阵容能力雷达"
          subtitle="六维评分的归一化分值"
          :loading="squadLoading && !squad"
          :empty="!squadLoading && !squadAvailable"
          empty-title="暂无六维评分"
          empty-description="指定本队后，后端会返回覆盖、深度、年龄、契合、薪资与潜力六个维度。"
          :footnote="radarFootnote"
        >
          <EChart :option="squadRadarOption" height="232px" aria-label="阵容六维能力雷达" />
        </ChartCard>
      </div>

      <div class="sm-grid sm-grid--wide-left">
        <ChartCard
          title="位置结构"
          subtitle="各位置现有球员数与模板需求人数"
          :loading="squadLoading && !squad"
          :empty="!squadLoading && !squadAvailable"
          empty-title="暂无位置数据"
          empty-description="数据源没有提供可识别的位置代码，或尚未指定本队。"
        >
          <EChart :option="positionOption" height="248px" aria-label="位置结构条形图" />
        </ChartCard>

        <SectionCard title="球员价值分析" subtitle="按当前存档 market_value 降序前 5 名">
          <el-skeleton v-if="topPlayersLoading && topPlayers.length === 0" :rows="5" animated />
          <ErrorState v-else-if="topPlayersError" :error="topPlayersError" compact @retry="loadAll" />
          <EmptyState
            v-else-if="topPlayers.length === 0"
            title="暂无身价数据"
            description="当前存档没有可用的 market_value，或尚未导入扫描数据。"
            compact
          />
          <ul v-else class="value-list">
            <li v-for="player in topPlayers" :key="player.instance_id" class="value-row">
              <router-link class="value-row__main" :to="`/players/${player.instance_id}`">
                <span class="value-row__name">{{ player.name }}</span>
                <span class="value-row__meta">
                  {{ displayText(player.position) }} · {{ player.age ?? EMPTY }} 岁 · CA {{ player.ca ?? EMPTY }}
                </span>
              </router-link>
              <span class="value-row__amount sm-num">{{ formatMoney(player.market_value) }}</span>
              <span class="value-row__bar" aria-hidden="true">
                <i :style="{ width: `${topValueMax > 0 ? Math.max(6, ((player.market_value ?? 0) / topValueMax) * 100) : 0}%` }" />
              </span>
            </li>
          </ul>
          <template #footer>
            身价单位为记录币种，页面只做 万 / 亿 显示换算，不做汇率转换。
          </template>
        </SectionCard>
      </div>

      <!-- 数据质量 -->
      <div class="sm-grid sm-grid--wide-left">
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
      <ErrorState v-if="squadError && !squad" :error="squadError" compact title="阵容数据加载失败" @retry="loadAll" />

      <!-- 最近活动 + 快捷入口 -->
      <div class="sm-grid sm-grid--wide-left">
        <SectionCard title="最近活动" subtitle="按接收时间倒序的前 6 条导入任务" flush>
          <DataTable
            :columns="importsColumns"
            :rows="imports"
            :loading="importsLoading"
            :error="importsError"
            row-key="id"
            clickable
            :empty-title="imports.length === 0 ? '还没有导入记录' : '暂无数据'"
            empty-description="在「数据中心」中拖入扫描 JSON/NDJSON，或先运行 ScoutMind.LiveReader.exe scan 生成真实数据。"
            @row-click="openImport"
            @retry="loadAll"
          />
        </SectionCard>

        <SectionCard title="快速入口" subtitle="按工作流进入对应模块">
          <div class="quick-links">
            <router-link v-for="link in quickLinks" :key="link.to" :to="link.to" class="quick-link">
              <span class="quick-link__icon"><AppIcon :name="link.icon" :size="16" /></span>
              <span class="quick-link__text">
                <span class="quick-link__title">{{ link.title }}</span>
                <span class="quick-link__desc">{{ link.description }}</span>
              </span>
            </router-link>
          </div>
        </SectionCard>
      </div>

      <SectionCard title="口径说明" dense>
        <ul class="notes">
          <li>所有比率（覆盖度、置信度）来自后端字段；页面不做二次估算，也不补默认值。</li>
          <li>金额单位为记录自带币种，默认 {{ currency }}；页面只做 万/亿 显示换算，不做汇率转换。</li>
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
/* ---------- 指挥条 ---------- */

.command {
  position: relative;
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--sm-space-5);
  padding: var(--sm-space-5);
  overflow: hidden;
  border: 1px solid var(--sm-border-strong);
  border-radius: var(--sm-radius-xl);
  background:
    linear-gradient(120deg, rgba(10, 34, 54, 0.92) 0%, rgba(9, 18, 34, 0.94) 48%, rgba(20, 16, 48, 0.9) 100%),
    var(--sm-surface);
  box-shadow: var(--sm-shadow-2);
}

.command__glow {
  position: absolute;
  top: -120px;
  right: -60px;
  width: 420px;
  height: 320px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(34, 211, 238, 0.22), transparent 68%);
  filter: blur(6px);
  pointer-events: none;
}

/* 细网格 + 渐变遮罩，营造「控制台」平面。 */
.command__grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(122, 162, 220, 0.08) 1px, transparent 1px),
    linear-gradient(90deg, rgba(122, 162, 220, 0.08) 1px, transparent 1px);
  background-size: 44px 44px;
  mask-image: radial-gradient(560px 240px at 78% 12%, #000 0%, transparent 78%);
  -webkit-mask-image: radial-gradient(560px 240px at 78% 12%, #000 0%, transparent 78%);
  pointer-events: none;
}

.command__body {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-2);
  min-width: 0;
}

.command__title {
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-3xl);
  font-weight: var(--sm-fw-semibold);
  letter-spacing: -0.02em;
  line-height: var(--sm-lh-tight);
}

.command__subtitle {
  max-width: 76ch;
  color: var(--sm-text-2);
  font-size: var(--sm-fs-sm);
}

.command__chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sm-space-2);
  margin-top: var(--sm-space-2);
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px var(--sm-space-2);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-pill);
  background: rgba(8, 17, 30, 0.72);
  color: var(--sm-text-2);
  font-size: var(--sm-fs-2xs);
  white-space: nowrap;
}

.chip--accent {
  border-color: rgba(34, 211, 238, 0.34);
  color: var(--sm-text-primary);
}

.chip--accent i {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--sm-accent-cyan);
  box-shadow: 0 0 8px rgba(34, 211, 238, 0.9);
}

.chip--demo {
  border-color: rgba(245, 181, 68, 0.4);
  color: #fcd34d;
}

.command__actions {
  position: relative;
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: var(--sm-space-2);
}

/* ---------- 规则摘要 ---------- */

.insights {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-2);
  padding: 0;
  margin: 0;
  list-style: none;
}

.insight {
  display: flex;
  align-items: flex-start;
  gap: var(--sm-space-2);
  padding: var(--sm-space-2) var(--sm-space-3);
  border: 1px solid var(--sm-border);
  border-left: 2px solid var(--sm-border-strong);
  border-radius: var(--sm-radius-sm);
  background: rgba(12, 23, 39, 0.6);
}

.insight--info {
  border-left-color: var(--sm-accent-blue);
}

.insight--warn {
  border-left-color: var(--sm-status-warning);
}

.insight--danger {
  border-left-color: var(--sm-status-danger);
}

.insight__dot {
  width: 5px;
  height: 5px;
  margin-top: 6px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: var(--sm-accent-blue);
}

.insight--warn .insight__dot {
  background: var(--sm-status-warning);
}

.insight--danger .insight__dot {
  background: var(--sm-status-danger);
}

.insight__body {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.insight__title {
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-sm);
  font-weight: var(--sm-fw-medium);
}

.insight__detail {
  color: var(--sm-text-2);
  font-size: var(--sm-fs-2xs);
  line-height: 1.6;
}

.insight__link {
  margin-left: auto;
  color: var(--sm-text-3);
  font-size: var(--sm-fs-sm);
}

.insight__link:hover {
  color: var(--sm-accent-cyan);
  text-decoration: none;
}

/* ---------- 价值列表 ---------- */

.value-list {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-2);
  padding: 0;
  margin: 0;
  list-style: none;
}

.value-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 2px var(--sm-space-3);
  padding-bottom: var(--sm-space-2);
  border-bottom: 1px solid var(--sm-border);
}

.value-row:last-child {
  padding-bottom: 0;
  border-bottom: 0;
}

.value-row__main {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
  color: inherit;
}

.value-row__main:hover {
  text-decoration: none;
}

.value-row__main:hover .value-row__name {
  color: var(--sm-accent-cyan);
}

.value-row__name {
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-sm);
  font-weight: var(--sm-fw-medium);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.value-row__meta {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}

.value-row__amount {
  color: var(--sm-text);
  font-size: var(--sm-fs-sm);
  font-weight: var(--sm-fw-semibold);
}

.value-row__bar {
  grid-column: 1 / -1;
  height: 3px;
  border-radius: 2px;
  background: rgba(22, 37, 59, 0.9);
  overflow: hidden;
}

.value-row__bar i {
  display: block;
  height: 100%;
  border-radius: 2px;
  background: linear-gradient(90deg, rgba(34, 211, 238, 0.55), rgba(167, 139, 250, 0.75));
}

/* ---------- 覆盖度 / 快捷入口 / 说明 ---------- */

.coverage-list {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-3);
}

.quick-links {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: var(--sm-space-2);
}

.quick-link {
  display: flex;
  align-items: flex-start;
  gap: var(--sm-space-2);
  padding: var(--sm-space-2) var(--sm-space-3);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-md);
  background: rgba(12, 23, 39, 0.55);
  color: inherit;
  transition:
    border-color var(--sm-dur-1) var(--sm-ease-out),
    background-color var(--sm-dur-1) var(--sm-ease-out);
}

.quick-link:hover {
  border-color: rgba(34, 211, 238, 0.4);
  background: rgba(34, 211, 238, 0.08);
  text-decoration: none;
}

.quick-link__icon {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  flex: 0 0 auto;
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-sm);
  color: var(--sm-accent-cyan);
  background: rgba(8, 17, 30, 0.8);
}

.quick-link__text {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.quick-link__title {
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-sm);
  font-weight: var(--sm-fw-medium);
}

.quick-link__desc {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
  line-height: 1.5;
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

@media (max-width: 1180px) {
  .command {
    flex-direction: column;
    align-items: flex-start;
  }

  .command__actions {
    justify-content: flex-start;
  }
}

@media (max-width: 640px) {
  .command {
    padding: var(--sm-space-4);
  }

  .command__title {
    font-size: var(--sm-fs-2xl);
  }

  .command__actions :deep(.el-button) {
    flex: 1 1 auto;
  }
}
</style>
