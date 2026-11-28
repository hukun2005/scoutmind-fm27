<script setup lang="ts">
/** V3.3.3-01：可恢复任务面板。进度用用户语义展示，高级诊断默认折叠。 */

import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { asApiError, type ApiError } from '../api/client'
import {
  approveAgentTask,
  cancelAgentTask,
  createAgentTask,
  getAgentTask,
  listAgentTaskApprovals,
  listAgentTaskEvents,
  listAgentTasks,
  rejectAgentTask,
} from '../api/agentTasks'
import { useSessionStore } from '../stores/session'
import type { AgentApproval, AgentTask, AgentTaskEvent } from '../types/agentTask'
import { displayText, formatTime } from '../utils/format'

const session = useSessionStore()

const goal = ref('')
const tasks = ref<AgentTask[]>([])
const selectedId = ref<string | null>(null)
const task = ref<AgentTask | null>(null)
const approvals = ref<AgentApproval[]>([])
const events = ref<AgentTaskEvent[]>([])
const creating = ref(false)
const busy = ref(false)
const error = ref<ApiError | null>(null)

const ACTIVE = new Set(['queued', 'running', 'waiting_approval', 'paused'])
const STATUS_LABELS: Record<string, string> = {
  queued: '排队中',
  running: '执行中',
  waiting_approval: '等待确认',
  paused: '已暂停',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
}

const TOOL_LABELS: Record<string, string> = {
  squad_overview: '查看阵容',
  position_depth: '分析位置深度',
  search_players: '搜索球员',
  transfer_targets: '筛选引援目标',
  recruitment_recommend: '推荐引援目标',
  transfer_price_stats: '统计成交价',
  transfer_valuation: '估值',
  player_profile: '读取球员档案',
  player_growth: '读取成长历史',
  player_forecast: '预测成长',
  player_transfer_history: '读取转会历史',
  club_transfer_history: '汇总俱乐部转会',
  club_transfer_intelligence: '分析俱乐部策略',
  transfer_roi: '计算交易收益',
  transfer_opportunities: '扫描转会机会',
  transfer_strategy_cases: '匹配策略案例',
  record_negotiation: '记录谈判',
  negotiation_review: '复盘谈判',
}

const isActive = computed(() => (task.value ? ACTIVE.has(task.value.status) : false))
const pendingApprovals = computed(() => approvals.value.filter((item) => item.status === 'pending'))
const statusType = computed(() => {
  const status = task.value?.status
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'cancelled') return 'info'
  if (status === 'waiting_approval') return 'warning'
  return 'primary'
})
const timeline = computed(() =>
  events.value
    .filter((item) => item.type !== 'tool_started')
    .slice(-8)
    .map((item) => ({ seq: item.seq, text: describe(item), created_at: item.created_at })),
)
const citations = computed(() => task.value?.report?.citations ?? [])

function statusLabel(status: string | null | undefined): string {
  if (!status) return '未知'
  return STATUS_LABELS[status] ?? status
}

function toolLabel(name: string | null | undefined): string {
  if (!name) return '未知操作'
  return TOOL_LABELS[name] ?? name
}

function describe(event: AgentTaskEvent): string {
  const payload = event.payload ?? {}
  const tool = toolLabel(String(payload.tool ?? ''))
  if (event.type === 'task_created') return '任务已创建'
  if (event.type === 'task_started') return '开始执行'
  if (event.type === 'plan_created') return '已生成执行计划'
  if (event.type === 'step_started') return `正在${tool}`
  if (event.type === 'tool_completed') {
    const status = String(payload.status ?? 'ok')
    if (status === 'skipped') return `已跳过 ${tool}`
    if (status === 'error') return `${tool}失败`
    return `完成 ${tool}`
  }
  if (event.type === 'approval_required') return '需要你确认一项写操作'
  if (event.type === 'task_paused') return '任务已暂停，等待确认'
  if (event.type === 'task_resumed') return '任务已恢复'
  if (event.type === 'task_completed') return '报告已生成'
  if (event.type === 'task_failed') return `任务失败：${String(payload.message ?? '')}`
  if (event.type === 'task_cancelled') return '任务已取消'
  return event.type
}

async function loadTasks(): Promise<void> {
  try {
    const response = await listAgentTasks({ limit: 10 })
    tasks.value = response.items ?? []
    if (selectedId.value === null && tasks.value.length > 0) {
      selectedId.value = tasks.value[0].id
    }
  } catch (caught) {
    error.value = asApiError(caught)
  }
}

async function refreshAll(): Promise<void> {
  if (!selectedId.value) return
  try {
    const [detail, eventList, approvalList] = await Promise.all([
      getAgentTask(selectedId.value),
      listAgentTaskEvents(selectedId.value, 0),
      listAgentTaskApprovals(selectedId.value),
    ])
    task.value = detail
    events.value = eventList.items ?? []
    approvals.value = approvalList.items ?? []
    const index = tasks.value.findIndex((item) => item.id === detail.id)
    if (index >= 0) tasks.value[index] = detail
    else tasks.value = [detail, ...tasks.value]
  } catch (caught) {
    error.value = asApiError(caught)
  }
}

async function create(): Promise<void> {
  const text = goal.value.trim()
  if (text === '' || creating.value) return
  creating.value = true
  error.value = null
  try {
    const created = await createAgentTask({ goal: text })
    goal.value = ''
    selectedId.value = created.id
    task.value = created
    approvals.value = []
    events.value = []
    tasks.value = [created, ...tasks.value.filter((item) => item.id !== created.id)]
    await refreshAll()
    ElMessage.success('任务已提交，进度会实时更新')
  } catch (caught) {
    error.value = asApiError(caught)
  } finally {
    creating.value = false
  }
}

async function approve(approval: AgentApproval): Promise<void> {
  if (busy.value) return
  busy.value = true
  error.value = null
  try {
    const updated = await approveAgentTask(approval.task_id, approval.id)
    task.value = updated
    await refreshAll()
    ElMessage.success('已确认，继续执行')
  } catch (caught) {
    error.value = asApiError(caught)
    await refreshAll()
  } finally {
    busy.value = false
  }
}

async function reject(approval: AgentApproval): Promise<void> {
  if (busy.value) return
  busy.value = true
  error.value = null
  try {
    const updated = await rejectAgentTask(approval.task_id, approval.id)
    task.value = updated
    await refreshAll()
    ElMessage.info('已拒绝该写操作，任务安全结束')
  } catch (caught) {
    error.value = asApiError(caught)
    await refreshAll()
  } finally {
    busy.value = false
  }
}

async function cancel(): Promise<void> {
  if (!task.value || busy.value) return
  busy.value = true
  try {
    task.value = await cancelAgentTask(task.value.id)
    await refreshAll()
  } catch (caught) {
    error.value = asApiError(caught)
  } finally {
    busy.value = false
  }
}

function selectTask(id: string): void {
  selectedId.value = id
}

watch(selectedId, (id) => {
  if (id === null) {
    task.value = null
    events.value = []
    approvals.value = []
    return
  }
  void refreshAll()
})

watch(
  () => session.activeSaveId,
  () => {
    selectedId.value = null
    task.value = null
    events.value = []
    approvals.value = []
    tasks.value = []
    void loadTasks()
  },
)

let timer: number | null = null

onMounted(() => {
  void loadTasks()
  timer = window.setInterval(() => {
    // 后台标签页不轮询：既省请求，也避免隐藏页面持续触发重渲染。
    if (isActive.value && !document.hidden) void refreshAll()
  }, 2500)
})

onUnmounted(() => {
  if (timer !== null) window.clearInterval(timer)
})
</script>

<template>
  <section class="task-panel" aria-label="可恢复任务">
    <header class="task-panel__head">
      <span class="sm-label">任务模式</span>
      <span class="sm-text-2xs sm-text-faint">长任务会保存进度，刷新后仍可恢复；写操作必须先确认。</span>
    </header>

    <div class="task-panel__composer">
      <el-input
        v-model="goal"
        type="textarea"
        :rows="2"
        resize="none"
        :disabled="creating"
        placeholder="描述一个任务，例如：分析阵容短板并给出两条引援建议"
        aria-label="任务目标"
        data-testid="agent-task-goal"
        @keydown.enter.exact.prevent="create"
      />
      <el-button
        type="primary"
        size="small"
        :loading="creating"
        :disabled="goal.trim() === ''"
        data-testid="agent-task-create"
        @click="create"
      >
        创建任务
      </el-button>
    </div>

    <el-alert v-if="error" type="error" :closable="false" show-icon class="task-panel__alert">
      <template #title>
        <span class="sm-text-xs">{{ error.message }}</span>
      </template>
    </el-alert>

    <article v-if="task" class="task-current" data-testid="agent-task-current">
      <div class="task-current__head">
        <el-tag size="small" :type="statusType" disable-transitions data-testid="agent-task-status">
          {{ statusLabel(task.status) }}
        </el-tag>
        <span class="task-current__goal">{{ displayText(task.user_goal) }}</span>
        <div class="task-current__actions">
          <el-button v-if="isActive" link size="small" :disabled="busy" @click="cancel">取消任务</el-button>
          <el-button link size="small" @click="refreshAll">刷新</el-button>
        </div>
      </div>

      <el-progress
        :percentage="task.progress"
        :stroke-width="6"
        :status="task.status === 'failed' ? 'exception' : task.status === 'completed' ? 'success' : undefined"
        data-testid="agent-task-progress"
      />
      <p v-if="task.current_step" class="sm-text-2xs sm-text-faint">当前步骤：{{ task.current_step }}</p>

      <ol v-if="timeline.length > 0" class="task-timeline">
        <li v-for="item in timeline" :key="item.seq" class="task-timeline__item">
          <span class="task-timeline__text">{{ item.text }}</span>
          <span class="sm-text-2xs sm-text-faint">{{ formatTime(item.created_at) }}</span>
        </li>
      </ol>

      <div
        v-for="approval in pendingApprovals"
        :key="approval.id"
        class="task-approval"
        data-testid="agent-task-approval"
      >
        <p class="task-approval__reason">需要你确认：{{ approval.reason }}</p>
        <p class="sm-text-2xs sm-text-faint">
          操作：{{ toolLabel(approval.operation_type) }} · 有效期至 {{ formatTime(approval.expires_at) }}
        </p>
        <div class="task-approval__actions">
          <el-button
            type="primary"
            size="small"
            :loading="busy"
            data-testid="agent-task-approve"
            @click="approve(approval)"
          >
            确认执行
          </el-button>
          <el-button size="small" :disabled="busy" data-testid="agent-task-reject" @click="reject(approval)">
            拒绝
          </el-button>
        </div>
      </div>

      <el-alert
        v-if="task.error"
        type="error"
        :closable="false"
        show-icon
        class="task-panel__alert"
        data-testid="agent-task-error"
      >
        <template #title>
          <span class="sm-text-xs">{{ task.error.message }}</span>
        </template>
      </el-alert>

      <div v-if="task.report" class="task-report" data-testid="agent-task-report">
        <span class="sm-label">结论</span>
        <p class="task-report__conclusion">{{ task.report.conclusion }}</p>
        <el-alert
          v-if="task.report.llm_fallback"
          type="info"
          :closable="false"
          show-icon
          class="task-panel__alert"
        >
          <template #title>
            <span class="sm-text-2xs">AI 模型不可用，已降级为本地确定性规则：{{ task.report.llm_fallback }}</span>
          </template>
        </el-alert>
        <div v-if="citations.length > 0" class="task-report__cites">
          <span class="sm-label">引用来源</span>
          <ul>
            <li v-for="(citation, index) in citations" :key="`${citation.tool}-${index}`">
              <span class="sm-mono">{{ toolLabel(citation.tool) }}</span>
              <span class="sm-text-2xs sm-text-faint">{{ citation.summary }}</span>
            </li>
          </ul>
        </div>
        <el-collapse class="task-report__diag">
          <el-collapse-item title="高级诊断" name="diagnostics">
            <dl class="task-diag">
              <div><dt>任务类型</dt><dd>{{ task.task_type }}</dd></div>
              <div><dt>Provider</dt><dd>{{ displayText(task.provider_id) }}</dd></div>
              <div><dt>模型</dt><dd>{{ displayText(task.model_id) }}</dd></div>
              <div><dt>模式</dt><dd>{{ displayText(task.mode) }}</dd></div>
              <div><dt>步数</dt><dd>{{ task.step_count }}</dd></div>
              <div><dt>工具调用</dt><dd>{{ task.tool_call_count }}</dd></div>
            </dl>
          </el-collapse-item>
        </el-collapse>
      </div>
    </article>

    <div v-if="tasks.length > 0" class="task-history" data-testid="agent-task-history">
      <span class="sm-label">最近任务</span>
      <div class="task-history__list">
        <button
          v-for="item in tasks.slice(0, 5)"
          :key="item.id"
          type="button"
          class="task-history__item"
          :class="{ 'task-history__item--active': item.id === selectedId }"
          @click="selectTask(item.id)"
        >
          <span class="task-history__goal">{{ displayText(item.user_goal) }}</span>
          <span class="sm-text-2xs sm-text-faint">{{ statusLabel(item.status) }} · {{ formatTime(item.created_at) }}</span>
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.task-panel {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-3);
  padding: var(--sm-space-3) var(--sm-space-4);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-lg);
  background: linear-gradient(150deg, rgba(34, 211, 238, 0.05), transparent 60%), var(--sm-surface-2);
}

.task-panel__head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--sm-space-2);
}

.task-panel__composer {
  display: flex;
  align-items: flex-end;
  gap: var(--sm-space-2);
}

.task-panel__composer :deep(.el-textarea) {
  flex: 1 1 auto;
}

.task-panel__alert {
  border-radius: var(--sm-radius-md);
}

.task-current {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-2);
  padding: var(--sm-space-3);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-md);
  background: var(--sm-surface);
}

.task-current__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sm-space-2);
}

.task-current__goal {
  flex: 1 1 auto;
  color: var(--sm-text);
  font-size: var(--sm-fs-sm);
}

.task-current__actions {
  display: flex;
  gap: var(--sm-space-1);
}

.task-timeline {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin: 0;
  padding-left: var(--sm-space-4);
  color: var(--sm-text-2);
  font-size: var(--sm-fs-xs);
}

.task-timeline__item {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--sm-space-2);
}

.task-timeline__text {
  overflow-wrap: anywhere;
}

.task-approval {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-1);
  padding: var(--sm-space-2) var(--sm-space-3);
  border: 1px solid var(--sm-warn);
  border-radius: var(--sm-radius-md);
  background: rgba(245, 158, 11, 0.08);
}

.task-approval__reason {
  color: var(--sm-text);
  font-size: var(--sm-fs-sm);
}

.task-approval__actions {
  display: flex;
  gap: var(--sm-space-2);
}

.task-report {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-2);
  padding-top: var(--sm-space-2);
  border-top: 1px dashed var(--sm-border);
}

.task-report__conclusion {
  color: var(--sm-text);
  font-size: var(--sm-fs-sm);
  line-height: 1.75;
}

.task-report__cites ul {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.task-report__cites li {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sm-space-2);
  align-items: baseline;
}

.task-diag {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: var(--sm-space-2);
  margin: 0;
}

.task-diag div {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.task-diag dt {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}

.task-diag dd {
  margin: 0;
  color: var(--sm-text);
  font-size: var(--sm-fs-xs);
  font-variant-numeric: tabular-nums;
}

.task-history {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-2);
}

.task-history__list {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sm-space-2);
}

.task-history__item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-width: 260px;
  padding: 6px 10px;
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-md);
  background: var(--sm-surface);
  color: var(--sm-text-2);
  text-align: left;
  cursor: pointer;
}

.task-history__item--active {
  border-color: var(--sm-accent-cyan);
}

.task-history__goal {
  overflow: hidden;
  font-size: var(--sm-fs-xs);
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 640px) {
  .task-panel__composer {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
