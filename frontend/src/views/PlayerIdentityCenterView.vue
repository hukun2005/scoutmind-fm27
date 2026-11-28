<template>
  <section class="sm-page identity-center">
    <PageHeader
      title="身份中心"
      subtitle="同名、重复身份与跨存档候选都会列在这里等待确认，系统不会自动合并。"
    >
      <template #actions>
        <el-button size="small" type="primary" :loading="loading" @click="reloadAll">刷新</el-button>
      </template>
    </PageHeader>

    <el-alert
      v-if="error"
      type="error"
      show-icon
      :closable="false"
      :title="error.isNetworkError ? '无法连接后端' : '身份中心请求失败'"
    >
      <p class="idc-alert-text">{{ error.message }}</p>
    </el-alert>

    <div class="sm-grid sm-grid--kpi">
      <KpiCard
        label="球员实例"
        :value="formatInt(summary?.player_instances ?? 0)"
        hint="当前存档"
        :loading="loading && !summary"
      />
      <KpiCard
        label="唯一 UID"
        :value="formatInt(summary?.uid.distinct_save_local_uids ?? 0)"
        hint="存档内关联键"
        :loading="loading && !summary"
      />
      <KpiCard
        label="重复 UID"
        :value="formatInt(summary?.uid.duplicate_uid_count ?? 0)"
        hint="不自动合并"
        :tone="(summary?.uid.duplicate_uid_count ?? 0) > 0 ? 'warn' : 'default'"
        :loading="loading && !summary"
      />
      <KpiCard
        label="待人工审核"
        :value="formatInt(summary?.reviews.PendingHumanReview ?? 0)"
        hint="同名 / UID / 转会"
        :tone="(summary?.reviews.PendingHumanReview ?? 0) > 0 ? 'warn' : 'default'"
        :loading="loading && !summary"
      />
      <KpiCard
        label="已验证关联"
        :value="formatInt(summary?.identity_links.ConfirmedByHuman ?? 0)"
        hint="人工确认，非 Verified"
        tone="accent"
        :loading="loading && !summary"
      />
    </div>

    <SectionCard title="全库身份扫描" subtitle="幂等扫描：同一 scan_id 重复执行不会产生重复记录" accent>
      <div class="idc-console">
        <label class="idc-field">
          <span class="idc-field__label">scan_id</span>
          <el-input v-model="scanId" size="small" placeholder="scan_id（幂等）" style="width: 220px" />
        </label>
        <label class="idc-field">
          <span class="idc-field__label">批次大小</span>
          <el-input-number v-model="batchSize" size="small" :min="1" :max="1000" controls-position="right" />
        </label>
        <el-button type="primary" size="small" :loading="scanning" @click="startScanNow">开始扫描</el-button>
        <span class="idc-hint">
          指纹：<span class="sm-mono">{{ displayText(summary?.current_save_identity_fingerprint) }}</span>
        </span>
      </div>

      <el-table :data="scans" size="small" empty-text="还没有扫描记录">
        <el-table-column prop="scan_id" label="scan_id" min-width="150" />
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <span class="idc-status" :class="statusClass(row.status)">{{ row.status }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="processed_count" label="已处理" width="90" align="right" />
        <el-table-column prop="matched_count" label="匹配" width="80" align="right" />
        <el-table-column prop="conflict_count" label="冲突" width="80" align="right" />
        <el-table-column prop="failed_count" label="失败" width="80" align="right" />
        <el-table-column label="错误码" width="180">
          <template #default="{ row }"><span class="sm-mono">{{ displayText(row.error_code) }}</span></template>
        </el-table-column>
        <el-table-column label="操作" width="200">
          <template #default="{ row }">
            <el-button link size="small" @click="pause(row.scan_id)">暂停</el-button>
            <el-button link size="small" @click="resume(row.scan_id)">恢复</el-button>
            <el-button link size="small" @click="cancel(row.scan_id)">取消</el-button>
          </template>
        </el-table-column>
      </el-table>
    </SectionCard>

    <div class="identity-center__layout">
      <SectionCard title="人工审核队列" dense class="identity-center__list">
        <div class="idc-console idc-console--filters">
          <label class="idc-field">
            <span class="idc-field__label">状态</span>
            <el-select v-model="statusFilter" size="small" style="width: 170px" @change="loadQueue">
              <el-option label="待处理" value="PendingHumanReview" />
              <el-option label="已确认" value="Confirmed" />
              <el-option label="已拒绝" value="Rejected" />
              <el-option label="保留独立" value="KeptIndependent" />
              <el-option label="暂缓" value="Deferred" />
              <el-option label="全部" value="all" />
            </el-select>
          </label>
          <label class="idc-field">
            <span class="idc-field__label">类型</span>
            <el-select
              v-model="typeFilter"
              size="small"
              style="width: 170px"
              @change="loadQueue"
              clearable
              placeholder="全部类型"
            >
              <el-option label="同名" value="same_name" />
              <el-option label="UID 重复" value="uid_duplicate" />
              <el-option label="转会身份" value="transfer_identity" />
            </el-select>
          </label>
          <span class="idc-hint idc-hint--push">当前筛选 {{ queue.length }} 条</span>
        </div>
        <el-table
          :data="queue"
          size="small"
          empty-text="没有待审核条目"
          highlight-current-row
          @row-click="selectItem"
        >
          <el-table-column prop="id" label="#" width="60" />
          <el-table-column prop="item_type" label="类型" width="140" />
          <el-table-column label="UID" width="110">
            <template #default="{ row }"><span class="sm-mono">{{ displayText(row.subject_uid) }}</span></template>
          </el-table-column>
          <el-table-column label="原因" min-width="200">
            <template #default="{ row }">{{ displayText(row.conflict_reason) }}</template>
          </el-table-column>
          <el-table-column label="状态" width="150">
            <template #default="{ row }">
              <span class="idc-status" :class="statusClass(row.status)">{{ row.status }}</span>
            </template>
          </el-table-column>
          <el-table-column label="时间" width="160">
            <template #default="{ row }">{{ formatDateTime(row.detected_at) }}</template>
          </el-table-column>
        </el-table>
      </SectionCard>

      <SectionCard v-if="detail" :title="`审核条目 #${detail.id}`" dense class="identity-center__detail">
        <div class="idc-detail">
          <div class="idc-detail__meta">
            <span class="idc-chip">{{ detail.item_type }}</span>
            <span class="idc-status" :class="statusClass(detail.status)">{{ detail.status }}</span>
            <span class="idc-chip idc-chip--mono">{{ displayText(detail.subject_uid) }}</span>
            <span class="idc-hint">{{ formatDateTime(detail.detected_at) }}</span>
          </div>

          <el-alert
            :title="`${detail.item_type} · ${displayText(detail.conflict_reason)}`"
            type="info"
            :closable="false"
            show-icon
          />

          <el-table :data="detail.instances" size="small" empty-text="没有实例">
            <el-table-column prop="instance_id" label="实例" width="80" />
            <el-table-column prop="player_id" label="球员" width="80" />
            <el-table-column label="UID" width="130">
              <template #default="{ row }"><span class="sm-mono">{{ row.save_local_uid }}</span></template>
            </el-table-column>
            <el-table-column prop="uid_occurrence" label="出现次数" width="90" align="right" />
            <el-table-column prop="position" label="位置" width="80" />
          </el-table>

          <details class="idc-payload">
            <summary>原始 payload（证据，不做修改）</summary>
            <pre class="idc-payload__body">{{ JSON.stringify(detail.payload, null, 2) }}</pre>
          </details>

          <label class="idc-field idc-field--block">
            <span class="idc-field__label">处理备注（写入审计）</span>
            <el-input v-model="note" size="small" placeholder="写明判断依据，例如生日或合同证据" />
          </label>

          <div class="idc-actions">
            <el-button type="primary" size="small" :loading="resolving" @click="decide('same')">确认同一人</el-button>
            <el-button size="small" :loading="resolving" @click="decide('different')">确认不同人</el-button>
            <el-button size="small" :loading="resolving" @click="decide('independent')">保留为独立身份</el-button>
            <el-button size="small" plain :loading="resolving" @click="decide('defer')">暂缓</el-button>
          </div>

          <div class="idc-history">
            <h4 class="idc-history__title">审核历史</h4>
            <p v-if="!detail.history.length" class="idc-hint">还没有人工操作记录。</p>
            <ul v-else class="idc-history__list">
              <li v-for="entry in detail.history" :key="entry.id" class="idc-history__item">
                <span class="idc-history__dot" aria-hidden="true" />
                <span class="idc-history__time">{{ formatDateTime(entry.created_at) }}</span>
                <span class="idc-history__decision">{{ entry.decision }}</span>
                <span class="idc-history__note">{{ entry.note || '无备注' }}</span>
              </li>
            </ul>
          </div>
          <p class="idc-hint">{{ detail.retention }}</p>
        </div>
      </SectionCard>
      <EmptyState
        v-else
        title="选择一条审核条目"
        description="左侧列表来自当前存档的扫描结果；审核决定会写入审计历史。"
        class="identity-center__detail"
      />
    </div>

    <SectionCard title="跨存档身份候选" subtitle="相同 UID 只是证据，不会自动认定为同一球员" dense>
      <div class="idc-console">
        <label class="idc-field">
          <span class="idc-field__label">另一个存档 ID</span>
          <el-input v-model="otherSaveId" size="small" placeholder="例如 2" style="width: 180px" />
        </label>
        <el-button size="small" :loading="crossLoading" @click="loadCrossSave(true)">生成并查看</el-button>
        <span class="idc-hint idc-hint--push">跨存档只是候选，最终判断仍需人工确认</span>
      </div>
      <el-table :data="crossSave" size="small" empty-text="还没有跨存档候选">
        <el-table-column prop="normalized_name" label="姓名（规范化）" min-width="180" />
        <el-table-column label="生日" width="120">
          <template #default="{ row }">{{ displayText(row.birth_date) }}</template>
        </el-table-column>
        <el-table-column prop="match_score" label="匹配度" width="90" align="right" />
        <el-table-column label="状态" width="190">
          <template #default="{ row }">
            <span class="idc-status" :class="statusClass(row.status)">{{ row.status }}</span>
          </template>
        </el-table-column>
        <el-table-column label="UID 相同" width="110">
          <template #default="{ row }">{{ row.uid_equal ? '是（仅证据）' : '否' }}</template>
        </el-table-column>
      </el-table>
    </SectionCard>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { asApiError, type ApiError } from '../api/client'
import {
  cancelScan,
  getIdentityCenterSummary,
  getReviewItem,
  listCrossSaveCandidates,
  listReviewQueue,
  listScans,
  pauseScan,
  resolveReviewItem,
  resumeScan,
  startScan,
} from '../api/identityCenter'
import EmptyState from '../components/EmptyState.vue'
import KpiCard from '../components/KpiCard.vue'
import PageHeader from '../components/PageHeader.vue'
import SectionCard from '../components/SectionCard.vue'
import type {
  CrossSaveCandidate,
  IdentityCenterSummary,
  ReviewDecision,
  ReviewQueueItem,
  ScanRun,
} from '../types/identityCenter'
import { displayText, formatDateTime, formatInt } from '../utils/format'

const loading = ref(false)
const scanning = ref(false)
const resolving = ref(false)
const crossLoading = ref(false)
const error = ref<ApiError | null>(null)

const summary = ref<IdentityCenterSummary | null>(null)
const scans = ref<ScanRun[]>([])
const queue = ref<ReviewQueueItem[]>([])
const detail = ref<ReviewQueueItem | null>(null)
const crossSave = ref<CrossSaveCandidate[]>([])

const scanId = ref(`ui-scan-${new Date().toISOString().slice(0, 10)}`)
const batchSize = ref(200)
const statusFilter = ref('PendingHumanReview')
const typeFilter = ref('')
const note = ref('')
const otherSaveId = ref('')

/**
 * 状态色调只影响徽标外观，不改变状态文案与业务含义。
 * Pending / 冲突类 → 警告；失败/拒绝 → 危险；完成/确认 → 成功。
 */
function statusClass(status: string): string {
  const normalized = status.toLowerCase()
  if (normalized.includes('fail') || normalized.includes('cancel') || normalized.includes('reject')) {
    return 'idc-status--danger'
  }
  if (normalized.includes('pending') || normalized.includes('conflict') || normalized.includes('defer')) {
    return 'idc-status--warn'
  }
  if (normalized.includes('complete') || normalized.includes('confirm') || normalized.includes('resolve')) {
    return 'idc-status--ok'
  }
  if (normalized.includes('pause')) return 'idc-status--muted'
  return 'idc-status--info'
}

function reportError(caught: unknown): void {
  const apiError = asApiError(caught)
  error.value = apiError
  ElMessage.error(apiError.message)
}

async function loadSummary(): Promise<void> {
  summary.value = await getIdentityCenterSummary()
}

async function loadScans(): Promise<void> {
  scans.value = (await listScans()).items
}

async function loadQueue(): Promise<void> {
  const response = await listReviewQueue({
    status: statusFilter.value,
    item_type: typeFilter.value || undefined,
    page_size: 50,
  })
  queue.value = response.items
}

async function reloadAll(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    await Promise.all([loadSummary(), loadScans(), loadQueue()])
  } catch (caught) {
    reportError(caught)
  } finally {
    loading.value = false
  }
}

async function startScanNow(): Promise<void> {
  scanning.value = true
  try {
    const run = await startScan({ scan_id: scanId.value, batch_size: batchSize.value })
    if (run.status === 'Failed') {
      ElMessage.error(run.error_message || '扫描失败')
    } else {
      ElMessage.success(`扫描 ${run.status}：${run.processed_count}/${run.total_instances}`)
    }
    await reloadAll()
  } catch (caught) {
    reportError(caught)
  } finally {
    scanning.value = false
  }
}

async function pause(id: string): Promise<void> {
  try {
    await pauseScan(id)
    await loadScans()
  } catch (caught) {
    reportError(caught)
  }
}

async function resume(id: string): Promise<void> {
  try {
    await resumeScan(id, {})
    await reloadAll()
  } catch (caught) {
    reportError(caught)
  }
}

async function cancel(id: string): Promise<void> {
  try {
    await cancelScan(id)
    await loadScans()
  } catch (caught) {
    reportError(caught)
  }
}

async function selectItem(row: ReviewQueueItem): Promise<void> {
  try {
    detail.value = await getReviewItem(row.id)
    note.value = ''
  } catch (caught) {
    reportError(caught)
  }
}

async function decide(decision: ReviewDecision): Promise<void> {
  if (!detail.value) return
  const itemId = detail.value.id
  resolving.value = true
  try {
    await resolveReviewItem(itemId, decision, note.value, detail.value.version)
    ElMessage.success('已记录审核决定')
    await reloadAll()
    detail.value = await getReviewItem(itemId)
  } catch (caught) {
    // 版本冲突时强制重新读取最新审核状态，避免继续用旧版本提交。
    try {
      detail.value = await getReviewItem(itemId)
    } catch {
      // 读取失败时保留原错误提示。
    }
    reportError(caught)
  } finally {
    resolving.value = false
  }
}

async function loadCrossSave(generate: boolean): Promise<void> {
  const other = Number(otherSaveId.value)
  if (generate && (!Number.isInteger(other) || other <= 0)) {
    ElMessage.warning('请填写另一个存档的 ID')
    return
  }
  crossLoading.value = true
  try {
    const response = await listCrossSaveCandidates({
      other_save_id: Number.isInteger(other) && other > 0 ? other : undefined,
      generate,
    })
    crossSave.value = response.items
  } catch (caught) {
    reportError(caught)
  } finally {
    crossLoading.value = false
  }
}

onMounted(() => {
  void reloadAll()
  void loadCrossSave(false)
})
</script>

<style scoped>
.identity-center {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-4);
}

.identity-center__layout {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(360px, 1fr);
  gap: var(--sm-space-4);
  align-items: start;
}

/* 详情列在桌面端跟随滚动，审核时不必反复上下移动。 */
.identity-center__detail {
  position: sticky;
  top: var(--sm-space-4);
}

@media (max-width: 1100px) {
  .identity-center__layout {
    grid-template-columns: minmax(0, 1fr);
  }

  .identity-center__detail {
    position: static;
  }
}

/* ---------- 控制台行 ---------- */

.idc-console {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: var(--sm-space-3);
  margin-bottom: var(--sm-space-4);
  padding: var(--sm-space-3);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-md);
  background:
    linear-gradient(120deg, rgba(49, 95, 206, 0.05), rgba(49, 95, 206, 0.04)),
    var(--sm-surface-2);
}

.idc-console--filters {
  margin-bottom: var(--sm-space-2);
  padding: var(--sm-space-2) var(--sm-space-3);
}

.idc-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.idc-field--block {
  width: 100%;
}

.idc-field__label {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
  font-weight: var(--sm-fw-medium);
  letter-spacing: var(--sm-tracking-label);
  text-transform: uppercase;
}

.idc-hint {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
  line-height: 1.6;
}

.idc-hint--push {
  margin-left: auto;
}

.idc-alert-text {
  font-size: var(--sm-fs-xs);
  line-height: 1.6;
}

/* ---------- 状态徽标 ---------- */

.idc-status {
  display: inline-flex;
  align-items: center;
  padding: 1px 8px;
  border: 1px solid var(--sm-border-strong);
  border-radius: var(--sm-radius-pill);
  background: var(--sm-surface-2);
  color: var(--sm-text-2);
  font-size: var(--sm-fs-2xs);
  font-family: var(--sm-font-mono);
  white-space: nowrap;
}

.idc-status--ok {
  border-color: rgba(22, 134, 91, 0.24);
  background: var(--sm-success-weak);
  color: var(--sm-status-success);
}

.idc-status--warn {
  border-color: rgba(183, 121, 31, 0.24);
  background: var(--sm-warn-weak);
  color: var(--sm-status-warning);
}

.idc-status--danger {
  border-color: rgba(194, 65, 75, 0.24);
  background: var(--sm-danger-weak);
  color: var(--sm-status-danger);
}

.idc-status--info {
  border-color: rgba(49, 95, 206, 0.22);
  background: #eaf1ff;
  color: var(--sm-accent-blue);
}

.idc-status--muted {
  color: var(--sm-text-3);
}

/* ---------- 详情 ---------- */

.idc-detail {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-3);
}

.idc-detail__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sm-space-2);
}

.idc-chip {
  display: inline-flex;
  align-items: center;
  padding: 1px 8px;
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-pill);
  background: var(--sm-surface-2);
  color: var(--sm-text-2);
  font-size: var(--sm-fs-2xs);
}

.idc-chip--mono {
  font-family: var(--sm-font-mono);
}

.idc-payload {
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-md);
  background: var(--sm-surface-2);
  overflow: hidden;
}

.idc-payload summary {
  padding: var(--sm-space-2) var(--sm-space-3);
  color: var(--sm-text-2);
  font-size: var(--sm-fs-xs);
  cursor: pointer;
  list-style: none;
}

.idc-payload summary::before {
  content: '▸ ';
  color: var(--sm-accent-cyan);
}

.idc-payload[open] summary::before {
  content: '▾ ';
}

.idc-payload summary:hover {
  color: var(--sm-text);
  background: var(--sm-surface-3);
}

.idc-payload__body {
  max-height: 220px;
  overflow: auto;
  margin: 0;
  padding: var(--sm-space-3);
  border-top: 1px solid var(--sm-border);
  color: var(--sm-text-2);
  font-family: var(--sm-font-mono);
  font-size: var(--sm-fs-2xs);
  line-height: 1.6;
}

.idc-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sm-space-2);
}

/* ---------- 审计历史 ---------- */

.idc-history {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-2);
}

.idc-history__title {
  color: var(--sm-text-2);
  font-size: var(--sm-fs-xs);
  font-weight: var(--sm-fw-semibold);
}

.idc-history__list {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.idc-history__item {
  display: grid;
  grid-template-columns: 6px auto auto 1fr;
  align-items: baseline;
  gap: var(--sm-space-2);
  padding: var(--sm-space-2) var(--sm-space-3);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-sm);
  background: var(--sm-surface-2);
  font-size: var(--sm-fs-2xs);
}

.idc-history__dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--sm-accent-cyan);
}

.idc-history__time {
  color: var(--sm-text-3);
  font-variant-numeric: tabular-nums;
}

.idc-history__decision {
  color: var(--sm-text);
  font-weight: var(--sm-fw-medium);
}

.idc-history__note {
  color: var(--sm-text-2);
}

@media (max-width: 640px) {
  .idc-console {
    align-items: stretch;
  }

  .idc-console > * {
    width: 100%;
  }

  .idc-console :deep(.el-input),
  .idc-console :deep(.el-select),
  .idc-console :deep(.el-input-number) {
    width: 100% !important;
  }

  .idc-hint--push {
    margin-left: 0;
  }

  .idc-history__item {
    grid-template-columns: 6px 1fr;
  }

  .idc-history__note {
    grid-column: 2;
  }
}
</style>
