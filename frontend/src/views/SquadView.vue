/**
 * 阵容智能：六维阵容评分、位置深度、年龄与工资结构、合同预警、短板排序与接班规划。
 */

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { asApiError, type ApiError } from '../api/client'
import { getSquadOverview, listSquadProfiles } from '../api/squad'
import ChartCard from '../components/ChartCard.vue'
import DataTable from '../components/DataTable.vue'
import EChart from '../components/EChart.vue'
import EmptyState from '../components/EmptyState.vue'
import ErrorState from '../components/ErrorState.vue'
import LoadingBlock from '../components/LoadingBlock.vue'
import PageHeader from '../components/PageHeader.vue'
import SectionCard from '../components/SectionCard.vue'
import StatHeader from '../components/StatHeader.vue'
import { useSessionStore } from '../stores/session'
import type {
  ContractEntry,
  DepthRow,
  SquadComponent,
  SquadMember,
  SquadOverview,
  SquadProfile,
  SuccessionRow,
  WeaknessRow,
} from '../types/squad'
import type { TableColumn } from '../types/table'
import { buildAgeDistribution, buildSquadRadar } from '../utils/chart'
import { EMPTY, displayText, formatDecimal, formatInt, formatMoney, formatPercent } from '../utils/format'
import { positionLabel } from '../utils/labels'
import { getUserClub, searchClubs, setUserClub } from '../api/clubResolution'
import type { ClubOption, SquadComposition } from '../types/clubResolution'

const session = useSessionStore()

const overview = ref<SquadOverview | null>(null)
const profiles = ref<SquadProfile[]>([])
const selectedProfile = ref('')
const loading = ref(false)
const error = ref<ApiError | null>(null)
const weightDraft = ref<Record<string, number>>({})

// -- 主执教俱乐部 ---------------------------------------------------------------------------------------------

const clubSearching = ref(false)
const clubOptions = ref<ClubOption[]>([])
const selectingClub = ref(false)
const userClub = ref<{ id: number; name: string; league: string | null; nation: string | null } | null>(null)
const userClubMeta = ref<{
  source_label: string | null
  confidence: number | null
  assignment_source: string | null
}>({ source_label: null, confidence: null, assignment_source: null })

/** 阵容构成：来自阵容 CSV 的归属，缺数据时明确说"未导入"而不是把所有人当一线队。 */
const composition = computed<SquadComposition | null>(() => overview.value?.composition ?? null)

/** Search clubs for the picker; empty query returns the first page. */
async function searchClubOptions(query: string): Promise<void> {
  if (!session.activeSaveId) return
  clubSearching.value = true
  try {
    const result = await searchClubs(query || undefined, 30)
    clubOptions.value = result.items
  } catch {
    clubOptions.value = []
  } finally {
    clubSearching.value = false
  }
}

/** Point the save at the chosen club; players are not moved. */
async function applyUserClub(clubId: number): Promise<void> {
  if (!session.activeSaveId) return
  selectingClub.value = true
  try {
    await setUserClub(session.activeSaveId, clubId)
    ElMessage.success('已设为我的俱乐部；球员所属俱乐部不会被修改')
    await loadUserClub()
    await load()
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '设置失败')
  } finally {
    selectingClub.value = false
  }
}

/** Load the current managed club and its provenance. */
async function loadUserClub(): Promise<void> {
  if (!session.activeSaveId) return
  try {
    const result = await getUserClub(session.activeSaveId)
    userClub.value = result.club
    userClubMeta.value = {
      source_label: result.source_label,
      confidence: result.confidence,
      assignment_source: result.assignment_source ?? null,
    }
  } catch {
    userClub.value = null
  }
}

/** 没有本队时，各区块的空状态要说明真正原因，而不是把缺席归咎于字段。 */
const noClubReason = computed<string | null>(() =>
  overview.value && !overview.value.club ? '该存档没有标记为「我的俱乐部」的球队，无法计算该区块' : null,
)
const depthEmpty = computed(() => noClubReason.value ?? '数据源没有提供可识别的位置代码')
const wageEmpty = computed(() => noClubReason.value ?? '数据源未提供工资字段')
const successionEmpty = computed(() => noClubReason.value ?? '队内没有 29 岁以上且带 CA 的球员')

/** Component order used everywhere on the page. */
const COMPONENT_ORDER = ['coverage', 'depth', 'age', 'fit', 'wage', 'potential'] as const

const components = computed<SquadComponent[]>(() => {
  const list = overview.value?.components ?? []
  return [...list].sort(
    (a, b) => COMPONENT_ORDER.indexOf(a.key as (typeof COMPONENT_ORDER)[number]) -
      COMPONENT_ORDER.indexOf(b.key as (typeof COMPONENT_ORDER)[number]),
  )
})

const profileOptions = computed(() =>
  profiles.value.map((profile) => ({ value: profile.key, label: profile.name })),
)

/** 仪表环角度：仅把 0–100 评分映射成 CSS 百分比，不改变分值含义。 */
const scorePercent = computed(() => {
  const score = overview.value?.score
  if (score === null || score === undefined || !Number.isFinite(score)) return 0
  return Math.max(0, Math.min(100, score))
})

/** 至少三个维度有数值时，雷达图才有可读形状。 */
const radarReady = computed(() => components.value.filter((component) => component.value !== null).length >= 3)

const radarOption = computed(() => buildSquadRadar(components.value.map(({ label, value }) => ({ label, value }))))

const radarFootnote = computed(() => {
  const base = '0–100 为加权前的归一化分值；缺失维度不计为 0。'
  const missing = components.value.filter((component) => component.value === null).map((component) => component.label)
  return missing.length > 0 ? `${base}缺失：${missing.join('、')}。` : base
})

const ageBuckets = computed(() => overview.value?.age_structure.buckets ?? [])

const ageOption = computed(() => buildAgeDistribution(ageBuckets.value))

const ageStats = computed(() => [
  { label: '平均年龄', value: formatDecimal(overview.value?.age_structure.average_age ?? null, 1) },
  { label: '中位年龄', value: formatDecimal(overview.value?.age_structure.median_age ?? null, 1) },
  { label: '区间数', value: String(ageBuckets.value.length) },
])

const wageStats = computed(() => [
  { label: '工资总额', value: formatMoney(overview.value?.wage_structure.total ?? null) },
  { label: '中位数', value: formatMoney(overview.value?.wage_structure.median ?? null) },
  { label: '前 3 名占比', value: formatPercent(overview.value?.wage_structure.top3_share ?? null, 0) },
])

/** 维度条宽度：0–100 直接作为百分比。 */
function dimWidth(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return '0%'
  return `${Math.max(0, Math.min(100, value))}%`
}

/** Depth table without the synthetic "unknown position" row. */
const depthRows = computed<DepthRow[]>(() => (overview.value?.depth ?? []).filter((row) => row.slot !== 'UNKNOWN'))

/** Weight inputs bound to the active profile; the user can override any component before re-scoring. */
const weightTotal = computed(() => Object.values(weightDraft.value).reduce((sum, value) => sum + (value || 0), 0))

/** Contract buckets in expiry order, with their Chinese labels. */
const contractBuckets = computed(() => {
  const buckets = overview.value?.contracts?.buckets ?? {}
  const labels: Record<string, string> = {
    expired: '已过期',
    '6m': '6 个月内',
    '12m': '12 个月内',
    '24m': '24 个月内',
    later: '更晚',
    unknown: '无到期日',
  }
  return Object.keys(labels)
    .map((key) => ({ key, label: labels[key] ?? key, entries: buckets[key] ?? [] }))
    .filter((bucket) => bucket.entries.length > 0)
})

const depthColumns: TableColumn<DepthRow>[] = [
  { prop: 'slot_name', label: '位置', width: 96 },
  { prop: 'count', label: '人数', width: 64, align: 'right' },
  { prop: 'required', label: '要求', width: 64, align: 'right' },
  { prop: 'status', label: '状态', width: 76, align: 'center' },
  { prop: 'coverage', label: '覆盖', width: 84, align: 'right', formatter: (row) => formatPercent(row.coverage, 0) },
  { prop: 'depth_quality', label: '替补质量', width: 96, align: 'right', formatter: (row) => formatPercent(row.depth_quality, 0) },
  { prop: 'suggestion', label: '建议', minWidth: 220 },
]

const weaknessColumns: TableColumn<WeaknessRow>[] = [
  { prop: 'slot_name', label: '位置', width: 96 },
  { prop: 'severity', label: '缺口评分', width: 96, align: 'right', formatter: (row) => formatDecimal(row.severity, 1) },
  { prop: 'count', label: '人数/要求', width: 104, align: 'right', formatter: (row) => `${row.count}/${row.required}` },
  { prop: 'suggestion', label: '建议', minWidth: 240 },
  { prop: 'evidence', label: '依据', minWidth: 280, formatter: (row) => row.evidence.join('；') },
]

const memberColumns: TableColumn<SquadMember>[] = [
  { prop: 'name', label: '球员', minWidth: 150 },
  { prop: 'position', label: '位置', width: 96, formatter: (row) => positionLabel(row.position) },
  { prop: 'age', label: '年龄', width: 64, align: 'right' },
  { prop: 'ca', label: 'CA', width: 60, align: 'right' },
  { prop: 'pa', label: 'PA', width: 60, align: 'right' },
  { prop: 'fit_score', label: '角色评分', width: 92, align: 'right' },
  { prop: 'market_value', label: '身价', width: 110, align: 'right', formatter: (row) => formatMoney(row.market_value) },
  { prop: 'contract_end', label: '合同到期', width: 108 },
]

const successionColumns: TableColumn<SuccessionRow>[] = [
  { prop: 'player', label: '主力', minWidth: 150, formatter: (row) => row.player.name },
  { prop: 'age', label: '年龄', width: 64, align: 'right', formatter: (row) => displayText(row.player.age) },
  { prop: 'ca', label: 'CA', width: 60, align: 'right', formatter: (row) => displayText(row.player.ca) },
  { prop: 'verdict', label: '判断', width: 140 },
  {
    prop: 'ready',
    label: '内部接班',
    minWidth: 180,
    formatter: (row) => (row.ready_now.length > 0 ? row.ready_now.map((item) => item.name).join('、') : EMPTY),
  },
  {
    prop: 'external',
    label: '外部画像',
    minWidth: 220,
    formatter: (row) => {
      const profile = row.external_profile
      if (!profile.slot) return EMPTY
      return `${profile.slot_name ?? profile.slot} · ≤${profile.age_max} 岁 · CA ≥ ${profile.ca_floor}`
    },
  },
]

/** Load the overview for the active save and profile. */
async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const result = await getSquadOverview({
      save_id: session.activeSaveId ?? undefined,
      profile: selectedProfile.value || undefined,
    })
    overview.value = result
    weightDraft.value = { ...result.profile.weights }
  } catch (caught) {
    error.value = asApiError(caught)
    overview.value = null
  } finally {
    loading.value = false
  }
}

/** Load the weight profiles once so the selector has labels. */
async function loadProfiles(): Promise<void> {
  try {
    const result = await listSquadProfiles()
    profiles.value = result.items ?? []
    if (!selectedProfile.value && profiles.value.length > 0) {
      selectedProfile.value = profiles.value.find((item) => item.is_default)?.key ?? profiles.value[0]?.key ?? ''
    }
  } catch {
    profiles.value = []
  }
}

/** Re-score the squad with the edited weights. */
async function applyWeights(): Promise<void> {
  if (weightTotal.value <= 0) {
    ElMessage.warning('权重之和必须大于 0')
    return
  }
  loading.value = true
  error.value = null
  try {
    const result = await getSquadOverview({
      save_id: session.activeSaveId ?? undefined,
      ...weightDraft.value,
    })
    overview.value = result
    ElMessage.success('已按自定义权重重算阵容评分')
  } catch (caught) {
    error.value = asApiError(caught)
  } finally {
    loading.value = false
  }
}

/** Restore the profile weights after a manual override. */
function resetWeights(): void {
  if (!overview.value) return
  weightDraft.value = { ...overview.value.profile.weights }
  void load()
}

/** Tone of one component card: unavailable and poor components are called out. */
function componentTone(component: SquadComponent): 'default' | 'accent' | 'warn' | 'danger' {
  if (component.value === null) return 'warn'
  if (component.value < 45) return 'danger'
  if (component.value < 65) return 'warn'
  return 'accent'
}

/** Contract entry rows reused by the contract bucket tables. */
/** Human labels for the composition buckets. */
function compositionLabel(key: string): string {
  const labels: Record<string, string> = {
    senior: '一线队',
    reserve: '预备队',
    youth: '青年队',
    loaned_out: '外租',
    loaned_in: '租入',
    unknown: '未知',
  }
  return labels[key] ?? key
}

function contractRows(entries: ContractEntry[]): ContractEntry[] {
  return [...entries].sort((a, b) => (a.contract_end ?? '9999').localeCompare(b.contract_end ?? '9999'))
}

watch(() => session.activeSaveId, () => void load())

onMounted(async () => {
  await loadProfiles()
  await loadUserClub()
  await searchClubOptions('')
  await load()
})
</script>

<template>
  <div class="sm-page">
    <PageHeader
      title="阵容分析"
      description="看清球队哪里强、哪里弱：位置覆盖、深度、年龄、战术适配、工资结构与潜力储备。缺少数据时明确标注，不会记零。"
    >
      <template #actions>
        <el-select v-model="selectedProfile" size="small" class="squad__profile" aria-label="权重模板" @change="load">
          <el-option v-for="item in profileOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
        <el-button size="small" :loading="loading" @click="load">刷新</el-button>
      </template>
    </PageHeader>

    <ErrorState v-if="error" :error="error" title="阵容数据加载失败" @retry="load" />
    <LoadingBlock v-else-if="loading && !overview" :rows="4" />

    <template v-else-if="overview">
      <section class="squad-hero" aria-label="阵容指挥条">
        <div class="squad-hero__glow" aria-hidden="true" />
        <div class="squad-hero__grid" aria-hidden="true" />

        <div class="squad-hero__identity">
          <span class="sm-section-label">本队概览</span>
          <h2 class="squad-hero__club">{{ overview.club ? overview.club.name : '未指定本队' }}</h2>
          <p class="squad-hero__meta">
            {{ overview.club
              ? `${overview.club.league ?? '联赛未知'} · ${overview.club.nation ?? '国家未知'}`
              : '数据源没有标记「我的俱乐部」，阵容评分无法覆盖本队' }}
          </p>
          <div class="squad-hero__chips">
            <span class="hero-chip">阵容人数 <strong>{{ formatInt(overview.squad_size) }}</strong></span>
            <span class="hero-chip">
              平均年龄
              <strong>{{ overview.age_structure.average_age === null ? EMPTY : formatDecimal(overview.age_structure.average_age, 1) }}</strong>
            </span>
            <span class="hero-chip" :class="{ 'hero-chip--warn': overview.contracts.at_risk_count > 0 }">
              12 个月内到期 <strong>{{ formatInt(overview.contracts.at_risk_count) }}</strong>
            </span>
          </div>
          <p class="squad-hero__hint">
            {{ overview.contracts.at_risk_names.slice(0, 3).join('、') || '没有即将到期的主力' }}
          </p>
        </div>

        <div class="squad-hero__gauge">
          <div
            class="gauge"
            :class="{ 'gauge--muted': overview.score === null }"
            :style="{ '--score': scorePercent }"
            role="img"
            :aria-label="overview.score === null
              ? '六维综合评分不可计算'
              : `六维综合评分 ${formatDecimal(overview.score, 1)} 分，满分 100`"
          >
            <span class="gauge__value sm-num">{{ overview.score === null ? EMPTY : formatDecimal(overview.score, 1) }}</span>
            <span class="gauge__label">六维综合评分</span>
          </div>
          <p class="gauge__hint">
            模板：{{ overview.profile.name }}{{ overview.profile.overridden ? '（自定义权重）' : '' }}
          </p>
        </div>

        <ul class="squad-hero__dims" aria-label="六维评分明细">
          <li v-for="component in components" :key="component.key" class="hero-dim">
            <div class="hero-dim__head">
              <span class="hero-dim__label">{{ component.label }}</span>
              <span class="hero-dim__value" :class="`hero-dim__value--${componentTone(component)}`">
                {{ component.value === null ? '缺失' : formatDecimal(component.value, 1) }}
              </span>
            </div>
            <div class="hero-dim__track" aria-hidden="true">
              <i :style="{ width: dimWidth(component.value) }" />
            </div>
            <span v-if="component.value === null" class="hero-dim__missing">
              缺失：{{ component.missing.join('；') || '数据源未提供' }}
            </span>
          </li>
        </ul>
      </section>

      <div class="sm-grid sm-grid--2">
        <ChartCard
          title="六维雷达"
          subtitle="至少三个维度有数值时绘制，缺失维度不按 0 计入"
          :empty="!radarReady"
          empty-title="六维数据不足"
          empty-description="后端返回的有效维度少于 3 个，无法画出可读的雷达形状；补齐覆盖、深度、年龄、适配、工资或潜力数据后会重新绘制。"
          :footnote="radarFootnote"
        >
          <EChart :option="radarOption" height="260px" aria-label="阵容六维评分雷达图" />
        </ChartCard>

        <ChartCard
          title="年龄分布"
          subtitle="实际占比与后端给出的理想占比"
          :empty="ageBuckets.length === 0"
          empty-title="没有年龄区间"
          empty-description="后端未返回 age_structure.buckets，无法绘制年龄分布；下方年龄结构区块仍会列出可用字段。"
          :footnote="`共 ${ageBuckets.length} 个区间 · 平均 ${formatDecimal(overview.age_structure.average_age ?? null, 1)} 岁 · 中位 ${formatDecimal(overview.age_structure.median_age ?? null, 1)} 岁`"
        >
          <EChart :option="ageOption" height="260px" aria-label="阵容年龄分布与理想占比" />
        </ChartCard>
      </div>

      <div class="sm-grid sm-grid--wide-left">
        <SectionCard title="主执教俱乐部" subtitle="阵容分析以它作为「本队」；手动指定不会改变任何球员的所属俱乐部">
          <div class="club">
            <div class="club__current">
              <span class="sm-label">当前本队</span>
              <div class="club__name">
                {{ userClub ? userClub.name : '尚未指定' }}
                <el-tag v-if="userClubMeta.source_label" size="small" type="info" effect="plain">
                  来源：{{ userClubMeta.source_label }}
                </el-tag>
                <el-tag
                  v-if="userClubMeta.confidence !== null"
                  size="small"
                  :type="userClubMeta.confidence >= 0.9 ? 'success' : 'warning'"
                  effect="plain"
                >
                  记录可信度 {{ formatDecimal(userClubMeta.confidence, 1) }}
                </el-tag>
                <el-tag v-if="userClubMeta.assignment_source" size="small" effect="plain">
                  {{ userClubMeta.assignment_source === 'manual' ? '你手动指定' : '报文声明' }}
                </el-tag>
              </div>
              <p class="club__hint">
                {{ userClub
                  ? `${userClub.league ?? '联赛未知'} · ${userClub.nation ?? '国家未知'}`
                  : '数据源没有提供主执教俱乐部，需要你手动选择；在此之前阵容分析无法进行' }}
              </p>
            </div>
            <label class="club__field">
              <span class="sm-label">搜索并切换</span>
              <el-select
                filterable
                remote
                clearable
                :remote-method="searchClubOptions"
                :loading="clubSearching"
                placeholder="搜索俱乐部名称"
                size="small"
                aria-label="主执教俱乐部"
                @change="(value: number) => value && applyUserClub(value)"
              >
                <el-option
                  v-for="item in clubOptions"
                  :key="item.id"
                  :value="item.id"
                  :label="`${item.name}（${item.players} 人）`"
                >
                  <span>{{ item.name }}</span>
                  <span class="club__option">
                    {{ item.players }} 人 · {{ item.source_label ?? '来源未知' }}
                    <template v-if="item.confidence !== null"> · 可信度 {{ formatDecimal(item.confidence, 1) }}</template>
                  </span>
                </el-option>
              </el-select>
            </label>
            <el-button size="small" :loading="selectingClub" @click="searchClubOptions('')">刷新列表</el-button>
          </div>
        </SectionCard>

        <SectionCard title="阵容构成" subtitle="一线队 / 预备队 / 青年队 / 外租 / 租入；没有名单依据的球员标为未知，不当成自由球员">
          <template v-if="composition && composition.available">
            <div class="composition">
              <div v-for="(count, key) in composition.counts" :key="key" class="composition__item">
                <span class="composition__count">{{ count }}</span>
                <span class="composition__label">{{ compositionLabel(String(key)) }}</span>
              </div>
            </div>
            <ul v-if="composition.gaps && composition.gaps.length" class="composition__gaps">
              <li v-for="gap in composition.gaps" :key="gap">{{ gap }}</li>
            </ul>
          </template>
          <EmptyState
            v-else
            title="没有阵容名单"
            :description="
              (composition?.missing ?? []).join('；') ||
              '数据源不提供一线队/预备队/青年队与租借状态，请到数据中心导入阵容 CSV'
            "
          />
        </SectionCard>
      </div>

      <SectionCard title="六个维度" subtitle="权重可在下方调整后重算；缺数据的维度会重新分配权重">
        <div class="dims">
          <article v-for="component in components" :key="component.key" class="dim-card">
            <header class="dim-card__head">
              <span class="dim-card__label">{{ component.label }}</span>
              <span class="dim-card__score" :class="`dim-card__score--${componentTone(component)}`">
                {{ component.value === null ? '不可计算' : formatDecimal(component.value, 1) }}
              </span>
            </header>
            <div class="dim-card__weight">权重 {{ formatPercent(component.weight, 0) }}</div>
            <div class="dim-card__track" aria-hidden="true">
              <i :style="{ width: dimWidth(component.value) }" />
            </div>
            <ul class="dim-card__evidence">
              <li v-for="line in component.evidence" :key="line">{{ line }}</li>
            </ul>
            <ul v-if="component.missing.length > 0" class="dim-card__missing">
              <li v-for="line in component.missing" :key="line">{{ line }}</li>
            </ul>
          </article>
        </div>

        <div class="weights sm-glass">
          <div class="weights__head">
            <span class="sm-label">自定义权重</span>
            <span class="weights__total">合计 {{ formatDecimal(weightTotal, 2) }}</span>
          </div>
          <div class="weights__fields">
            <label v-for="component in components" :key="component.key" class="weights__field">
              <span>{{ component.label.split('（')[0] }}</span>
              <el-input-number
                v-model="weightDraft[component.key]"
                :min="0"
                :max="1"
                :step="0.05"
                :precision="2"
                size="small"
                controls-position="right"
                :aria-label="`${component.label.split('（')[0]} 权重`"
              />
            </label>
          </div>
          <div class="weights__actions">
            <el-button size="small" type="primary" :loading="loading" @click="applyWeights">按此权重重算</el-button>
            <el-button size="small" @click="resetWeights">恢复模板</el-button>
          </div>
        </div>

        <el-alert
          v-if="overview.data_gaps && overview.data_gaps.length > 0"
          class="dims__gaps"
          type="warning"
          :closable="false"
          show-icon
          title="数据缺口"
        >
          <ul class="dim-card__evidence">
            <li v-for="gap in overview.data_gaps" :key="gap">{{ gap }}</li>
          </ul>
        </el-alert>
      </SectionCard>

      <SectionCard title="位置深度" subtitle="人数、替补质量与建议；位置映射把翼卫并入边后卫">
        <DataTable
          :columns="depthColumns"
          :rows="depthRows"
          row-key="slot"
          expandable
          empty-title="没有位置数据"
          :empty-description="depthEmpty"
        >
          <template #expand="{ row }">
            <DataTable :columns="memberColumns" :rows="row.players" row-key="instance_id" dense :show-pagination="false" />
          </template>
        </DataTable>
      </SectionCard>

      <div class="sm-grid sm-grid--2">
        <SectionCard title="阵容短板" subtitle="按缺口严重程度排序，可追溯到人数与替补质量">
          <DataTable
            :columns="weaknessColumns"
            :rows="overview.weakness"
            row-key="slot"
            empty-title="没有短板数据"
          />
        </SectionCard>

        <SectionCard title="年龄结构" subtitle="与基线分布对比，偏差越大扣分越多">
          <StatHeader :items="ageStats" />
          <div v-if="ageBuckets.length > 0" class="age-list">
            <div v-for="bucket in ageBuckets" :key="bucket.bucket" class="age-row">
              <span class="age-row__label">{{ bucket.bucket }}</span>
              <div class="age-row__track">
                <div class="age-row__bar" :style="{ width: `${Math.min(100, bucket.share * 100)}%` }" />
                <div class="age-row__ideal" :style="{ left: `${Math.min(100, bucket.ideal_share * 100)}%` }" />
              </div>
              <span class="age-row__value">{{ bucket.count }} 人 · {{ formatPercent(bucket.share, 0) }}</span>
            </div>
          </div>
          <p v-else class="sm-text-2xs sm-text-faint">后端未返回年龄区间。</p>
          <template #footer>竖线为基线占比；平均年龄 {{ formatDecimal(overview.age_structure.average_age ?? null, 1) }}，中位 {{ formatDecimal(overview.age_structure.median_age ?? null, 1) }}</template>
        </SectionCard>
      </div>

      <div class="sm-grid sm-grid--2">
        <SectionCard title="工资结构" subtitle="集中度与低产出高薪球员共同决定工分">
          <div class="wage">
            <StatHeader :items="wageStats" />
            <DataTable
              :columns="[
                { prop: 'name', label: '球员', minWidth: 140 },
                { prop: 'wage', label: '工资', width: 110, align: 'right', formatter: (row) => formatMoney(row.wage) },
                { prop: 'minutes_played', label: '出场分钟', width: 96, align: 'right' },
                { prop: 'age', label: '年龄', width: 64, align: 'right' },
              ]"
              :rows="overview.wage_structure.top_earners"
              row-key="instance_id"
              dense
              :show-pagination="false"
              empty-title="没有工资数据"
              :empty-description="wageEmpty"
            />
          </div>
        </SectionCard>

        <SectionCard title="合同预警" subtitle="按到期时间分桶，尽早处理即将自由身的主力">
          <el-collapse v-if="contractBuckets.length > 0" class="contracts">
            <el-collapse-item
              v-for="bucket in contractBuckets"
              :key="bucket.key"
              :title="`${bucket.label}（${bucket.entries.length}）`"
              :name="bucket.key"
            >
              <DataTable
                :columns="[
                  { prop: 'name', label: '球员', minWidth: 140 },
                  { prop: 'contract_end', label: '到期日', width: 108 },
                  { prop: 'age', label: '年龄', width: 64, align: 'right' },
                  { prop: 'ca', label: 'CA', width: 60, align: 'right' },
                  { prop: 'market_value', label: '身价', width: 110, align: 'right', formatter: (row) => formatMoney(row.market_value) },
                ]"
                :rows="contractRows(bucket.entries)"
                row-key="instance_id"
                dense
                :show-pagination="false"
              />
            </el-collapse-item>
          </el-collapse>
          <p v-else class="sm-text-2xs sm-text-faint">没有合同到期数据。</p>
        </SectionCard>
      </div>

      <SectionCard title="接班规划" subtitle="每个 29 岁以上的主力都给出内部接班人与外部搜索画像">
        <DataTable
          :columns="successionColumns"
          :rows="overview.succession"
          :row-key="(row) => String(row.player.instance_id)"
          empty-title="没有需要规划接班的球员"
          :empty-description="successionEmpty"
        />
      </SectionCard>
    </template>
  </div>
</template>

<style scoped>
.squad__profile {
  width: 168px;
}

/* ---------- 阵容指挥条 ---------- */

.squad-hero {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) auto minmax(230px, 0.85fr);
  align-items: center;
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

.squad-hero__glow {
  position: absolute;
  top: -120px;
  right: -40px;
  width: 380px;
  height: 300px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(34, 211, 238, 0.2), transparent 70%);
  filter: blur(4px);
  pointer-events: none;
}

.squad-hero__grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(122, 162, 220, 0.07) 1px, transparent 1px),
    linear-gradient(90deg, rgba(122, 162, 220, 0.07) 1px, transparent 1px);
  background-size: 44px 44px;
  mask-image: radial-gradient(520px 220px at 82% 10%, #000 0%, transparent 76%);
  -webkit-mask-image: radial-gradient(520px 220px at 82% 10%, #000 0%, transparent 76%);
  pointer-events: none;
}

.squad-hero__identity {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-2);
  min-width: 0;
}

.squad-hero__club {
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-2xl);
  font-weight: var(--sm-fw-semibold);
  letter-spacing: -0.015em;
  line-height: var(--sm-lh-tight);
  overflow-wrap: anywhere;
}

.squad-hero__meta {
  color: var(--sm-text-2);
  font-size: var(--sm-fs-sm);
}

.squad-hero__chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sm-space-2);
  margin-top: var(--sm-space-1);
}

.hero-chip {
  display: inline-flex;
  align-items: baseline;
  gap: 6px;
  padding: 3px var(--sm-space-2);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-pill);
  background: rgba(8, 17, 30, 0.72);
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
  white-space: nowrap;
}

.hero-chip strong {
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-sm);
  font-weight: var(--sm-fw-semibold);
  font-variant-numeric: tabular-nums;
}

.hero-chip--warn {
  border-color: rgba(245, 181, 68, 0.4);
}

.hero-chip--warn strong {
  color: var(--sm-status-warning);
}

.squad-hero__hint {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
  overflow-wrap: anywhere;
}

.squad-hero__gauge {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--sm-space-2);
}

.gauge {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  width: 152px;
  height: 152px;
  border-radius: 50%;
}

.gauge::before {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: 50%;
  background: conic-gradient(
    from -90deg,
    #22d3ee 0deg,
    #4d8dff calc(var(--score) * 1.8deg),
    #a78bfa calc(var(--score) * 3.6deg),
    rgba(122, 162, 220, 0.14) calc(var(--score) * 3.6deg) 360deg
  );
  -webkit-mask: radial-gradient(farthest-side, transparent calc(100% - 12px), #000 calc(100% - 11px));
  mask: radial-gradient(farthest-side, transparent calc(100% - 12px), #000 calc(100% - 11px));
}

.gauge--muted::before {
  background: rgba(122, 162, 220, 0.18);
}

.gauge__value {
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-3xl);
  font-weight: var(--sm-fw-semibold);
  letter-spacing: -0.02em;
  line-height: 1;
}

.gauge--muted .gauge__value {
  color: var(--sm-text-3);
}

.gauge__label {
  margin-top: var(--sm-space-1);
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
  letter-spacing: var(--sm-tracking-label);
}

.gauge__hint {
  max-width: 200px;
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
  text-align: center;
}

.squad-hero__dims {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-2);
  min-width: 0;
  margin: 0;
  padding: 0;
  list-style: none;
}

.hero-dim {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.hero-dim__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--sm-space-2);
}

.hero-dim__label {
  overflow: hidden;
  color: var(--sm-text-2);
  font-size: var(--sm-fs-2xs);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.hero-dim__value {
  color: var(--sm-text-2);
  font-size: var(--sm-fs-xs);
  font-weight: var(--sm-fw-semibold);
  font-variant-numeric: tabular-nums;
}

.hero-dim__value--accent {
  color: var(--sm-accent-cyan);
}

.hero-dim__value--warn {
  color: var(--sm-status-warning);
}

.hero-dim__value--danger {
  color: var(--sm-status-danger);
}

.hero-dim__track {
  height: 4px;
  overflow: hidden;
  border-radius: 2px;
  background: rgba(22, 37, 59, 0.9);
}

.hero-dim__track i {
  display: block;
  height: 100%;
  border-radius: 2px;
  background: var(--sm-gradient-accent);
}

.hero-dim__missing {
  overflow-wrap: anywhere;
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
  line-height: 1.5;
}

/* ---------- 六维卡片与权重面板 ---------- */

.dims {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: var(--sm-space-3);
  margin-bottom: var(--sm-space-4);
}

.dim-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
  padding: var(--sm-space-3);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-md);
  background: var(--sm-surface-2);
}

.dim-card__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--sm-space-2);
}

.dim-card__label {
  color: var(--sm-text);
  font-size: var(--sm-fs-sm);
  font-weight: var(--sm-fw-medium);
}

.dim-card__score {
  color: var(--sm-text-2);
  font-size: var(--sm-fs-xl);
  font-weight: var(--sm-fw-semibold);
  font-variant-numeric: tabular-nums;
}

.dim-card__score--accent {
  color: var(--sm-accent-cyan);
}

.dim-card__score--warn {
  color: var(--sm-status-warning);
}

.dim-card__score--danger {
  color: var(--sm-status-danger);
}

.dim-card__weight {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}

.dim-card__track {
  height: 5px;
  overflow: hidden;
  border-radius: 3px;
  background: rgba(22, 37, 59, 0.9);
}

.dim-card__track i {
  display: block;
  height: 100%;
  border-radius: 3px;
  background: var(--sm-gradient-accent);
}

.dim-card__evidence,
.dim-card__missing {
  margin: 0;
  padding-left: var(--sm-space-4);
  color: var(--sm-text-2);
  font-size: var(--sm-fs-xs);
  line-height: 1.6;
}

.dim-card__missing {
  color: var(--sm-status-warning);
}

.weights {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-3);
  padding: var(--sm-space-3) var(--sm-space-4);
  border-radius: var(--sm-radius-md);
}

.weights__head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--sm-space-2);
}

.weights__total {
  color: var(--sm-text-2);
  font-size: var(--sm-fs-2xs);
  font-variant-numeric: tabular-nums;
}

.weights__fields {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(128px, 1fr));
  gap: var(--sm-space-2) var(--sm-space-3);
}

.weights__field {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}

.weights__field :deep(.el-input-number) {
  width: 100%;
}

.weights__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sm-space-2);
  padding-top: var(--sm-space-2);
  border-top: 1px solid var(--sm-border);
}

.dims__gaps {
  margin-top: var(--sm-space-3);
}

/* ---------- 俱乐部与阵容构成 ---------- */

.club {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: var(--sm-space-3);
}

.club__current {
  flex: 1 1 240px;
  min-width: 0;
}

.club__name {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sm-space-2);
  margin-top: 2px;
  color: var(--sm-text);
  font-size: var(--sm-fs-lg);
  font-weight: var(--sm-fw-semibold);
}

.club__hint {
  margin: var(--sm-space-1) 0 0;
  color: var(--sm-text-2);
  font-size: var(--sm-fs-2xs);
  line-height: 1.6;
}

.club__field {
  display: flex;
  flex: 0 1 280px;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.club__option {
  float: right;
  margin-left: var(--sm-space-3);
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}

.composition {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(84px, 1fr));
  gap: var(--sm-space-2);
}

.composition__item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  padding: var(--sm-space-2) var(--sm-space-3);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-sm);
  background: var(--sm-surface-2);
}

.composition__count {
  color: var(--sm-text);
  font-size: var(--sm-fs-xl);
  font-weight: var(--sm-fw-semibold);
  font-variant-numeric: tabular-nums;
}

.composition__label {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}

.composition__gaps {
  margin: var(--sm-space-3) 0 0;
  padding-left: var(--sm-space-4);
  color: var(--sm-text-2);
  font-size: var(--sm-fs-2xs);
  line-height: 1.6;
}

/* ---------- 年龄结构 / 工资 / 合同 ---------- */

.age-list {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-2);
  margin-top: var(--sm-space-3);
}

.age-row {
  display: grid;
  grid-template-columns: 64px minmax(0, 1fr) 110px;
  align-items: center;
  gap: var(--sm-space-2);
  font-size: var(--sm-fs-xs);
}

.age-row__label {
  color: var(--sm-text-2);
}

.age-row__track {
  position: relative;
  height: 8px;
  overflow: hidden;
  border-radius: 4px;
  background: var(--sm-surface-3);
}

.age-row__bar {
  height: 100%;
  border-radius: 4px;
  background: linear-gradient(90deg, rgba(34, 211, 238, 0.85), rgba(77, 141, 255, 0.85));
}

.age-row__ideal {
  position: absolute;
  top: -2px;
  bottom: -2px;
  width: 2px;
  background: var(--sm-status-warning);
}

.age-row__value {
  color: var(--sm-text-2);
  font-variant-numeric: tabular-nums;
  text-align: right;
}

.wage {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-3);
}

.contracts :deep(.el-collapse-item__header) {
  font-size: var(--sm-fs-sm);
}

/* ---------- 响应式 ---------- */

@media (max-width: 1180px) {
  .squad-hero {
    grid-template-columns: minmax(0, 1fr) auto;
    align-items: flex-start;
  }

  .squad-hero__dims {
    display: grid;
    grid-column: 1 / -1;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: var(--sm-space-3) var(--sm-space-4);
  }
}

@media (max-width: 768px) {
  .squad-hero {
    grid-template-columns: minmax(0, 1fr);
    gap: var(--sm-space-4);
    padding: var(--sm-space-4);
  }

  .squad-hero__gauge {
    align-items: flex-start;
  }

  .gauge {
    width: 132px;
    height: 132px;
  }

  .gauge__value {
    font-size: var(--sm-fs-2xl);
  }

  .gauge__hint {
    text-align: left;
  }

  .squad-hero__dims {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 480px) {
  .squad-hero__dims {
    grid-template-columns: minmax(0, 1fr);
  }

  .age-row {
    grid-template-columns: 56px minmax(0, 1fr) 92px;
  }

  .club__field {
    flex: 1 1 100%;
  }

  .weights__fields {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
