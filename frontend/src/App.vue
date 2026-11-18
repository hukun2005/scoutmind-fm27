/**
 * Application shell: dark sidebar navigation, topbar with save selector and token
 * settings, the demo-data banner and the routed screen.
 */

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import AppIcon from './components/AppIcon.vue'
import DemoBanner from './components/DemoBanner.vue'
import { useSessionStore } from './stores/session'
import { formatInt } from './utils/format'

type IconName =
  | 'overview'
  | 'players'
  | 'watchlist'
  | 'scouting'
  | 'squad'
  | 'development'
  | 'performance'
  | 'transfers'
  | 'agent'
  | 'data'

interface NavItem {
  key: string
  label: string
  to: string
  icon: IconName
  hint: string
}

/**
 * Navigation follows the V2 product structure: analysis modules first, tool screens last.
 * Each entry states what the screen answers rather than naming the underlying endpoint.
 */
const NAV_ITEMS: NavItem[] = [
  { key: 'overview', label: '概览', to: '/', icon: 'overview', hint: '全局数据与覆盖度' },
  { key: 'squad', label: '阵容智能', to: '/squad', icon: 'squad', hint: '六维评分、位置深度与接班规划' },
  { key: 'recruitment', label: '智能球探引擎', to: '/recruitment', icon: 'scouting', hint: '六维球员评分、隐藏价值与候选名单' },
  { key: 'transfers', label: '转会情报', to: '/transfers', icon: 'transfers', hint: '成本模型、投资效率与历史复盘' },
  { key: 'development', label: '球员发展', to: '/development', icon: 'development', hint: '成长速率、建议与潜力区间' },
  { key: 'performance', label: '表现分析', to: '/performance', icon: 'performance', hint: '分位置产出与能力对比' },
  { key: 'agent', label: 'AI 体育总监', to: '/agent', icon: 'agent', hint: '自然语言提问，工具级证据' },
  { key: 'data', label: '数据中心', to: '/data', icon: 'data', hint: '数据导入、覆盖度与兼容性' },
]

/** Secondary screens reachable from the analysis pages rather than the main rail. */
const SECONDARY_ITEMS: NavItem[] = [
  { key: 'players', label: '球员中心', to: '/players', icon: 'players', hint: '筛选、排序与球员档案' },
  { key: 'scouting', label: '角色球探', to: '/scouting', icon: 'scouting', hint: '战术角色模板与排序' },
  { key: 'watchlist', label: '关注名单', to: '/watchlist', icon: 'watchlist', hint: '关注球员与提醒规则' },
]

const session = useSessionStore()
const route = useRoute()

const settingsOpen = ref(false)
const tokenDraft = ref(session.token)

/** Nav key highlighted for the current route (detail pages keep their parent lit). */
const activeKey = computed(() => {
  const name = typeof route.name === 'string' ? route.name : ''
  if (name === 'player-detail') return 'players'
  return name
})

/** Topbar title from the route meta. */
const pageTitle = computed(() => (typeof route.meta.title === 'string' ? route.meta.title : '工作台'))

/** Save selector model bound to the session store. */
const saveModel = computed<number | null>({
  get: () => session.activeSaveId,
  set: (value) => {
    session.selectSave(value)
  },
})

/** Total records across the sources reported by bootstrap. */
const totalRecords = computed(() => session.dataSources.reduce((sum, entry) => sum + entry.records, 0))

/** Short status of the data plane shown in the sidebar footer. */
const dataStatus = computed(() => {
  if (session.demoMode) return '演示数据'
  if (session.hasRealScanData) return '真实扫描数据'
  return '尚未导入扫描数据'
})

/** Refresh metadata and force every view to refetch. */
async function refreshSession(): Promise<void> {
  await session.load()
  if (session.error) {
    ElMessage.error(`元信息刷新失败：${session.error.message}`)
    return
  }
  ElMessage.success('元信息已刷新')
}

/** Persist the token draft and reload the affected data. */
async function saveToken(): Promise<void> {
  session.applyToken(tokenDraft.value)
  settingsOpen.value = false
  await session.load()
  ElMessage.success(tokenDraft.value ? '令牌已保存' : '令牌已清除')
}

/** Remove the stored token. */
function clearToken(): void {
  tokenDraft.value = ''
  session.applyToken('')
  void session.load()
  ElMessage.success('令牌已清除')
}

watch(
  () => session.authRequired,
  (required) => {
    if (required) settingsOpen.value = true
  },
)

watch(
  () => session.token,
  (token) => {
    tokenDraft.value = token
  },
)

onMounted(() => {
  void session.load()
})
</script>

<template>
  <div class="shell">
    <aside class="sidebar">
      <div class="brand">
        <span class="brand__name">ScoutMind</span>
        <span class="brand__sub">FM27 球探工作台</span>
      </div>

      <nav class="nav" aria-label="主导航">
        <router-link
          v-for="item in NAV_ITEMS"
          :key="item.key"
          :to="item.to"
          class="nav__item"
          :class="{ 'nav__item--active': activeKey === item.key }"
          :aria-current="activeKey === item.key ? 'page' : undefined"
          :title="item.hint"
        >
          <AppIcon :name="item.icon" :size="17" />
          <span class="nav__label">{{ item.label }}</span>
        </router-link>
      </nav>

      <nav class="nav nav--secondary" aria-label="辅助页面">
        <router-link
          v-for="item in SECONDARY_ITEMS"
          :key="item.key"
          :to="item.to"
          class="nav__item"
          :class="{ 'nav__item--active': activeKey === item.key }"
          :aria-current="activeKey === item.key ? 'page' : undefined"
          :title="item.hint"
        >
          <AppIcon :name="item.icon" :size="15" />
          <span class="nav__label">{{ item.label }}</span>
        </router-link>
      </nav>

      <div class="sidebar__foot">
        <div class="sidebar__status">
          <span class="sidebar__dot" :class="{ 'sidebar__dot--demo': session.demoMode }" aria-hidden="true" />
          <span>{{ dataStatus }}</span>
        </div>
        <div class="sidebar__meta">
          记录 {{ formatInt(totalRecords) }} · 版本 {{ session.version }}
        </div>
        <div class="sidebar__meta">
          LLM {{ session.agentLlm ? '已配置' : '未配置（确定性模式）' }}
        </div>
      </div>
    </aside>

    <div class="main">
      <header class="topbar">
        <div class="topbar__title">{{ pageTitle }}</div>
        <div class="topbar__right">
          <el-select
            v-model="saveModel"
            class="topbar__save"
            size="small"
            placeholder="无存档"
            :disabled="session.saves.length === 0"
            aria-label="选择存档"
          >
            <el-option v-for="save in session.saves" :key="save.id" :label="save.name" :value="save.id" />
          </el-select>

          <el-button
            size="small"
            :loading="session.loading"
            aria-label="刷新元信息"
            title="刷新元信息"
            @click="refreshSession"
          >
            <AppIcon name="refresh" :size="15" />
          </el-button>

          <el-popover v-model:visible="settingsOpen" placement="bottom-end" :width="330" trigger="click">
            <template #reference>
              <el-button size="small" aria-label="设置：API 令牌" title="设置">
                <AppIcon name="settings" :size="15" />
              </el-button>
            </template>
            <div class="settings">
              <p class="settings__title">接口与令牌</p>
              <p class="settings__hint">
                后端配置了 <code>SCOUTMIND_API_TOKEN</code> 时，所有请求都需要
                <code>X-ScoutMind-Token</code>。令牌仅保存在本浏览器 localStorage。
              </p>
              <el-input
                v-model="tokenDraft"
                type="password"
                show-password
                size="small"
                placeholder="粘贴 SCOUTMIND_API_TOKEN"
                aria-label="API 令牌"
              />
              <div class="settings__row">
                <el-button size="small" type="primary" @click="saveToken">保存并重载</el-button>
                <el-button size="small" @click="clearToken">清除</el-button>
              </div>
              <p class="settings__state">
                当前状态：<strong>{{ session.token ? '已配置令牌' : '未配置令牌' }}</strong>
                <span v-if="session.authRequired" class="settings__danger"> · 后端返回 401</span>
              </p>
              <p class="settings__meta">后端地址：/api/v1 → http://127.0.0.1:8000</p>
            </div>
          </el-popover>
        </div>
      </header>

      <div class="content">
        <div class="content__inner">
          <el-alert
            v-if="session.authRequired"
            class="shell__alert"
            type="error"
            show-icon
            :closable="false"
            title="后端要求 API 令牌"
          >
            <p class="shell__alert-text">
              请求返回 401。请在右上角「设置」中填入后端 <code>SCOUTMIND_API_TOKEN</code> 对应的令牌后重试。
            </p>
          </el-alert>

          <el-alert
            v-if="session.error && !session.meta"
            class="shell__alert"
            type="error"
            show-icon
            :closable="false"
            :title="session.error.isNetworkError ? '无法连接后端' : '元信息加载失败'"
          >
            <p class="shell__alert-text">{{ session.error.message }}</p>
            <el-button size="small" @click="refreshSession">重试</el-button>
          </el-alert>

          <DemoBanner />

          <router-view />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.shell {
  display: grid;
  grid-template-columns: var(--sm-sidebar-width) minmax(0, 1fr);
  height: 100vh;
  overflow: hidden;
}

/* ---------- Sidebar ---------- */

.sidebar {
  display: flex;
  flex-direction: column;
  min-height: 0;
  padding: var(--sm-space-4) var(--sm-space-3);
  background: var(--sm-sidebar);
  color: var(--sm-sidebar-text);
}

.brand {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 0 var(--sm-space-2) var(--sm-space-4);
}

.brand__name {
  color: var(--sm-sidebar-text-strong);
  font-size: var(--sm-fs-lg);
  font-weight: var(--sm-fw-semibold);
  letter-spacing: 0.01em;
}

.brand__sub {
  color: var(--sm-sidebar-text);
  font-size: var(--sm-fs-2xs);
}

.nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1 1 auto;
  overflow-y: auto;
}

.nav__item {
  display: flex;
  align-items: center;
  gap: var(--sm-space-2);
  padding: var(--sm-space-2) var(--sm-space-3);
  border-radius: var(--sm-radius-md);
  color: var(--sm-sidebar-text);
  font-size: var(--sm-fs-sm);
  text-decoration: none;
  border-left: 2px solid transparent;
}

.nav__item:hover {
  background: var(--sm-sidebar-2);
  color: var(--sm-sidebar-text-strong);
  text-decoration: none;
}

.nav__item--active {
  background: var(--sm-sidebar-3);
  border-left-color: var(--sm-accent);
  color: var(--sm-sidebar-text-strong);
  font-weight: var(--sm-fw-medium);
}

.nav--secondary {
  flex: 0 0 auto;
  margin-top: var(--sm-space-2);
  padding-top: var(--sm-space-2);
  border-top: 1px solid var(--sm-sidebar-2);
}

.nav--secondary .nav__item {
  font-size: var(--sm-fs-xs);
  color: var(--sm-sidebar-text);
  opacity: 0.85;
}

.nav--secondary .nav__item:hover,
.nav--secondary .nav__item--active {
  opacity: 1;
}

.nav__label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sidebar__foot {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--sm-space-3) var(--sm-space-2) 0;
  border-top: 1px solid var(--sm-sidebar-2);
  font-size: var(--sm-fs-2xs);
  color: var(--sm-sidebar-text);
}

.sidebar__status {
  display: flex;
  align-items: center;
  gap: var(--sm-space-2);
  color: var(--sm-sidebar-text-strong);
}

.sidebar__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--sm-success);
}

.sidebar__dot--demo {
  background: var(--sm-warn);
}

.sidebar__meta {
  line-height: 1.6;
}

/* ---------- Main column ---------- */

.main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  background: var(--sm-bg);
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sm-space-4);
  flex: 0 0 var(--sm-topbar-height);
  height: var(--sm-topbar-height);
  padding: 0 var(--sm-space-5);
  background: var(--sm-surface);
  border-bottom: 1px solid var(--sm-border);
}

.topbar__title {
  color: var(--sm-text);
  font-size: var(--sm-fs-md);
  font-weight: var(--sm-fw-semibold);
}

.topbar__right {
  display: flex;
  align-items: center;
  gap: var(--sm-space-2);
}

.topbar__save {
  width: 190px;
}

.content {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
}

.content__inner {
  max-width: var(--sm-page-max);
  margin: 0 auto;
  padding: var(--sm-space-5);
}

.shell__alert {
  margin-bottom: var(--sm-space-3);
}

.shell__alert-text {
  font-size: var(--sm-fs-xs);
  line-height: 1.6;
}

/* ---------- Settings popover ---------- */

.settings {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-2);
}

.settings__title {
  color: var(--sm-text);
  font-size: var(--sm-fs-sm);
  font-weight: var(--sm-fw-semibold);
}

.settings__hint {
  color: var(--sm-text-2);
  font-size: var(--sm-fs-2xs);
  line-height: 1.7;
}

.settings__hint code,
.shell__alert-text code {
  padding: 0 3px;
  border-radius: 3px;
  background: var(--sm-surface-3);
  font-family: var(--sm-font-mono);
  font-size: 0.95em;
}

.settings__row {
  display: flex;
  gap: var(--sm-space-2);
}

.settings__state {
  color: var(--sm-text-2);
  font-size: var(--sm-fs-2xs);
}

.settings__danger {
  color: var(--sm-danger);
}

.settings__meta {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}

@media (max-width: 1100px) {
  .shell {
    grid-template-columns: 56px minmax(0, 1fr);
  }

  .brand__name,
  .brand__sub,
  .nav__label,
  .sidebar__foot {
    display: none;
  }

  .nav__item {
    justify-content: center;
    padding: var(--sm-space-2);
  }
}
</style>
