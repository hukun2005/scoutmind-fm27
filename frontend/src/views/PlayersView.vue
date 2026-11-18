/** 球员中心：服务端筛选、排序与分页的球员实例列表。 */

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { asApiError, type ApiError } from '../api/client'
import { listClubs } from '../api/clubs'
import DataTable from '../components/DataTable.vue'
import NumberCell from '../components/NumberCell.vue'
import PageHeader from '../components/PageHeader.vue'
import SectionCard from '../components/SectionCard.vue'
import type { Club } from '../types/clubs'
import type { PlayerSummary } from '../types/players'
import type { TableColumn, TableSortPayload } from '../types/table'
import { usePlayersStore } from '../stores/players'
import { useSessionStore } from '../stores/session'
import { EMPTY, displayText, formatDate, formatInt, formatPercent } from '../utils/format'
import { POSITION_GROUPS, POSITION_OPTIONS, positionGroupLabel, positionLabel } from '../utils/labels'

const router = useRouter()
const session = useSessionStore()
const players = usePlayersStore()

const clubs = ref<Club[]>([])
const clubsError = ref<ApiError | null>(null)
const clubsLoading = ref(false)

/** Max value filter is edited in 万 but sent in base units. */
const maxValueWan = ref<number | undefined>(undefined)

const columns: TableColumn<PlayerSummary>[] = [
  { prop: 'name', label: '姓名', minWidth: 136, sortable: 'custom', showOverflowTooltip: true },
  { prop: 'age', label: '年龄', width: 60, align: 'right', sortable: 'custom' },
  { prop: 'position', label: '位置', width: 100, formatter: (row) => positionLabel(row.position) },
  { prop: 'position_group', label: '位置组', width: 72, formatter: (row) => positionGroupLabel(row.position_group) },
  { prop: 'club', label: '俱乐部', width: 112, showOverflowTooltip: true, formatter: (row) => displayText(row.club) },
  { prop: 'ca', label: 'CA', width: 58, align: 'right', sortable: 'custom' },
  { prop: 'pa', label: 'PA', width: 58, align: 'right', sortable: 'custom' },
  { prop: 'market_value', label: '身价（€）', width: 100, align: 'right', sortable: 'custom' },
  { prop: 'contract_end', label: '合同到期', width: 100, formatter: (row) => displayText(row.contract_end) },
  { prop: 'data_completeness', label: '完整度', width: 72, align: 'right' },
  {
    prop: 'updated_at',
    label: '最近观测',
    width: 104,
    sortable: 'custom',
    title: '按 updated_at 排序，显示最近一次 observed_at',
    formatter: (row) => formatDate(row.observed_at),
  },
]

/** Coverage chips shown under the table header. */
const coverageItems = computed(() => Object.entries(players.coverage))

/** Signature that decides when to refetch (filters, paging, save, token). */
const querySignature = computed(() =>
  JSON.stringify({
    filters: players.filters,
    page: players.page,
    pageSize: players.pageSize,
    saveId: session.activeSaveId,
    revision: session.dataRevision,
  }),
)

let reloadTimer: ReturnType<typeof setTimeout> | null = null
let firstRun = true

/** Debounced reload: typing in the search box should not fire a request per key. */
function scheduleReload(): void {
  if (reloadTimer) clearTimeout(reloadTimer)
  const delay = firstRun ? 0 : 220
  firstRun = false
  reloadTimer = setTimeout(() => {
    void players.load(session.activeSaveId)
  }, delay)
}

/** Load the club filter options once per session. */
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

/** Sync the 万 input with the base-unit filter. */
function onMaxValueChange(value: number | undefined): void {
  players.setFilter('max_value', value === undefined ? undefined : Math.round(value * 10_000))
}

/** Clear every filter in one action. */
function resetFilters(): void {
  maxValueWan.value = undefined
  players.reset()
}

/** Open the detail screen for a row. */
function openPlayer(row: PlayerSummary): void {
  void router.push(`/players/${row.instance_id}`)
}

function onPageChange(value: number): void {
  players.setPage(value)
}

function onPageSizeChange(value: number): void {
  players.setPageSize(value)
}

function onSortChange(payload: TableSortPayload): void {
  players.setSort(payload.prop, payload.order)
}

watch(querySignature, scheduleReload, { immediate: true })

onBeforeUnmount(() => {
  if (reloadTimer) clearTimeout(reloadTimer)
})

void loadClubs()
</script>

<template>
  <div class="sm-page">
    <PageHeader
      title="球员中心"
      description="服务端分页与排序。筛选条件全部按 API 契约发送，缺失字段显示为 —；点击行进入球员详情。"
    >
      <template #meta>
        <span class="sm-text-xs sm-text-faint">共 {{ formatInt(players.total) }} 条球员实例</span>
        <el-tag
          v-for="[key, value] in coverageItems"
          :key="key"
          size="small"
          type="info"
          disable-transitions
        >
          {{ key }} 覆盖 {{ formatPercent(value) }}
        </el-tag>
        <span v-if="clubsError" class="sm-text-2xs sm-text-faint">俱乐部筛选项加载失败：{{ clubsError.message }}</span>
      </template>
      <template #actions>
        <el-button size="small" :loading="players.loading" @click="players.load(session.activeSaveId)">刷新</el-button>
      </template>
    </PageHeader>

    <SectionCard title="筛选" subtitle="条件变更后自动查询，输入框有 220ms 防抖" dense>
      <div class="filter-grid">
        <label class="filter-field">
          <span class="sm-label">姓名搜索</span>
          <el-input
            :model-value="players.filters.query ?? ''"
            size="small"
            clearable
            placeholder="模糊匹配球员姓名"
            @update:model-value="(value) => players.setFilter('query', value === '' ? undefined : String(value))"
          />
        </label>

        <label class="filter-field">
          <span class="sm-label">位置</span>
          <el-select
            :model-value="players.filters.position"
            size="small"
            clearable
            filterable
            placeholder="全部位置"
            @update:model-value="(value) => players.setFilter('position', value === '' ? undefined : String(value))"
          >
            <el-option v-for="option in POSITION_OPTIONS" :key="option.value" :label="option.label" :value="option.value" />
          </el-select>
        </label>

        <label class="filter-field">
          <span class="sm-label">位置组</span>
          <el-select
            :model-value="players.filters.position_group"
            size="small"
            clearable
            placeholder="全部位置组"
            @update:model-value="(value) => players.setFilter('position_group', value === '' ? undefined : String(value))"
          >
            <el-option v-for="group in POSITION_GROUPS" :key="group.value" :label="group.label" :value="group.value" />
          </el-select>
        </label>

        <div class="filter-field filter-field--pair">
          <span class="sm-label">年龄区间</span>
          <div class="filter-pair">
            <el-input-number
              :model-value="players.filters.min_age"
              size="small"
              :min="14"
              :max="60"
              :controls="false"
              placeholder="最小"
              @update:model-value="(value) => players.setFilter('min_age', typeof value === 'number' ? value : undefined)"
            />
            <span class="filter-pair__dash">–</span>
            <el-input-number
              :model-value="players.filters.max_age"
              size="small"
              :min="14"
              :max="60"
              :controls="false"
              placeholder="最大"
              @update:model-value="(value) => players.setFilter('max_age', typeof value === 'number' ? value : undefined)"
            />
          </div>
        </div>

        <label class="filter-field">
          <span class="sm-label" title="API 契约只提供 min_ca 参数">CA 下限</span>
          <el-input-number
            :model-value="players.filters.min_ca"
            size="small"
            :min="1"
            :max="200"
            :controls="false"
            placeholder="min_ca"
            @update:model-value="(value) => players.setFilter('min_ca', typeof value === 'number' ? value : undefined)"
          />
        </label>

        <label class="filter-field">
          <span class="sm-label" title="API 契约只提供 max_pa 参数">PA 上限</span>
          <el-input-number
            :model-value="players.filters.max_pa"
            size="small"
            :min="1"
            :max="200"
            :controls="false"
            placeholder="max_pa"
            @update:model-value="(value) => players.setFilter('max_pa', typeof value === 'number' ? value : undefined)"
          />
        </label>

        <label class="filter-field">
          <span class="sm-label">身价上限（万 €）</span>
          <el-input-number
            v-model="maxValueWan"
            size="small"
            :min="0"
            :step="100"
            :controls="false"
            placeholder="不限"
            @update:model-value="onMaxValueChange"
          />
        </label>

        <label class="filter-field">
          <span class="sm-label">俱乐部</span>
          <el-select
            :model-value="players.filters.club_id"
            size="small"
            clearable
            filterable
            :loading="clubsLoading"
            placeholder="全部俱乐部"
            @update:model-value="(value) => players.setFilter('club_id', typeof value === 'number' ? value : undefined)"
          >
            <el-option v-for="club in clubs" :key="club.club_id" :label="club.name" :value="club.club_id" />
          </el-select>
        </label>

        <div class="filter-field">
          <span class="sm-label">只看关注名单</span>
          <el-switch
            :model-value="players.filters.watchlist_only === true"
            size="small"
            @update:model-value="(value) => players.setFilter('watchlist_only', value === true ? true : undefined)"
          />
        </div>

        <div class="filter-field filter-field--actions">
          <el-button size="small" @click="resetFilters">重置条件</el-button>
        </div>
      </div>
      <template #footer>
        契约参数说明：CA 只有下限（min_ca）、PA 只有上限（max_pa）；身价上限按万输入后换算为游戏货币单位发送（max_value）。
      </template>
    </SectionCard>

    <SectionCard title="球员列表" flush>
      <DataTable
        :columns="columns"
        :rows="players.items"
        :loading="players.loading"
        :error="players.error"
        :total="players.total"
        :page="players.page"
        :page-size="players.pageSize"
        :page-sizes="[25, 50, 100, 200]"
        :initial-sort="{ prop: 'updated_at', order: 'descending' }"
        row-key="instance_id"
        clickable
        show-pagination
        :empty-title="players.error ? '加载失败' : '没有符合筛选条件的球员'"
        empty-description="放宽年龄、CA/PA 或身价区间；也可以清空位置与俱乐部筛选后重试。数据为空通常意味着当前存档尚未导入扫描结果。"
        @row-click="openPlayer"
        @sort-change="onSortChange"
        @update:page="onPageChange"
        @update:page-size="onPageSizeChange"
        @retry="players.load(session.activeSaveId)"
      >
        <template #cell="{ row, column }">
          <template v-if="column.prop === 'name'">
            <button type="button" class="player-link" @click.stop="openPlayer(row)">
              {{ displayText(row.name) }}
            </button>
          </template>
          <template v-else-if="column.prop === 'age'">
            <NumberCell :value="row.age" unit="岁" />
          </template>
          <template v-else-if="column.prop === 'ca'">
            <NumberCell :value="row.ca" />
          </template>
          <template v-else-if="column.prop === 'pa'">
            <NumberCell :value="row.pa" />
          </template>
          <template v-else-if="column.prop === 'market_value'">
            <NumberCell :value="row.market_value" kind="money" />
          </template>
          <template v-else-if="column.prop === 'data_completeness'">
            <span
              class="completeness"
              :class="{ 'sm-null': row.data_completeness === null }"
              :title="row.data_completeness === null ? '后端未提供完整度' : '非空字段比例'"
            >
              {{ formatPercent(row.data_completeness) }}
            </span>
          </template>
          <template v-else>
            {{ column.formatter ? column.formatter(row) : EMPTY }}
          </template>
        </template>
      </DataTable>
    </SectionCard>

    <p class="page-note">
      排序字段：年龄、CA、PA、身价、姓名、最近观测。点击表头切换升/降序，排序与分页都由后端执行。
    </p>
  </div>
</template>

<style scoped>
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

.filter-field--pair {
  min-width: 200px;
}

.filter-field--actions {
  justify-content: flex-end;
  flex-direction: row;
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

.filter-field :deep(.el-input-number) {
  width: 100%;
}

.player-link {
  padding: 0;
  border: 0;
  background: none;
  color: var(--sm-accent);
  font: inherit;
  font-weight: var(--sm-fw-medium);
  text-align: left;
  cursor: pointer;
}

.player-link:hover {
  text-decoration: underline;
}

.completeness {
  font-variant-numeric: tabular-nums;
}

.page-note {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}
</style>



