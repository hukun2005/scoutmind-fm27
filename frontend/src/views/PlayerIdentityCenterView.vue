<template>
  <section class="identity-center">
    <PageHeader
      title="球员身份中心"
      subtitle="UID 只在存档内有效；同名、重复 UID 与跨存档候选都只作为待审核项，系统绝不自动合并"
    >
      <template #actions>
        <el-button size="small" :loading="loading" @click="reloadAll">刷新</el-button>
      </template>
    </PageHeader>

    <div class="identity-center__kpis">
      <KpiCard label="球员实例" :value="formatInt(summary?.player_instances ?? 0)" hint="当前存档" />
      <KpiCard label="唯一 UID" :value="formatInt(summary?.uid.distinct_save_local_uids ?? 0)" hint="存档内关联键" />
      <KpiCard label="重复 UID" :value="formatInt(summary?.uid.duplicate_uid_count ?? 0)" hint="不自动合并" />
      <KpiCard label="待人工审核" :value="formatInt(summary?.reviews.PendingHumanReview ?? 0)" hint="同名 / UID / 转会" />
      <KpiCard label="已验证关联" :value="formatInt(summary?.identity_links.ConfirmedByHuman ?? 0)" hint="人工确认，非 Verified" />
    </div>

    <SectionCard title="全库身份扫描" dense>
      <div class="identity-center__scanbar">
        <el-input v-model="scanId" size="small" placeholder="scan_id（幂等）" style="width: 220px" />
        <el-input-number v-model="batchSize" size="small" :min="1" :max="1000" controls-position="right" />
        <el-button type="primary" size="small" :loading="scanning" @click="startScanNow">开始扫描</el-button>
        <span class="identity-center__hint">
          指纹：{{ displayText(summary?.current_save_identity_fingerprint) }}
        </span>
      </div>
      <el-table :data="scans" size="small" empty-text="还没有扫描记录">
        <el-table-column prop="scan_id" label="scan_id" min-width="140" />
        <el-table-column prop="status" label="状态" width="110" />
        <el-table-column prop="processed_count" label="已处理" width="90" />
        <el-table-column prop="matched_count" label="匹配" width="80" />
        <el-table-column prop="conflict_count" label="冲突" width="80" />
        <el-table-column prop="failed_count" label="失败" width="80" />
        <el-table-column prop="error_code" label="错误码" width="180">
          <template #default="{ row }">{{ displayText(row.error_code) }}</template>
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
        <div class="identity-center__filters">
          <el-select v-model="statusFilter" size="small" style="width: 170px" @change="loadQueue">
            <el-option label="待处理" value="PendingHumanReview" />
            <el-option label="已确认" value="Confirmed" />
            <el-option label="已拒绝" value="Rejected" />
            <el-option label="保留独立" value="KeptIndependent" />
            <el-option label="暂缓" value="Deferred" />
            <el-option label="全部" value="all" />
          </el-select>
          <el-select v-model="typeFilter" size="small" style="width: 170px" @change="loadQueue" clearable placeholder="全部类型">
            <el-option label="同名" value="same_name" />
            <el-option label="UID 重复" value="uid_duplicate" />
            <el-option label="转会身份" value="transfer_identity" />
          </el-select>
        </div>
        <el-table
          :data="queue"
          size="small"
          empty-text="没有待审核条目"
          highlight-current-row
          @row-click="selectItem"
        >
          <el-table-column prop="id" label="#" width="60" />
          <el-table-column prop="item_type" label="类型" width="130" />
          <el-table-column label="UID" width="110">
            <template #default="{ row }">{{ displayText(row.subject_uid) }}</template>
          </el-table-column>
          <el-table-column label="原因" min-width="200">
            <template #default="{ row }">{{ displayText(row.conflict_reason) }}</template>
          </el-table-column>
          <el-table-column prop="status" label="状态" width="140" />
          <el-table-column label="时间" width="160">
            <template #default="{ row }">{{ formatDateTime(row.detected_at) }}</template>
          </el-table-column>
        </el-table>
      </SectionCard>

      <SectionCard v-if="detail" :title="`审核条目 #${detail.id}`" dense class="identity-center__detail">
        <div class="identity-center__detail-body">
          <el-alert :title="`${detail.item_type} · ${displayText(detail.conflict_reason)}`" type="info" :closable="false" show-icon />
          <el-table :data="detail.instances" size="small" empty-text="没有实例">
            <el-table-column prop="instance_id" label="实例" width="80" />
            <el-table-column prop="player_id" label="球员" width="80" />
            <el-table-column prop="save_local_uid" label="UID" width="120" />
            <el-table-column prop="uid_occurrence" label="出现次数" width="90" />
            <el-table-column prop="position" label="位置" width="80" />
          </el-table>

          <pre class="identity-center__payload">{{ JSON.stringify(detail.payload, null, 2) }}</pre>

          <el-input v-model="note" size="small" placeholder="处理备注（写入审计）" />
          <div class="identity-center__buttons">
            <el-button type="primary" size="small" :loading="resolving" @click="decide('same')">确认同一人</el-button>
            <el-button size="small" :loading="resolving" @click="decide('different')">确认不同人</el-button>
            <el-button size="small" :loading="resolving" @click="decide('independent')">保留为独立身份</el-button>
            <el-button size="small" :loading="resolving" @click="decide('defer')">暂缓</el-button>
          </div>

          <div class="identity-center__history">
            <h4>审核历史</h4>
            <p v-if="!detail.history.length" class="identity-center__muted">还没有人工操作记录。</p>
            <ul v-else>
              <li v-for="entry in detail.history" :key="entry.id">
                {{ formatDateTime(entry.created_at) }} · {{ entry.decision }} · {{ entry.note || '无备注' }}
              </li>
            </ul>
          </div>
          <p class="identity-center__muted">{{ detail.retention }}</p>
        </div>
      </SectionCard>
      <EmptyState v-else title="选择一条审核条目" hint="左侧列表来自当前存档的扫描结果" class="identity-center__detail" />
    </div>

    <SectionCard title="跨存档身份候选" dense>
      <div class="identity-center__scanbar">
        <el-input v-model="otherSaveId" size="small" placeholder="另一个存档 ID" style="width: 180px" />
        <el-button size="small" :loading="crossLoading" @click="loadCrossSave(true)">生成并查看</el-button>
        <span class="identity-center__hint">相同 UID 只是证据，不会自动认定为同一球员</span>
      </div>
      <el-table :data="crossSave" size="small" empty-text="还没有跨存档候选">
        <el-table-column prop="normalized_name" label="姓名（规范化）" min-width="180" />
        <el-table-column label="生日" width="120">
          <template #default="{ row }">{{ displayText(row.birth_date) }}</template>
        </el-table-column>
        <el-table-column prop="match_score" label="匹配度" width="90" />
        <el-table-column prop="status" label="状态" width="190" />
        <el-table-column label="UID 相同" width="100">
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
  resolving.value = true
  try {
    await resolveReviewItem(detail.value.id, decision, note.value)
    ElMessage.success('已记录审核决定')
    await reloadAll()
    detail.value = await getReviewItem(detail.value.id)
  } catch (caught) {
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

.identity-center__kpis {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: var(--sm-space-3);
}

.identity-center__scanbar,
.identity-center__filters,
.identity-center__buttons {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sm-space-2);
  margin-bottom: var(--sm-space-2);
}

.identity-center__layout {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(320px, 1fr);
  gap: var(--sm-space-4);
  align-items: start;
}

@media (max-width: 1100px) {
  .identity-center__layout {
    grid-template-columns: minmax(0, 1fr);
  }
}

.identity-center__detail-body {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-2);
}

.identity-center__payload {
  max-height: 180px;
  overflow: auto;
  margin: 0;
  padding: var(--sm-space-2);
  border-radius: var(--sm-radius-md);
  background: var(--sm-surface-3);
  color: var(--sm-text-2);
  font-family: var(--sm-font-mono);
  font-size: var(--sm-fs-2xs);
}

.identity-center__history ul {
  margin: 0;
  padding-left: var(--sm-space-4);
  color: var(--sm-text-2);
  font-size: var(--sm-fs-xs);
  line-height: 1.8;
}

.identity-center__hint,
.identity-center__muted {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}
</style>
