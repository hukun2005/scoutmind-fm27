/** 智能球探：角色模板选择、筛选与带覆盖度的候选人排序。 */

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { asApiError, type ApiError } from '../api/client'
import { listClubs } from '../api/clubs'
import { evaluateRole, listRoles, searchScouting } from '../api/scouting'
import DataTable from '../components/DataTable.vue'
import EmptyState from '../components/EmptyState.vue'
import ErrorState from '../components/ErrorState.vue'
import NumberCell from '../components/NumberCell.vue'
import PageHeader from '../components/PageHeader.vue'
import ScoreBadge from '../components/ScoreBadge.vue'
import SectionCard from '../components/SectionCard.vue'
import type { Club } from '../types/clubs'
import type { PlayerFilters } from '../types/players'
import type { RoleEvaluation, RoleTemplate, ScoutingCandidate } from '../types/scouting'
import type { TableColumn } from '../types/table'
import { useSessionStore } from '../stores/session'
import {
  EMPTY,
  displayText,
  formatDecimal,
  formatInt,
} from '../utils/format'
import { POSITION_GROUPS, attributeLabel, positionGroupLabel, positionLabel } from '../utils/labels'

const router = useRouter()
const session = useSessionStore()

const roles = ref<RoleTemplate[]>([])
const rolesLoading = ref(false)
const rolesError = ref<ApiError | null>(null)
const selectedRoleKey = ref('')

const form = reactive<{
  positionGroup: string | undefined
  minAge: number | undefined
  maxAge: number | undefined
  minCa: number | undefined
  maxPa: number | undefined
  maxValueWan: number | undefined
  clubId: number | undefined
  watchlistOnly: boolean
  limit: number
}>({
  positionGroup: undefined,
  minAge: undefined,
  maxAge: undefined,
  minCa: undefined,
  maxPa: undefined,
  maxValueWan: undefined,
  clubId: undefined,
  watchlistOnly: false,
  limit: 100,
})

const clubs = ref<Club[]>([])
const clubsLoading = ref(false)
const clubsError = ref<ApiError | null>(null)

const candidates = ref<ScoutingCandidate[]>([])
const total = ref(0)
const loading = ref(false)
const error = ref<ApiError | null>(null)
const searched = ref(false)

const evaluations = ref<Record<number, RoleEvaluation>>({})
const evaluationLoading = ref<Record<number, boolean>>({})
const evaluationErrors = ref<Record<number, ApiError | null>>({})

const selectedRole = computed(() => roles.value.find((role) => role.key === selectedRoleKey.value) ?? null)

/** Top weighted attributes of the selected template, for the template summary. */
const roleWeights = computed(() => {
  const weights = selectedRole.value?.weights ?? {}
  return Object.entries(weights)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8)
    .map(([key, value]) => ({ key, label: attributeLabel(key), value }))
})

/** Stable row key: the player instance behind each candidate. */
function candidateKey(row: ScoutingCandidate): string {
  return String(row.player.instance_id)
}

/** Candidate rows with attribute coverage below 100%. */
const partialCoverageCount = computed(
  () => candidates.value.filter((item) => item.coverage !== null && item.coverage < 1).length,
)

const columns: TableColumn<ScoutingCandidate>[] = [
  { prop: 'rank', label: '排名', width: 64, align: 'right' },
  { prop: 'name', label: '球员', minWidth: 158, formatter: (row) => displayText(row.player.name) },
  { prop: 'position', label: '位置', width: 116, formatter: (row) => positionLabel(row.player.position) },
  { prop: 'position_group', label: '位置组', width: 84, formatter: (row) => positionGroupLabel(row.player.position_group) },
  { prop: 'age', label: '年龄', width: 68, align: 'right' },
  { prop: 'ca', label: 'CA', width: 64, align: 'right' },
  { prop: 'pa', label: 'PA', width: 64, align: 'right' },
  { prop: 'market_value', label: '身价', width: 110, align: 'right' },
  { prop: 'score', label: '角色评分', width: 176, align: 'right' },
  { prop: 'role', label: '角色', width: 124, formatter: (row) => roleLabel(row.role_key) },
  { prop: 'coverage', label: '属性覆盖', width: 96, align: 'right' },
  { prop: 'data_gap', label: '数据缺口', width: 96, align: 'center' },
]

/** Display name of the role key attached to a candidate. */
function roleLabel(key: string | null): string {
  if (!key) return EMPTY
  return roles.value.find((role) => role.key === key)?.name ?? key
}

/** Assemble the filter object sent as `filters` (same names as `GET /players`). */
function buildFilters(): PlayerFilters {
  return {
    position_group: form.positionGroup,
    min_age: form.minAge,
    max_age: form.maxAge,
    min_ca: form.minCa,
    max_pa: form.maxPa,
    max_value: form.maxValueWan === undefined ? undefined : Math.round(form.maxValueWan * 10_000),
    club_id: form.clubId,
    watchlist_only: form.watchlistOnly ? true : undefined,
  }
}

/** Load role templates and preselect the first one. */
async function loadRoles(): Promise<void> {
  rolesLoading.value = true
  rolesError.value = null
  try {
    const response = await listRoles()
    roles.value = response.items ?? []
    if (!selectedRoleKey.value && roles.value.length > 0) {
      selectedRoleKey.value = roles.value[0]?.key ?? ''
    }
  } catch (caught) {
    rolesError.value = asApiError(caught)
    roles.value = []
  } finally {
    rolesLoading.value = false
  }
}

/** Load club options for the filter panel. */
async function loadClubs(): Promise<void> {
  clubsLoading.value = true
  clubsError.value = null
  try {
    const response = await listClubs()
    clubs.value = response.items
  } catch (caught) {
    clubsError.value = asApiError(caught)
    clubs.value = []
  } finally {
    clubsLoading.value = false
  }
}

/** Run the ranking search. */
async function search(): Promise<void> {
  loading.value = true
  error.value = null
  searched.value = true
  candidates.value = []
  evaluations.value = {}
  evaluationErrors.value = {}
  try {
    const response = await searchScouting({
      save_id: session.activeSaveId ?? undefined,
      role_key: selectedRoleKey.value || undefined,
      filters: buildFilters(),
      limit: form.limit,
    })
    candidates.value = response.items ?? []
    total.value = response.total ?? 0
    session.markSources(candidates.value.map((item) => item.player.source))
  } catch (caught) {
    error.value = asApiError(caught)
    candidates.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

/** Load strengths/weaknesses for a candidate when its row is expanded. */
async function onExpand(row: ScoutingCandidate, expanded: boolean): Promise<void> {
  if (!expanded) return
  const instanceId = row.player.instance_id
  const roleKey = row.role_key ?? selectedRoleKey.value
  if (!roleKey) return
  if (evaluations.value[instanceId] || evaluationLoading.value[instanceId]) return
  evaluationLoading.value = { ...evaluationLoading.value, [instanceId]: true }
  evaluationErrors.value = { ...evaluationErrors.value, [instanceId]: null }
  try {
    const result = await evaluateRole({ instance_id: instanceId, role_key: roleKey })
    evaluations.value = { ...evaluations.value, [instanceId]: result }
  } catch (caught) {
    evaluationErrors.value = { ...evaluationErrors.value, [instanceId]: asApiError(caught) }
  } finally {
    evaluationLoading.value = { ...evaluationLoading.value, [instanceId]: false }
  }
}

/** Retry one expanded evaluation. */
async function retryEvaluation(row: ScoutingCandidate): Promise<void> {
  const instanceId = row.player.instance_id
  delete evaluations.value[instanceId]
  await onExpand(row, true)
}

/** Clear the filter panel. */
function resetFilters(): void {
  form.positionGroup = undefined
  form.minAge = undefined
  form.maxAge = undefined
  form.minCa = undefined
  form.maxPa = undefined
  form.maxValueWan = undefined
  form.clubId = undefined
  form.watchlistOnly = false
}

/** Open the player detail page. */
function openPlayer(row: ScoutingCandidate): void {
  void router.push(`/players/${row.player.instance_id}`)
}

watch(selectedRoleKey, () => {
  // Cached strengths/weaknesses belong to the previous template.
  evaluations.value = {}
  evaluationErrors.value = {}
  if (searched.value) void search()
})

watch(
  [() => session.activeSaveId, () => session.dataRevision],
  () => {
    if (searched.value) void search()
  },
)

void loadRoles()
void loadClubs()
</script>

<template>
  <div class="sm-page">
    <PageHeader
      title="角色球探"
      description="按战术角色的属性权重给球员打分并排序。评分是规则计算结果，样本不足时请谨慎比较。"
    >
      <template #meta>
        <span class="sm-text-xs sm-text-faint">
          模板 {{ formatInt(roles.length) }} 个 · 本次返回 {{ formatInt(candidates.length) }} / {{ formatInt(total) }} 名候选人
        </span>
        <el-tag v-if="selectedRole" size="small" type="info" disable-transitions>
          {{ selectedRole.name }} · v{{ selectedRole.version }}
        </el-tag>
        <el-tag v-if="partialCoverageCount > 0" size="small" type="warning" disable-transitions>
          {{ partialCoverageCount }} 名候选人属性覆盖不足 100%
        </el-tag>
      </template>
      <template #actions>
        <el-button size="small" :loading="loading" @click="search">重新检索</el-button>
      </template>
    </PageHeader>

    <ErrorState v-if="rolesError" :error="rolesError" title="角色模板加载失败" @retry="loadRoles" />

    <section class="console sm-glass" aria-label="角色筛选控制台">
      <header class="console__head">
        <div class="console__titles">
          <span class="sm-section-label">筛选球员</span>
          <p class="console__hint">筛选参数与球员中心一致，均由后端执行；角色模板决定加权规则。</p>
        </div>
      </header>
      <div class="filter-grid">
        <label class="filter-field filter-field--wide">
          <span class="sm-label">角色模板</span>
          <el-select
            v-model="selectedRoleKey"
            size="small"
            filterable
            :loading="rolesLoading"
            placeholder="选择角色模板"
            aria-label="角色模板"
          >
            <el-option
              v-for="role in roles"
              :key="role.key"
              :label="`${role.name} · ${positionGroupLabel(role.position_group)}`"
              :value="role.key"
            />
          </el-select>
        </label>

        <label class="filter-field">
          <span class="sm-label">位置组</span>
          <el-select v-model="form.positionGroup" size="small" clearable placeholder="全部位置组">
            <el-option v-for="group in POSITION_GROUPS" :key="group.value" :label="group.label" :value="group.value" />
          </el-select>
        </label>

        <div class="filter-field filter-field--pair">
          <span class="sm-label">年龄区间</span>
          <div class="filter-pair">
            <el-input-number v-model="form.minAge" size="small" :min="14" :max="60" :controls="false" placeholder="最小" />
            <span class="filter-pair__dash">–</span>
            <el-input-number v-model="form.maxAge" size="small" :min="14" :max="60" :controls="false" placeholder="最大" />
          </div>
        </div>

        <label class="filter-field">
          <span class="sm-label" title="API 契约仅提供 min_ca">CA 下限</span>
          <el-input-number v-model="form.minCa" size="small" :min="1" :max="200" :controls="false" placeholder="min_ca" />
        </label>

        <label class="filter-field">
          <span class="sm-label" title="API 契约仅提供 max_pa">PA 上限</span>
          <el-input-number v-model="form.maxPa" size="small" :min="1" :max="200" :controls="false" placeholder="max_pa" />
        </label>

        <label class="filter-field">
          <span class="sm-label">身价上限（万 €）</span>
          <el-input-number v-model="form.maxValueWan" size="small" :min="0" :step="100" :controls="false" placeholder="不限" />
        </label>

        <label class="filter-field">
          <span class="sm-label">俱乐部</span>
          <el-select v-model="form.clubId" size="small" clearable filterable :loading="clubsLoading" placeholder="全部俱乐部">
            <el-option v-for="club in clubs" :key="club.club_id" :label="club.name" :value="club.club_id" />
          </el-select>
        </label>

        <label class="filter-field">
          <span class="sm-label">候选上限</span>
          <el-select v-model="form.limit" size="small" aria-label="候选上限">
            <el-option :value="50" label="50" />
            <el-option :value="100" label="100" />
            <el-option :value="150" label="150" />
            <el-option :value="200" label="200" />
          </el-select>
        </label>

        <div class="filter-field filter-field--actions">
          <el-switch v-model="form.watchlistOnly" size="small" active-text="仅关注" aria-label="仅关注名单" />
        </div>

        <div class="filter-field filter-field--actions">
          <el-button size="small" @click="resetFilters">重置</el-button>
          <el-button size="small" type="primary" :loading="loading" @click="search">开始检索</el-button>
        </div>
      </div>

      <div v-if="selectedRole" class="role-weights">
        <span class="sm-label">模板权重</span>
        <span v-for="weight in roleWeights" :key="weight.key" class="chip">
          {{ weight.label }} {{ formatDecimal(weight.value, 2) }}
        </span>
        <span v-if="roleWeights.length === 0" class="sm-text-2xs sm-text-faint">该模板未返回权重字段</span>
      </div>
      <p class="console__foot">
        <span v-if="clubsError">俱乐部选项加载失败：{{ clubsError.message }}</span>
        <span v-else>评分 = 参与属性按权重加权（后端 /scouting/evaluate 与 /scouting/search 使用同一模板）。</span>
      </p>
    </section>    <SectionCard title="候选人" subtitle="按角色评分降序；展开行可查看优势与短板" flush>
      <ErrorState v-if="error" :error="error" compact @retry="search" />

      <EmptyState
        v-else-if="searched && !loading && candidates.length === 0"
        title="没有符合条件的候选人"
        description="放宽年龄、CA/PA、身价或位置组筛选后重试；如果全部为空，请先在「数据与诊断」导入扫描数据。"
        variant="empty"
      >
        <el-button size="small" @click="resetFilters">清空筛选</el-button>
        <el-button size="small" @click="search">重新检索</el-button>
      </EmptyState>

      <EmptyState
        v-else-if="!searched"
        title="选择角色模板后开始检索"
        description="模板决定加权规则；扫描数据为空时不会返回候选人，页面也不会编造候选名单。"
        compact
      />

      <DataTable
        v-else
        :columns="columns"
        :rows="candidates"
        :loading="loading"
        :error="error"
        :row-key="candidateKey"
        expandable
        dense
        max-height="560"
        :empty-title="loading ? '正在检索' : '没有候选数据'"
        @expand-change="onExpand"
        @retry="search"
      >
        <template #expand="{ row }">
          <div class="expand">
            <div v-if="evaluationLoading[row.player.instance_id]" class="sm-stack">
              <el-skeleton :rows="3" animated />
            </div>
            <ErrorState
              v-else-if="evaluationErrors[row.player.instance_id]"
              :error="evaluationErrors[row.player.instance_id]"
              compact
              @retry="retryEvaluation(row)"
            />
            <template v-else-if="evaluations[row.player.instance_id]">
              <div class="expand__head">
                <ScoreBadge
                  :score="evaluations[row.player.instance_id]?.score ?? null"
                  :coverage="evaluations[row.player.instance_id]?.coverage ?? null"
                />
                <span class="sm-text-xs sm-text-muted">
                  {{ evaluations[row.player.instance_id]?.role_name }} · 模板 v{{ evaluations[row.player.instance_id]?.template_version }}
                </span>
              </div>
              <div class="expand__lists">
                <div>
                  <p class="sm-label">优势</p>
                  <ul class="chips">
                    <li v-for="item in evaluations[row.player.instance_id]?.strengths ?? []" :key="item" class="chip chip--good">
                      {{ item }}
                    </li>
                    <li v-if="(evaluations[row.player.instance_id]?.strengths ?? []).length === 0" class="sm-text-faint sm-text-2xs">无</li>
                  </ul>
                </div>
                <div>
                  <p class="sm-label">短板</p>
                  <ul class="chips">
                    <li v-for="item in evaluations[row.player.instance_id]?.weaknesses ?? []" :key="item" class="chip chip--weak">
                      {{ item }}
                    </li>
                    <li v-if="(evaluations[row.player.instance_id]?.weaknesses ?? []).length === 0" class="sm-text-faint sm-text-2xs">无</li>
                  </ul>
                </div>
              </div>
              <p class="sm-text-2xs sm-text-faint">
                评分来自 POST /scouting/evaluate（实例 {{ row.player.instance_id }}，模板
                {{ evaluations[row.player.instance_id]?.role_key }}）；展开行时才请求，未展开不会产生额外调用。
              </p>
            </template>
            <p v-else class="sm-text-2xs sm-text-faint">未获得评分明细。</p>
          </div>
        </template>

        <template #cell="{ row, column, index }">
          <template v-if="column.prop === 'rank'">
            <span class="sm-num">{{ index + 1 }}</span>
          </template>
          <template v-else-if="column.prop === 'name'">
            <button type="button" class="player-link" @click="openPlayer(row)">
              {{ displayText(row.player.name) }}
            </button>
          </template>
          <template v-else-if="column.prop === 'age'">
            <NumberCell :value="row.player.age" unit="岁" />
          </template>
          <template v-else-if="column.prop === 'ca'">
            <NumberCell :value="row.player.ca" />
          </template>
          <template v-else-if="column.prop === 'pa'">
            <NumberCell :value="row.player.pa" />
          </template>
          <template v-else-if="column.prop === 'market_value'">
            <NumberCell :value="row.player.market_value" kind="money" />
          </template>
          <template v-else-if="column.prop === 'score'">
            <ScoreBadge :score="row.score" :coverage="row.coverage" size="sm" />
          </template>
          <template v-else-if="column.prop === 'coverage'">
            <NumberCell :value="row.coverage" kind="percent" />
          </template>
          <template v-else-if="column.prop === 'data_gap'">
            <el-tag v-if="row.coverage !== null && row.coverage < 1" size="small" type="warning" disable-transitions>
              缺数据
            </el-tag>
            <el-tag v-else-if="row.coverage === null" size="small" type="info" disable-transitions>未知</el-tag>
            <span v-else class="sm-text-2xs sm-text-faint">完整</span>
          </template>
          <template v-else>
            {{ column.formatter ? column.formatter(row) : EMPTY }}
          </template>
        </template>

        <template #toolbar>
          <span class="sm-text-2xs sm-text-faint">
            共 {{ formatInt(total) }} 名候选人 · 当前显示 {{ formatInt(candidates.length) }} 名 ·
            覆盖率 = 参与计算属性权重之和 / 模板总权重
          </span>
        </template>
      </DataTable>
    </SectionCard>

    <p class="page-note">
      角色评分为确定性加权结果：属性缺失会降低覆盖率，但不会用平均值填充；比较候选人时应先看覆盖率再看分数。
      身价默认 EUR，百分位与角色权重均来自后端模板 {{ selectedRole ? `v${selectedRole.version}` : EMPTY }}。
    </p>
  </div>
</template>

<style scoped>
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
  line-height: 1.6;
}

.console__foot {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
  line-height: 1.5;
}

.filter-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(168px, 1fr));
  gap: var(--sm-space-3);
  align-items: end;
}

.filter-field {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-1);
  min-width: 0;
}

.filter-field--wide {
  grid-column: span 2;
}

.filter-field--pair {
  min-width: 200px;
}

.filter-field--actions {
  flex-direction: row;
  justify-content: flex-end;
  align-items: center;
  gap: var(--sm-space-2);
}

.filter-pair {
  display: flex;
  align-items: center;
  gap: var(--sm-space-1);
}

.filter-pair :deep(.el-input-number) {
  width: 84px;
}

.filter-pair__dash {
  color: var(--sm-text-3);
}

.role-weights {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--sm-space-2);
  margin-top: var(--sm-space-3);
  padding-top: var(--sm-space-3);
  border-top: 1px solid var(--sm-border);
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sm-space-1);
  margin: 2px 0 0;
  padding: 0;
  list-style: none;
}

.chip {
  padding: 1px 6px;
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-sm);
  background: var(--sm-surface-2);
  color: var(--sm-text-2);
  font-size: var(--sm-fs-2xs);
  font-variant-numeric: tabular-nums;
}

.chip--good {
  border-color: rgba(53, 201, 138, 0.35);
  background: var(--sm-success-weak);
  color: var(--sm-success);
}

.chip--weak {
  border-color: rgba(240, 106, 99, 0.35);
  background: var(--sm-danger-weak);
  color: var(--sm-danger);
}

.expand {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-2);
}

.expand__head {
  display: flex;
  align-items: baseline;
  gap: var(--sm-space-2);
}

.expand__lists {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--sm-space-3);
}

.player-link {
  padding: 0;
  border: 0;
  background: none;
  color: var(--sm-accent);
  font: inherit;
  font-weight: var(--sm-fw-medium);
  cursor: pointer;
}

.player-link:hover {
  text-decoration: underline;
}

.page-note {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}

@media (max-width: 640px) {
  .console {
    padding: var(--sm-space-3);
  }

  /* 单列布局下取消跨列，避免隐式网格列造成横向溢出。 */
  .filter-field--wide {
    grid-column: auto;
  }
}
</style>
