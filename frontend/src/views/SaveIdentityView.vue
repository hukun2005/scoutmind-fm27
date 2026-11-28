<script setup lang="ts">
/**
 * 存档身份诊断（V3.2.7.2）：只读展示服务端判定的身份状态、证据、会话与采集阻断原因。
 * 本页不做任何状态提升——CANDIDATE / DISCOVERED 永远不会因为展示而变成 VERIFIED。
 */

import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { asApiError, type ApiError } from '../api/client'
import { listImports } from '../api/imports'
import { getSaveIdentity, listSaveIdentities, listSaveIdentityAudit } from '../api/saveIdentity'
import DataTable from '../components/DataTable.vue'
import EmptyState from '../components/EmptyState.vue'
import ErrorState from '../components/ErrorState.vue'
import InsightPanel from '../components/InsightPanel.vue'
import PageHeader from '../components/PageHeader.vue'
import SectionCard from '../components/SectionCard.vue'
import StatStrip from '../components/StatStrip.vue'
import AppTag from '../components/AppTag.vue'
import { useSessionStore } from '../stores/session'
import type { Save } from '../types/bootstrap'
import type { ImportJob } from '../types/imports'
import type { TableColumn } from '../types/table'
import type { InsightItem, StatItem } from '../types/ui'
import type {
  SaveIdentityAuditEvent,
  SaveEvidenceLevel,
  SaveIdentityDetail,
  SaveIdentityEvidence,
  SaveIdentityStatus,
  SaveIdentitySummary,
  SaveSession,
} from '../types/saveIdentity'
import { EMPTY, displayText, formatDateTime, formatInt } from '../utils/format'

const session = useSessionStore()

const STATUS_LABELS: Record<SaveIdentityStatus, string> = {
  unknown: '未知',
  discovered: '已发现',
  candidate: '候选',
  verified: '已确认',
  conflict: '冲突',
  invalidated: '已失效',
}

/** 身份状态可信度排序，仅用于摘要展示。 */
const STATUS_WEIGHT: Record<SaveIdentityStatus, number> = {
  verified: 5,
  candidate: 4,
  discovered: 3,
  unknown: 2,
  conflict: 1,
  invalidated: 0,
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

const jobs = ref<ImportJob[]>([])
const jobsLoading = ref(false)
const jobsError = ref<ApiError | null>(null)

const IMPORT_STATUS_LABELS: Record<string, string> = {
  queued: '排队中',
  running: '运行中',
  cancel_requested: '取消请求中',
  cancelled: '已取消',
  succeeded: '成功',
  partial: '部分成功',
  failed: '失败',
  rejected: '已拒绝',
}

const HEARTBEAT_TIMEOUT_SECONDS = 120

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

const jobColumns: TableColumn<ImportJob>[] = [
  { prop: 'id', label: 'ID', width: 72, align: 'right' },
  { prop: 'status', label: '状态', width: 110, formatter: (row) => IMPORT_STATUS_LABELS[row.status] ?? row.status },
  { prop: 'scan_id', label: '扫描', minWidth: 120, showOverflowTooltip: true, formatter: (row) => displayText(row.scan_id) },
  { prop: 'attempt_count', label: '尝试', width: 72, align: 'right', formatter: (row) => displayText(row.attempt_count ?? 0) },
  { prop: 'player_count', label: '球员', width: 72, align: 'right', formatter: (row) => displayText(row.player_count) },
  { prop: 'received_at', label: '接收', width: 150, formatter: (row) => formatDateTime(row.received_at) },
  { prop: 'finished_at', label: '结束', width: 150, formatter: (row) => formatDateTime(row.finished_at) },
  {
    prop: 'rejected_reason',
    label: '拒绝/取消原因',
    minWidth: 180,
    showOverflowTooltip: true,
    formatter: (row) => displayText(row.rejected_reason ?? (row.cancelled_at ? 'worker_cancelled' : null)),
  },
]

const countEntries = computed(() =>
  (Object.entries(counts.value) as Array<[SaveIdentityStatus, number]>).sort((a, b) => b[1] - a[1]),
)

const gateBlockers = computed(() => detail.value?.blockers ?? [])

const latestSession = computed<SaveSession | null>(() => detail.value?.sessions?.[0] ?? null)

const heartbeatAgeSeconds = computed<number | null>(() => {
  const last = latestSession.value?.last_heartbeat_at
  if (!last) return null
  const parsed = Date.parse(last)
  return Number.isNaN(parsed) ? null : Math.max(0, Math.round((Date.now() - parsed) / 1000))
})

const networkFacts = computed(() => {
  const session = latestSession.value
  const age = heartbeatAgeSeconds.value
  return {
    sessionStatus: session ? SESSION_LABELS[session.status] ?? session.status : '无会话',
    heartbeatFresh: age !== null && age <= HEARTBEAT_TIMEOUT_SECONDS,
    heartbeatAge: age,
    epoch: session?.session_epoch ?? null,
    reconnects: audit.value.filter((event) => event.event_type === 'network_reconnected').length,
    backendRestarts: audit.value.filter((event) => event.event_type === 'backend_restarted').length,
  }
})

const workerCounts = computed(() => {
  const result = new Map<string, number>()
  for (const job of jobs.value) {
    result.set(job.status, (result.get(job.status) ?? 0) + 1)
  }
  return Array.from(result.entries()).sort((a, b) => b[1] - a[1])
})

const cancelRequestedCount = computed(
  () => jobs.value.filter((job) => job.status === 'cancel_requested' || job.status === 'cancelled').length,
)

/** 导入任务仍在排队或运行。 */
const runningJobs = computed(() =>
  jobs.value.filter((job) => job.status === 'queued' || job.status === 'running' || job.status === 'cancel_requested'),
)

/** 身份识别摘要：优先使用已选身份，否则取列表中最可信的一条。 */
const identitySummary = computed<SaveIdentityStatus | null>(() => {
  if (detail.value) return detail.value.identity_status
  const ranked = [...items.value].sort(
    (a, b) => STATUS_WEIGHT[b.identity_status] - STATUS_WEIGHT[a.identity_status],
  )
  return ranked[0]?.identity_status ?? null
})

/** 存档状态结论：只复述 session 与身份/任务接口的真实数据。 */
const statusItems = computed<InsightItem[]>(() => {
  const active = session.activeSave
  const status = identitySummary.value
  const items: InsightItem[] = [
    {
      label: '当前存档',
      text: active ? active.name : '未选择存档',
      tone: active ? 'neutral' : 'warning',
    },
    {
      label: '身份状态',
      text: status ? STATUS_LABELS[status] : '还没有身份记录',
      tone: status === 'verified' ? 'success' : status === 'conflict' || status === 'invalidated' ? 'danger' : 'warning',
    },
    {
      label: '进行中任务',
      text: runningJobs.value.length
        ? `${runningJobs.value.length} 个导入任务未结束，切换存档会让旧会话与在途任务失效。`
        : '当前没有排队或运行中的导入任务。',
      tone: runningJobs.value.length ? 'warning' : 'neutral',
    },
    {
      label: '下一步',
      text: active ? '在存档列表选择要切换的存档；切换前会再次确认。' : '先到「游戏数据」导入或同步一个存档。',
    },
  ]
  return items
})

/** 存档关键指标。 */
const statusStats = computed<StatItem[]>(() => {
  const active = session.activeSave
  return [
    { label: '存档数量', value: formatInt(session.saves.length) },
    { label: '当前存档', value: active?.name ?? EMPTY },
    {
      label: '球员 / 快照',
      value: active ? `${formatInt(active.player_count)} / ${formatInt(active.snapshot_count)}` : EMPTY,
    },
    { label: '最近读取', value: formatDateTime(active?.last_import_at ?? null) },
    { label: '身份记录', value: formatInt(total.value) },
  ]
})

/** 存档状态面板的整体状态色。 */
const statusTone = computed<'success' | 'warning' | 'danger' | 'neutral'>(() => {
  const status = identitySummary.value
  if (!status) return 'neutral'
  if (status === 'verified') return 'success'
  if (status === 'conflict' || status === 'invalidated') return 'danger'
  return 'warning'
})

/** 切换存档：有任务在跑时明确提示风险，确认后才切换。 */
async function switchSave(target: Save): Promise<void> {
  if (target.id === session.activeSaveId) return
  const running = runningJobs.value.length
  const message = running
    ? `当前还有 ${running} 个导入任务未结束。切换存档后旧会话与在途任务会失效，可能导致本次同步中断。确定切换到「${target.name}」？`
    : `切换后所有页面将使用「${target.name}」的数据；旧存档不会被修改。确定切换？`
  try {
    await ElMessageBox.confirm(message, '切换存档', {
      type: 'warning',
      confirmButtonText: '切换',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  session.selectSave(target.id)
  ElMessage.success(`已切换到「${target.name}」`)
}

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

async function loadJobs(): Promise<void> {
  const saveId = session.activeSave?.id
  if (!saveId) {
    jobs.value = []
    return
  }
  jobsLoading.value = true
  jobsError.value = null
  try {
    const response = await listImports({ save_id: saveId, limit: 8 })
    jobs.value = response.items
  } catch (failure) {
    jobsError.value = asApiError(failure)
    jobs.value = []
  } finally {
    jobsLoading.value = false
  }
}

onMounted(() => {
  void reload()
  void loadJobs()
})

watch(
  [() => session.dataRevision, () => session.activeSaveId],
  () => {
    detail.value = null
    audit.value = []
    void reload()
    void loadJobs()
  },
)
</script>

<template>
  <div class="save-identity">
    <PageHeader
      title="存档管理"
      description="查看当前存档的识别状态、最近同步与采集闸门；只有 verified 身份 + 心跳有效的会话才允许采集写入，本页不会提升任何状态。"
    >
      <template #meta>
        <span class="save-identity__meta">协议 {{ displayText(protocolVersion) }}</span>
        <span v-if="session.activeSave" class="save-identity__meta">当前存档：{{ session.activeSave.name }}</span>
      </template>
      <template #actions>
        <el-button size="small" :loading="loading" @click="reload">刷新</el-button>
      </template>
    </PageHeader>

    <InsightPanel
      title="存档状态"
      badge="数据事实"
      :tone="statusTone"
      :items="statusItems"
      footnote="切换存档只改变当前页面使用的数据源，不写入游戏、不修改旧存档；身份状态由服务端判定，本页不会提升任何状态。"
    />

    <StatStrip :items="statusStats" />

    <SectionCard title="我的存档" :subtitle="`共 ${session.saves.length} 个`">
      <EmptyState
        v-if="session.saves.length === 0"
        title="还没有存档"
        description="在「游戏数据」导入或同步一个 FM27 存档后，这里会显示可切换的存档。"
        compact
      />
      <div v-else class="save-identity__saves">
        <article
          v-for="saveItem in session.saves"
          :key="saveItem.id"
          class="save-card"
          :class="{ 'save-card--active': saveItem.id === session.activeSaveId }"
        >
          <header class="save-card__head">
            <span class="save-card__name">{{ saveItem.name }}</span>
            <AppTag v-if="saveItem.id === session.activeSaveId" label="当前存档" tone="success" />
          </header>
          <p class="save-card__meta">
            版本 {{ displayText(saveItem.game_version) }} · build {{ displayText(saveItem.game_build) }}
          </p>
          <dl class="save-card__facts">
            <div><dt>球员</dt><dd>{{ formatInt(saveItem.player_count) }}</dd></div>
            <div><dt>快照</dt><dd>{{ formatInt(saveItem.snapshot_count) }}</dd></div>
            <div><dt>转会</dt><dd>{{ formatInt(saveItem.transfer_count) }}</dd></div>
            <div><dt>最近读取</dt><dd>{{ formatDateTime(saveItem.last_import_at) }}</dd></div>
          </dl>
          <el-button
            v-if="saveItem.id !== session.activeSaveId"
            size="small"
            @click="switchSave(saveItem)"
          >
            切换到此存档
          </el-button>
          <span v-else class="sm-text-2xs sm-text-faint">所有页面正在使用该存档</span>
        </article>
      </div>
    </SectionCard>

    <SectionCard title="身份列表" :subtitle="`共 ${total} 条`">
      <template #actions>
        <el-select v-model="statusFilter" size="small" style="width: 160px" @change="reload">
          <el-option label="全部状态" value="all" />
          <el-option v-for="(label, value) in STATUS_LABELS" :key="value" :label="label" :value="value" />
        </el-select>
      </template>

      <div v-if="countEntries.length" class="save-identity__counts">
        <AppTag
          v-for="[status, count] in countEntries"
          :key="status"
          :tag="status"
          :label="`${STATUS_LABELS[status]} ${count}`"
        />
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
          <AppTag
            v-if="column.prop === 'identity_status'"
            :tag="row.identity_status"
            :label="STATUS_LABELS[row.identity_status] ?? row.identity_status"
          />
          <span v-else>{{ value }}</span>
        </template>
      </DataTable>
    </SectionCard>

    <ErrorState v-if="detailError" :error="detailError" title="身份详情加载失败" @retry="detail && selectIdentity(detail)" />

    <template v-if="detail">
      <el-collapse class="save-identity__advanced">
        <el-collapse-item name="identity-detail">
          <template #title>
            <span class="sm-text-xs">身份证据、采集闸门与审计（高级）</span>
          </template>
          <div class="sm-stack">
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

      <SectionCard title="Worker / 网络诊断" :subtitle="`最近 ${jobs.length} 个导入任务`">
        <template #actions>
          <el-button size="small" :loading="jobsLoading" @click="loadJobs">刷新任务</el-button>
        </template>

        <dl class="save-identity__facts save-identity__facts--compact">
          <div>
            <dt>会话状态</dt>
            <dd>
              {{ networkFacts.sessionStatus }}
              <AppTag
                :tag="networkFacts.heartbeatFresh ? 'heartbeat_ok' : 'heartbeat_stale'"
                :label="networkFacts.heartbeatFresh ? '心跳有效' : '心跳超时/未知'"
                dot
              />
            </dd>
          </div>
          <div>
            <dt>最近心跳</dt>
            <dd>
              {{ formatDateTime(latestSession?.last_heartbeat_at) }}
              <span v-if="networkFacts.heartbeatAge !== null" class="save-identity__muted">
                （{{ networkFacts.heartbeatAge }} 秒前，阈值 {{ HEARTBEAT_TIMEOUT_SECONDS }} 秒）
              </span>
            </dd>
          </div>
          <div><dt>写入代次</dt><dd>{{ displayText(networkFacts.epoch) }}</dd></div>
          <div><dt>断网重连 / 后端重启</dt><dd>{{ networkFacts.reconnects }} / {{ networkFacts.backendRestarts }} 次</dd></div>
          <div><dt>取消相关任务</dt><dd>{{ cancelRequestedCount }} 个（cancel_requested + cancelled）</dd></div>
        </dl>

        <div v-if="workerCounts.length" class="save-identity__counts save-identity__counts--tight">
          <AppTag
            v-for="[status, count] in workerCounts"
            :key="status"
            :tag="status"
            :label="`${IMPORT_STATUS_LABELS[status] ?? status} ${count}`"
          />
        </div>

        <ErrorState v-if="jobsError" :error="jobsError" title="导入任务加载失败" compact @retry="loadJobs" />
        <EmptyState
          v-else-if="!jobsLoading && jobs.length === 0"
          title="当前存档还没有导入任务"
          description="任务进入队列后，这里会显示排队、运行、取消与最终结果；取消是状态转换，不会删除历史。"
          compact
        />
        <DataTable
          v-else
          :columns="jobColumns"
          :rows="jobs"
          :loading="jobsLoading"
          row-key="id"
          dense
        >
          <template #cell="{ row, column, value }">
            <AppTag
              v-if="column.prop === 'status'"
              :tag="row.status"
              :label="IMPORT_STATUS_LABELS[row.status] ?? row.status"
            />
            <span v-else>{{ value }}</span>
          </template>
        </DataTable>
        <p class="save-identity__hint">
          仅展示只读诊断：本页不会取消任务、不会重试、不会修改身份状态。
        </p>
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
          </div>
        </el-collapse-item>
      </el-collapse>
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

.save-identity__saves {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: var(--sm-space-3);
}

.save-card {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-2);
  padding: var(--sm-space-3);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-md);
  background: var(--sm-surface-2);
}

.save-card--active {
  border-color: var(--sm-status-success);
}

.save-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sm-space-2);
}

.save-card__name {
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-sm);
  font-weight: var(--sm-fw-semibold);
}

.save-card__meta {
  margin: 0;
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}

.save-card__facts {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px var(--sm-space-3);
  margin: 0;
}

.save-card__facts dt {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}

.save-card__facts dd {
  margin: 0;
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-xs);
}

.save-identity__advanced {
  border: 0;
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

.save-identity__facts--compact {
  margin-bottom: var(--sm-space-3);
}

.save-identity__inline-tag {
  margin-left: var(--sm-space-2);
}

.save-identity__muted {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}

.save-identity__counts--tight {
  margin-bottom: var(--sm-space-2);
}

.save-identity__hint {
  margin: var(--sm-space-2) 0 0;
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}
</style>
