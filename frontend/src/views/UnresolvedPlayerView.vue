<script setup lang="ts">
/**
 * 待确认球员（SM-119）。
 *
 * 只展示证据与建议：没有任何候选被默认标成"已确认身份"。关联身份必须由人点确认按钮并再次确认，
 * 忽略候选不会删除观察记录。
 */

import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { asApiError, type ApiError } from '../api/client'
import {
  dismissUnresolvedPlayer,
  getUnresolvedPlayer,
  listUnresolvedObservations,
  listUnresolvedPlayers,
  resolveUnresolvedPlayer,
} from '../api/unresolved'
import DataTable from '../components/DataTable.vue'
import EmptyState from '../components/EmptyState.vue'
import KpiCard from '../components/KpiCard.vue'
import PageHeader from '../components/PageHeader.vue'
import SectionCard from '../components/SectionCard.vue'
import type { TableColumn } from '../types/table'
import type {
  UnresolvedCandidate,
  UnresolvedDetail,
  UnresolvedObservation,
  UnresolvedStatus,
} from '../types/unresolved'
import { displayText, formatDateTime, formatInt } from '../utils/format'

const STATUS_LABELS: Record<UnresolvedStatus, string> = {
  pending: '待确认',
  review_required: '需复核',
  resolved: '已确认关联',
  dismissed: '已忽略',
}

const UID_STATUS_LABELS: Record<string, string> = {
  sentinel: '上游哨兵 0xFFFFFFFF',
  missing: '上游未提供 ID',
  invalid: '非法 ID',
}

const items = ref<UnresolvedCandidate[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const error = ref<ApiError | null>(null)
const counts = ref({ pending: 0, review_required: 0, resolved: 0, dismissed: 0 })

const statusFilter = ref<'all' | UnresolvedStatus>('all')
const nameFilter = ref('')
const positionFilter = ref('')
const minCa = ref<number | undefined>(undefined)
const minPa = ref<number | undefined>(undefined)

const detail = ref<UnresolvedDetail | null>(null)
const detailError = ref<ApiError | null>(null)
const observations = ref<UnresolvedObservation[]>([])
const note = ref('')
const manualInstanceId = ref<number | undefined>(undefined)
const dismissReason = ref('')
const busy = ref(false)

const columns: TableColumn<UnresolvedCandidate>[] = [
  { prop: 'display_name', label: '姓名', width: 180 },
  { prop: 'position', label: '位置', width: 80, formatter: (row) => displayText(row.position) },
  {
    prop: 'ca',
    label: 'CA / PA',
    width: 100,
    formatter: (row) =>
      `${displayText(row.latest_observation?.ca)} / ${displayText(row.latest_observation?.pa)}`,
  },
  { prop: 'birth_date', label: '出生日期', width: 120, formatter: (row) => displayText(row.birth_date) },
  {
    prop: 'uid',
    label: 'UID 原始状态',
    width: 180,
    formatter: (row) => `${UID_STATUS_LABELS[row.uid.status] ?? row.uid.status}（${displayText(row.uid.raw_uid)}）`,
  },
  { prop: 'observation_count', label: '观察次数', width: 90, formatter: (row) => formatInt(row.observation_count) },
  { prop: 'first_seen_at', label: '首次发现', width: 160, formatter: (row) => formatDateTime(row.first_seen_at) },
  { prop: 'last_seen_at', label: '最近观察', width: 160, formatter: (row) => formatDateTime(row.last_seen_at) },
  {
    prop: 'status',
    label: '状态',
    width: 110,
    formatter: (row) => STATUS_LABELS[row.status] ?? row.status,
  },
]

const pendingCount = computed(() => counts.value.pending + counts.value.review_required)

async function reload(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const response = await listUnresolvedPlayers({
      status: statusFilter.value,
      name: nameFilter.value || undefined,
      position: positionFilter.value || undefined,
      min_ca: minCa.value ?? undefined,
      min_pa: minPa.value ?? undefined,
      page: page.value,
      page_size: pageSize.value,
    })
    items.value = response.items
    total.value = response.total
    counts.value = response.counts
  } catch (failure) {
    error.value = asApiError(failure)
  } finally {
    loading.value = false
  }
}

async function openDetail(row: UnresolvedCandidate): Promise<void> {
  detailError.value = null
  note.value = ''
  manualInstanceId.value = undefined
  dismissReason.value = ''
  observations.value = []
  try {
    detail.value = await getUnresolvedPlayer(row.id)
    const history = await listUnresolvedObservations(row.id, { page: 1, page_size: 20 })
    observations.value = history.items
  } catch (failure) {
    detail.value = null
    detailError.value = asApiError(failure)
    ElMessage.error(detailError.value.message)
  }
}

async function confirmLink(playerInstanceId: number): Promise<void> {
  const candidate = detail.value
  if (!candidate) return
  try {
    await ElMessageBox.confirm(
      `确认把「${candidate.display_name}」关联到球员实例 #${playerInstanceId}？这会写入审计记录，且不能撤销。`,
      '人工确认身份关联',
      { confirmButtonText: '确认关联', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  busy.value = true
  try {
    const response = await resolveUnresolvedPlayer(candidate.id, {
      player_instance_id: playerInstanceId,
      confirm: true,
      note: note.value || undefined,
    })
    ElMessage.success(response.note)
    await openDetail({ ...candidate, id: candidate.id })
    await reload()
  } catch (failure) {
    const apiError = asApiError(failure)
    ElMessage.error(
      apiError.code === 'unresolved_already_decided' ? '该候选已经处理过，不能重复确认。' : apiError.message,
    )
  } finally {
    busy.value = false
  }
}

async function confirmManualLink(): Promise<void> {
  if (!manualInstanceId.value) {
    ElMessage.warning('请先填写同一存档内的球员实例 ID')
    return
  }
  await confirmLink(manualInstanceId.value)
}

async function dismiss(): Promise<void> {
  const candidate = detail.value
  if (!candidate) return
  const reason = dismissReason.value.trim()
  if (!reason) {
    ElMessage.warning('请填写忽略原因（会写入审计）')
    return
  }
  try {
    await ElMessageBox.confirm(
      `忽略「${candidate.display_name}」？观察记录会保留，之后仍可查看。`,
      '忽略候选',
      { confirmButtonText: '忽略', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  busy.value = true
  try {
    const response = await dismissUnresolvedPlayer(candidate.id, {
      reason,
      note: note.value || undefined,
    })
    ElMessage.success(`已忽略；保留 ${response.observations_kept} 条观察记录`)
    await openDetail({ ...candidate, id: candidate.id })
    await reload()
  } catch (failure) {
    const apiError = asApiError(failure)
    ElMessage.error(
      apiError.code === 'unresolved_already_dismissed' ? '该候选已经被忽略。' : apiError.message,
    )
  } finally {
    busy.value = false
  }
}

function onPage(value: number): void {
  page.value = value
  void reload()
}

function onPageSize(value: number): void {
  pageSize.value = value
  page.value = 1
  void reload()
}

function applyFilters(): void {
  page.value = 1
  void reload()
}

onMounted(reload)
</script>

<template>
  <section class="unresolved">
    <PageHeader
      title="待确认球员"
      subtitle="缺少可用身份信息的球员会先保存在这里，确认之前不进入任何正式统计。"
    >
      <template #actions>
        <el-button size="small" :loading="loading" @click="reload">刷新</el-button>
      </template>
    </PageHeader>

    <div class="unresolved__counters">
      <KpiCard label="待确认" :value="formatInt(counts.pending)" hint="需要人工判断身份" />
      <KpiCard label="需复核" :value="formatInt(counts.review_required)" hint="存在匹配建议，但建议不是事实" />
      <KpiCard label="已确认关联" :value="formatInt(counts.resolved)" hint="人工关联到既有身份" />
      <KpiCard label="已忽略" :value="formatInt(counts.dismissed)" hint="观察记录仍保留" />
    </div>

    <SectionCard title="筛选" dense>
      <div class="unresolved__filters">
        <el-select v-model="statusFilter" size="small" style="width: 140px" aria-label="状态" @change="applyFilters">
          <el-option label="全部状态" value="all" />
          <el-option label="待确认" value="pending" />
          <el-option label="需复核" value="review_required" />
          <el-option label="已确认" value="resolved" />
          <el-option label="已忽略" value="dismissed" />
        </el-select>
        <el-input
          v-model="nameFilter"
          size="small"
          placeholder="姓名"
          style="width: 180px"
          clearable
          aria-label="姓名筛选"
          @change="applyFilters"
        />
        <el-input
          v-model="positionFilter"
          size="small"
          placeholder="位置（如 ST）"
          style="width: 130px"
          clearable
          aria-label="位置筛选"
          @change="applyFilters"
        />
        <el-input-number
          v-model="minCa"
          size="small"
          :min="0"
          :max="400"
          :controls="false"
          placeholder="最低 CA"
          aria-label="最低 CA"
          style="width: 100px"
          @change="applyFilters"
        />
        <el-input-number
          v-model="minPa"
          size="small"
          :min="0"
          :max="400"
          :controls="false"
          placeholder="最低 PA"
          aria-label="最低 PA"
          style="width: 100px"
          @change="applyFilters"
        />
        <el-button size="small" @click="applyFilters">查询</el-button>
        <span class="unresolved__muted">共 {{ formatInt(total) }} 条；待处理 {{ formatInt(pendingCount) }} 条</span>
      </div>
    </SectionCard>

    <div class="unresolved__layout">
      <SectionCard title="候选列表" dense class="unresolved__list">
        <DataTable
          :columns="columns"
          :rows="items"
          row-key="id"
          :loading="loading"
          :error="error"
          :total="total"
          :page="page"
          :page-size="pageSize"
          :page-sizes="[20, 50, 100]"
          show-pagination
          clickable
          empty-title="暂无待确认球员"
          empty-description="扫描导入后，没有可用身份的球员会出现在这里"
          @update:page="onPage"
          @update:page-size="onPageSize"
          @row-click="openDetail"
          @retry="reload"
        />
      </SectionCard>

      <SectionCard
        v-if="detail"
        :title="`候选 #${detail.id} · ${detail.display_name}`"
        dense
        class="unresolved__detail"
      >
        <div class="unresolved__detail-body">
          <el-alert
            type="warning"
            :closable="false"
            show-icon
            title="这只是待确认观察，不是已确认身份"
            description="系统不会自动把候选并入任何球员；请对照证据后人工确认，或忽略候选。"
          />

          <div class="unresolved__facts">
            <dl>
              <dt>状态</dt><dd>{{ STATUS_LABELS[detail.status] }}</dd>
              <dt>位置</dt><dd>{{ displayText(detail.position) }}</dd>
              <dt>CA / PA</dt>
              <dd>{{ displayText(detail.latest_observation?.ca) }} / {{ displayText(detail.latest_observation?.pa) }}</dd>
              <dt>出生日期</dt><dd>{{ displayText(detail.birth_date) }}</dd>
              <dt>国籍</dt><dd>{{ displayText(detail.nationality) }}</dd>
              <dt>俱乐部</dt><dd>{{ displayText(detail.latest_observation?.club_name) }}</dd>
              <dt>合同到期</dt><dd>{{ displayText(detail.latest_observation?.contract_end) }}</dd>
              <dt>首次发现</dt><dd>{{ formatDateTime(detail.first_seen_at) }}</dd>
              <dt>最近观察</dt><dd>{{ formatDateTime(detail.last_seen_at) }}</dd>
              <dt>观察次数</dt><dd>{{ formatInt(detail.observation_count) }}</dd>
              <dt>所属存档</dt><dd>存档 #{{ detail.save_id }}</dd>
            </dl>
          </div>

          <div class="unresolved__uid">
            <h4>UID 原始状态</h4>
            <p>
              {{ UID_STATUS_LABELS[detail.uid.status] ?? detail.uid.status }}
              <span class="sm-mono">（{{ displayText(detail.uid.raw_uid) }}）</span>
            </p>
            <p class="unresolved__muted">{{ detail.uid.note }}</p>
          </div>

          <div class="unresolved__suggestions">
            <h4>匹配建议（建议，不是事实）</h4>
            <p v-if="!detail.suggestions.player_matches.length" class="unresolved__muted">
              没有找到姓名相同的既有球员。可以填写球员实例 ID 手工关联。
            </p>
            <ul v-else>
              <li v-for="match in detail.suggestions.player_matches" :key="match.player_instance_id">
                <span class="unresolved__match">
                  {{ match.name }}（实例 #{{ match.player_instance_id }}，UID {{ displayText(match.save_local_uid) }}）
                  · 置信度 {{ Math.round(match.confidence * 100) }}%
                </span>
                <span class="unresolved__muted">{{ match.reasons.join('；') }}</span>
                <el-button
                  size="small"
                  type="primary"
                  :disabled="busy || detail.status === 'resolved' || detail.status === 'dismissed'"
                  @click="confirmLink(match.player_instance_id)"
                >
                  确认关联
                </el-button>
              </li>
            </ul>
            <div v-if="detail.suggestions.sibling_candidates.length" class="unresolved__siblings">
              <p class="unresolved__muted">同名候选（不会自动合并）：</p>
              <ul>
                <li v-for="sibling in detail.suggestions.sibling_candidates" :key="sibling.candidate_id">
                  #{{ sibling.candidate_id }} · {{ sibling.display_name }} · {{ sibling.status }}
                </li>
              </ul>
            </div>
          </div>

          <div class="unresolved__actions">
            <el-input v-model="note" size="small" placeholder="处理备注（写入审计）" maxlength="512" />
            <div class="unresolved__row">
              <el-input-number
                v-model="manualInstanceId"
                size="small"
                :min="1"
                :controls="false"
                placeholder="球员实例 ID"
                aria-label="球员实例 ID"
              />
              <el-button
                size="small"
                type="primary"
                :loading="busy"
                :disabled="detail.status === 'resolved' || detail.status === 'dismissed'"
                @click="confirmManualLink"
              >
                确认身份关联
              </el-button>
            </div>
            <div class="unresolved__row">
              <el-input v-model="dismissReason" size="small" placeholder="忽略原因（必填，写入审计）" maxlength="256" />
              <el-button
                size="small"
                :loading="busy"
                :disabled="detail.status === 'dismissed'"
                @click="dismiss"
              >
                忽略候选
              </el-button>
            </div>
          </div>

          <div class="unresolved__history">
            <h4>历史观察</h4>
            <p v-if="!observations.length" class="unresolved__muted">没有可展示的观察记录。</p>
            <ul v-else class="unresolved__observations">
              <li v-for="item in observations" :key="item.id">
                {{ formatDateTime(item.observed_at) }} · scan {{ item.scan_id }} · 行 {{ item.row_index }} ·
                {{ item.uid_status }} · CA {{ displayText(item.ca) }} / PA {{ displayText(item.pa) }} ·
                {{ displayText(item.club_name) }}
              </li>
            </ul>
          </div>

          <div class="unresolved__history">
            <h4>人工操作审计</h4>
            <p v-if="!detail.history.length" class="unresolved__muted">还没有人工操作。</p>
            <ul v-else>
              <li v-for="entry in detail.history" :key="entry.id">
                {{ formatDateTime(entry.created_at) }} · {{ entry.action }} · {{ entry.decision }} ·
                {{ entry.note || '无备注' }}
              </li>
            </ul>
            <p class="unresolved__muted">{{ detail.retention }}</p>
          </div>

          <div class="unresolved__history">
            <h4>来源证据</h4>
            <pre class="unresolved__evidence">{{ JSON.stringify(detail.evidence_summary, null, 2) }}</pre>
          </div>
        </div>
      </SectionCard>

      <div v-else class="unresolved__detail">
        <EmptyState
          v-if="!detailError"
          title="选择一名候选查看证据"
          description="左侧列表来自当前存档的无身份观察；确认与忽略都会写入审计"
        />
        <EmptyState
          v-else
          variant="error"
          title="无法查看该候选"
          :description="detailError.message"
        />
      </div>
    </div>
  </section>
</template>

<style scoped>
.unresolved__counters {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
  margin-bottom: 12px;
}
.unresolved__filters {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
}
.unresolved__muted {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.unresolved__layout {
  display: grid;
  grid-template-columns: minmax(0, 3fr) minmax(340px, 2fr);
  gap: 12px;
  align-items: start;
}
@media (max-width: 1100px) {
  .unresolved__layout {
    grid-template-columns: 1fr;
  }
}
.unresolved__detail-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
  font-size: 13px;
}
.unresolved__facts dl {
  display: grid;
  grid-template-columns: 76px 1fr;
  gap: 4px 8px;
  margin: 0;
}
.unresolved__facts dt {
  color: var(--el-text-color-secondary);
}
.unresolved__facts dd {
  margin: 0;
}
.unresolved__actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.unresolved__row {
  display: flex;
  gap: 8px;
  align-items: center;
}
.unresolved__suggestions ul,
.unresolved__history ul {
  padding-left: 18px;
  margin: 6px 0;
}
.unresolved__suggestions li {
  margin-bottom: 4px;
}
.unresolved__match {
  display: block;
}
.unresolved__evidence {
  max-height: 180px;
  overflow: auto;
  padding: 8px;
  border-radius: 6px;
  background: var(--el-fill-color-light);
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
