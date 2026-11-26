/**
 * 球员中心：搜索 → 常用筛选 → 精简列表 → 详情。
 *
 * 交互取舍（V3.3.0）：
 * - 高频条件平铺，低频条件收进「更多筛选」，不删除任何业务能力；
 * - 列表只保留 7 列，其余字段进入球员详情；
 * - 空状态区分「数据库为空」「筛选无结果」「加载中」「加载失败」四种情况。
 * 分页、排序与筛选仍由后端执行，请求参数与 API 契约保持一致。
 */

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { asApiError, type ApiError } from '../api/client'
import { listClubs } from '../api/clubs'
import { listPlayers } from '../api/players'
import DataTable from '../components/DataTable.vue'
import EmptyState from '../components/EmptyState.vue'
import FilterPanel from '../components/FilterPanel.vue'
import KpiCard from '../components/KpiCard.vue'
import NumberCell from '../components/NumberCell.vue'
import PageHeader from '../components/PageHeader.vue'
import SectionCard from '../components/SectionCard.vue'
import ValueScatterCard from '../components/ValueScatterCard.vue'
import { MAX_COMPARE, useCompareStore } from '../stores/compare'
import { usePlayersStore } from '../stores/players'
import { useSessionStore } from '../stores/session'
import type { Club } from '../types/clubs'
import type { PlayerSummary } from '../types/players'
import type { TableColumn, TableSortPayload } from '../types/table'
import { EMPTY, displayText, formatInt, formatMoney, formatPercent } from '../utils/format'
import { POSITION_GROUPS, POSITION_LABELS, POSITION_OPTIONS, coverageLabel } from '../utils/labels'

const route = useRoute()
const router = useRouter()
const session = useSessionStore()
const players = usePlayersStore()
const compare = useCompareStore()

/** 列表形态：表格或卡片；只影响展示，不改变服务端分页与筛选。 */
const viewMode = ref<'table' | 'cards'>('table')

const clubs = ref<Club[]>([])
const clubsError = ref<ApiError | null>(null)
const clubsLoading = ref(false)

/** 已关注球员：由后端 `watchlist_only` 计数得到，未取到时不显示。 */
const watchCount = ref<number | null>(null)

/** 身价上限在界面上按「万」输入，发送时换算为基础货币单位。 */
const maxValueWan = ref<number | undefined>(undefined)

/** 列表只保留 7 列；其余字段在球员详情中查看。 */
const columns: TableColumn<PlayerSummary>[] = [
  { prop: 'name', label: '球员', minWidth: 150, sortable: 'custom', showOverflowTooltip: true },
  { prop: 'age', label: '年龄', width: 64, align: 'right', sortable: 'custom' },
  { prop: 'position', label: '位置', width: 88, formatter: (row) => shortPosition(row.position) },
  { prop: 'club', label: '俱乐部', width: 132, showOverflowTooltip: true, formatter: (row) => displayText(row.club) },
  {
    prop: 'ca',
    label: '当前能力',
    width: 84,
    align: 'right',
    sortable: 'custom',
    title: 'CA（当前能力）：球员目前达到的能力水平',
  },
  {
    prop: 'pa',
    label: '潜力',
    width: 72,
    align: 'right',
    sortable: 'custom',
    title: 'PA（潜力）：球员可能达到的能力上限',
  },
  { prop: 'market_value', label: '身价', width: 96, align: 'right', sortable: 'custom', title: '按记录币种显示' },
  { prop: 'compare', label: '对比', width: 92, align: 'center' },
]

/** 是否存在任何生效中的筛选条件。 */
const hasActiveFilters = computed(() => Object.keys(players.filters).length > 0)

/** 数据完整度条目，默认折叠在「更多筛选」里，不占用主视线。 */
const coverageItems = computed(() => Object.entries(players.coverage))

/** 请求签名：筛选、分页、排序、存档或令牌变化时重新拉取。 */
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

/** 防抖加载：输入姓名时不会每敲一个字就发一次请求。 */
function scheduleReload(): void {
  if (reloadTimer) clearTimeout(reloadTimer)
  const delay = firstRun ? 0 : 220
  firstRun = false
  reloadTimer = setTimeout(() => {
    void players.load(session.activeSaveId)
  }, delay)
}

/** 俱乐部筛选项加载一次。 */
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

/** 关注名单总数：只取 total，不拉取整页数据。 */
async function loadWatchCount(): Promise<void> {
  try {
    const response = await listPlayers({
      save_id: session.activeSaveId ?? undefined,
      watchlist_only: true,
      limit: 1,
      offset: 0,
    })
    watchCount.value = response.total ?? 0
  } catch {
    // 统计失败不影响主列表，隐藏该指标即可。
    watchCount.value = null
  }
}

/** 列表里的位置只显示中文，完整代码在球员详情中查看。 */
function shortPosition(position: string | null | undefined): string {
  if (!position) return EMPTY
  return POSITION_LABELS[position.toUpperCase()] ?? position
}

/** 万 → 基础单位。 */
function onMaxValueChange(value: number | undefined): void {
  players.setFilter('max_value', value === undefined ? undefined : Math.round(value * 10_000))
}

/** 位置变化时同步清空位置组，避免两个条件互相冲突。 */
function setPosition(value: string | undefined): void {
  players.setFilter('position', value)
  if (value !== undefined) players.setFilter('position_group', undefined)
}

/** 清空全部条件。 */
function resetFilters(): void {
  maxValueWan.value = undefined
  players.reset()
}

/** 打开球员详情。 */
function openPlayer(row: PlayerSummary): void {
  void router.push(`/players/${row.instance_id}`)
}

/** 是否已在对比选择中。 */
function inCompare(row: PlayerSummary): boolean {
  return compare.ids.includes(row.instance_id)
}

/** 加入 / 移出对比。 */
function toggleCompare(row: PlayerSummary): void {
  compare.ensureSave(session.activeSaveId)
  if (inCompare(row)) {
    compare.remove(row.instance_id)
    ElMessage.info(`已移出对比：${row.name}`)
    return
  }
  const outcome = compare.add(row.instance_id)
  if (outcome === 'added') ElMessage.success(`已加入对比：${row.name}`)
  else if (outcome === 'full') ElMessage.warning(`对比最多 ${MAX_COMPARE} 名球员`)
}

/** 读取搜索或热力图带来的 URL 筛选，只应用一次。 */
function applyQueryFilters(): void {
  const { position_group: group, position, club_id: clubId, query } = route.query
  if (typeof position === 'string' && position) players.setFilter('position', position.toUpperCase())
  if (typeof group === 'string' && group) players.setFilter('position_group', group.toUpperCase())
  if (typeof clubId === 'string' && clubId) {
    const parsed = Number.parseInt(clubId, 10)
    if (Number.isInteger(parsed) && parsed > 0) players.setFilter('club_id', parsed)
  }
  if (typeof query === 'string' && query) players.setFilter('query', query)
}

/** 去数据中心同步游戏数据。 */
function goSync(): void {
  void router.push('/data')
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

applyQueryFilters()

watch(querySignature, scheduleReload, { immediate: true })
watch(
  [() => session.activeSaveId, () => session.dataRevision],
  () => {
    compare.ensureSave(session.activeSaveId)
    void loadWatchCount()
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  if (reloadTimer) clearTimeout(reloadTimer)
})

void loadClubs()
</script>

<template>
  <div class="sm-page">
    <PageHeader title="球员中心" description="寻找优秀球员，发现潜力新星。">
      <template #actions>
        <el-button size="small" @click="router.push('/compare')">
          球员对比（{{ compare.count }}/{{ MAX_COMPARE }}）
        </el-button>
        <el-button size="small" :loading="players.loading" @click="players.load(session.activeSaveId)">刷新</el-button>
      </template>
    </PageHeader>

    <FilterPanel
      title="筛选球员"
      hint="输入姓名即可搜索；条件变更后自动查询。"
    >
      <template #actions>
        <el-button v-if="hasActiveFilters" size="small" text @click="resetFilters">清除筛选</el-button>
      </template>

      <label class="sm-field field-search">
        <span class="sm-field__label">球员姓名</span>
        <el-input
          :model-value="players.filters.query ?? ''"
          size="large"
          clearable
          placeholder="输入球员姓名"
          aria-label="按球员姓名搜索"
          @update:model-value="(value) => players.setFilter('query', value === '' ? undefined : String(value))"
        >
          <template #prefix><span class="search-glyph" aria-hidden="true">⌕</span></template>
        </el-input>
      </label>

      <label class="sm-field">
        <span class="sm-field__label">位置</span>
        <el-select
          :model-value="players.filters.position"
          size="default"
          clearable
          filterable
          placeholder="全部位置"
          @update:model-value="(value) => setPosition(value === '' ? undefined : String(value))"
        >
          <el-option v-for="option in POSITION_OPTIONS" :key="option.value" :label="option.label" :value="option.value" />
        </el-select>
      </label>

      <div class="sm-field sm-field--pair">
        <span class="sm-field__label">年龄</span>
        <div class="sm-field__pair">
          <el-input-number
            :model-value="players.filters.min_age"
            size="default"
            :min="14"
            :max="60"
            :controls="false"
            placeholder="最小"
            aria-label="最小年龄"
            @update:model-value="(value) => players.setFilter('min_age', typeof value === 'number' ? value : undefined)"
          />
          <span class="sm-field__dash">–</span>
          <el-input-number
            :model-value="players.filters.max_age"
            size="default"
            :min="14"
            :max="60"
            :controls="false"
            placeholder="最大"
            aria-label="最大年龄"
            @update:model-value="(value) => players.setFilter('max_age', typeof value === 'number' ? value : undefined)"
          />
        </div>
      </div>

      <label class="sm-field">
        <span class="sm-field__label">俱乐部</span>
        <el-select
          :model-value="players.filters.club_id"
          size="default"
          clearable
          filterable
          :loading="clubsLoading"
          placeholder="全部俱乐部"
          @update:model-value="(value) => players.setFilter('club_id', typeof value === 'number' ? value : undefined)"
        >
          <el-option v-for="club in clubs" :key="club.club_id" :label="club.name" :value="club.club_id" />
        </el-select>
      </label>

      <label class="sm-field">
        <span class="sm-field__label">潜力上限</span>
        <el-input-number
          :model-value="players.filters.max_pa"
          size="default"
          :min="1"
          :max="200"
          :controls="false"
          placeholder="不限"
          aria-label="潜力上限"
          @update:model-value="(value) => players.setFilter('max_pa', typeof value === 'number' ? value : undefined)"
        />
      </label>

      <template #advanced>
        <label class="sm-field">
          <span class="sm-field__label">当前能力下限</span>
          <el-input-number
            :model-value="players.filters.min_ca"
            size="default"
            :min="1"
            :max="200"
            :controls="false"
            placeholder="不限"
            aria-label="当前能力下限"
            @update:model-value="(value) => players.setFilter('min_ca', typeof value === 'number' ? value : undefined)"
          />
        </label>

        <label class="sm-field">
          <span class="sm-field__label">位置组</span>
          <el-select
            :model-value="players.filters.position_group"
            size="default"
            clearable
            placeholder="全部位置组"
            @update:model-value="(value) => players.setFilter('position_group', value === '' ? undefined : String(value))"
          >
            <el-option v-for="group in POSITION_GROUPS" :key="group.value" :label="group.label" :value="group.value" />
          </el-select>
        </label>

        <label class="sm-field">
          <span class="sm-field__label">身价上限（万）</span>
          <el-input-number
            v-model="maxValueWan"
            size="default"
            :min="0"
            :step="100"
            :controls="false"
            placeholder="不限"
            aria-label="身价上限，单位万"
            @update:model-value="onMaxValueChange"
          />
        </label>

        <div class="sm-field">
          <span class="sm-field__label">只看关注名单</span>
          <el-switch
            :model-value="players.filters.watchlist_only === true"
            @update:model-value="(value) => players.setFilter('watchlist_only', value === true ? true : undefined)"
          />
        </div>

        <div v-if="coverageItems.length > 0" class="sm-field field-coverage">
          <span class="sm-field__label">数据完整度</span>
          <div class="coverage-chips">
            <span v-for="[key, value] in coverageItems" :key="key" class="coverage-chip">
              {{ coverageLabel(key) }} {{ formatPercent(value) }}
            </span>
          </div>
        </div>

        <p v-if="clubsError" class="field-error sm-text-2xs">俱乐部筛选项加载失败：{{ clubsError.message }}</p>
      </template>
    </FilterPanel>

    <div class="metrics">
      <KpiCard label="球员总数" :value="formatInt(players.total)" hint="当前存档" :loading="players.loading && players.items.length === 0" />
      <KpiCard
        v-if="watchCount !== null"
        label="已关注球员"
        :value="formatInt(watchCount)"
        hint="来自关注名单"
        tone="accent"
        to="/watchlist"
      />
    </div>

    <ValueScatterCard :save-id="session.activeSaveId" :club-id="players.filters.club_id ?? null" />

    <SectionCard title="球员列表" flush>
      <template #actions>
        <el-radio-group v-model="viewMode" size="small" aria-label="列表显示方式">
          <el-radio-button value="table">表格</el-radio-button>
          <el-radio-button value="cards">卡片</el-radio-button>
        </el-radio-group>
      </template>

      <DataTable
        v-if="viewMode === 'table'"
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
        caption="球员列表，可按年龄、当前能力、潜力与身价排序"
        @row-click="openPlayer"
        @sort-change="onSortChange"
        @update:page="onPageChange"
        @update:page-size="onPageSizeChange"
        @retry="players.load(session.activeSaveId)"
      >
        <template #empty>
          <EmptyState
            v-if="hasActiveFilters"
            title="没有找到符合条件的球员"
            description="当前筛选条件没有匹配结果。可以放宽条件，或清除筛选查看全部球员。"
            compact
          >
            <el-button size="small" type="primary" @click="resetFilters">清除筛选条件</el-button>
          </EmptyState>
          <EmptyState
            v-else
            title="还没有球员数据"
            description="同步 FM27 游戏数据后，球员就会显示在这里。"
            compact
          >
            <el-button size="small" type="primary" @click="goSync">同步游戏数据</el-button>
          </EmptyState>
        </template>

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
          <template v-else-if="column.prop === 'compare'">
            <button
              type="button"
              class="compare-btn"
              :class="{ 'compare-btn--active': inCompare(row) }"
              :aria-pressed="inCompare(row)"
              @click.stop="toggleCompare(row)"
            >
              {{ inCompare(row) ? '已加入' : '加入对比' }}
            </button>
          </template>
          <template v-else>
            {{ column.formatter ? column.formatter(row) : EMPTY }}
          </template>
        </template>
      </DataTable>

      <template v-else>
        <EmptyState
          v-if="players.items.length === 0 && !players.loading && !players.error"
          :title="hasActiveFilters ? '没有找到符合条件的球员' : '还没有球员数据'"
          :description="
            hasActiveFilters
              ? '当前筛选条件没有匹配结果。可以放宽条件，或清除筛选查看全部球员。'
              : '同步 FM27 游戏数据后，球员就会显示在这里。'
          "
          compact
        >
          <el-button v-if="hasActiveFilters" size="small" type="primary" @click="resetFilters">清除筛选条件</el-button>
          <el-button v-else size="small" type="primary" @click="goSync">同步游戏数据</el-button>
        </EmptyState>

        <div v-else class="player-cards">
          <article v-for="row in players.items" :key="row.instance_id" class="player-card">
            <header class="player-card__head">
              <button type="button" class="player-link" @click="openPlayer(row)">{{ displayText(row.name) }}</button>
              <span class="player-card__position">{{ shortPosition(row.position) }}</span>
            </header>
            <p class="player-card__meta">
              {{ row.age === null ? '年龄未知' : `${row.age} 岁` }} · {{ displayText(row.club) }}
            </p>
            <dl class="player-card__stats">
              <div><dt>CA</dt><dd>{{ formatInt(row.ca) }}</dd></div>
              <div><dt>PA</dt><dd>{{ formatInt(row.pa) }}</dd></div>
              <div><dt>身价</dt><dd>{{ formatMoney(row.market_value) }}</dd></div>
            </dl>
            <footer class="player-card__actions">
              <el-button size="small" text @click="openPlayer(row)">查看详情</el-button>
              <el-button size="small" text :type="inCompare(row) ? 'primary' : 'default'" @click="toggleCompare(row)">
                {{ inCompare(row) ? '已加入对比' : '加入对比' }}
              </el-button>
            </footer>
          </article>
        </div>

        <div v-if="players.items.length > 0" class="cards-pagination">
          <el-pagination
            :current-page="players.page"
            :page-size="players.pageSize"
            :page-sizes="[25, 50, 100, 200]"
            :total="players.total"
            layout="total, sizes, prev, pager, next"
            background
            @current-change="onPageChange"
            @size-change="onPageSizeChange"
          />
        </div>
      </template>
    </SectionCard>

    <p class="page-note">
      点击球员进入详情查看技术、身体、精神属性与合同信息；CA 指当前能力，PA 指潜力上限。
    </p>
  </div>
</template>

<style scoped>
.field-search {
  min-width: 220px;
}

.search-glyph {
  color: var(--sm-text-3);
  font-size: 15px;
}

.field-coverage {
  grid-column: 1 / -1;
}

.coverage-chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sm-space-1);
}

.coverage-chip {
  padding: 2px var(--sm-space-2);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-pill);
  color: var(--sm-text-2);
  font-size: var(--sm-fs-2xs);
  white-space: nowrap;
}

.field-error {
  grid-column: 1 / -1;
  color: var(--sm-danger);
}

.metrics {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: var(--sm-space-3);
}

.player-link {
  padding: 0;
  border: 0;
  background: none;
  color: var(--sm-accent-cyan);
  font: inherit;
  font-weight: var(--sm-fw-medium);
  text-align: left;
  cursor: pointer;
}

.player-link:hover {
  text-decoration: underline;
}

.page-note {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}

.compare-btn {
  padding: 2px 8px;
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-pill);
  background: transparent;
  color: var(--sm-text-2);
  font-size: var(--sm-fs-2xs);
  cursor: pointer;
}

.compare-btn:hover {
  border-color: var(--sm-border-glow);
  color: var(--sm-text-primary);
}

.compare-btn--active {
  border-color: rgba(34, 211, 238, 0.4);
  background: rgba(34, 211, 238, 0.12);
  color: var(--sm-accent-cyan);
}

.player-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
  gap: var(--sm-space-3);
  padding: var(--sm-space-3);
}

.player-card {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-2);
  padding: var(--sm-space-3);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-md);
  background: rgba(12, 23, 39, 0.55);
}

.player-card__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--sm-space-2);
}

.player-card__position {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}

.player-card__meta {
  color: var(--sm-text-2);
  font-size: var(--sm-fs-xs);
}

.player-card__stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--sm-space-2);
  margin: 0;
}

.player-card__stats dt {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}

.player-card__stats dd {
  margin: 0;
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-sm);
  font-variant-numeric: tabular-nums;
}

.player-card__actions {
  display: flex;
  justify-content: space-between;
  gap: var(--sm-space-2);
  border-top: 1px solid var(--sm-border);
  padding-top: var(--sm-space-1);
}

.cards-pagination {
  display: flex;
  justify-content: flex-end;
  padding: var(--sm-space-2) var(--sm-space-3) var(--sm-space-3);
}
</style>
