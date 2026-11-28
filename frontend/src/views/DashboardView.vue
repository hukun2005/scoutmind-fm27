/**
 * 首页：几秒钟内看清球队现状。
 *
 * 页面只回答四个问题：我是谁（存档/俱乐部/连接）、阵容怎么样、哪里有问题、下一步去哪。
 * 图表、覆盖度、导入明细等低频内容收进「更多数据洞察」，能力不删除但默认不占用主视线。
 * 所有数值来自后端接口；缺失显示为 —，无数据时给出明确引导，不使用演示或硬编码数据。
 */

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { asApiError, type ApiError } from '../api/client'
import { getOverview } from '../api/analytics'
import { getDataHubStatus } from '../api/datahub'
import { listImports } from '../api/imports'
import { listPlayers } from '../api/players'
import { getHiddenValue } from '../api/recruitment'
import { getSquadOverview } from '../api/squad'
import { getTransferStats, listTransfers } from '../api/transfers'
import AppIcon from '../components/AppIcon.vue'
import ChartCard from '../components/ChartCard.vue'
import CoverageBar from '../components/CoverageBar.vue'
import DataTable from '../components/DataTable.vue'
import EChart from '../components/EChart.vue'
import EmptyState from '../components/EmptyState.vue'
import ErrorState from '../components/ErrorState.vue'
import KpiCard from '../components/KpiCard.vue'
import SectionCard from '../components/SectionCard.vue'
import type { OverviewResponse } from '../types/analytics'
import type { DataHubStatus } from '../types/datahub'
import type { ImportJob } from '../types/imports'
import type { PlayerSummary } from '../types/players'
import type { HiddenValueResponse } from '../types/recruitment'
import type { SquadOverview } from '../types/squad'
import type { TableColumn } from '../types/table'
import type { Transfer, TransferStatsResponse } from '../types/transfers'
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
  displayText,
  formatDateTime,
  formatDecimal,
  formatInt,
  formatMoney,
  formatPercent,
} from '../utils/format'
import {
  coverageLabel,
  importStatusLabel,
  sourceLabel,
  transferStatusLabel,
  transferTypeLabel,
} from '../utils/labels'

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

const recentTransfers = ref<Transfer[]>([])
const transfersLoading = ref(false)
const transfersError = ref<ApiError | null>(null)

const hub = ref<DataHubStatus | null>(null)

const opportunities = ref<HiddenValueResponse | null>(null)
const oppLoading = ref(false)

/** 俱乐部名称：用于首屏标题，缺省时回退到分析员口吻。 */
const clubName = computed(() => squad.value?.club?.name ?? '分析员')

/** 当前存档的联赛与游戏版本。 */
const leagueLine = computed(() => {
  const league = squad.value?.club?.league
  const version = session.activeSave?.game_version
  const parts = [league, version ? `游戏版本 ${version}` : null].filter(Boolean)
  return parts.length > 0 ? parts.join(' · ') : '联赛与游戏版本未知'
})

/** AI 简报：全部来自当前存档真实字段，界面明确标注为规则生成。 */
const briefing = computed<
  Array<{ key: string; label: string; title: string; detail: string; to?: string; tone: 'info' | 'warn' | 'danger' }>
>(() => {
  const current = squad.value
  const rows: Array<{ key: string; label: string; title: string; detail: string; to?: string; tone: 'info' | 'warn' | 'danger' }> = []
  if (!current) return rows

  const weakestSlot = current.weakness[0]
  rows.push({
    key: 'problem',
    label: '最大问题',
    title: weakestSlot ? `${weakestSlot.slot_name} 人手不足` : '未发现明显短板',
    detail: weakestSlot
      ? `现有 ${weakestSlot.count} 人，模板要求 ${weakestSlot.required} 人。${weakestSlot.suggestion}`
      : '当前阵容每个位置都达到最低人数要求。',
    to: '/squad',
    tone: weakestSlot && weakestSlot.severity >= 2 ? 'danger' : 'warn',
  })

  const top = opportunities.value?.items?.[0]
  rows.push({
    key: 'opportunity',
    label: '引援机会',
    title: top ? top.player.name : '暂无可用引援机会',
    detail: top
      ? `${top.player.club ?? '俱乐部未知'} · ${top.rule_label}。${top.evidence[0] ?? ''}`
      : '需要更多带身价、年龄与合同的扫描数据后，才会生成可追溯的引援机会。',
    to: '/recruitment',
    tone: top ? 'info' : 'warn',
  })

  rows.push({
    key: 'contract',
    label: '合同风险',
    title:
      current.contracts.at_risk_count > 0
        ? `${formatInt(current.contracts.at_risk_count)} 名球员 12 个月内到期`
        : '近期没有合同到期风险',
    detail:
      current.contracts.at_risk_names.slice(0, 4).join('、') ||
      (current.contracts.at_risk_count > 0 ? '到期名单未返回姓名。' : '按当前合同到期日计算。'),
    to: '/squad',
    tone: current.contracts.at_risk_count > 0 ? 'warn' : 'info',
  })

  const watch = current.succession[0]?.player ?? topPlayers.value[0] ?? null
  rows.push({
    key: 'watch',
    label: '值得关注球员',
    title: watch ? watch.name : '暂无可用球员',
    detail: watch
      ? current.succession[0]
        ? current.succession[0].verdict
        : `当前能力 ${watch.ca ?? EMPTY} · 潜力 ${watch.pa ?? EMPTY}`
      : '导入球员数据后，这里会列出最值得跟踪的球员。',
    to: watch ? `/players/${watch.instance_id}` : '/players',
    tone: 'info',
  })

  const next = weakestSlot
    ? `优先补强 ${weakestSlot.slot_name}，并核对合同到期主力。`
    : '继续同步游戏数据，保持阵容与转会样本最新。'
  rows.push({
    key: 'next',
    label: '下一步',
    title: next,
    detail: weakestSlot
      ? '点击右侧进入引援机会，系统会按同一套确定性规则给出候选与理由。'
      : '也可以在 AI 足球总监中提出更具体的问题。',
    to: weakestSlot ? `/recruitment?slot=${encodeURIComponent(weakestSlot.slot)}` : '/director',
    tone: 'info',
  })

  return rows
})

/** 本队是否可分析。 */
const squadAvailable = computed(() => (squad.value?.squad_size ?? 0) > 0)

/** 默认存档是否真的有球员：用于区分「还没导入」与「导入后为空」。 */
const hasPlayers = computed(() => (overview.value?.players ?? 0) > 0 || topPlayers.value.length > 0)

/** 游戏连接状态：优先使用数据中心的真实进程检测，其次退回数据来源。 */
const connection = computed<{ text: string; tone: 'ok' | 'idle' | 'warn' }>(() => {
  const game = hub.value?.game
  if (game) {
    if (game.running) return { text: game.version ? `游戏已连接 · ${game.version}` : '游戏已连接', tone: 'ok' }
    if (game.detected) return { text: '游戏未启动', tone: 'idle' }
    return { text: '未检测到游戏', tone: 'warn' }
  }
  if (session.hasRealScanData) return { text: '已有扫描数据', tone: 'ok' }
  return { text: '尚未导入数据', tone: 'idle' }
})

/** 主要短板。 */
const weakest = computed(() => squad.value?.weakness[0] ?? null)

/** 需要关注的合同。 */
const contracts = computed(() => squad.value?.contracts ?? null)

/** 首页关注点：只使用后端字段，按严重程度排序，最多 4 条。 */
const highlights = computed<Array<{ tone: 'info' | 'warn' | 'danger'; title: string; detail: string; to?: string }>>(() => {
  const list: Array<{ tone: 'info' | 'warn' | 'danger'; title: string; detail: string; to?: string }> = []
  const current = squad.value
  if (!current) return list

  const weakestSlot = current.weakness[0]
  if (weakestSlot) {
    list.push({
      tone: weakestSlot.severity >= 2 ? 'danger' : 'warn',
      title: `阵容短板：${weakestSlot.slot_name}`,
      detail: `现有 ${weakestSlot.count} 人，模板需要 ${weakestSlot.required} 人。${weakestSlot.suggestion}`,
      to: '/squad',
    })
  }

  if (current.contracts.at_risk_count > 0) {
    const names = current.contracts.at_risk_names.slice(0, 3).join('、')
    list.push({
      tone: 'warn',
      title: `${formatInt(current.contracts.at_risk_count)} 名球员合同需要关注`,
      detail: names + (current.contracts.at_risk_names.length > 3 ? ' 等' : ''),
      to: '/squad',
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
      title: `关注名单有 ${formatInt(overview.value?.alerts)} 条提醒`,
      detail: '由关注规则生成，可在关注名单中逐条处理。',
      to: '/watchlist',
    })
  }

  return list.slice(0, 4)
})

/** Top 5 身价最大值，用作条形宽度比例。 */
const topValueMax = computed(() => Math.max(0, ...topPlayers.value.map((row) => row.market_value ?? 0)))

/** 快捷入口：按用户任务组织，而不是按页面模块组织。 */
const quickLinks = [
  { to: '/squad', icon: 'squad' as const, title: '分析阵容', description: '看清强项、短板与补强优先级' },
  { to: '/players', icon: 'players' as const, title: '搜索球员', description: '按位置、年龄与能力筛选目标' },
  { to: '/recruitment', icon: 'scouting' as const, title: '发现引援机会', description: '按确定性规则获得候选与理由' },
  { to: '/compare', icon: 'players' as const, title: '比较球员', description: '2–4 名球员横向比较能力与成本' },
  { to: '/transfer-director', icon: 'transfers' as const, title: '生成转会策略', description: '买入、出售与租借方案与谈判记录' },
  { to: '/director', icon: 'agent' as const, title: '向 AI 足球总监提问', description: '用一句话提出阵容或引援问题' },
]

// ---------- 高级区图表 ----------

const coverageEntries = computed(() => Object.entries(overview.value?.coverage ?? {}))

const feeChartOption = computed(() => buildFeeHistogram(stats.value?.distribution ?? []))
const trendOption = computed(() => buildTrendChart(overview.value?.trend ?? []))
const ageOption = computed(() => buildAgeDistribution(squad.value?.age_structure.buckets ?? []))
const positionOption = computed(() => buildPositionDistribution(squad.value?.depth ?? []))
const squadRadarOption = computed(() => buildSquadRadar(squad.value?.components ?? []))

const lastTrend = computed(() => {
  const points = overview.value?.trend ?? []
  return points.length > 0 ? points[points.length - 1] : null
})

const feeEmpty = computed(() => {
  const value = stats.value
  if (!value) return false
  return value.sample_size === 0 || value.distribution.length === 0
})

const feeFootnote = computed(() => {
  const value = stats.value
  if (!value) return ''
  return `样本 ${formatInt(value.sample_size)} 笔 · 中位数 ${formatMoney(value.median)} · P25 ${formatMoney(value.p25)} · P75 ${formatMoney(value.p75)} · 币种 ${value.currency}`
})

const radarFootnote = computed(() => {
  const components = squad.value?.components ?? []
  if (components.length === 0) return ''
  const missing = components.filter((entry) => entry.value === null).map((entry) => entry.label)
  return missing.length > 0 ? `0–100 为归一化分值；缺失维度：${missing.join('、')}。` : '0–100 为六维归一化分值，权重可在阵容分析中调整。'
})

const trendFootnote = computed(() => {
  const points = overview.value?.trend ?? []
  if (points.length === 0) return ''
  return `共 ${points.length} 个快照点 · 最近 ${points[points.length - 1]?.date ?? EMPTY}`
})

const importsColumns: TableColumn<ImportJob>[] = [
  { prop: 'received_at', label: '接收时间', width: 150, formatter: (row) => formatDateTime(row.received_at) },
  { prop: 'source', label: '来源', width: 110, formatter: (row) => sourceLabel(row.source) },
  { prop: 'status', label: '状态', width: 96, formatter: (row) => importStatusLabel(row.status) },
  { prop: 'player_count', label: '球员', width: 80, align: 'right', formatter: (row) => formatInt(row.player_count) },
  { prop: 'transfer_count', label: '交易', width: 80, align: 'right', formatter: (row) => formatInt(row.transfer_count) },
]

const transferColumns: TableColumn<Transfer>[] = [
  { prop: 'player_name', label: '球员', minWidth: 140, showOverflowTooltip: true },
  { prop: 'from_club', label: '原俱乐部', width: 130, showOverflowTooltip: true, formatter: (row) => displayText(row.from_club) },
  { prop: 'to_club', label: '新俱乐部', width: 130, showOverflowTooltip: true, formatter: (row) => displayText(row.to_club) },
  { prop: 'transfer_type', label: '类型', width: 96, formatter: (row) => transferTypeLabel(row.transfer_type) },
  { prop: 'status', label: '状态', width: 88, formatter: (row) => transferStatusLabel(row.status) },
  { prop: 'transfer_date', label: '日期', width: 100, formatter: (row) => displayText(row.transfer_date) },
  { prop: 'effective_fee', label: '费用', width: 96, align: 'right', formatter: (row) => formatMoney(row.effective_fee) },
]

/** 加载首页需要的全部真实数据。 */
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
  transfersLoading.value = true
  transfersError.value = null

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
        const response = await listImports({ save_id: saveId ?? undefined, limit: 5 })
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
    (async () => {
      try {
        const response = await listTransfers({ save_id: saveId ?? undefined, limit: 5, offset: 0, sort: '-transfer_date' })
        recentTransfers.value = response.items ?? []
      } catch (caught) {
        transfersError.value = asApiError(caught)
        recentTransfers.value = []
      } finally {
        transfersLoading.value = false
      }
    })(),
  ])

  try {
    hub.value = await getDataHubStatus()
  } catch {
    // 数据中心接口不可用时只隐藏连接细节，不影响首页其它内容。
    hub.value = null
  }

  oppLoading.value = true
  opportunities.value = null
  try {
    opportunities.value = await getHiddenValue(squad.value?.weakness[0]?.slot, 3)
  } catch {
    // 引援引擎不可用时，简报会明确说明「暂无可用引援机会」。
    opportunities.value = null
  } finally {
    oppLoading.value = false
  }
}

function go(path: string): void {
  void router.push(path)
}

watch([() => session.activeSaveId, () => session.dataRevision], () => void loadAll(), { immediate: true })
</script>

<template>
  <div class="sm-page dashboard">
    <section class="welcome" aria-label="当前存档">
      <div class="welcome__body">
        <p class="welcome__eyebrow">
          {{ displayText(session.activeSave?.name) }} · {{ displayText(session.activeSave?.game_version) }}
        </p>
        <h1 class="welcome__title">欢迎回来，<span class="welcome__name">{{ clubName }}</span></h1>
        <p class="welcome__subtitle">{{ leagueLine }}</p>
        <div class="welcome__chips">
          <span class="chip" :class="`chip--${connection.tone}`">
            <i aria-hidden="true" />
            {{ connection.text }}
          </span>
          <span class="chip">当前存档 {{ displayText(session.activeSave?.name) }}</span>
          <span class="chip">
            最近导入 {{ formatDateTime(overview?.last_import?.finished_at ?? null) }}
          </span>
        </div>
      </div>
      <div class="welcome__actions">
        <el-button type="primary" @click="go('/data')">同步游戏数据</el-button>
        <el-button :loading="overviewLoading || squadLoading" @click="loadAll">刷新</el-button>
      </div>
    </section>

    <ErrorState
      v-if="overviewError && !overview"
      :error="overviewError"
      title="首页数据加载失败"
      @retry="loadAll"
    />

    <EmptyState
      v-else-if="!overviewLoading && !hasPlayers"
      title="还没有球队数据"
      description="同步 FM27 游戏数据后，这里会显示球队规模、平均年龄、阵容短板和需要注意的合同。"
    >
      <el-button size="small" type="primary" @click="go('/data')">同步游戏数据</el-button>
      <el-button size="small" @click="go('/players')">先看看球员探索</el-button>
    </EmptyState>

    <template v-else>
      <div class="sm-grid sm-grid--kpi">
        <KpiCard
          label="一线队人数"
          :value="squadAvailable ? formatInt(squad?.squad_size) : EMPTY"
          :hint="squadAvailable ? `全库球员 ${formatInt(overview?.players)}` : '未指定本队'"
          :loading="squadLoading && !squad"
          to="/squad"
        />
        <KpiCard
          label="平均年龄"
          :value="formatDecimal(squad?.age_structure.average_age, 1)"
          :hint="squad?.age_structure.median_age ? `中位 ${formatDecimal(squad.age_structure.median_age, 1)} 岁` : '需要阵容数据'"
          :loading="squadLoading && !squad"
        />
        <KpiCard
          label="阵容综合评分"
          :value="formatDecimal(squad?.score ?? null, 1)"
          :hint="squad?.profile?.name ? `模板：${squad.profile.name}` : '需要阵容数据'"
          tone="accent"
          :loading="squadLoading && !squad"
          to="/squad"
        />
        <KpiCard
          label="主要短板"
          :value="weakest ? weakest.slot_name : '无明显短板'"
          :hint="weakest ? `现有 ${weakest.count} / 需要 ${weakest.required}` : '需要阵容数据'"
          :tone="weakest ? 'warn' : 'default'"
          :loading="squadLoading && !squad"
          to="/squad"
        />
        <KpiCard
          label="合同需要关注"
          :value="contracts ? formatInt(contracts.at_risk_count) : EMPTY"
          hint="人名见重点关注"
          :tone="(contracts?.at_risk_count ?? 0) > 0 ? 'warn' : 'default'"
          :loading="squadLoading && !squad"
          to="/squad"
        />
      </div>

      <div class="sm-grid sm-grid--wide-left">
        <SectionCard
          title="AI 总监简报"
          subtitle="基于当前存档真实字段的规则生成结论，不替代游戏内数据"
          accent
        >
          <el-skeleton v-if="(squadLoading && !squad) || (oppLoading && !opportunities)" :rows="5" animated />
          <EmptyState
            v-else-if="!squad"
            title="还没有球队上下文"
            description="指定本队并导入扫描后，这里会给出最大问题、引援机会、合同风险与下一步建议。"
            compact
          >
            <el-button size="small" type="primary" @click="go('/data')">同步游戏数据</el-button>
          </EmptyState>
          <ol v-else class="brief">
            <li v-for="row in briefing" :key="row.key" class="brief__row" :class="`brief__row--${row.tone}`">
              <span class="brief__label">{{ row.label }}</span>
              <div class="brief__body">
                <p class="brief__title">{{ row.title }}</p>
                <p class="brief__detail">{{ row.detail }}</p>
              </div>
              <button
                v-if="row.to"
                type="button"
                class="brief__link"
                :aria-label="`查看${row.label}`"
                @click="go(row.to)"
              >
                查看 →
              </button>
            </li>
          </ol>
          <template #footer>
            简报只使用当前存档可观测字段；缺失字段会说明原因，不会被记为 0，也不会把推测当成游戏真实属性。
          </template>
        </SectionCard>

        <SectionCard title="值得关注的球员" subtitle="按身价排序的前 5 名">
          <el-skeleton v-if="topPlayersLoading && topPlayers.length === 0" :rows="5" animated />
          <ErrorState v-else-if="topPlayersError" :error="topPlayersError" compact @retry="loadAll" />
          <EmptyState
            v-else-if="topPlayers.length === 0"
            title="暂无身价数据"
            description="当前存档没有球员身价，或尚未导入扫描数据。"
            compact
          />
          <ul v-else class="value-list">
            <li v-for="player in topPlayers" :key="player.instance_id" class="value-row">
              <router-link class="value-row__main" :to="`/players/${player.instance_id}`">
                <span class="value-row__name">{{ player.name }}</span>
                <span class="value-row__meta">
                  {{ displayText(player.position) }} · {{ player.age ?? EMPTY }} 岁 · 当前能力 {{ player.ca ?? EMPTY }}
                </span>
              </router-link>
              <span class="value-row__amount sm-num">{{ formatMoney(player.market_value) }}</span>
              <span class="value-row__bar" aria-hidden="true">
                <i :style="{ width: `${topValueMax > 0 ? Math.max(6, ((player.market_value ?? 0) / topValueMax) * 100) : 0}%` }" />
              </span>
            </li>
          </ul>
          <template #footer>
            <button type="button" class="link-btn" @click="go('/players')">查看全部球员 →</button>
          </template>
        </SectionCard>
      </div>

      <SectionCard title="重要提醒" subtitle="需要你处理或了解的事项；不展示没有行动价值的系统日志" dense>
        <EmptyState
          v-if="highlights.length === 0"
          title="暂时没有需要处理的事项"
          description="位置短板、合同风险与关注提醒会在这里集中出现。"
          compact
        />
        <ul v-else class="highlights">
          <li v-for="item in highlights" :key="item.title" class="highlight" :class="`highlight--${item.tone}`">
            <span class="highlight__dot" aria-hidden="true" />
            <div class="highlight__body">
              <p class="highlight__title">{{ item.title }}</p>
              <p class="highlight__detail">{{ item.detail }}</p>
            </div>
            <button v-if="item.to" type="button" class="highlight__link" :aria-label="`查看 ${item.title}`" @click="go(item.to)">
              →
            </button>
          </li>
        </ul>
      </SectionCard>

      <SectionCard title="最近转会动态" subtitle="按转会日期倒序的前 5 条" flush>
        <DataTable
          :columns="transferColumns"
          :rows="recentTransfers"
          :loading="transfersLoading"
          :error="transfersError"
          row-key="id"
          clickable
          empty-title="还没有转会记录"
          empty-description="导入包含转会数据的扫描后，最近交易会显示在这里。"
          @row-click="go('/transfers')"
          @retry="loadAll"
        />
      </SectionCard>

      <SectionCard title="快捷入口" dense>
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

      <details class="sm-details">
        <summary>更多数据洞察（图表、覆盖度与导入记录）</summary>
        <div class="sm-details__body advanced">
          <div class="sm-grid sm-grid--wide-left">
            <ChartCard
              title="球队实力趋势"
              subtitle="总身价与阵容当前能力均值随时间变化"
              :loading="overviewLoading && !overview"
              :empty="!overviewLoading && (overview?.trend.length ?? 0) === 0"
              empty-title="暂无趋势数据"
              empty-description="导入至少两次扫描后，趋势才会出现。"
              :footnote="trendFootnote"
            >
              <EChart :option="trendOption" height="240px" aria-label="总身价与当前能力均值时间序列" />
            </ChartCard>

            <ChartCard
              title="阵容年龄分布"
              subtitle="实际占比与理想占比"
              :loading="squadLoading && !squad"
              :empty="!squadLoading && !squadAvailable"
              empty-title="未指定本队"
              empty-description="在阵容分析中选择本队后，这里会显示年龄结构。"
              :footnote="squadAvailable ? `平均年龄 ${formatDecimal(squad?.age_structure.average_age, 1)} 岁 · 中位 ${formatDecimal(squad?.age_structure.median_age, 1)} 岁` : ''"
            >
              <EChart :option="ageOption" height="220px" aria-label="阵容年龄结构占比" />
            </ChartCard>
          </div>

          <div class="sm-grid sm-grid--wide-left">
            <ChartCard
              title="阵容能力雷达"
              subtitle="六维评分的归一化分值"
              :loading="squadLoading && !squad"
              :empty="!squadLoading && !squadAvailable"
              empty-title="暂无六维评分"
              empty-description="指定本队后，后端会返回覆盖、深度、年龄、契合、薪资与潜力六个维度。"
              :footnote="radarFootnote"
            >
              <EChart :option="squadRadarOption" height="220px" aria-label="阵容六维能力雷达" />
            </ChartCard>

            <ChartCard
              title="位置结构"
              subtitle="各位置现有球员数与模板需求人数"
              :loading="squadLoading && !squad"
              :empty="!squadLoading && !squadAvailable"
              empty-title="暂无位置数据"
              empty-description="数据源没有提供可识别的位置代码，或尚未指定本队。"
            >
              <EChart :option="positionOption" height="230px" aria-label="位置结构条形图" />
            </ChartCard>
          </div>

          <div class="sm-grid sm-grid--wide-left">
            <SectionCard title="数据覆盖度" subtitle="各字段的非空比例">
              <EmptyState
                v-if="coverageEntries.length === 0"
                title="覆盖度未提供"
                description="当前存档尚未导入任何扫描数据。"
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
            </SectionCard>

            <ChartCard
              title="成交费用分布"
              subtitle="已完成交易的费用直方图"
              :loading="statsLoading && !stats"
              :empty="!statsLoading && feeEmpty"
              empty-title="暂无成交样本"
              empty-description="当前窗口内没有可统计的已完成交易。"
              :footnote="feeFootnote"
            >
              <EChart :option="feeChartOption" height="210px" aria-label="成交费用直方图" />
            </ChartCard>
          </div>

          <ErrorState v-if="statsError && !stats" :error="statsError" compact @retry="loadAll" />
          <ErrorState v-if="squadError && !squad" :error="squadError" compact title="阵容数据加载失败" @retry="loadAll" />

          <SectionCard title="最近导入记录" subtitle="按接收时间倒序的前 5 条" flush>
            <DataTable
              :columns="importsColumns"
              :rows="imports"
              :loading="importsLoading"
              :error="importsError"
              row-key="id"
              clickable
              empty-title="还没有导入记录"
              empty-description="在游戏数据中导入扫描文件后，这里会显示导入结果。"
              @row-click="go('/data')"
              @retry="loadAll"
            />
          </SectionCard>

          <SectionCard title="统计口径" dense>
            <ul class="notes">
              <li>所有比率（覆盖度、置信度）来自后端字段，页面不做二次估算。</li>
              <li>金额按记录币种显示，只做 万/亿 换算，不做汇率转换。</li>
              <li>成交统计只包含已完成的交易；未触发的附加条款不计入已支付金额。</li>
              <li>最近一次快照的当前能力均值 {{ formatDecimal(lastTrend?.ca_avg, 1) }}。</li>
              <li>覆盖度合计：{{ formatPercent(stats?.coverage ? (stats.coverage.fee ?? null) : null) }}（费用字段）。</li>
            </ul>
          </SectionCard>
        </div>
      </details>
    </template>
  </div>
</template>

<style scoped>
/* ---------- 欢迎区 ---------- */

.welcome {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--sm-space-5);
  padding: var(--sm-space-5);
  border: 1px solid var(--sm-border-strong);
  border-radius: var(--sm-radius-xl);
  background:
    radial-gradient(520px 220px at 88% -30%, rgba(34, 211, 238, 0.16), transparent 70%),
    linear-gradient(140deg, rgba(12, 30, 48, 0.94), rgba(10, 18, 34, 0.96) 60%);
  box-shadow: var(--sm-shadow-2);
}

.welcome__body {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-2);
  min-width: 0;
}

.welcome__title {
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-2xl);
  font-weight: var(--sm-fw-semibold);
  letter-spacing: -0.02em;
  line-height: var(--sm-lh-tight);
}

.welcome__name {
  background: var(--sm-gradient-text);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}

.welcome__subtitle {
  color: var(--sm-text-2);
  font-size: var(--sm-fs-sm);
}

.welcome__eyebrow {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
  font-weight: var(--sm-fw-semibold);
  letter-spacing: var(--sm-tracking-label);
  text-transform: uppercase;
}

.welcome__chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sm-space-2);
  margin-top: var(--sm-space-1);
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

.chip i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--sm-text-3);
}

.chip--ok {
  border-color: rgba(52, 211, 153, 0.36);
}

.chip--ok i {
  background: var(--sm-success);
}

.chip--warn {
  border-color: rgba(245, 181, 68, 0.4);
}

.chip--warn i {
  background: var(--sm-warn);
}

.welcome__actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: var(--sm-space-2);
}

/* ---------- AI 总监简报 ---------- */

.brief {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-2);
  padding: 0;
  margin: 0;
  list-style: none;
}

.brief__row {
  display: grid;
  grid-template-columns: 76px minmax(0, 1fr) auto;
  align-items: start;
  gap: var(--sm-space-3);
  padding: var(--sm-space-2) var(--sm-space-3);
  border: 1px solid var(--sm-border);
  border-left: 2px solid var(--sm-accent-blue);
  border-radius: var(--sm-radius-sm);
  background: rgba(12, 23, 39, 0.55);
}

.brief__row--warn {
  border-left-color: var(--sm-status-warning);
}

.brief__row--danger {
  border-left-color: var(--sm-status-danger);
}

.brief__label {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
  letter-spacing: var(--sm-tracking-label);
  white-space: nowrap;
}

.brief__body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.brief__title {
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-sm);
  font-weight: var(--sm-fw-medium);
}

.brief__detail {
  color: var(--sm-text-2);
  font-size: var(--sm-fs-2xs);
  line-height: 1.6;
}

.brief__link {
  padding: 0;
  border: 0;
  background: none;
  color: var(--sm-accent-cyan);
  font: inherit;
  font-size: var(--sm-fs-2xs);
  white-space: nowrap;
  cursor: pointer;
}

.brief__link:hover {
  text-decoration: underline;
}

/* ---------- 关注点 ---------- */

.highlights {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-2);
  padding: 0;
  margin: 0;
  list-style: none;
}

.highlight {
  display: flex;
  align-items: flex-start;
  gap: var(--sm-space-2);
  padding: var(--sm-space-2) var(--sm-space-3);
  border: 1px solid var(--sm-border);
  border-left: 2px solid var(--sm-border-strong);
  border-radius: var(--sm-radius-sm);
  background: rgba(12, 23, 39, 0.6);
}

.highlight--info {
  border-left-color: var(--sm-accent-blue);
}

.highlight--warn {
  border-left-color: var(--sm-status-warning);
}

.highlight--danger {
  border-left-color: var(--sm-status-danger);
}

.highlight__dot {
  width: 5px;
  height: 5px;
  margin-top: 6px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: var(--sm-accent-blue);
}

.highlight--warn .highlight__dot {
  background: var(--sm-status-warning);
}

.highlight--danger .highlight__dot {
  background: var(--sm-status-danger);
}

.highlight__body {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.highlight__title {
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-sm);
  font-weight: var(--sm-fw-medium);
}

.highlight__detail {
  color: var(--sm-text-2);
  font-size: var(--sm-fs-2xs);
  line-height: 1.6;
}

.highlight__link {
  margin-left: auto;
  padding: 0 4px;
  border: 0;
  background: none;
  color: var(--sm-text-3);
  font-size: var(--sm-fs-sm);
  cursor: pointer;
}

.highlight__link:hover {
  color: var(--sm-accent-cyan);
}

/* ---------- 身价列表 ---------- */

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

.link-btn {
  padding: 0;
  border: 0;
  background: none;
  color: var(--sm-accent-cyan);
  font: inherit;
  cursor: pointer;
}

.link-btn:hover {
  text-decoration: underline;
}

/* ---------- 快捷入口 / 高级区 ---------- */

.quick-links {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
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

.advanced {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-4);
  padding-top: var(--sm-space-3);
}

.coverage-list {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-3);
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

@media (max-width: 1180px) {
  .welcome {
    flex-direction: column;
    align-items: flex-start;
  }

  .welcome__actions {
    justify-content: flex-start;
  }
}

@media (max-width: 640px) {
  .welcome {
    padding: var(--sm-space-4);
  }

  .welcome__title {
    font-size: var(--sm-fs-xl);
  }

  .welcome__actions :deep(.el-button) {
    flex: 1 1 auto;
  }
}
</style>
