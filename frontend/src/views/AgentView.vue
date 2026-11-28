/** AI 球探助手：会话、结构化回答、可靠性分类、工具引用、球员卡片与确定性模式提示。 */

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { asApiError, type ApiError } from '../api/client'
import {
  createConversation,
  deleteConversation,
  listConversations,
  listMessages,
  sendMessage,
} from '../api/agent'
import { addWatchlistItem } from '../api/watchlist'
import ConfidenceTag from '../components/ConfidenceTag.vue'
import EmptyState from '../components/EmptyState.vue'
import ErrorState from '../components/ErrorState.vue'
import PageHeader from '../components/PageHeader.vue'
import AppTag from '../components/AppTag.vue'
import type { AgentAnswer, AgentMessage, AgentPlayerCard, AgentToolCall, Conversation } from '../types/agent'
import { useSessionStore } from '../stores/session'
import { EMPTY, displayText, formatInt, formatTime } from '../utils/format'
import { agentModeLabel, positionLabel } from '../utils/labels'

const session = useSessionStore()
const router = useRouter()
const route = useRoute()

const conversations = ref<Conversation[]>([])
const conversationsLoading = ref(false)
const conversationsError = ref<ApiError | null>(null)

const activeId = ref<number | null>(null)
const messages = ref<AgentMessage[]>([])
const messagesLoading = ref(false)
const messagesError = ref<ApiError | null>(null)

const question = ref('')
const sending = ref(false)
const sendError = ref<ApiError | null>(null)
const instanceContext = ref<number | undefined>(undefined)
const lastMode = ref<string | null>(null)
const thread = ref<HTMLElement | null>(null)

/** Suggested questions from the product spec; they work in deterministic mode too. */
const SUGGESTIONS = [
  '帮我分析目前球队阵容。',
  '哪些位置需要补强？',
  '帮我寻找年轻前锋。',
  '哪些球员值得重点培养？',
  '哪些球员可能需要出售？',
  '帮我比较两名球员。',
]

const activeConversation = computed(
  () => conversations.value.find((conversation) => conversation.id === activeId.value) ?? null,
)

/** Free-text input is disabled when the backend reports no LLM; suggestions still run deterministic answers. */
const inputDisabled = computed(() => session.meta !== null && !session.agentLlm)

const llmNotice = computed(() =>
  session.meta !== null && !session.agentLlm
    ? '本地尚未配置 AI 模型，自由提问已停用；点击下方推荐问题，仍会基于真实数据作答。'
    : '',
)

/** Load the conversation list and keep a valid selection. */
async function loadConversations(): Promise<void> {
  conversationsLoading.value = true
  conversationsError.value = null
  try {
    const response = await listConversations(session.activeSaveId ?? undefined)
    conversations.value = response.items ?? []
    if (activeId.value === null || !conversations.value.some((item) => item.id === activeId.value)) {
      activeId.value = conversations.value[0]?.id ?? null
    }
  } catch (caught) {
    conversationsError.value = asApiError(caught)
    conversations.value = []
  } finally {
    conversationsLoading.value = false
  }
}

/** Load the transcript of the selected conversation. */
async function loadMessages(): Promise<void> {
  const id = activeId.value
  if (id === null) {
    messages.value = []
    return
  }
  messagesLoading.value = true
  messagesError.value = null
  try {
    const response = await listMessages(id)
    messages.value = response.items ?? []
    await nextTick()
    if (thread.value) thread.value.scrollTop = thread.value.scrollHeight
  } catch (caught) {
    messagesError.value = asApiError(caught)
    messages.value = []
  } finally {
    messagesLoading.value = false
  }
}

/** Create a new conversation and select it. */
async function startConversation(): Promise<void> {
  conversationsLoading.value = true
  conversationsError.value = null
  try {
    const created = await createConversation()
    conversations.value = [created, ...conversations.value]
    activeId.value = created.id
    messages.value = []
  } catch (caught) {
    conversationsError.value = asApiError(caught)
  } finally {
    conversationsLoading.value = false
  }
}

/** Ensure a conversation exists before sending the first question. */
async function ensureConversation(): Promise<number | null> {
  if (activeId.value !== null) return activeId.value
  try {
    const created = await createConversation()
    conversations.value = [created, ...conversations.value]
    activeId.value = created.id
    return created.id
  } catch (caught) {
    sendError.value = asApiError(caught)
    return null
  }
}

/** Ask one question (free input or a suggestion) and reload the transcript. */
async function ask(text: string): Promise<void> {
  const trimmed = text.trim()
  if (trimmed === '' || sending.value) return
  const id = await ensureConversation()
  if (id === null) return
  sending.value = true
  sendError.value = null
  try {
    const response = await sendMessage(id, {
      question: trimmed,
      save_id: session.activeSaveId ?? undefined,
      instance_id: instanceContext.value,
    })
    lastMode.value = response.mode
    question.value = ''
    await loadMessages()
    await loadConversations()
  } catch (caught) {
    sendError.value = asApiError(caught)
  } finally {
    sending.value = false
  }
}

/** Submit the composer text. */
function submit(): void {
  if (inputDisabled.value) return
  void ask(question.value)
}

/** Delete the active conversation and start a clean one. */
async function clearConversation(): Promise<void> {
  if (activeId.value === null) {
    await startConversation()
    return
  }
  try {
    await ElMessageBox.confirm('清空后会删除当前会话及其消息（已保存的报告保留）。是否继续？', '清空对话', {
      type: 'warning',
      confirmButtonText: '清空',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await deleteConversation(activeId.value)
    activeId.value = null
    messages.value = []
    await loadConversations()
    ElMessage.success('对话已清空')
  } catch (caught) {
    ElMessage.error(`清空失败：${asApiError(caught).message}`)
  }
}

/** Follow one player card; the backend rejects duplicates with a readable message. */
async function followCard(card: AgentPlayerCard): Promise<void> {
  try {
    await addWatchlistItem({ instance_id: card.instance_id })
    ElMessage.success(`已关注 ${card.name}`)
  } catch (caught) {
    const error = asApiError(caught)
    ElMessage.warning(error.message)
  }
}

/** Open the player detail page of one card. */
function openCard(card: AgentPlayerCard): void {
  void router.push(`/players/${card.instance_id}`)
}

/** Render a tool-call argument object as compact JSON. */
function toolArguments(tool: AgentToolCall): string {
  try {
    return JSON.stringify(tool.arguments, null, 2)
  } catch {
    return '（参数无法序列化）'
  }
}

/** Filter chips of a structured answer. */
function answerFilters(answer: AgentAnswer): Array<{ key: string; value: string }> {
  return Object.entries(answer.filters ?? {}).map(([key, value]) => ({
    key,
    value: typeof value === 'string' || typeof value === 'number' ? String(value) : displayText(null),
  }))
}

/** Sections in the order returned by the backend. */
function answerSections(answer: AgentAnswer): AgentAnswer['sections'] {
  return answer.sections ?? []
}

/** Chinese label of one reliability class. */
function reliabilityLabel(value: string): string {
  return (
    { fact: '数据库事实', computed: '模型计算', inference: 'AI 推断', unavailable: '无法获得' }[value] ?? value
  )
}

/** Element tag type of one reliability class. */
/** Select a conversation from the sidebar. */
function selectConversation(id: number): void {
  activeId.value = id
}

watch(
  [() => session.activeSaveId, () => session.dataRevision],
  () => {
    activeId.value = null
    void loadConversations()
  },
  { immediate: true },
)

watch(activeId, () => {
  void loadMessages()
})

/** Accept a preset question and player context from the player detail page. */
async function applyRouteContext(): Promise<void> {
  const rawInstance = route.query.instance_id
  if (typeof rawInstance === 'string' && Number.isFinite(Number(rawInstance))) {
    instanceContext.value = Number(rawInstance)
  }
  const preset = route.query.q
  if (typeof preset === 'string' && preset.trim() !== '') {
    await ask(preset)
    void router.replace({ query: {} })
  }
}

onMounted(() => {
  void applyRouteContext()
})
</script>

<template>
  <div class="sm-page agent-page">
    <PageHeader
      title="AI 球探助手"
      description="用一句话提问，助手只基于本存档的真实数据回答；结论、依据、数据缺口与球员卡片都可核对。"
    >
      <template #meta>
        <AppTag
          :tag="session.agentLlm ? 'ai_llm' : 'ai_rules'"
          :label="session.agentLlm ? 'AI 模型已配置' : '本地规则模式（未配置 AI 模型）'"
        />
        <AppTag v-if="lastMode" :tag="lastMode === 'llm' ? 'ai_llm' : 'ai_rules'" :label="`最近回答：${agentModeLabel(lastMode)}`" />
        <span class="sm-text-xs sm-text-faint">会话 {{ formatInt(conversations.length) }} 个</span>
      </template>
      <template #actions>
        <el-button size="small" :loading="conversationsLoading" @click="startConversation">新建会话</el-button>
        <el-button size="small" @click="clearConversation">清空对话</el-button>
        <el-button size="small" @click="loadConversations">刷新会话</el-button>
      </template>
    </PageHeader>

    <el-alert v-if="llmNotice" class="agent-notice" type="info" :closable="false" show-icon>
      <template #title>
        <span class="sm-text-xs">{{ llmNotice }}</span>
      </template>
    </el-alert>

    <section class="agent-tasks" aria-label="常用任务">
      <span class="sm-label">常用任务</span>
      <div class="agent-tasks__list">
        <button
          v-for="suggestion in SUGGESTIONS"
          :key="`task-${suggestion}`"
          type="button"
          class="agent-task"
          :disabled="sending"
          :title="suggestion"
          @click="ask(suggestion)"
        >
          {{ suggestion }}
        </button>
      </div>
    </section>

    <div class="agent-layout">
      <aside class="conversations" aria-label="会话列表">
        <div class="conversations__head">
          <span class="sm-label">会话记录</span>
          <span class="conversations__count sm-num">{{ formatInt(conversations.length) }}</span>
        </div>
        <ErrorState v-if="conversationsError" :error="conversationsError" compact @retry="loadConversations" />
        <div v-else-if="conversationsLoading && conversations.length === 0" class="sm-stack">
          <el-skeleton :rows="5" animated />
        </div>
        <EmptyState
          v-else-if="conversations.length === 0"
          title="还没有会话"
          description="新建会话后即可提问。"
          compact
        >
          <el-button size="small" type="primary" @click="startConversation">新建会话</el-button>
        </EmptyState>
        <ul v-else class="conversation-list">
          <li v-for="conversation in conversations" :key="conversation.id">
            <button
              type="button"
              class="conversation"
              :class="{ 'conversation--active': conversation.id === activeId }"
              :aria-current="conversation.id === activeId ? 'true' : undefined"
              @click="selectConversation(conversation.id)"
            >
              <span class="conversation__title">{{ displayText(conversation.title) }}</span>
              <span class="conversation__meta">
                {{ formatInt(conversation.message_count) }} 条消息 · {{ formatTime(conversation.created_at) }}
              </span>
            </button>
          </li>
        </ul>
      </aside>

      <section class="chat">
        <header class="chat__head">
          <div class="chat__title">{{ activeConversation ? displayText(activeConversation.title) : '新会话' }}</div>
          <span class="chat__context">
            上下文：存档 {{ session.activeSaveId ?? EMPTY
            }}<template v-if="instanceContext !== undefined"> · 实例 {{ instanceContext }}</template>
          </span>
        </header>

        <div ref="thread" class="chat__thread" role="log" aria-live="polite">
          <ErrorState v-if="messagesError" :error="messagesError" @retry="loadMessages" />

          <div v-else-if="messagesLoading && messages.length === 0" class="sm-stack">
            <el-skeleton :rows="6" animated />
          </div>

          <EmptyState
            v-else-if="messages.length === 0"
            title="提出第一个问题"
            description="示例问题覆盖估值、合同到期、角色评分与统计样本；回答会展示样本量、置信度、数据缺口与工具调用。"
            compact
          >
            <div class="suggestions suggestions--inline">
              <button
                v-for="suggestion in SUGGESTIONS"
                :key="suggestion"
                type="button"
                class="suggestion"
                :disabled="sending"
                @click="ask(suggestion)"
              >
                {{ suggestion }}
              </button>
            </div>
          </EmptyState>

          <template v-else>
            <article
              v-for="message in messages"
              :key="message.id"
              class="message"
              :class="message.role === 'user' ? 'message--user' : 'message--assistant'"
            >
              <div class="message__meta">
                <span class="message__role">{{ message.role === 'user' ? '你' : 'ScoutMind' }}</span>
                <span class="message__time">{{ formatTime(message.created_at) }}</span>
                <template v-if="message.role !== 'user' && message.answer">
                  <ConfidenceTag :confidence="message.answer.confidence" />
                  <span class="chip">样本量 {{ formatInt(message.answer.sample_size) }}</span>
                  <span class="chip">模式 {{ agentModeLabel(message.answer.mode) }}</span>
                  <span v-for="filter in answerFilters(message.answer)" :key="filter.key" class="chip">
                    {{ filter.key }}={{ filter.value }}
                  </span>
                  <span v-if="(message.answer.citations ?? []).length > 0" class="meta-cites">
                    <span class="meta-cites__label">引用</span>
                    <span
                      v-for="(citation, index) in message.answer.citations ?? []"
                      :key="`${citation.tool}-meta-${index}`"
                      class="chip chip--cite"
                      :title="citation.summary"
                    >
                      <span class="sm-mono">{{ citation.tool }}</span>
                    </span>
                  </span>
                </template>
              </div>

              <div v-if="message.role === 'user'" class="message__bubble">{{ message.content }}</div>

              <div v-else class="answer">
                <template v-if="message.answer">
                  <span class="sm-label">结论</span>
                  <p class="answer__conclusion">{{ message.answer.conclusion }}</p>

                  <el-alert
                    v-if="(message.answer.warnings ?? []).length > 0"
                    type="warning"
                    :closable="false"
                    show-icon
                    class="answer__warnings"
                  >
                    <template #title>
                      <span class="sm-text-xs">{{ (message.answer.warnings ?? []).join(' ') }}</span>
                    </template>
                  </el-alert>

                  <span v-if="answerSections(message.answer).length > 0" class="sm-label">依据分析</span>
                  <section v-for="section in answerSections(message.answer)" :key="section.key" class="answer__section">
                    <h3 class="answer__section-title">
                      {{ section.title }}
                      <AppTag
                        v-if="section.reliability"
                        :tag="`reliability_${section.reliability}`"
                        :label="reliabilityLabel(section.reliability)"
                      />
                    </h3>
                    <ul v-if="section.bullets && section.bullets.length > 0" class="answer__bullets">
                      <li v-for="bullet in section.bullets" :key="bullet">{{ bullet }}</li>
                    </ul>
                    <div v-if="section.table" class="answer-table__wrap">
                      <table class="answer-table">
                        <thead>
                          <tr>
                            <th v-for="(column, index) in section.table.columns" :key="`${column}-${index}`">{{ column }}</th>
                          </tr>
                        </thead>
                        <tbody>
                          <tr v-for="(row, rowIndex) in section.table.rows" :key="rowIndex">
                            <td v-for="(cell, cellIndex) in row" :key="cellIndex" :class="{ 'sm-null': cell === null }">
                              {{ displayText(cell) }}
                            </td>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                  </section>

                  <div v-if="message.answer.reliability" class="answer__block">
                    <span class="sm-label">可靠性分类</span>
                    <div class="answer__reliability">
                      <AppTag tag="reliability_fact" :label="`事实 ${message.answer.reliability.facts.length}`" />
                      <AppTag tag="reliability_computed" :label="`计算 ${message.answer.reliability.computed.length}`" />
                      <AppTag tag="reliability_inference" :label="`推断 ${message.answer.reliability.inferences.length}`" />
                      <AppTag tag="reliability_unavailable" :label="`无法获得 ${message.answer.reliability.unavailable.length}`" />
                    </div>
                    <ul v-if="message.answer.reliability.unavailable.length > 0" class="answer__bullets">
                      <li v-for="item in message.answer.reliability.unavailable" :key="item">{{ item }}</li>
                    </ul>
                    <p v-if="message.answer.reliability.rule" class="sm-text-2xs sm-text-faint">
                      {{ message.answer.reliability.rule }}
                    </p>
                  </div>

                  <div v-if="(message.answer.citations ?? []).length > 0" class="answer__block">
                    <span class="sm-label">引用来源</span>
                    <ul class="answer__evidence">
                      <li v-for="(citation, index) in message.answer.citations ?? []" :key="`${citation.tool}-${index}`">
                        <span class="sm-mono">{{ citation.tool }}</span>
                        <span class="sm-text-2xs sm-text-faint">{{ citation.summary }}</span>
                      </li>
                    </ul>
                  </div>

                  <div v-if="message.answer.data_gaps.length > 0" class="answer__block">
                    <span class="sm-label">数据缺口</span>
                    <ul class="answer__bullets">
                      <li v-for="gap in message.answer.data_gaps" :key="gap">{{ gap }}</li>
                    </ul>
                  </div>

                  <div v-if="message.answer.disclaimers.length > 0" class="answer__block answer__disclaimers">
                    <span class="sm-label">声明</span>
                    <ul class="answer__bullets">
                      <li v-for="disclaimer in message.answer.disclaimers" :key="disclaimer">{{ disclaimer }}</li>
                    </ul>
                  </div>

                  <div v-if="message.answer.evidence.length > 0" class="answer__block">
                    <span class="sm-label">证据</span>
                    <ul class="answer__evidence">
                      <li v-for="(item, index) in message.answer.evidence" :key="`${item.label}-${index}`">
                        <span class="sm-mono">{{ item.label }}</span>
                        <span class="sm-text-2xs sm-text-faint">{{ item.type }}</span>
                      </li>
                    </ul>
                  </div>

                  <div v-if="(message.answer.player_cards ?? []).length > 0" class="answer__block">
                    <span class="sm-label">相关球员 · 下一步</span>
                    <p class="sm-text-2xs sm-text-faint">
                      可打开球员详情核实能力与合同，或直接加入关注名单持续跟踪。
                    </p>
                    <div class="agent-cards">
                      <article
                        v-for="card in message.answer.player_cards ?? []"
                        :key="`card-${message.id}-${card.instance_id}`"
                        class="agent-card"
                      >
                        <button type="button" class="agent-card__name" @click="openCard(card)">
                          {{ card.name }}
                        </button>
                        <p class="agent-card__meta">
                          {{ positionLabel(card.position) }}
                          <template v-if="card.age !== null"> · {{ card.age }} 岁</template>
                          <template v-if="card.club"> · {{ card.club }}</template>
                        </p>
                        <p class="agent-card__stats">
                          CA {{ card.ca ?? EMPTY }} · PA {{ card.pa ?? EMPTY }}
                        </p>
                        <div class="agent-card__actions">
                          <el-button link size="small" @click="openCard(card)">查看详情</el-button>
                          <el-button link size="small" type="primary" @click="followCard(card)">关注</el-button>
                        </div>
                      </article>
                    </div>
                  </div>

                  <el-collapse v-if="message.tool_calls.length > 0" class="answer__tools">
                    <el-collapse-item :name="`tools-${message.id}`">
                      <template #title>
                        <span class="sm-text-xs">工具调用（{{ message.tool_calls.length }}）</span>
                      </template>
                      <div v-for="(tool, index) in message.tool_calls" :key="`${tool.name}-${index}`" class="tool">
                        <div class="tool__head">
                          <span class="sm-mono">{{ tool.name }}</span>
                          <span v-if="tool.result_summary" class="sm-text-2xs sm-text-faint">{{ tool.result_summary }}</span>
                        </div>
                        <pre class="sm-code">{{ toolArguments(tool) }}</pre>
                      </div>
                    </el-collapse-item>
                  </el-collapse>
                </template>
                <p v-else class="message__bubble">{{ message.content || EMPTY }}</p>
              </div>
            </article>
          </template>

          <div v-if="sending" class="chat__pending" role="status">
            <span class="chat__pending-dot" aria-hidden="true" />
            <span class="sm-text-xs sm-text-faint">正在等待后端工具结果…</span>
          </div>

          <ErrorState v-if="sendError" :error="sendError" compact @retry="submit" />
        </div>

        <footer class="chat__composer">
          <div v-if="llmNotice" class="composer__notice">{{ llmNotice }}</div>
          <div class="composer__row">
            <el-input
              v-model="question"
              type="textarea"
              :rows="2"
              resize="none"
              :disabled="inputDisabled || sending"
              :placeholder="inputDisabled ? '本地未配置 AI 模型：请使用下方推荐问题' : '输入问题，例如：20 岁 CA 145 PA 175 的前锋通常卖多少钱？'"
              aria-label="向 AI 球探助手提问"
              @keydown.enter.exact.prevent="submit"
            />
            <div class="composer__side">
              <el-input-number
                v-model="instanceContext"
                size="small"
                :min="1"
                :controls="false"
                placeholder="实例 ID（可选）"
                aria-label="上下文球员实例 ID"
                class="composer__instance"
              />
              <el-button type="primary" size="small" :loading="sending" :disabled="inputDisabled || question.trim() === ''" @click="submit">
                发送
              </el-button>
            </div>
          </div>
          <div class="suggestions">
            <button
              v-for="suggestion in SUGGESTIONS"
              :key="suggestion"
              type="button"
              class="suggestion"
              :disabled="sending"
              @click="ask(suggestion)"
            >
              {{ suggestion }}
            </button>
          </div>
          <p class="composer__hint">
            回答由后端确定性规则或 LLM 生成；页面不重排、不改写任何数值，样本不足时后端会返回
            insufficient_sample 并拒绝精确估值。
          </p>
        </footer>
      </section>
    </div>
  </div>
</template>

<style scoped>
.agent-page {
  min-height: 0;
}

.agent-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: var(--sm-space-2);
  margin-top: var(--sm-space-2);
}

.agent-card {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--sm-space-2) var(--sm-space-3);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-md);
  background: var(--sm-surface-2);
}

.agent-card__name {
  padding: 0;
  border: 0;
  background: none;
  color: var(--sm-accent);
  font: inherit;
  font-weight: var(--sm-fw-medium);
  text-align: left;
  cursor: pointer;
}

.agent-card__name:hover {
  text-decoration: underline;
}

.agent-card__meta,
.agent-card__stats {
  color: var(--sm-text-2);
  font-size: var(--sm-fs-2xs);
}

.agent-card__actions {
  display: flex;
  gap: var(--sm-space-2);
  margin-top: var(--sm-space-1);
}

.agent-notice {
  margin-bottom: 0;
  border-radius: var(--sm-radius-md);
}

.agent-tasks {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-2);
}

.agent-tasks__list {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sm-space-2);
}

.agent-task {
  padding: 6px 12px;
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-pill);
  background: var(--sm-surface-2);
  color: var(--sm-text-2);
  font-size: var(--sm-fs-xs);
  cursor: pointer;
}

.agent-task:hover:not(:disabled) {
  border-color: var(--sm-border-glow);
  color: var(--sm-text-primary);
}

.agent-layout {
  display: grid;
  grid-template-columns: 272px minmax(0, 1fr);
  gap: var(--sm-space-4);
  min-height: 0;
}

/* ---------- 会话面板 ---------- */

.conversations {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-2);
  min-width: 0;
  max-height: 720px;
  padding: var(--sm-space-3);
  overflow-y: auto;
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-lg);
  background: var(--sm-surface);
  box-shadow: var(--sm-shadow-1);
}

.conversations__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--sm-space-1);
}

.conversations__count {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}

.conversation-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.conversation {
  display: flex;
  flex-direction: column;
  gap: 2px;
  width: 100%;
  padding: var(--sm-space-2);
  border: 1px solid transparent;
  border-left: 2px solid transparent;
  border-radius: var(--sm-radius-md);
  background: none;
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition:
    background-color var(--sm-dur-1) var(--sm-ease-out),
    border-color var(--sm-dur-1) var(--sm-ease-out);
}

.conversation:hover {
  background: var(--sm-surface-2);
}

.conversation--active {
  border-color: var(--sm-border);
  border-left-color: var(--sm-accent-blue);
  background: var(--sm-accent-weak);
}

.conversation__title {
  color: var(--sm-text);
  font-size: var(--sm-fs-sm);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.conversation__meta {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}

/* ---------- 对话面板 ---------- */

.chat {
  display: flex;
  flex-direction: column;
  min-width: 0;
  height: clamp(520px, calc(100vh - 300px), 900px);
  overflow: hidden;
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-lg);
  background: var(--sm-surface);
  box-shadow: var(--sm-shadow-1);
}

.chat__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--sm-space-2);
  padding: var(--sm-space-3) var(--sm-space-4);
  border-bottom: 1px solid var(--sm-border);
}

.chat__title {
  color: var(--sm-text);
  font-size: var(--sm-fs-md);
  font-weight: var(--sm-fw-semibold);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chat__context {
  flex: 0 0 auto;
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
  font-variant-numeric: tabular-nums;
}

.chat__thread {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  gap: var(--sm-space-4);
  min-height: 0;
  padding: var(--sm-space-4);
  overflow-y: auto;
  background: radial-gradient(720px 260px at 12% 0%, rgba(53, 106, 230, 0.04), transparent 72%);
}

/* ---------- 消息 ---------- */

.message {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-1);
  min-width: 0;
}

.message__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sm-space-2);
  min-width: 0;
}

.message__role {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--sm-text-2);
  font-size: var(--sm-fs-2xs);
  font-weight: var(--sm-fw-medium);
}

.message__role::before {
  content: '';
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--sm-text-3);
}

.message--assistant .message__role {
  color: var(--sm-text);
}

.message--assistant .message__role::before {
  background: var(--sm-accent-blue);
  box-shadow: 0 0 0 3px rgba(53, 106, 230, 0.14);
}

.message__time {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
  font-variant-numeric: tabular-nums;
}

.message--user {
  align-items: flex-end;
}

.message--user .message__meta {
  flex-direction: row-reverse;
}

.message__bubble {
  max-width: min(68ch, 100%);
  padding: var(--sm-space-2) var(--sm-space-3);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-lg);
  background: var(--sm-surface-2);
  color: var(--sm-text);
  font-size: var(--sm-fs-sm);
  line-height: 1.75;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

/* 助手没有结构化回答时，内容直接落在 .answer 面板里，不再套一层气泡。 */
.answer > .message__bubble {
  max-width: none;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: none;
}

.chip {
  display: inline-flex;
  align-items: center;
  padding: 1px 7px;
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-pill);
  background: var(--sm-surface);
  color: var(--sm-text-2);
  font-size: var(--sm-fs-2xs);
}

.chip--cite {
  border-color: var(--sm-border-strong);
}

.meta-cites {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sm-space-1);
  min-width: 0;
}

.meta-cites__label {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}

/* ---------- 结构化回答 ---------- */

.answer {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-3);
  width: 100%;
  max-width: 96ch;
  padding: var(--sm-space-3) var(--sm-space-4) var(--sm-space-4);
  border: 1px solid var(--sm-border);
  border-left: 2px solid rgba(53, 106, 230, 0.4);
  border-radius: var(--sm-radius-lg);
  background:
    linear-gradient(150deg, rgba(53, 106, 230, 0.05) 0%, rgba(124, 107, 214, 0.03) 42%, transparent 72%),
    var(--sm-surface-2);
}

.answer__conclusion {
  color: var(--sm-text);
  font-size: var(--sm-fs-sm);
  line-height: 1.8;
}

.answer__section {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-1);
}

.answer__section-title {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sm-space-2);
  color: var(--sm-text);
  font-size: var(--sm-fs-sm);
  font-weight: var(--sm-fw-semibold);
}

.answer__bullets {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin: 0;
  padding-left: var(--sm-space-4);
  color: var(--sm-text-2);
  font-size: var(--sm-fs-xs);
  line-height: 1.7;
}

.answer-table__wrap {
  overflow-x: auto;
}

.answer-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--sm-fs-xs);
}

.answer-table th,
.answer-table td {
  padding: var(--sm-space-1) var(--sm-space-2);
  border-bottom: 1px solid var(--sm-border);
  text-align: left;
}

.answer-table th {
  color: var(--sm-text-3);
  font-weight: var(--sm-fw-medium);
}

.answer-table td {
  color: var(--sm-text);
  font-variant-numeric: tabular-nums;
}

.answer__block {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.answer__disclaimers {
  padding-top: var(--sm-space-2);
  border-top: 1px dashed var(--sm-border);
}

.answer__evidence {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sm-space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.answer__evidence li {
  display: flex;
  align-items: baseline;
  gap: var(--sm-space-1);
  padding: 1px 6px;
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-sm);
  background: var(--sm-surface);
}

.answer__reliability {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sm-space-2);
  margin-bottom: var(--sm-space-2);
}

.answer__tools {
  padding-top: var(--sm-space-1);
  border-top: 1px solid var(--sm-border);
}

.tool {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-1);
  margin-bottom: var(--sm-space-2);
}

.tool__head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--sm-space-2);
}

/* ---------- 等待状态 ---------- */

.chat__pending {
  display: flex;
  align-items: center;
  gap: var(--sm-space-2);
  padding: var(--sm-space-1) 0;
}

.chat__pending-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--sm-accent-cyan);
  animation: agent-pulse 1.4s var(--sm-ease-out) infinite;
}

@keyframes agent-pulse {
  0%,
  100% {
    opacity: 1;
    transform: scale(1);
  }

  50% {
    opacity: 0.5;
    transform: scale(0.8);
  }
}

@media (prefers-reduced-motion: reduce) {
  .chat__pending-dot {
    animation: none;
  }
}

/* ---------- 输入区 ---------- */

.chat__composer {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-2);
  padding: var(--sm-space-3) var(--sm-space-4) var(--sm-space-4);
  border-top: 1px solid var(--sm-border);
  background: var(--sm-surface-2);
}

.composer__notice {
  color: var(--sm-warn);
  font-size: var(--sm-fs-2xs);
  line-height: 1.6;
}

.composer__row {
  display: flex;
  gap: var(--sm-space-2);
  align-items: flex-end;
}

.composer__side {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-1);
  width: 132px;
}

.composer__instance {
  width: 100%;
}

.suggestions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sm-space-1);
}

.suggestions--inline {
  margin-top: var(--sm-space-2);
}

.suggestion {
  padding: 2px 8px;
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-pill);
  background: var(--sm-surface);
  color: var(--sm-text-2);
  font-size: var(--sm-fs-2xs);
  text-align: left;
  cursor: pointer;
  transition:
    border-color var(--sm-dur-1) var(--sm-ease-out),
    color var(--sm-dur-1) var(--sm-ease-out);
}

.suggestion:hover:enabled {
  border-color: var(--sm-accent-cyan);
  color: var(--sm-accent-cyan);
}

.suggestion:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.composer__hint {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
  line-height: 1.6;
}

/* ---------- 响应式 ---------- */

@media (max-width: 1180px) {
  .agent-layout {
    grid-template-columns: minmax(0, 1fr);
  }

  .conversations {
    max-height: 264px;
  }

  .chat {
    height: auto;
  }

  .chat__thread {
    min-height: 320px;
    max-height: 60vh;
  }
}

@media (max-width: 640px) {
  .chat__head {
    flex-direction: column;
    align-items: flex-start;
    gap: 2px;
    padding: var(--sm-space-3);
  }

  .chat__thread {
    min-height: 280px;
    max-height: 54vh;
    padding: var(--sm-space-3);
    gap: var(--sm-space-3);
  }

  .chat__composer {
    padding: var(--sm-space-3);
  }

  .composer__row {
    flex-direction: column;
    align-items: stretch;
  }

  .composer__side {
    flex-direction: row;
    align-items: center;
    width: 100%;
  }

  .composer__instance {
    flex: 1 1 auto;
    width: auto;
  }

  .answer {
    max-width: 100%;
  }
}
</style>
