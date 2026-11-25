<script setup lang="ts">
/**
 * 存档身份诊断（V3.2.7.2）：只读展示服务端判定的身份状态、证据、会话与采集阻断原因。
 * 本页不做任何状态提升——CANDIDATE / DISCOVERED 永远不会因为展示而变成 VERIFIED。
 */

import { computed, onMounted, ref, watch } from 'vue'
import { asApiError, type ApiError } from '../api/client'
import { getSaveIdentity, listSaveIdentities, listSaveIdentityAudit } from '../api/saveIdentity'
import DataTable from '../components/DataTable.vue'
import EmptyState from '../components/EmptyState.vue'
import ErrorState from '../components/ErrorState.vue'
import PageHeader from '../components/PageHeader.vue'
import SectionCard from '../components/SectionCard.vue'
import { useSessionStore } from '../stores/session'
import type { TableColumn } from '../types/table'
import type {
  SaveIdentityAuditEvent,
  SaveEvidenceLevel,
  SaveIdentityDetail,
  SaveIdentityEvidence,
  SaveIdentityStatus,
  SaveIdentitySummary,
  SaveSession,
} from '../types/saveIdentity'
import { displayText, formatDateTime } from '../utils/format'

const session = useSessionStore()

const STATUS_LABELS: Record<SaveIdentityStatus, string> = {
  unknown: '未知',
  discovered: '已发现',
  candidate: '候选',
  verified: '已确认',
  conflict: '冲突',
  invalidated: '已失效',
}

const STATUS_TAG_TYPES: Record<SaveIdentityStatus, 'success' | 'warning' | 'danger' | 'info'> = {
  unknown: 'info',
  discovered: 'info',
  candidate: 'warning',
  verified: 'success',
  conflict: 'danger',
  invalidated: 'danger',
}

const EVIDENCE_LABELS: Record<SaveEvidenceLevel, string> = {
  primary: '主证据',
  secondary: '次证据',
  auxiliary: '辅助',
  none: '无',
}

const SESSION_LABELS: Record<string, string> = {
  created: '已创建（未验证）',
  verified: '已验证',
  switching: '切换中',
  invalidated: '已失效',
  closed: '已关闭',
}

const items = ref<SaveIdentitySummary[]>([])
const total = ref(0)
const counts = ref<Partial<Record<SaveIdentityStatus, number>>>({})
const protocolVersion = ref('')
const loading = ref(false)
const error = ref<ApiError | null>(null)
const statusFilter = ref<'all' | SaveIdentityStatus>('all')

const detail = ref<SaveIdentityDetail | null>(null)
const detailLoading = ref(false)
const detailError = ref<ApiError | null>(null)

const audit = ref<SaveIdentityAuditEvent[]>([])
const auditLoading = ref(false)
const auditError = ref<ApiError | null>(null)

const identityColumns: TableColumn<SaveIdentitySummary>[] = [
  { prop: 'identity_id', label: 'ID', width: 72, align: 'right' },
  {
    prop: 'identity_status',
    label: '状态',
    width: 110,
    formatter: (row) => STATUS_LABELS[row.identity_status] ?? row.identity_status,
  },
  { prop: 'confidence', label: '置信度', width: 96, formatter: (row) => displayText(row.confidence) },
  {
    prop: 'evidence_level',
    label: '证据',
    width: 90,
    formatter: (row) => EVIDENCE_LABELS[row.evidence_level] ?? row.evidence_level,
  },
  { prop: 'kind', label: '类型', width: 140, formatter: (row) => displayText(row.kind) },
  { prop: 'game_build', label: '版本', width: 110, formatter: (row) => displayText(row.game_build) },
  { prop: 'first_seen_at', label: '首次发现', width: 150, formatter: (row) => formatDateTime(row.first_seen_at) },
  { prop: 'last_seen_at', label: '最近发现', width: 150, formatter: (row) => formatDateTime(row.last_seen_at) },
  { prop: 'fingerprint', label: '指纹', minWidth: 240, showOverflowTooltip: true },
]

const evidenceColumns: TableColumn<SaveIdentityEvidence>[] = [
  { prop: 'type', label: '证据类型', width: 190 },
  { prop: 'source', label: '来源', width: 110 },
  { prop: 'hash', label: '哈希', minWidth: 260, showOverflowTooltip: true, formatter: (row) => displayText(row.hash) },
  { prop: 'version', label: '版本', width: 100, formatter: (row) => displayText(row.version) },
  { prop: 'confidence', label: '置信度', width: 96 },
  { prop: 'observed_at', label: '观察时间', width: 150, formatter: (row) => formatDateTime(row.observed_at) },
]

const sessionColumns: TableColumn<SaveSession>[] = [
  { prop: 'session_id', label: 'ID', width: 72, align: 'right' },
  {
    prop: 'status',
    label: '状态',
    width: 140,
    formatter: (row) => SESSION_LABELS[row.status] ?? row.status,
  },
  { prop: 'session_key', label: '会话键', minWidth: 220, showOverflowTooltip: true },
  { prop: 'session_epoch', label: '代次', width: 80, align: 'right', formatter: (row) => displayText(row.session_epoch) },
  { prop: 'process_id', label: 'PID', width: 80, align: 'right', formatter: (row) => displayText(row.process_id) },
  { prop: 'game_build', label: '版本', width: 110, formatter: (row) => displayText(row.game_build) },
  { prop: 'agent_id', label: 'Agent', width: 130, formatter: (row) => displayText(row.agent_id) },
  { prop: 'started_at', label: '开始', width: 150, formatter: (row) => formatDateTime(row.started_at) },
  {
    prop: 'last_heartbeat_at',
    label: '最近心跳',
    width: 150,
    formatter: (row) => formatDateTime(row.last_heartbeat_at),
  },
  {
    prop: 'invalidated_reason',
    label: '失效原因',
    width: 140,
    formatter: (row) => displayText(row.invalidated_reason),
  },
]

const auditColumns: TableColumn<SaveIdentityAuditEvent>[] = [
  { prop: 'occurred_at', label: '时间', width: 150, formatter: (row) => formatDateTime(row.occurred_at) },
  { prop: 'event_type', label: '事件', width: 180 },
  {
    prop: 'new_status',
    label: '状态变化',
    width: 150,
    formatter: (row) => `${displayText(row.old_status)} → ${displayText(row.new_status)}`,
  },
  { prop: 'actor', label: '执行者', width: 110, formatter: (row) => displayText(row.actor) },
  { prop: 'reason', label: '原因', minWidth: 200, showOverflowTooltip: true, formatter: (row) => displayText(row.reason) },
]

const countEntries = computed(() =>
  (Object.entries(counts.value) as Array<[SaveIdentityStatus, number]>).sort((a, b) => b[1] - a[1]),
)

const gateBlockers = computed(() => detail.value?.blockers ?? [])

async function reload(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const response = await listSaveIdentities({
      status: statusFilter.value === 'all' ? undefined : statusFilter.value,
      limit: 100,
    })
    items.value = response.items
    total.value = response.total
    counts.value = response.counts
    protocolVersion.value = response.protocol_version
    if (detail.value && !response.items.some((row) => row.identity_id === detail.value?.identity_id)) {
      detail.value = null
      audit.value = []
    }
  } catch (failure) {
    error.value = asApiError(failure)
  } finally {
    loading.value = false
  }
}

async function selectIdentity(row: SaveIdentitySummary): Promise<void> {
  detailLoading.value = true
  detailError.value = null
  auditError.value = null
  try {
    detail.value = await getSaveIdentity(row.identity_id)
  } catch (failure) {
    detailError.value = asApiError(failure)
    detail.value = null
  } finally {
    detailLoading.value = false
  }
  await loadAudit(row.identity_id)
}

async function loadAudit(identityId: number): Promise<void> {
  auditLoading.value = true
  auditError.value = null
  try {
    const response = await listSaveIdentityAudit({ identity_id: identityId, limit: 50 })
    audit.value = response.items
  } catch (failure) {
    auditError.value = asApiError(failure)
    audit.value = []
  } finally {
    auditLoading.value = false
  }
}

onMounted(reload)

watch(
  () => session.dataRevision,
  () => {
    detail.value = null
    audit.value = []
    void reload()
  },
)
</script>

<template>
  <div class="save-identity">
    <PageHeader
      title="存档身份"
      description="服务端判定的存档身份、证据与会话状态。只有 verified 身份 + 心跳有效的 verified 会话才允许采集写入；诊断页不会提升任何状态。"
    >
      <template #meta>
        <span class="save-identity__meta">协议 {{ displayText(protocolVersion) }}</span>
        <span v-if="session.activeSave" class="save-identity__meta">当前存档：{{ session.activeSave.name }}</span>
      </template>
      <template #actions>
        <el-button size="small" :loading="loading" @click="reload">刷新</el-button>
      </template>
    </PageHeader>

    <SectionCard title="身份列表" :subtitle="`共 ${total} 条`">
      <template #actions>
        <el-select v-model="statusFilter" size="small" style="width: 160px" @change="reload">
          <el-option label="全部状态" value="all" />
          <el-option v-for="(label, value) in STATUS_LABELS" :key="value" :label="label" :value="value" />
        </el-select>
      </template>

      <div v-if="countEntries.length" class="save-identity__counts">
        <el-tag
          v-for="[status, count] in countEntries"
          :key="status"
          size="small"
          effect="plain"
          :type="STATUS_TAG_TYPES[status]"
        >
          {{ STATUS_LABELS[status] }} {{ count }}
        </el-tag>
      </div>

      <ErrorState v-if="error" :error="error" @retry="reload" />
      <DataTable
        v-else
        :columns="identityColumns"
        :rows="items"
        :loading="loading"
        row-key="identity_id"
        clickable
        dense
        :empty-title="statusFilter === 'all' ? '还没有登记过存档身份' : '该状态下没有身份'"
        empty-description="身份由 Reader 产生证据、Agent 上报；本页只读。"
        @row-click="selectIdentity"
      >
        <template #cell="{ row, column, value }">
          <el-tag
            v-if="column.prop === 'identity_status'"
            size="small"
            :type="STATUS_TAG_TYPES[row.identity_status]"
          >
            {{ STATUS_LABELS[row.identity_status] ?? row.identity_status }}
          </el-tag>
          <span v-else>{{ value }}</span>
        </template>
      </DataTable>
    </SectionCard>

    <ErrorState v-if="detailError" :error="detailError" title="身份详情加载失败" @retry="detail && selectIdentity(detail)" />

    <template v-if="detail">
      <SectionCard title="采集闸门" :subtitle="`身份 #${detail.identity_id}`">
        <div v-if="detail.capture_allowed" class="save-identity__gate save-identity__gate--ok">
          允许采集：身份为 verified，且最近会话心跳有效。
        </div>
        <div v-else class="save-identity__gate save-identity__gate--blocked">
          <p class="save-identity__gate-title">当前禁止采集写入</p>
          <ul class="save-identity__blockers">
            <li v-for="blocker in gateBlockers" :key="blocker">{{ blocker }}</li>
          </ul>
        </div>
        <p class="save-identity__generation">
          写入代次：{{ displayText(detail.write_gate?.generation) }}；
          当前可写会话：{{ displayText(detail.write_gate?.current_session_id) }}。
          存档切换会推进代次，旧会话与在途任务随即失效。
        </p>

        <dl class="save-identity__facts">
          <div><dt>状态</dt><dd>{{ STATUS_LABELS[detail.identity_status] ?? detail.identity_status }}</dd></div>
          <div><dt>置信度 / 证据</dt><dd>{{ displayText(detail.confidence) }} / {{ EVIDENCE_LABELS[detail.evidence_level] ?? detail.evidence_level }}</dd></div>
          <div><dt>类型</dt><dd>{{ displayText(detail.kind) }}</dd></div>
          <div><dt>游戏版本</dt><dd>{{ displayText(detail.game_build) }}</dd></div>
          <div><dt>确认时间 / 人</dt><dd>{{ formatDateTime(detail.verified_at) }} / {{ displayText(detail.verified_by) }}</dd></div>
          <div><dt>首次 / 最近发现</dt><dd>{{ formatDateTime(detail.first_seen_at) }} / {{ formatDateTime(detail.last_seen_at) }}</dd></div>
          <div class="save-identity__fact-wide"><dt>指纹</dt><dd class="sm-mono">{{ detail.fingerprint }}</dd></div>
        </dl>
      </SectionCard>

      <SectionCard title="证据" :subtitle="`${detail.evidence.length} 条`">
        <EmptyState
          v-if="detail.evidence.length === 0"
          title="没有证据记录"
          description="没有证据的身份最多只能是 discovered，不能作为已确认身份写入数据。"
          compact
        />
        <DataTable
          v-else
          :columns="evidenceColumns"
          :rows="detail.evidence"
          :row-key="(row: SaveIdentityEvidence) => `${row.type}:${row.hash ?? ''}:${row.observed_at ?? ''}`"
          dense
        />
      </SectionCard>

      <SectionCard title="最近会话" :subtitle="`${detail.sessions.length} 个`">
        <EmptyState
          v-if="detail.sessions.length === 0"
          title="没有会话记录"
          description="Agent 启动时必须先登记会话并通过验证；没有会话的身份不会放行采集。"
          compact
        />
        <DataTable v-else :columns="sessionColumns" :rows="detail.sessions" row-key="session_id" dense />
      </SectionCard>

      <SectionCard title="审计事件" :subtitle="`${audit.length} 条`">
        <ErrorState v-if="auditError" :error="auditError" title="审计加载失败" compact @retry="loadAudit(detail.identity_id)" />
        <EmptyState v-else-if="!auditLoading && audit.length === 0" title="没有审计事件" compact />
        <DataTable v-else :columns="auditColumns" :rows="audit" :loading="auditLoading" row-key="event_id" dense />
      </SectionCard>
    </template>

    <EmptyState
      v-else-if="!detailLoading && items.length > 0"
      title="选择一条身份查看证据与会话"
      description="点击上方任意一行，查看服务端的采集闸门判定与审计记录。"
    />
  </div>
</template>

<style scoped>
.save-identity {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-4);
}

.save-identity__meta {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-xs);
}

.save-identity__counts {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sm-space-2);
  margin-bottom: var(--sm-space-3);
}

.save-identity__gate {
  border-radius: var(--sm-radius-md);
  padding: var(--sm-space-3);
  font-size: var(--sm-fs-sm);
  margin-bottom: var(--sm-space-3);
}

.save-identity__gate--ok {
  background: var(--sm-success-weak);
  color: var(--sm-text);
  border: 1px solid rgba(61, 187, 128, 0.4);
}

.save-identity__gate--blocked {
  background: var(--sm-danger-weak);
  border: 1px solid rgba(240, 106, 99, 0.45);
}

.save-identity__gate-title {
  color: var(--sm-danger);
  font-weight: var(--sm-fw-medium);
}

.save-identity__blockers {
  margin: var(--sm-space-1) 0 0;
  padding-left: var(--sm-space-4);
  color: var(--sm-text-2);
  font-size: var(--sm-fs-xs);
  line-height: 1.8;
}

.save-identity__facts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--sm-space-3);
  margin: 0;
}

.save-identity__facts dt {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}

.save-identity__facts dd {
  color: var(--sm-text);
  font-size: var(--sm-fs-sm);
  margin: 2px 0 0;
  word-break: break-all;
}

.save-identity__fact-wide {
  grid-column: 1 / -1;
}
</style>
