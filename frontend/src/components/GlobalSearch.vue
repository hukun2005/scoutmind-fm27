/**
 * 全局搜索面板：Ctrl/⌘ + K 打开，搜索当前存档的球员、俱乐部与转会。
 *
 * 交互约束：
 * - 输入防抖 280ms，过期请求按序号丢弃；
 * - 键盘 ↑/↓ 选择、Enter 打开、Esc 关闭；
 * - 最近搜索只保存在本地 localStorage，不上传。
 */

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { asApiError, type ApiError } from '../api/client'
import { searchAll } from '../api/search'
import { useCompareStore } from '../stores/compare'
import { useSessionStore } from '../stores/session'
import type { SearchResultItem, SearchType } from '../types/search'
import { metaNumber, metaText } from '../types/search'
import { EMPTY, formatMoney } from '../utils/format'
import { transferStatusLabel, transferTypeLabel } from '../utils/labels'
import { clearRecent, recentFor, rememberRecent, type RecentEntry } from '../utils/recent'
import EmptyState from './EmptyState.vue'
import LoadingBlock from './LoadingBlock.vue'

const HISTORY_KEY = 'scoutmind.search.history'
const MAX_HISTORY = 6

const router = useRouter()
const session = useSessionStore()
const compare = useCompareStore()

const open = ref(false)
const query = ref('')
const type = ref<SearchType>('all')
const loading = ref(false)
const error = ref<ApiError | null>(null)
const results = ref<SearchResultItem[]>([])
const activeIndex = ref(0)
const history = ref<string[]>(readHistory())
const recent = ref<RecentEntry[]>(recentFor(session.activeSaveId))
const inputRef = ref<HTMLInputElement | null>(null)

let debounceTimer: ReturnType<typeof setTimeout> | null = null
let requestSeq = 0

const categories: Array<{
  key: 'players' | 'clubs' | 'transfers' | 'watchlist'
  entity: 'player' | 'club' | 'transfer' | 'watchlist'
  type: SearchType
  label: string
  empty: string
}> = [
  { key: 'players', entity: 'player', type: 'players', label: '球员', empty: '没有匹配的球员' },
  { key: 'clubs', entity: 'club', type: 'clubs', label: '俱乐部', empty: '没有匹配的俱乐部' },
  { key: 'transfers', entity: 'transfer', type: 'transfers', label: '转会', empty: '没有匹配的转会记录' },
  { key: 'watchlist', entity: 'watchlist', type: 'watchlist', label: '关注', empty: '没有匹配的关注球员' },
]

/** 当前分类下要显示的分组。 */
const groups = computed(() =>
  categories
    .filter((category) => type.value === 'all' || type.value === category.type)
    .map((category) => ({
      ...category,
      items: results.value.filter((item) => item.entity_type === category.entity),
    })),
)

/** 键盘导航使用的扁平列表。 */
const flatItems = computed(() => groups.value.flatMap((group) => group.items))

const tabs: Array<{ value: SearchType; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'players', label: '球员' },
  { value: 'clubs', label: '俱乐部' },
  { value: 'transfers', label: '转会' },
  { value: 'watchlist', label: '关注' },
]

/** 读取本地搜索历史。 */
function readHistory(): string[] {
  if (typeof localStorage === 'undefined') return []
  try {
    const raw = localStorage.getItem(HISTORY_KEY)
    const parsed = raw ? (JSON.parse(raw) as unknown) : []
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === 'string').slice(0, MAX_HISTORY) : []
  } catch {
    return []
  }
}

/** 记录一次成功打开的搜索词。 */
function remember(term: string): void {
  const value = term.trim()
  if (!value) return
  history.value = [value, ...history.value.filter((item) => item !== value)].slice(0, MAX_HISTORY)
  if (typeof localStorage !== 'undefined') localStorage.setItem(HISTORY_KEY, JSON.stringify(history.value))
}

/** 打开面板并聚焦输入框。 */
async function show(): Promise<void> {
  compare.ensureSave(session.activeSaveId)
  open.value = true
  await nextTick()
  inputRef.value?.focus()
}

function close(): void {
  open.value = false
  activeIndex.value = 0
}

/** 请求搜索；空查询直接清空结果，不发请求。 */
async function runSearch(): Promise<void> {
  const term = query.value.trim()
  if (!term) {
    results.value = []
    error.value = null
    loading.value = false
    return
  }
  const seq = ++requestSeq
  loading.value = true
  error.value = null
  try {
    const response = await searchAll(term, type.value, { saveId: session.activeSaveId, limit: 8 })
    if (seq !== requestSeq) return
    results.value = [
      ...(response.categories.players ?? []),
      ...(response.categories.clubs ?? []),
      ...(response.categories.transfers ?? []),
      ...(response.categories.watchlist ?? []),
    ]
    activeIndex.value = 0
  } catch (caught) {
    if (seq !== requestSeq) return
    error.value = asApiError(caught)
    results.value = []
  } finally {
    if (seq === requestSeq) loading.value = false
  }
}

/** 输入变化后防抖查询。 */
function onInput(): void {
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => {
    void runSearch()
  }, 280)
}

/** 分类切换立即重查。 */
function setType(value: SearchType): void {
  type.value = value
  activeIndex.value = 0
  void runSearch()
}

/** 选择一条结果：记录搜索词与最近访问并跳转。 */
function openResult(item: SearchResultItem): void {
  remember(query.value || item.display_name)
  rememberRecent({
    entity_type: item.entity_type,
    entity_id: item.entity_id,
    display_name: item.display_name,
    subtitle: item.subtitle,
    navigation_target: item.navigation_target,
    save_id: session.activeSaveId,
  })
  recent.value = recentFor(session.activeSaveId)
  router.push(item.navigation_target)
  close()
}

/** 打开最近访问的对象。 */
function openRecent(entry: RecentEntry): void {
  rememberRecent(entry)
  recent.value = recentFor(session.activeSaveId)
  router.push(entry.navigation_target)
  close()
}

function forgetRecent(): void {
  clearRecent(session.activeSaveId)
  recent.value = []
}

/** 高亮匹配片段：先转义 HTML，再只包裹命中的文字。 */
function escapeHtml(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

function highlight(text: string): string {
  const term = query.value.trim()
  if (!term) return escapeHtml(text)
  const pattern = new RegExp(`(${term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'ig')
  return text
    .split(pattern)
    .map((part, index) => (index % 2 === 1 ? `<mark>${escapeHtml(part)}</mark>` : escapeHtml(part)))
    .join('')
}

/** 关注状态的显示文案。 */
const WATCH_STATUS: Record<string, string> = {
  watching: '关注中',
  preparing: '准备引进',
  paused: '暂缓观察',
  done: '已完成',
}

/** 关注结果：名单 + 状态 + 备注。 */
function watchMeta(item: SearchResultItem): string {
  const listName = metaText(item.meta, 'list_name')
  const status = metaText(item.meta, 'status')
  const note = metaText(item.meta, 'note')
  return [listName, status ? (WATCH_STATUS[status] ?? status) : null, note]
    .filter(Boolean)
    .join(' · ')
}

/** 键盘：↑/↓/Enter/Esc。 */
function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    event.preventDefault()
    close()
    return
  }
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    if (flatItems.value.length === 0) return
    activeIndex.value = (activeIndex.value + 1) % flatItems.value.length
    return
  }
  if (event.key === 'ArrowUp') {
    event.preventDefault()
    if (flatItems.value.length === 0) return
    activeIndex.value = (activeIndex.value - 1 + flatItems.value.length) % flatItems.value.length
    return
  }
  if (event.key === 'Enter') {
    const item = flatItems.value[activeIndex.value]
    if (item) {
      event.preventDefault()
      openResult(item)
    }
  }
}

/** 全局快捷键：Ctrl/⌘ + K。 */
function onGlobalKeydown(event: KeyboardEvent): void {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    if (open.value) close()
    else void show()
  }
}

/** 把球员加入对比。 */
function addToCompare(item: SearchResultItem): void {
  compare.ensureSave(session.activeSaveId)
  const outcome = compare.add(item.entity_id)
  if (outcome === 'added') ElMessage.success(`已加入对比：${item.display_name}`)
  else if (outcome === 'exists') ElMessage.info('该球员已在对比中')
  else ElMessage.warning('对比最多 4 名球员')
}

/** 球员结果的能力摘要。 */
function playerMeta(item: SearchResultItem): string {
  const ca = metaNumber(item.meta, 'ca')
  const pa = metaNumber(item.meta, 'pa')
  if (ca === null && pa === null) return '能力数据暂无'
  return `CA ${ca ?? EMPTY} · PA ${pa ?? EMPTY}`
}

/** 转会结果的状态与费用。 */
function transferMeta(item: SearchResultItem): string {
  const status = metaText(item.meta, 'status')
  const kind = metaText(item.meta, 'transfer_type')
  const fee = metaNumber(item.meta, 'fee')
  return [transferStatusLabel(status), transferTypeLabel(kind), fee === null ? '费用未知' : formatMoney(fee)]
    .filter(Boolean)
    .join(' · ')
}

/** 使用历史词。 */
function useHistory(term: string): void {
  query.value = term
  void runSearch()
  inputRef.value?.focus()
}

watch(
  () => [session.activeSaveId, session.dataRevision],
  () => {
    compare.ensureSave(session.activeSaveId)
    results.value = []
    error.value = null
    query.value = ''
    recent.value = recentFor(session.activeSaveId)
    close()
  },
)

watch(query, onInput)

onMounted(() => window.addEventListener('keydown', onGlobalKeydown))
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onGlobalKeydown)
  if (debounceTimer) clearTimeout(debounceTimer)
})
</script>

<template>
  <button
    type="button"
    class="icon-btn gs-trigger"
    aria-label="全局搜索（Ctrl+K）"
    title="全局搜索（Ctrl+K）"
    @click="show"
  >
    <span class="gs-trigger__glyph" aria-hidden="true">⌕</span>
    <kbd class="gs-trigger__kbd">Ctrl K</kbd>
  </button>

  <el-dialog
    v-model="open"
    class="gs-dialog"
    width="680px"
    top="10vh"
    :show-close="false"
    append-to-body
    @closed="close"
  >
    <div class="gs-panel" @keydown="onKeydown">
      <div class="gs-head">
        <span class="gs-head__glyph" aria-hidden="true">⌕</span>
        <input
          ref="inputRef"
          v-model="query"
          class="gs-input"
          type="search"
          placeholder="搜索球员、俱乐部、转会或关注名单"
          aria-label="搜索球员、俱乐部、转会或关注名单"
          autocomplete="off"
        />
        <button type="button" class="gs-esc" aria-label="关闭搜索" @click="close">Esc</button>
      </div>

      <div class="gs-tabs" role="tablist" aria-label="搜索分类">
        <button
          v-for="tab in tabs"
          :key="tab.value"
          type="button"
          role="tab"
          class="gs-tab"
          :class="{ 'gs-tab--active': type === tab.value }"
          :aria-selected="type === tab.value"
          @click="setType(tab.value)"
        >
          {{ tab.label }}
        </button>
      </div>

      <div class="gs-body">
        <LoadingBlock v-if="loading" :rows="4" compact label="正在搜索" />

        <div v-else-if="error" class="gs-error">
          <p class="gs-error__title">搜索暂时不可用</p>
          <p class="gs-error__text">{{ error.message }}</p>
          <el-button size="small" @click="runSearch">重试</el-button>
        </div>

        <div v-else-if="query.trim() === ''" class="gs-history">
          <div v-if="recent.length > 0">
            <p class="gs-section__label">
              最近访问
              <button type="button" class="gs-clear" @click="forgetRecent">清空</button>
            </p>
            <button
              v-for="entry in recent"
              :key="`recent-${entry.entity_type}-${entry.entity_id}`"
              type="button"
              class="gs-recent"
              @click="openRecent(entry)"
            >
              <span class="gs-recent__name">{{ entry.display_name }}</span>
              <span class="gs-recent__sub">{{ entry.subtitle }}</span>
            </button>
          </div>
          <div v-if="history.length > 0">
            <p class="gs-section__label">最近搜索</p>
            <div class="gs-history__chips">
              <button v-for="term in history" :key="term" type="button" class="gs-chip" @click="useHistory(term)">
                {{ term }}
              </button>
            </div>
          </div>
          <p v-if="recent.length === 0 && history.length === 0" class="gs-hint">
            输入姓名、俱乐部或球员名开始搜索；本搜索只覆盖当前存档。
          </p>
          <p class="gs-hint gs-hint--muted">支持 ↑ ↓ 选择，Enter 打开，Esc 关闭。</p>
        </div>

        <div v-else-if="flatItems.length === 0" class="gs-empty">
          <EmptyState title="没有找到结果" :description="`没有与“${query.trim()}”匹配的球员、俱乐部或转会记录。`" compact />
        </div>

        <div v-else class="gs-results">
          <section v-for="group in groups" :key="group.key" class="gs-section">
            <p class="gs-section__label">{{ group.label }} <span>{{ group.items.length }}</span></p>
            <p v-if="group.items.length === 0" class="gs-hint gs-hint--muted">{{ group.empty }}</p>
            <button
              v-for="item in group.items"
              :key="`${item.entity_type}-${item.entity_id}`"
              type="button"
              class="gs-result"
              :class="{ 'gs-result--active': flatItems[activeIndex] === item }"
              @mouseenter="activeIndex = flatItems.indexOf(item)"
              @click="openResult(item)"
            >
              <span class="gs-result__icon" aria-hidden="true">
                {{ item.entity_type === 'player' ? 'P' : item.entity_type === 'club' ? 'C' : item.entity_type === 'watchlist' ? 'W' : 'T' }}
              </span>
              <span class="gs-result__main">
                <span class="gs-result__name" v-html="highlight(item.display_name)" />
                <span class="gs-result__sub" v-html="highlight(item.subtitle)" />
                <span v-if="item.entity_type === 'player'" class="gs-result__meta">{{ playerMeta(item) }}</span>
                <span v-else-if="item.entity_type === 'transfer'" class="gs-result__meta">{{ transferMeta(item) }}</span>
                <span v-else-if="item.entity_type === 'watchlist'" class="gs-result__meta">{{ watchMeta(item) }}</span>
              </span>
              <span
                v-if="item.entity_type === 'player'"
                class="gs-result__action"
                role="button"
                tabindex="0"
                title="加入球员对比"
                @click.stop="addToCompare(item)"
                @keydown.enter.stop="addToCompare(item)"
              >
                + 对比
              </span>
            </button>
          </section>
        </div>
      </div>

      <footer class="gs-foot">
        <span><kbd>↑</kbd><kbd>↓</kbd> 选择</span>
        <span><kbd>Enter</kbd> 打开</span>
        <span><kbd>Esc</kbd> 关闭</span>
        <router-link class="gs-foot__link" to="/compare" @click="close">球员对比 →</router-link>
      </footer>
    </div>
  </el-dialog>
</template>

<style>
/* 通过 append-to-body 渲染，样式使用全局命名空间，避免依赖 scoped 作用域。 */
.gs-trigger {
  width: auto;
  min-width: 30px;
  gap: 6px;
  padding: 0 8px;
  display: inline-flex;
  align-items: center;
}

.gs-trigger__glyph {
  font-size: 15px;
  line-height: 1;
}

.gs-trigger__kbd {
  padding: 1px 5px;
  border: 1px solid var(--sm-border);
  border-radius: 4px;
  color: var(--sm-text-3);
  font-family: var(--sm-font-mono);
  font-size: 9px;
}

.gs-dialog {
  background: transparent;
  box-shadow: none;
}

.gs-dialog .el-dialog__header {
  display: none;
}

.gs-dialog .el-dialog__body {
  padding: 0;
}

.gs-panel {
  overflow: hidden;
  border: 1px solid var(--sm-border-strong);
  border-radius: 16px;
  background:
    linear-gradient(168deg, rgba(20, 35, 56, 0.72) 0%, rgba(7, 14, 25, 0.98) 58%),
    var(--sm-surface);
  box-shadow: 0 32px 80px -30px rgba(2, 7, 16, 0.95);
}

.gs-head {
  display: flex;
  align-items: center;
  gap: var(--sm-space-3);
  padding: var(--sm-space-4) var(--sm-space-4) var(--sm-space-2);
  border-bottom: 1px solid var(--sm-border);
}

.gs-head__glyph {
  color: var(--sm-accent-cyan);
  font-size: 20px;
}

.gs-input {
  flex: 1 1 auto;
  min-width: 0;
  padding: 6px 0;
  border: 0;
  background: transparent;
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-lg, 16px);
  outline: none;
}

.gs-input::placeholder {
  color: var(--sm-text-3);
}

.gs-esc {
  padding: 3px 8px;
  border: 1px solid var(--sm-border);
  border-radius: 5px;
  background: transparent;
  color: var(--sm-text-3);
  font-size: 10px;
  cursor: pointer;
}

.gs-tabs {
  display: flex;
  gap: var(--sm-space-1);
  padding: var(--sm-space-2) var(--sm-space-4);
  border-bottom: 1px solid var(--sm-border);
}

.gs-tab {
  padding: 4px 12px;
  border: 1px solid transparent;
  border-radius: var(--sm-radius-pill);
  background: transparent;
  color: var(--sm-text-2);
  font-size: var(--sm-fs-xs);
  cursor: pointer;
}

.gs-tab--active {
  border-color: rgba(34, 211, 238, 0.32);
  background: rgba(34, 211, 238, 0.12);
  color: var(--sm-text-primary);
}

.gs-body {
  max-height: 56vh;
  overflow-y: auto;
  padding: var(--sm-space-2) var(--sm-space-3) var(--sm-space-3);
}

.gs-section__label {
  margin: var(--sm-space-2) var(--sm-space-2) var(--sm-space-1);
  color: var(--sm-text-3);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.gs-section__label span {
  margin-left: 4px;
  color: var(--sm-text-2);
}

.gs-result {
  display: flex;
  align-items: center;
  gap: var(--sm-space-3);
  width: 100%;
  padding: 8px 10px;
  border: 0;
  border-radius: var(--sm-radius-sm);
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.gs-result--active,
.gs-result:hover {
  background: rgba(34, 211, 238, 0.09);
}

.gs-result__icon {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  flex: 0 0 auto;
  border: 1px solid var(--sm-border);
  border-radius: 8px;
  background: rgba(12, 23, 39, 0.7);
  color: var(--sm-accent-cyan);
  font-size: 10px;
  font-weight: 700;
}

.gs-result__main {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
  flex: 1 1 auto;
}

.gs-result__name {
  overflow: hidden;
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-sm);
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.gs-result__sub {
  overflow: hidden;
  color: var(--sm-text-2);
  font-size: var(--sm-fs-xs);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.gs-result__meta {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}

.gs-result__action {
  flex: 0 0 auto;
  padding: 3px 8px;
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-pill);
  color: var(--sm-text-2);
  font-size: var(--sm-fs-2xs);
  cursor: pointer;
}

.gs-result__action:hover {
  border-color: var(--sm-border-glow);
  color: var(--sm-text-primary);
}

.gs-history,
.gs-empty,
.gs-error {
  padding: var(--sm-space-3);
}

.gs-history__chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sm-space-2);
}

.gs-clear {
  margin-left: 6px;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--sm-accent-cyan);
  font-size: 10px;
  font-weight: 500;
  text-transform: none;
  cursor: pointer;
}

.gs-recent {
  display: flex;
  flex-direction: column;
  gap: 1px;
  width: 100%;
  padding: 6px 10px;
  border: 0;
  border-radius: var(--sm-radius-sm);
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.gs-recent:hover {
  background: rgba(34, 211, 238, 0.09);
}

.gs-recent__name {
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-sm);
}

.gs-recent__sub {
  overflow: hidden;
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.gs-result__name mark,
.gs-result__sub mark {
  border-radius: 2px;
  background: rgba(34, 211, 238, 0.24);
  color: var(--sm-text-primary);
}

.gs-chip {
  padding: 4px 10px;
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-pill);
  background: rgba(12, 23, 39, 0.6);
  color: var(--sm-text-2);
  font-size: var(--sm-fs-xs);
  cursor: pointer;
}

.gs-chip:hover {
  border-color: var(--sm-border-glow);
  color: var(--sm-text-primary);
}

.gs-hint {
  margin: var(--sm-space-2) var(--sm-space-2);
  color: var(--sm-text-2);
  font-size: var(--sm-fs-xs);
}

.gs-hint--muted {
  color: var(--sm-text-3);
}

.gs-error__title {
  color: var(--sm-danger);
  font-size: var(--sm-fs-sm);
  font-weight: 600;
}

.gs-error__text {
  margin: var(--sm-space-1) 0 var(--sm-space-2);
  color: var(--sm-text-2);
  font-size: var(--sm-fs-xs);
}

.gs-foot {
  display: flex;
  align-items: center;
  gap: var(--sm-space-3);
  padding: var(--sm-space-2) var(--sm-space-4);
  border-top: 1px solid var(--sm-border);
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}

.gs-foot kbd {
  padding: 0 4px;
  margin-right: 3px;
  border: 1px solid var(--sm-border);
  border-radius: 3px;
  font-family: var(--sm-font-mono);
  font-size: 9px;
}

.gs-foot__link {
  margin-left: auto;
  color: var(--sm-accent-cyan);
  font-size: var(--sm-fs-2xs);
}

@media (max-width: 760px) {
  .gs-dialog {
    width: calc(100vw - 24px) !important;
  }

  .gs-trigger__kbd {
    display: none;
  }
}
</style>
