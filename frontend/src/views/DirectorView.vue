<script setup lang="ts">
/**
 * AI 足球总监工作台（V3.3.2）。
 *
 * 左侧是当前存档与俱乐部上下文，中间是问题与分析结果，右侧是可操作的球员卡片。
 * 所有结论来自后端确定性工具；前端不计算分数，也不推测缺失字段。
 */

import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import EmptyState from '../components/EmptyState.vue'
import InsightPanel from '../components/InsightPanel.vue'
import LoadingBlock from '../components/LoadingBlock.vue'
import PageHeader from '../components/PageHeader.vue'
import StatStrip from '../components/StatStrip.vue'
import { asApiError, type ApiError } from '../api/client'
import { askDirector, getDirectorContext } from '../api/director'
import { addWatchlistItem } from '../api/watchlist'
import { useCompareStore } from '../stores/compare'
import { useSessionStore } from '../stores/session'
import type {
  DirectorAnswer,
  DirectorContext,
  DirectorRecommendation,
  DirectorSection,
} from '../types/director'
import type { InsightItem, StatItem } from '../types/ui'
import { EMPTY, formatMoney } from '../utils/format'

const QUICK_QUESTIONS = [
  '分析我的球队阵容',
  '我的球队最需要补强什么位置？',
  '帮我寻找年轻引援目标',
  '哪些球员值得重点培养？',
  '哪些球员可以考虑出售？',
  '帮我分析球队年龄结构',
  '分析当前关注名单',
  '制定下一阶段引援计划',
]

/** 任务卡：与快捷问题使用同一批后端意图，只补充面向用户的任务说明。 */
const TASKS = [
  { label: '分析我的球队阵容', goal: '看清阵容结构、短板与可用球员' },
  { label: '我的球队最需要补强什么位置？', goal: '确定当前最该补强的位置' },
  { label: '帮我寻找年轻引援目标', goal: '按年龄与潜力筛选可引进球员' },
  { label: '哪些球员值得重点培养？', goal: '识别成长空间最大的球员' },
  { label: '哪些球员可以考虑出售？', goal: '发现可以变现或清理的合同' },
  { label: '帮我分析球队年龄结构', goal: '检查阵容老化与接班风险' },
  { label: '制定下一阶段引援计划', goal: '形成可执行的引援顺序' },
]

/** 任务卡之外的其他问题，仍保留为轻量入口。 */
const MORE_QUESTIONS = QUICK_QUESTIONS.filter(
  (prompt) => !TASKS.some((task) => task.label === prompt),
)

const RELIABILITY: Record<string, string> = {
  fact: '数据事实',
  computed: '规则计算',
  inference: '推断',
  unavailable: '数据缺失',
}

const router = useRouter()
const session = useSessionStore()
const compare = useCompareStore()

const context = ref<DirectorContext | null>(null)
const contextLoading = ref(false)
const contextError = ref<ApiError | null>(null)
const question = ref('')
const asking = ref(false)
const error = ref<ApiError | null>(null)
const answer = ref<DirectorAnswer | null>(null)
const lastQuestion = ref('')

let requestSeq = 0

const completeness = computed(() => {
  const value = context.value?.data_completeness
  return typeof value === 'number' ? `${(value * 100).toFixed(0)}%` : EMPTY
})

const updatedAt = computed(() => {
  const value = context.value?.data_updated_at
  if (!value) return '暂无数据时间'
  return value.replace('T', ' ').replace('Z', '').slice(0, 16)
})

const cards = computed(() => answer.value?.player_cards ?? [])

/** 总监简报：只复述上下文接口返回的俱乐部、数据时间、完整度与缺口。 */
const briefTone = computed<'info' | 'warning' | 'danger' | 'neutral'>(() => {
  if (contextError.value) return 'danger'
  if (!context.value) return 'neutral'
  return context.value.data_completeness < 0.6 ? 'warning' : 'info'
})

const briefItems = computed<InsightItem[]>(() => {
  const data = context.value
  if (!data) return []
  const items: InsightItem[] = [
    { label: '存档数据', text: `${data.counts.players} 名球员 · ${data.counts.snapshots} 份快照` },
    { label: '数据更新时间', text: updatedAt.value },
    { label: '数据完整度', text: completeness.value, tone: data.data_completeness < 0.6 ? 'warning' : 'neutral' },
    {
      label: '已知数据缺口',
      text: data.data_gaps.length > 0 ? data.data_gaps.join('；') : '暂无已知缺口',
      tone: data.data_gaps.length > 0 ? 'warning' : 'neutral',
    },
    { label: '下一步', text: '选择左侧任务，或直接输入问题；分析结果会给出结论、依据与数据缺口。' },
  ]
  return items
})

/** 本次分析的执行指标：全部取自后端回答字段。 */
const reportStats = computed<StatItem[]>(() => {
  const current = answer.value
  if (!current) return []
  return [
    { label: '任务类型', value: current.intent_label },
    { label: '分析区块', value: String(current.sections.length) },
    { label: '推荐球员', value: String(current.recommendations.length) },
    {
      label: '数据缺口',
      value: String(current.data_gaps.length),
      tone: current.data_gaps.length > 0 ? 'warning' : 'default',
    },
    { label: '工具引用', value: String(current.citations.length) },
  ]
})

/** 基于本次回答的下一步建议，不引入后端未返回的结论。 */
const nextSteps = computed<string[]>(() => {
  const current = answer.value
  if (!current) return []
  const steps: string[] = []
  if (current.recommendations.length > 0) {
    steps.push(`在右侧查看 ${current.recommendations.length} 名推荐球员，确认位置、年龄与身价后再决定是否加入关注。`)
  }
  if (current.data_gaps.length > 0) {
    steps.push('先补齐上方数据缺口，再次分析可以得到更完整的结论。')
  }
  if (steps.length === 0) {
    steps.push('继续追问具体位置、预算或球员姓名，以得到可执行的下一步。')
  }
  return steps
})

async function loadContext(): Promise<void> {
  contextLoading.value = true
  contextError.value = null
  try {
    context.value = await getDirectorContext(session.activeSaveId)
  } catch (caught) {
    contextError.value = asApiError(caught)
  } finally {
    contextLoading.value = false
  }
}

async function ask(value?: string): Promise<void> {
  const text = (value ?? question.value).trim()
  if (!text || asking.value) return
  const seq = ++requestSeq
  question.value = text
  asking.value = true
  error.value = null
  try {
    const payload = await askDirector(text, { saveId: session.activeSaveId })
    if (seq !== requestSeq) return
    answer.value = payload
    lastQuestion.value = text
  } catch (caught) {
    if (seq !== requestSeq) return
    error.value = asApiError(caught)
    answer.value = null
  } finally {
    if (seq === requestSeq) asking.value = false
  }
}

function reset(): void {
  answer.value = null
  error.value = null
  lastQuestion.value = ''
  question.value = ''
}

function openTarget(target: string): void {
  if (target.startsWith('/')) router.push(target)
}

async function follow(item: DirectorRecommendation): Promise<void> {
  if (typeof item.instance_id !== 'number') return
  try {
    await addWatchlistItem({ instance_id: item.instance_id })
    ElMessage.success(`已加入关注名单：${item.name ?? '球员'}`)
  } catch (caught) {
    const failure = asApiError(caught)
    if (failure.message.includes('已在关注名单')) ElMessage.info('该球员已在关注名单')
    else ElMessage.error(failure.message)
  }
}

function addCompare(item: DirectorRecommendation): void {
  if (typeof item.instance_id !== 'number') return
  compare.ensureSave(session.activeSaveId)
  const outcome = compare.add(item.instance_id)
  if (outcome === 'added') ElMessage.success(`已加入对比：${item.name ?? '球员'}`)
  else if (outcome === 'exists') ElMessage.info('该球员已在对比中')
  else ElMessage.warning('对比最多 4 名球员')
}

function sectionClass(section: DirectorSection): string {
  return `director-section director-section--${section.reliability}`
}

function money(value: number | null): string {
  return typeof value === 'number' ? formatMoney(value) : '暂无数据'
}

watch(
  () => [session.activeSaveId, session.dataRevision],
  () => {
    compare.ensureSave(session.activeSaveId)
    reset()
    void loadContext()
  },
)

onMounted(() => {
  compare.ensureSave(session.activeSaveId)
  void loadContext()
})
</script>

<template>
  <div class="director-view">
    <PageHeader
      title="AI 足球总监"
      description="用当前存档的真实阵容、引援、关注与成长数据分析球队问题；所有建议都可以回到球员或模块查看。"
    >
      <template #actions>
        <el-button v-if="answer" size="small" @click="reset">重新开始</el-button>
      </template>
    </PageHeader>

    <InsightPanel
      title="总监简报"
      badge="数据事实"
      :tone="briefTone"
      :items="briefItems"
      footnote="阵容问题与引援需求在你选择任务后由本地规则分析得出；简报不会预先下结论。"
    />

    <div class="director-grid">
      <aside class="director-panel">
        <LoadingBlock v-if="contextLoading" :rows="3" compact label="读取球队上下文" />
        <div v-else-if="contextError" class="director-context director-context--error">
          <p class="director-context__title">无法读取球队上下文</p>
          <p class="director-context__muted">{{ contextError.message }}</p>
          <el-button size="small" @click="loadContext">重试</el-button>
        </div>
        <div v-else-if="context" class="director-context">
          <p class="director-context__label">当前俱乐部</p>
          <p class="director-context__club">{{ context.club?.name ?? '未标记我的俱乐部' }}</p>
          <p class="director-context__muted">
            {{ context.club?.league || '联赛未知' }} · {{ context.club?.nation || '国家未知' }}
          </p>
          <dl class="director-facts">
            <div><dt>存档</dt><dd>{{ context.save.name ?? `#${context.save.id}` }}</dd></div>
            <div><dt>数据更新</dt><dd>{{ updatedAt }}</dd></div>
            <div><dt>数据完整度</dt><dd>{{ completeness }}</dd></div>
            <div><dt>球员 / 快照</dt><dd>{{ context.counts.players }} / {{ context.counts.snapshots }}</dd></div>
            <div><dt>转会 / 统计</dt><dd>{{ context.counts.transfers }} / {{ context.counts.statistics }}</dd></div>
            <div><dt>关注</dt><dd>{{ context.counts.watchlist }}</dd></div>
          </dl>
          <div v-if="context.data_gaps.length" class="director-gaps">
            <p class="director-context__label">数据缺口</p>
            <p v-for="gap in context.data_gaps" :key="gap" class="director-gaps__item">{{ gap }}</p>
          </div>
        </div>

        <p class="director-context__label">选择任务</p>
        <div class="director-tasks">
          <button
            v-for="task in TASKS"
            :key="task.label"
            type="button"
            class="director-task"
            :disabled="asking"
            @click="ask(task.label)"
          >
            <span class="director-task__label">{{ task.label }}</span>
            <span class="director-task__goal">{{ task.goal }}</span>
          </button>
        </div>

        <template v-if="MORE_QUESTIONS.length">
          <p class="director-context__label">其他问题</p>
          <div class="director-quick">
            <button
              v-for="prompt in MORE_QUESTIONS"
              :key="prompt"
              type="button"
              class="director-quick__item"
              :disabled="asking"
              @click="ask(prompt)"
            >
              {{ prompt }}
            </button>
          </div>
        </template>
      </aside>

      <section class="director-main">
        <div class="director-ask">
          <textarea
            v-model="question"
            class="director-ask__input"
            rows="2"
            maxlength="500"
            placeholder="例如：我的球队最需要补强什么位置？"
            @keydown.enter.exact.prevent="ask()"
          />
          <el-button type="primary" :loading="asking" :disabled="!question.trim()" @click="ask()">分析</el-button>
        </div>
        <p class="director-ask__hint">Enter 发送；结论只使用本地数据，不会修改游戏或数据库中的球员状态。</p>

        <LoadingBlock v-if="asking" :rows="6" label="正在调用阵容、引援与关注分析" />

        <div v-else-if="error" class="director-error">
          <p class="director-error__title">分析暂时不可用</p>
          <p class="director-error__text">{{ error.message }}</p>
          <el-button size="small" @click="ask(lastQuestion || question)">重试</el-button>
        </div>

        <EmptyState
          v-else-if="!answer"
          title="向 AI 足球总监提问"
          description="选择左侧快捷问题，或输入自己的问题。分析会说明结论、数据依据、风险与缺失字段。"
        />

        <article v-else class="director-answer">
          <header class="director-answer__head">
            <span class="director-answer__tag">{{ answer.intent_label }}</span>
            <span class="director-answer__mode">{{ answer.mode === 'deterministic-rules' ? '本地规则引擎' : answer.mode }}</span>
            <span v-if="lastQuestion" class="director-answer__question">“{{ lastQuestion }}”</span>
          </header>
          <p class="director-answer__conclusion">{{ answer.conclusion }}</p>

          <div class="director-report">
            <p class="director-report__goal"><span class="sm-label">任务目标</span>{{ lastQuestion || answer.intent_label }}</p>
            <StatStrip :items="reportStats" dense />
          </div>

          <p class="director-report__label">依据分析</p>
          <section v-for="section in answer.sections" :key="section.key" :class="sectionClass(section)">
            <p class="director-section__title">
              {{ section.title }}
              <span class="director-section__badge">{{ RELIABILITY[section.reliability] ?? section.reliability }}</span>
            </p>
            <ul v-if="section.bullets?.length" class="director-section__list">
              <li v-for="line in section.bullets" :key="line">{{ line }}</li>
            </ul>
            <div v-if="section.table" class="director-table-wrap">
              <table class="director-table">
                <thead>
                  <tr><th v-for="column in section.table.columns" :key="column">{{ column }}</th></tr>
                </thead>
                <tbody>
                  <tr v-for="(row, index) in section.table.rows" :key="index">
                    <td v-for="(cell, cellIndex) in row" :key="cellIndex">{{ cell }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <section v-if="answer.data_gaps.length" class="director-section director-section--unavailable">
            <p class="director-section__title">风险与数据缺口</p>
            <ul class="director-section__list">
              <li v-for="gap in answer.data_gaps" :key="gap">{{ gap }}</li>
            </ul>
          </section>

          <section v-if="nextSteps.length" class="director-section director-section--next">
            <p class="director-section__title">下一步</p>
            <ul class="director-section__list">
              <li v-for="step in nextSteps" :key="step">{{ step }}</li>
            </ul>
          </section>

          <footer class="director-answer__foot">
            <span>来源与声明 · 数据来源：{{ answer.citations.map((item) => item.tool).filter(Boolean).join('、') || '本地数据库' }}</span>
            <span v-for="note in answer.disclaimers ?? []" :key="note">{{ note }}</span>
          </footer>
        </article>
      </section>

      <aside class="director-panel director-panel--cards">
        <p class="director-context__label">推荐与球员卡片</p>
        <p v-if="!answer || answer.recommendations.length === 0" class="director-context__muted">
          当前分析没有可操作的球员推荐。
        </p>
        <div v-for="item in answer?.recommendations ?? []" :key="`${item.instance_id}-${item.reason}`" class="director-card">
          <div class="director-card__head">
            <button type="button" class="director-card__name" @click="item.instance_id && openTarget(`/players/${item.instance_id}`)">
              {{ item.name ?? '未知球员' }}
            </button>
            <span class="director-card__meta">{{ item.position || '位置未知' }} · {{ item.age ?? '—' }} 岁</span>
          </div>
          <p class="director-card__club">{{ item.club || '自由球员' }}</p>
          <p class="director-card__reason">{{ item.reason }}</p>
          <div class="director-card__stats">
            <span>CA {{ item.ca ?? EMPTY }}</span>
            <span>PA {{ item.pa ?? EMPTY }}</span>
            <span>{{ money(item.market_value) }}</span>
          </div>
          <div class="director-card__actions">
            <el-button size="small" @click="openTarget(`/players/${item.instance_id}`)">查看球员</el-button>
            <el-button size="small" @click="follow(item)">加入关注</el-button>
            <el-button size="small" @click="addCompare(item)">加入对比</el-button>
          </div>
        </div>

        <div v-if="cards.length" class="director-cards-note">
          <p class="director-context__label">本次引用的球员</p>
          <button
            v-for="card in cards"
            :key="card.instance_id"
            type="button"
            class="director-card__chip"
            @click="openTarget(`/players/${card.instance_id}`)"
          >
            {{ card.name }}
          </button>
        </div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.director-view {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-4);
}

.director-grid {
  display: grid;
  grid-template-columns: minmax(220px, 270px) minmax(0, 1fr) minmax(260px, 330px);
  gap: var(--sm-space-4);
  align-items: start;
}

.director-panel {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-3);
  padding: var(--sm-space-4);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-lg);
  background: var(--sm-surface);
}

.director-context__label {
  margin: var(--sm-space-2) 0 var(--sm-space-1);
  color: var(--sm-text-3);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.director-context__club {
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-lg);
  font-weight: 600;
}

.director-context__title {
  color: var(--sm-danger);
  font-weight: 600;
}

.director-context__muted {
  color: var(--sm-text-2);
  font-size: var(--sm-fs-xs);
  line-height: 1.55;
}

.director-facts {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px 12px;
  margin: var(--sm-space-2) 0;
}

.director-facts div {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.director-facts dt {
  color: var(--sm-text-3);
  font-size: 10px;
}

.director-facts dd {
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-xs);
}

.director-gaps__item {
  margin: 2px 0;
  color: var(--sm-warning, #f0b429);
  font-size: var(--sm-fs-2xs);
  line-height: 1.5;
}

.director-quick {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.director-quick__item {
  padding: 7px 10px;
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-sm);
  background: rgba(12, 23, 39, 0.55);
  color: var(--sm-text-2);
  font-size: var(--sm-fs-xs);
  text-align: left;
  cursor: pointer;
}

.director-quick__item:hover:not(:disabled) {
  border-color: var(--sm-border-glow);
  color: var(--sm-text-primary);
}

.director-main {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-3);
  min-width: 0;
}

.director-ask {
  display: flex;
  gap: var(--sm-space-2);
  align-items: flex-end;
}

.director-ask__input {
  flex: 1 1 auto;
  min-height: 58px;
  padding: 10px 12px;
  border: 1px solid var(--sm-border-strong);
  border-radius: var(--sm-radius-md);
  background: rgba(7, 14, 25, 0.75);
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-sm);
  line-height: 1.55;
  resize: vertical;
  outline: none;
}

.director-ask__input:focus {
  border-color: var(--sm-border-glow);
}

.director-ask__hint {
  margin: -4px 0 0;
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}

.director-error__title {
  color: var(--sm-danger);
  font-weight: 600;
}

.director-error__text {
  margin: var(--sm-space-1) 0 var(--sm-space-2);
  color: var(--sm-text-2);
  font-size: var(--sm-fs-xs);
}

.director-answer {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-3);
  padding: var(--sm-space-4);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-lg);
  background:
    radial-gradient(420px 160px at 100% 0%, rgba(34, 211, 238, 0.06), transparent 70%),
    var(--sm-surface);
}

.director-answer__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sm-space-2);
}

.director-answer__tag {
  padding: 3px 9px;
  border: 1px solid rgba(34, 211, 238, 0.32);
  border-radius: var(--sm-radius-pill);
  background: rgba(34, 211, 238, 0.1);
  color: var(--sm-accent-cyan);
  font-size: var(--sm-fs-2xs);
}

.director-answer__mode,
.director-answer__question {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}

.director-answer__conclusion {
  margin: 0;
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-md);
  font-weight: 600;
  line-height: 1.6;
}

.director-section {
  padding: var(--sm-space-3);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-md);
  background: rgba(9, 18, 31, 0.55);
}

.director-section--fact {
  border-left: 3px solid var(--sm-accent-cyan);
}

.director-section--computed {
  border-left: 3px solid #7c8cff;
}

.director-section--inference {
  border-left: 3px solid var(--sm-warning, #f0b429);
}

.director-section--unavailable {
  border-left: 3px solid var(--sm-danger);
}

.director-section__title {
  display: flex;
  align-items: center;
  gap: var(--sm-space-2);
  margin: 0 0 var(--sm-space-2);
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-sm);
  font-weight: 600;
}

.director-section__badge {
  padding: 1px 7px;
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-pill);
  color: var(--sm-text-3);
  font-size: 9px;
  font-weight: 500;
}

.director-section__list {
  margin: 0;
  padding-left: 16px;
  color: var(--sm-text-2);
  font-size: var(--sm-fs-xs);
  line-height: 1.7;
}

.director-table-wrap {
  overflow-x: auto;
}

.director-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--sm-fs-2xs);
}

.director-table th,
.director-table td {
  padding: 5px 8px;
  border-bottom: 1px solid var(--sm-border);
  text-align: left;
  white-space: nowrap;
}

.director-table th {
  color: var(--sm-text-3);
  font-weight: 600;
}

.director-table td {
  color: var(--sm-text-2);
}

.director-answer__foot {
  display: flex;
  flex-direction: column;
  gap: 2px;
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}

.director-panel--cards {
  max-height: 76vh;
  overflow-y: auto;
}

.director-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: var(--sm-space-3);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-md);
  background: rgba(12, 23, 39, 0.6);
}

.director-card__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--sm-space-2);
}

.director-card__name {
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-sm);
  font-weight: 600;
  cursor: pointer;
}

.director-card__meta,
.director-card__club {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}

.director-card__reason {
  margin: 0;
  color: var(--sm-text-2);
  font-size: var(--sm-fs-xs);
  line-height: 1.5;
}

.director-card__stats {
  display: flex;
  gap: var(--sm-space-3);
  color: var(--sm-text-2);
  font-size: var(--sm-fs-2xs);
}

.director-card__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 2px;
}

.director-card__chip {
  margin: 2px 4px 2px 0;
  padding: 3px 9px;
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-pill);
  background: transparent;
  color: var(--sm-text-2);
  font-size: var(--sm-fs-2xs);
  cursor: pointer;
}

.director-card__chip:hover {
  border-color: var(--sm-border-glow);
  color: var(--sm-text-primary);
}

.director-tasks {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.director-task {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 8px 10px;
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-sm);
  background: rgba(12, 23, 39, 0.55);
  text-align: left;
  cursor: pointer;
}

.director-task:hover:not(:disabled) {
  border-color: var(--sm-border-glow);
}

.director-task__label {
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-xs);
  font-weight: var(--sm-fw-medium);
}

.director-task__goal {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
  line-height: 1.45;
}

.director-report {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-2);
}

.director-report__goal {
  display: flex;
  align-items: baseline;
  gap: var(--sm-space-2);
  margin: 0;
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-xs);
}

.director-report__label {
  margin: var(--sm-space-2) 0 0;
  color: var(--sm-text-3);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.director-section--next {
  border-left: 3px solid var(--sm-accent-cyan);
}

@media (max-width: 1200px) {
  .director-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .director-panel--cards {
    max-height: none;
  }
}
</style>
