/**
 * 阵容智能：六维阵容评分、位置深度、年龄与工资结构、合同预警、短板排序与接班规划。
 */

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { asApiError, type ApiError } from '../api/client'
import { getSquadOverview, listSquadProfiles } from '../api/squad'
import DataTable from '../components/DataTable.vue'
import ErrorState from '../components/ErrorState.vue'
import KpiCard from '../components/KpiCard.vue'
import LoadingBlock from '../components/LoadingBlock.vue'
import PageHeader from '../components/PageHeader.vue'
import SectionCard from '../components/SectionCard.vue'
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
      title="Squad Intelligence · 阵容智能"
      description="阵容评分拆成位置覆盖、深度、年龄、战术适配、工资结构与潜力储备六个维度；每个维度都给出数据依据，缺少数据时明确标注而不是记零。"
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
      <section class="sm-grid sm-grid--kpi">
        <KpiCard
          label="阵容评分"
          :value="overview.score === null ? EMPTY : formatDecimal(overview.score, 1)"
          :hint="`模板：${overview.profile.name}${overview.profile.overridden ? '（自定义权重）' : ''}`"
          :tone="overview.score !== null && overview.score < 55 ? 'warn' : 'accent'"
        />
        <KpiCard label="阵容人数" :value="formatInt(overview.squad_size)" hint="来自最近一次快照" />
        <KpiCard
          label="平均年龄"
          :value="overview.age_structure.average_age === null ? EMPTY : formatDecimal(overview.age_structure.average_age, 1)"
          hint="与基线年龄分布对比"
        />
        <KpiCard
          label="12 个月内到期"
          :value="formatInt(overview.contracts.at_risk_count)"
          :hint="overview.contracts.at_risk_names.slice(0, 3).join('、') || '没有即将到期的主力'"
          :tone="overview.contracts.at_risk_count > 0 ? 'warn' : 'default'"
        />
      </section>

      <SectionCard title="主执教俱乐部" subtitle="阵容分析以它作为「本队」；手动指定不会改变任何球员的所属俱乐部">
        <div class="squad__club">
          <div class="squad__club-current">
            <div class="squad__club-name">
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
            <p class="squad__club-hint">
              {{ userClub
                ? `${userClub.league ?? '联赛未知'} · ${userClub.nation ?? '国家未知'}`
                : '数据源没有提供主执教俱乐部，需要你手动选择；在此之前阵容分析无法进行' }}
            </p>
          </div>
          <el-select
            class="squad__club-select"
            filterable
            remote
            clearable
            :remote-method="searchClubOptions"
            :loading="clubSearching"
            placeholder="搜索俱乐部名称"
            size="small"
            @change="(value: number) => value && applyUserClub(value)"
          >
            <el-option
              v-for="item in clubOptions"
              :key="item.id"
              :value="item.id"
              :label="`${item.name}（${item.players} 人）`"
            >
              <span>{{ item.name }}</span>
              <span class="squad__club-option">
                {{ item.players }} 人 · {{ item.source_label ?? '来源未知' }}
                <template v-if="item.confidence !== null"> · 可信度 {{ formatDecimal(item.confidence, 1) }}</template>
              </span>
            </el-option>
          </el-select>
          <el-button size="small" :loading="selectingClub" @click="searchClubOptions('')">刷新列表</el-button>
        </div>
      </SectionCard>

      <SectionCard title="阵容构成" subtitle="一线队 / 预备队 / 青年队 / 外租 / 租入；没有名单依据的球员标为未知，不当成自由球员">
        <template v-if="composition && composition.available">
          <div class="squad__composition">
            <div v-for="(count, key) in composition.counts" :key="key" class="squad__composition-item">
              <span class="squad__composition-count">{{ count }}</span>
              <span class="squad__composition-label">{{ compositionLabel(String(key)) }}</span>
            </div>
          </div>
          <ul v-if="composition.gaps && composition.gaps.length" class="squad__gaps">
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

      <SectionCard title="六个维度" subtitle="权重可在下方调整后重算；缺数据的维度会重新分配权重">
        <div class="sm-grid sm-grid--3 squad__components">
          <div v-for="component in components" :key="component.key" class="squad__component">
            <div class="squad__component-head">
              <span class="squad__component-label">{{ component.label }}</span>
              <span class="squad__component-score" :class="`squad__component-score--${componentTone(component)}`">
                {{ component.value === null ? '不可计算' : formatDecimal(component.value, 1) }}
              </span>
            </div>
            <div class="squad__component-weight">权重 {{ formatPercent(component.weight, 0) }}</div>
            <ul class="squad__evidence">
              <li v-for="line in component.evidence" :key="line">{{ line }}</li>
            </ul>
            <ul v-if="component.missing.length > 0" class="squad__missing">
              <li v-for="line in component.missing" :key="line">{{ line }}</li>
            </ul>
          </div>
        </div>

        <div class="squad__weights">
          <span class="sm-label">自定义权重</span>
          <label v-for="component in components" :key="component.key" class="squad__weight-input">
            <span>{{ component.label.split('（')[0] }}</span>
            <el-input-number
              v-model="weightDraft[component.key]"
              :min="0"
              :max="1"
              :step="0.05"
              :precision="2"
              size="small"
              controls-position="right"
            />
          </label>
          <div class="sm-row">
            <span class="sm-text-2xs sm-text-faint">合计 {{ formatDecimal(weightTotal, 2) }}</span>
            <el-button size="small" type="primary" :loading="loading" @click="applyWeights">按此权重重算</el-button>
            <el-button size="small" @click="resetWeights">恢复模板</el-button>
          </div>
        </div>

        <el-alert
          v-if="overview.data_gaps && overview.data_gaps.length > 0"
          class="squad__gaps"
          type="warning"
          :closable="false"
          show-icon
          title="数据缺口"
        >
          <ul class="squad__evidence">
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
          <div class="squad__age">
            <div v-for="bucket in overview.age_structure.buckets" :key="bucket.bucket" class="squad__age-row">
              <span class="squad__age-label">{{ bucket.bucket }}</span>
              <div class="squad__age-track">
                <div class="squad__age-bar" :style="{ width: `${Math.min(100, bucket.share * 100)}%` }" />
                <div class="squad__age-ideal" :style="{ left: `${Math.min(100, bucket.ideal_share * 100)}%` }" />
              </div>
              <span class="squad__age-value">{{ bucket.count }} 人 · {{ formatPercent(bucket.share, 0) }}</span>
            </div>
            <p class="sm-text-2xs sm-text-faint">
              竖线为基线占比；平均年龄 {{ overview.age_structure.average_age ?? EMPTY }}，中位
              {{ overview.age_structure.median_age ?? EMPTY }}
            </p>
          </div>
        </SectionCard>
      </div>

      <div class="sm-grid sm-grid--2">
        <SectionCard title="工资结构" subtitle="集中度与低产出高薪球员共同决定工分">
          <div class="squad__wage">
            <div class="squad__wage-summary">
              <div><span class="sm-label">工资总额</span><strong>{{ formatMoney(overview.wage_structure.total) }}</strong></div>
              <div><span class="sm-label">中位数</span><strong>{{ formatMoney(overview.wage_structure.median) }}</strong></div>
              <div>
                <span class="sm-label">前 3 名占比</span>
                <strong>{{ overview.wage_structure.top3_share === null ? EMPTY : formatPercent(overview.wage_structure.top3_share, 0) }}</strong>
              </div>
            </div>
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
          <el-collapse v-if="contractBuckets.length > 0" class="squad__contracts">
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

.squad__components {
  margin-bottom: var(--sm-space-4);
}

.squad__component {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-1);
  padding: var(--sm-space-3);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-md);
  background: var(--sm-surface-2);
}

.squad__component-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--sm-space-2);
}

.squad__component-label {
  font-size: var(--sm-fs-sm);
  font-weight: var(--sm-fw-medium);
  color: var(--sm-text);
}

.squad__component-score {
  font-size: var(--sm-fs-xl);
  font-weight: var(--sm-fw-semibold);
  font-variant-numeric: tabular-nums;
}

.squad__component-score--accent {
  color: var(--sm-accent);
}

.squad__component-score--warn {
  color: var(--sm-warn);
}

.squad__component-score--danger {
  color: var(--sm-danger);
}

.squad__component-weight {
  font-size: var(--sm-fs-2xs);
  color: var(--sm-text-3);
}

.squad__evidence,
.squad__missing {
  margin: 0;
  padding-left: var(--sm-space-4);
  font-size: var(--sm-fs-xs);
  line-height: 1.6;
  color: var(--sm-text-2);
}

.squad__missing {
  color: var(--sm-warn);
}

.squad__weights {
  display: flex;
  align-items: flex-end;
  flex-wrap: wrap;
  gap: var(--sm-space-3);
  padding-top: var(--sm-space-3);
  border-top: 1px solid var(--sm-border);
}

.squad__weight-input {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: var(--sm-fs-2xs);
  color: var(--sm-text-3);
}

.squad__weight-input :deep(.el-input-number) {
  width: 96px;
}

.squad__gaps {
  margin-top: var(--sm-space-3);
}

.squad__age {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-2);
}

.squad__age-row {
  display: grid;
  grid-template-columns: 64px minmax(0, 1fr) 120px;
  align-items: center;
  gap: var(--sm-space-2);
  font-size: var(--sm-fs-xs);
}

.squad__age-label {
  color: var(--sm-text-2);
}

.squad__age-track {
  position: relative;
  height: 10px;
  background: var(--sm-surface-3);
  border-radius: 5px;
  overflow: hidden;
}

.squad__age-bar {
  height: 100%;
  background: var(--sm-accent);
}

.squad__age-ideal {
  position: absolute;
  top: -2px;
  bottom: -2px;
  width: 2px;
  background: var(--sm-warn);
}

.squad__age-value {
  text-align: right;
  color: var(--sm-text-2);
  font-variant-numeric: tabular-nums;
}

.squad__wage {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-3);
}

.squad__wage-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--sm-space-3);
  font-size: var(--sm-fs-sm);
}

.squad__wage-summary span {
  display: block;
  font-size: var(--sm-fs-2xs);
  color: var(--sm-text-3);
}

.squad__contracts :deep(.el-collapse-item__header) {
  font-size: var(--sm-fs-sm);
}
.squad__club {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: flex-end;
}

.squad__club-current {
  flex: 1 1 260px;
  min-width: 220px;
}

.squad__club-name {
  display: flex;
  gap: 8px;
  align-items: center;
  font-weight: 600;
}

.squad__club-hint {
  margin: 4px 0 0;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.squad__club-select {
  flex: 0 1 320px;
}

.squad__club-option {
  float: right;
  margin-left: 12px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.squad__composition {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
}

.squad__composition-item {
  display: flex;
  flex-direction: column;
  min-width: 84px;
  padding: 10px 14px;
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
}

.squad__composition-count {
  font-size: 20px;
  font-weight: 600;
}

.squad__composition-label {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.squad__gaps {
  margin: 12px 0 0;
  padding-left: 18px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
</style>
