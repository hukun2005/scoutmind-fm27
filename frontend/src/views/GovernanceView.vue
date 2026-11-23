<template>
  <section class="governance">
    <PageHeader
      title="数据治理中心"
      description="同日冲突、canonical 审核与成长时间轴；原始快照永不删除，人工决策全部留痕"
    >
      <template #actions>
        <el-button size="small" :loading="loading" @click="reloadAll">刷新</el-button>
        <el-button size="small" :disabled="!queue.length" @click="exportCsv">导出当前页 CSV</el-button>
      </template>
    </PageHeader>

    <div class="governance__kpis">
      <KpiCard label="原始快照" :value="fmt(overview?.total_snapshots)" :loading="overviewLoading" hint="不过滤、不删除" />
      <KpiCard label="独立 game_date" :value="fmt(overview?.unique_game_dates)" :loading="overviewLoading" />
      <KpiCard label="Canonical 组" :value="fmt(overview?.canonical_groups)" :loading="overviewLoading" />
      <KpiCard label="自动确认" :value="fmt(overview?.resolved_auto)" :loading="overviewLoading" hint="单条或内容一致" />
      <KpiCard label="人工确认" :value="fmt(overview?.resolved_manual)" :loading="overviewLoading" tone="accent" />
      <KpiCard label="待审核" :value="fmt(overview?.needs_review)" :loading="overviewLoading" tone="warn" />
      <KpiCard label="已排除" :value="fmt(overview?.excluded)" :loading="overviewLoading" tone="danger" />
      <KpiCard label="质量异常计数" :value="fmt(overview?.quality_anomalies)" :loading="overviewLoading" tone="warn" />
    </div>

    <SectionCard v-if="overview" title="审核进度与冲突类型" dense>
      <div class="governance__progress">
        <div class="governance__progress-head">
          <span>待审核 {{ fmt(overview.needs_review) }} / {{ fmt(overview.canonical_groups) }} 组</span>
          <span>{{ progressLabel }}</span>
        </div>
        <el-progress :percentage="progressPercent" :stroke-width="10" :show-text="false" />
        <div class="governance__types">
          <el-tag v-for="item in overview.conflict_types" :key="item.type" size="small" type="warning" effect="plain">
            {{ conflictLabel(item.type) }} · {{ fmt(item.count) }}
          </el-tag>
          <span v-if="!overview.conflict_types.length" class="governance__muted">当前没有待审核冲突类型</span>
        </div>
      </div>
    </SectionCard>

    <SectionCard title="Canonical 审核队列" subtitle="冲突组不会被自动选中；打开一组查看快照差异与人工决策" dense>
      <div class="governance__filters">
        <el-select v-model="filters.status" size="small" style="width: 150px" @change="reloadQueue(true)">
          <el-option label="待审核" value="needs_review" />
          <el-option label="人工确认" value="resolved_manual" />
          <el-option label="已排除" value="excluded" />
          <el-option label="需复核" value="review_required" />
          <el-option label="自动确认" value="resolved" />
          <el-option label="全部" value="all" />
        </el-select>
        <el-input
          v-model="filters.player"
          size="small"
          clearable
          placeholder="球员姓名 / UID"
          style="width: 190px"
          @keyup.enter="reloadQueue(true)"
        />
        <el-date-picker
          v-model="filters.game_date"
          size="small"
          type="date"
          value-format="YYYY-MM-DD"
          placeholder="game_date"
          style="width: 140px"
          @change="reloadQueue(true)"
        />
        <el-select v-model="filters.conflict_type" size="small" style="width: 180px" @change="reloadQueue(true)">
          <el-option label="全部冲突类型" value="" />
          <el-option v-for="item in conflictOptions" :key="item" :label="conflictLabel(item)" :value="item" />
        </el-select>
        <el-button size="small" @click="reloadQueue(true)">查询</el-button>
        <el-button size="small" text @click="resetFilters">重置</el-button>
      </div>

      <DataTable
        :columns="queueColumns"
        :rows="queue"
        row-key="id"
        :loading="queueLoading"
        :error="queueError"
        :total="queueTotal"
        :page="page"
        :page-size="pageSize"
        show-pagination
        clickable
        @update:page="onPage"
        @update:page-size="onPageSize"
        @row-click="selectRow"
      >
        <template #cell="{ row, column }">
          <span v-if="column.prop === 'conflict_types'">
            <el-tag v-for="type in row.conflict_types || []" :key="type" size="small" type="warning" effect="plain" class="governance__tag">
              {{ conflictLabel(type) }}
            </el-tag>
          </span>
          <span v-else-if="column.prop === 'status'">
            <el-tag size="small" :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag>
          </span>
          <span v-else>{{ cellValue(row, column.prop) }}</span>
        </template>
      </DataTable>
    </SectionCard>

    <SectionCard v-if="detail" :title="`${detail.canonical.player_name} · ${detail.canonical.game_date}`" dense>
      <template #actions>
        <el-tag size="small" :type="statusType(detail.canonical.status)">{{ statusLabel(detail.canonical.status) }}</el-tag>
      </template>

      <div class="governance__detail-meta">
        <span>UID {{ detail.canonical.player_uid }}</span>
        <span>快照 {{ detail.snapshots.length }} 条</span>
        <span>不同内容 {{ detail.canonical.distinct_content_count }} 种</span>
        <span>{{ detail.canonical.reason }}</span>
        <span v-if="detail.suggestion">
          风险 {{ detail.suggestion.risk_score }} · {{ detail.suggestion.priority }} · 建议 #{{ detail.suggestion.recommended_snapshot_id ?? '—' }}（仅建议，未写入）
        </span>
      </div>

      <h4 class="governance__subhead">核心字段差异</h4>
      <div class="governance__diff-scroll">
        <table class="governance__diff">
          <thead>
            <tr>
              <th>字段</th>
              <th v-for="snapshot in detail.snapshots" :key="snapshot.id">
                #{{ snapshot.id }}<br />
                <small>{{ formatDateTime(snapshot.observed_at) }}</small><br />
                <small>{{ snapshot.source || '未知来源' }} · {{ snapshot.reader_version || '—' }}</small>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in coreRows" :key="row.key" :class="{ 'governance__diff-row--changed': row.changed }">
              <th>{{ row.label }}</th>
              <td v-for="(value, index) in row.values" :key="index" :class="{ 'governance__diff-cell--changed': row.changed }">
                {{ value }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <h4 class="governance__subhead">全部属性（来自真实数据字典，缺失显示 —）</h4>
      <div class="governance__diff-scroll">
        <table class="governance__diff">
          <thead>
            <tr>
              <th>属性</th>
              <th v-for="snapshot in detail.snapshots" :key="snapshot.id">#{{ snapshot.id }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in attributeRows" :key="row.key" :class="{ 'governance__diff-row--changed': row.changed }">
              <th>{{ row.label }}</th>
              <td v-for="(value, index) in row.values" :key="index" :class="{ 'governance__diff-cell--changed': row.changed }">
                {{ value }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="governance__review">
        <h4 class="governance__subhead">人工决策</h4>
        <el-radio-group v-model="decision.action" size="small">
          <el-radio value="select_snapshot">选择一条作为 canonical</el-radio>
          <el-radio value="exclude_game_date">排除该 game_date</el-radio>
          <el-radio value="keep_pending">保持待审核</el-radio>
        </el-radio-group>
        <el-select
          v-if="decision.action === 'select_snapshot'"
          v-model="decision.selected_snapshot_id"
          size="small"
          placeholder="选择快照"
          style="width: 220px; margin-left: 12px"
        >
          <el-option v-for="snapshot in detail.snapshots" :key="snapshot.id" :label="`#${snapshot.id} · ${formatDateTime(snapshot.observed_at)}`" :value="snapshot.id" />
        </el-select>
        <el-input v-model="decision.reason" size="small" type="textarea" :rows="2" placeholder="审核理由（必填，会写入审计）" class="governance__reason" />
        <div class="governance__submit">
          <el-button type="primary" size="small" :loading="submitting" @click="submitDecision">提交审核</el-button>
          <span class="governance__muted">提交前会二次确认；不会删除任何原始快照。</span>
        </div>
      </div>

      <div class="governance__history">
        <h4 class="governance__subhead">审核历史（只追加）</h4>
        <p v-if="!history.length" class="governance__muted">还没有人工审核记录。</p>
        <ul v-else>
          <li v-for="entry in history" :key="entry.id">
            {{ formatDateTime(entry.created_at) }} · {{ actionLabel(entry.action) }} · {{ entry.previous_status }} → {{ entry.new_status }} · {{ entry.reason }}
          </li>
        </ul>
      </div>

      <h4 class="governance__subhead">成长时间轴（canonical）</h4>
      <table class="governance__timeline">
        <thead><tr><th>game_date</th><th>状态</th><th>canonical 快照</th><th>说明</th></tr></thead>
        <tbody>
          <tr v-for="point in detail.timeline" :key="point.id">
            <td>{{ point.game_date }}</td>
            <td><el-tag size="small" :type="statusType(point.status)">{{ statusLabel(point.status) }}</el-tag></td>
            <td>{{ point.canonical_snapshot_id ? `#${point.canonical_snapshot_id}` : '—（不纳入）' }}</td>
            <td>{{ point.reason }}</td>
          </tr>
        </tbody>
      </table>
    </SectionCard>

    <EmptyState v-else title="选择一组 canonical 冲突" hint="左侧队列按冲突严重程度排序；审核会写入审计历史" />
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { asApiError, type ApiError } from '../api/client'
import { getCanonicalDetail, getGovernanceOverview, getReviewHistory, getReviewQueue, submitReviewDecision } from '../api/governance'
import DataTable from '../components/DataTable.vue'
import EmptyState from '../components/EmptyState.vue'
import KpiCard from '../components/KpiCard.vue'
import PageHeader from '../components/PageHeader.vue'
import SectionCard from '../components/SectionCard.vue'
import type { TableColumn } from '../types/table'
import type {
  CanonicalDetail,
  DecisionAction,
  GovernanceOverview,
  ReviewAction,
  ReviewQueueItem,
} from '../types/governance'
import { formatDateTime, formatInt, formatMoney } from '../utils/format'
import { useSessionStore } from '../stores/session'

const session = useSessionStore()
const overview = ref<GovernanceOverview | null>(null)
const overviewLoading = ref(false)
const queue = ref<ReviewQueueItem[]>([])
const queueLoading = ref(false)
const queueError = ref<ApiError | null>(null)
const queueTotal = ref(0)
const page = ref(1)
const pageSize = ref(20)
const detail = ref<CanonicalDetail | null>(null)
const history = ref<ReviewAction[]>([])
const loading = ref(false)
const submitting = ref(false)
const decision = ref<{ action: DecisionAction; selected_snapshot_id: number | null; reason: string }>({
  action: 'select_snapshot',
  selected_snapshot_id: null,
  reason: '',
})
const filters = ref({ status: 'needs_review', player: '', game_date: '', conflict_type: '' })

const fmt = (value: number | null | undefined) => formatInt(value ?? 0)
const progressPercent = computed(() => {
  if (!overview.value?.canonical_groups) return 0
  return Math.round((overview.value.needs_review / overview.value.canonical_groups) * 100)
})
const progressLabel = computed(() => `${progressPercent.value}% 待处理`)

const conflictOptions = computed(() => overview.value?.conflict_types.map((item) => item.type) ?? [])

function cellValue(row: ReviewQueueItem, prop: string): string {
  const value = (row as unknown as Record<string, unknown>)[prop]
  return value === null || value === undefined ? '—' : String(value)
}

const queueColumns: TableColumn<ReviewQueueItem>[] = [
  { prop: 'player_name', label: '球员', minWidth: 150 },
  { prop: 'player_uid', label: 'UID', width: 100 },
  { prop: 'game_date', label: 'game_date', width: 110 },
  { prop: 'snapshot_count', label: '快照', width: 70, align: 'right' },
  { prop: 'conflict_types', label: '冲突类型', minWidth: 220 },
  { prop: 'status', label: '状态', width: 100 },
]

interface DiffRow {
  key: string
  label: string
  values: string[]
  changed: boolean
}

const coreFields: Array<{ key: keyof CanonicalDetail['snapshots'][number]; label: string; money?: boolean }> = [
  { key: 'ca', label: 'CA' },
  { key: 'pa', label: 'PA' },
  { key: 'wage', label: '工资', money: true },
  { key: 'market_value', label: '身价', money: true },
  { key: 'contract_end', label: '合同到期' },
  { key: 'club_name', label: '俱乐部' },
  { key: 'position', label: '位置' },
  { key: 'height_cm', label: '身高' },
  { key: 'foot', label: '惯用脚' },
  { key: 'source', label: '来源' },
  { key: 'reader_version', label: 'Reader 版本' },
  { key: 'game_build', label: '游戏构建' },
]

function display(value: unknown, money = false): string {
  if (value === null || value === undefined || value === '') return '—'
  if (money && typeof value === 'number') return formatMoney(value)
  return String(value)
}

const coreRows = computed<DiffRow[]>(() => {
  if (!detail.value) return []
  return coreFields.map((field) => {
    const values = detail.value!.snapshots.map((snapshot) => display(snapshot[field.key], field.money))
    return { key: String(field.key), label: field.label, values, changed: new Set(values).size > 1 }
  })
})

const attributeRows = computed<DiffRow[]>(() => {
  if (!detail.value) return []
  const byKey = new Map<string, { label: string; values: string[] }>()
  detail.value.snapshots.forEach((snapshot, index) => {
    for (const attribute of snapshot.attributes) {
      if (!byKey.has(attribute.key)) {
        byKey.set(attribute.key, { label: attribute.name_zh || attribute.name, values: detail.value!.snapshots.map(() => '—') })
      }
      byKey.get(attribute.key)!.values[index] = String(attribute.value)
    }
  })
  return [...byKey.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([key, row]) => ({ key, label: row.label, values: row.values, changed: new Set(row.values).size > 1 }))
})

function statusLabel(status: string): string {
  return ({ resolved: '自动确认', resolved_auto: '自动确认', resolved_manual: '人工确认', needs_review: '待审核', excluded: '已排除', review_required: '需复核' } as Record<string, string>)[status] ?? status
}
function statusType(status: string): 'success' | 'warning' | 'danger' | 'info' {
  if (status === 'resolved' || status === 'resolved_auto' || status === 'resolved_manual') return 'success'
  if (status === 'needs_review') return 'warning'
  if (status === 'excluded') return 'danger'
  return 'info'
}
function conflictLabel(type: string): string {
  return ({ ability_changed: '能力', contract_changed: '合同', valuation_changed: '身价', club_changed: '俱乐部', position_changed: '位置', physical_data_changed: '身体', missing_vs_present: '缺失/有值', source_changed: '来源', reader_version_changed: 'Reader 版本', mixed_changes: '混合变化' } as Record<string, string>)[type] ?? type
}
function actionLabel(action: string): string {
  return ({ select_snapshot: '选择快照', exclude_game_date: '排除日期', keep_pending: '保持待审' } as Record<string, string>)[action] ?? action
}

async function loadOverview(): Promise<void> {
  overviewLoading.value = true
  try {
    overview.value = await getGovernanceOverview()
  } catch (error) {
    ElMessage.error(asApiError(error).message)
  } finally {
    overviewLoading.value = false
  }
}

async function reloadQueue(reset = false): Promise<void> {
  if (reset) page.value = 1
  queueLoading.value = true
  queueError.value = null
  try {
    const response = await getReviewQueue({
      status: filters.value.status === 'all' ? undefined : filters.value.status,
      player: filters.value.player || undefined,
      game_date: filters.value.game_date || undefined,
      conflict_type: filters.value.conflict_type || undefined,
      limit: pageSize.value,
      offset: (page.value - 1) * pageSize.value,
    })
    queue.value = response.items
    queueTotal.value = response.total
  } catch (error) {
    queueError.value = asApiError(error)
  } finally {
    queueLoading.value = false
  }
}

async function selectRow(row: ReviewQueueItem): Promise<void> {
  try {
    detail.value = await getCanonicalDetail(row.id)
    history.value = (await getReviewHistory(row.id)).items
    decision.value = { action: 'select_snapshot', selected_snapshot_id: null, reason: '' }
  } catch (error) {
    ElMessage.error(asApiError(error).message)
  }
}

async function submitDecision(): Promise<void> {
  if (!detail.value) return
  if (!decision.value.reason.trim()) {
    ElMessage.warning('必须填写审核理由')
    return
  }
  if (decision.value.action === 'select_snapshot' && !decision.value.selected_snapshot_id) {
    ElMessage.warning('请选择一条快照')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确认对 ${detail.value.canonical.player_name}（${detail.value.canonical.game_date}）执行“${actionLabel(decision.value.action)}”？`,
      '确认审核',
      { type: 'warning' },
    )
  } catch {
    return
  }
  submitting.value = true
  try {
    await submitReviewDecision(detail.value.canonical.id, {
      action: decision.value.action,
      selected_snapshot_id: decision.value.action === 'select_snapshot' ? decision.value.selected_snapshot_id : null,
      reason: decision.value.reason.trim(),
    })
    ElMessage.success('审核已记录')
    await Promise.all([loadOverview(), reloadQueue(), selectRow(detail.value.canonical)])
  } catch (error) {
    ElMessage.error(asApiError(error).message)
  } finally {
    submitting.value = false
  }
}

function resetFilters(): void {
  filters.value = { status: 'needs_review', player: '', game_date: '', conflict_type: '' }
  void reloadQueue(true)
}

function onPage(value: number): void { page.value = value; void reloadQueue() }
function onPageSize(value: number): void { pageSize.value = value; page.value = 1; void reloadQueue() }

async function reloadAll(): Promise<void> {
  loading.value = true
  try {
    await Promise.all([loadOverview(), reloadQueue()])
  } finally {
    loading.value = false
  }
}

function exportCsv(): void {
  const head = ['id', 'player_name', 'player_uid', 'game_date', 'snapshot_count', 'conflict_types', 'status', 'reason']
  const rows = queue.value.map((item) => [item.id, item.player_name, item.player_uid, item.game_date, item.snapshot_count, item.conflict_types.join('|'), item.status, item.reason])
  const escape = (value: unknown) => `"${String(value ?? '').replaceAll('"', '""')}"`
  const csv = [head, ...rows].map((row) => row.map(escape).join(',')).join('\r\n')
  const blob = new Blob([`\ufeff${csv}`], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `canonical-review-${new Date().toISOString().slice(0, 10)}.csv`
  link.click()
  URL.revokeObjectURL(url)
}

watch(() => session.activeSaveId, () => { void reloadAll() })
onMounted(() => { void reloadAll() })
</script>

<style scoped>
.governance { display: flex; flex-direction: column; gap: var(--sm-space-4); }
.governance__kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: var(--sm-space-3); }
.governance__progress { display: flex; flex-direction: column; gap: 10px; }
.governance__progress-head { display: flex; justify-content: space-between; color: var(--sm-text-2); font-size: var(--sm-fs-sm); }
.governance__types { display: flex; flex-wrap: wrap; gap: 6px; }
.governance__filters { display: flex; flex-wrap: wrap; gap: 8px; padding: 0 var(--sm-space-3) var(--sm-space-3); }
.governance__tag { margin-right: 4px; }
.governance__detail-meta { display: flex; flex-wrap: wrap; gap: 16px; padding: 0 var(--sm-space-4) var(--sm-space-3); color: var(--sm-text-2); font-size: var(--sm-fs-sm); }
.governance__subhead { margin: var(--sm-space-3) var(--sm-space-4) 8px; font-size: var(--sm-fs-sm); color: var(--sm-text-2); }
.governance__diff-scroll { overflow: auto; max-height: 360px; margin: 0 var(--sm-space-4); border: 1px solid var(--sm-border); border-radius: var(--sm-radius-md); }
.governance__diff { width: 100%; border-collapse: collapse; font-size: var(--sm-fs-sm); }
.governance__diff th, .governance__diff td { padding: 6px 10px; border-bottom: 1px solid var(--sm-border); text-align: left; white-space: nowrap; }
.governance__diff thead th { position: sticky; top: 0; z-index: 1; background: var(--sm-surface-2); color: var(--sm-text-2); font-size: var(--sm-fs-xs); }
.governance__diff-row--changed th, .governance__diff-cell--changed { background: rgba(210, 150, 60, 0.12); }
.governance__review { margin: var(--sm-space-4); padding: var(--sm-space-3); border: 1px solid var(--sm-border); border-radius: var(--sm-radius-md); background: var(--sm-surface-2); }
.governance__reason { margin-top: 10px; max-width: 780px; }
.governance__submit { display: flex; align-items: center; gap: 12px; margin-top: 10px; }
.governance__history { margin: 0 var(--sm-space-4); font-size: var(--sm-fs-sm); color: var(--sm-text-2); }
.governance__history ul { margin: 0; padding-left: 18px; }
.governance__timeline { width: calc(100% - var(--sm-space-8)); margin: 0 var(--sm-space-4) var(--sm-space-4); border-collapse: collapse; font-size: var(--sm-fs-sm); }
.governance__timeline th, .governance__timeline td { padding: 6px 10px; border-bottom: 1px solid var(--sm-border); text-align: left; }
.governance__muted { color: var(--sm-text-3); font-size: var(--sm-fs-sm); }
@media (max-width: 1100px) { .governance__kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
