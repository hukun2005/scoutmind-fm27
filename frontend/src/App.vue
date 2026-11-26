/**
 * 应用外壳：未来感侧栏、玻璃顶栏、存档选择与令牌设置，以及路由视图。
 * 导航结构按「指挥 → 分析 → 身份与数据 → 工具」分组；窄屏折叠为图标轨，移动端变为抽屉。
 */

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
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

interface NavGroup {
  key: string
  label: string
  items: NavItem[]
}

/**
 * 导航分组：分析模块优先，身份与数据治理随后，工具页最后。
 * 每条提示说明该页面回答的问题，而不是接口名称。
 */
const NAV_GROUPS: NavGroup[] = [
  {
    key: 'command',
    label: 'Command',
    items: [{ key: 'overview', label: '指挥中心', to: '/', icon: 'overview', hint: '全局数据、覆盖度与今日重点' }],
  },
  {
    key: 'intelligence',
    label: 'Intelligence',
    items: [
      { key: 'squad', label: '阵容智能', to: '/squad', icon: 'squad', hint: '六维评分、位置深度与接班规划' },
      { key: 'players', label: '球员中心', to: '/players', icon: 'players', hint: '筛选、排序与球员档案' },
      { key: 'recruitment', label: '智能球探', to: '/recruitment', icon: 'scouting', hint: '六维评分、隐藏价值与候选名单' },
      { key: 'transfers', label: '转会情报', to: '/transfers', icon: 'transfers', hint: '成本模型、投资效率与历史复盘' },
      { key: 'development', label: '球员发展', to: '/development', icon: 'development', hint: '成长速率、建议与潜力区间' },
      { key: 'performance', label: '表现分析', to: '/performance', icon: 'performance', hint: '分位置产出与能力对比' },
      { key: 'agent', label: 'AI 体育总监', to: '/agent', icon: 'agent', hint: '自然语言提问，工具级证据' },
    ],
  },
  {
    key: 'operations',
    label: 'Identity & Data',
    items: [
      { key: 'data', label: '数据中心', to: '/data', icon: 'data', hint: '数据导入、覆盖度与兼容性' },
      { key: 'governance', label: '数据治理', to: '/governance', icon: 'data', hint: '同日冲突、canonical 审核与成长时间轴' },
      { key: 'identity', label: '身份复核', to: '/identity', icon: 'players', hint: '同 UID 冲突的人工确认与审计' },
      {
        key: 'identity-center',
        label: '球员身份中心',
        to: '/identity-center',
        icon: 'players',
        hint: 'UID 作用域、审核队列与跨存档候选',
      },
      { key: 'save-identity', label: '存档身份', to: '/save-identity', icon: 'data', hint: '存档身份、会话心跳与采集阻断诊断' },
      { key: 'unresolved', label: '自由球员', to: '/unresolved', icon: 'players', hint: '无 UID 球员的观察、确认与忽略' },
    ],
  },
  {
    key: 'tools',
    label: 'Tools',
    items: [
      { key: 'scouting', label: '角色球探', to: '/scouting', icon: 'scouting', hint: '战术角色模板与排序' },
      { key: 'watchlist', label: '关注名单', to: '/watchlist', icon: 'watchlist', hint: '关注球员与提醒规则' },
    ],
  },
]

const session = useSessionStore()
const route = useRoute()

const settingsOpen = ref(false)
const tokenDraft = ref(session.token)
const navOpen = ref(false)

/** 当前路由对应的高亮项；详情页保持父级高亮。 */
const activeKey = computed(() => {
  const name = typeof route.name === 'string' ? route.name : ''
  if (name === 'player-detail') return 'players'
  return name
})

/** 顶栏标题与所属模块名。 */
const pageTitle = computed(() => (typeof route.meta.title === 'string' ? route.meta.title : '工作台'))
const activeGroupLabel = computed(() => {
  const group = NAV_GROUPS.find((entry) => entry.items.some((item) => item.key === activeKey.value))
  return group?.label ?? 'Command'
})

/** 存档选择器。 */
const saveModel = computed<number | null>({
  get: () => session.activeSaveId,
  set: (value) => {
    session.selectSave(value)
  },
})

/** 当前存档的规模摘要。 */
const totalRecords = computed(() => session.dataSources.reduce((sum, entry) => sum + entry.records, 0))

/** 数据来源状态：演示 / 真实扫描 / 未导入。 */
const dataStatus = computed(() => {
  if (session.demoMode) return '演示数据'
  if (session.hasRealScanData) return '真实扫描数据'
  return '尚未导入扫描数据'
})

/** 当前存档最近一次导入时间（本地时间，月-日 时:分）。 */
const lastSyncLabel = computed(() => {
  const latest = session.activeSave?.last_import_at
  if (!latest) return '无导入记录'
  const parsed = new Date(latest)
  if (Number.isNaN(parsed.getTime())) return '无导入记录'
  return parsed.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
})

/** 分析员入口的缩写（本地界面标识，不代表远端账号）。 */
const analystInitials = 'SD'

/** 刷新元信息并让所有视图重新拉取。 */
async function refreshSession(): Promise<void> {
  await session.load()
  if (session.error) {
    ElMessage.error(`元信息刷新失败：${session.error.message}`)
    return
  }
  ElMessage.success('元信息已刷新')
}

/** 保存令牌并重新加载受影响的数据。 */
async function saveToken(): Promise<void> {
  session.applyToken(tokenDraft.value)
  settingsOpen.value = false
  await session.load()
  ElMessage.success(tokenDraft.value ? '令牌已保存' : '令牌已清除')
}

/** 移除已保存的令牌。 */
function clearToken(): void {
  tokenDraft.value = ''
  session.applyToken('')
  void session.load()
  ElMessage.success('令牌已清除')
}

/** 移动端抽屉开关。 */
function toggleNav(): void {
  navOpen.value = !navOpen.value
}

/** Escape 关闭抽屉（键盘用户不必依赖遮罩）。 */
function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape' && navOpen.value) navOpen.value = false
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

// 路由变化后关闭移动抽屉，避免遮挡新页面。
watch(
  () => route.fullPath,
  () => {
    navOpen.value = false
  },
)

onMounted(() => {
  void session.load()
  window.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <div class="shell">
    <a class="skip-link" href="#main-content">跳到主内容</a>

    <div v-if="navOpen" class="scrim" aria-hidden="true" @click="navOpen = false" />

    <aside class="sidebar" :class="{ 'sidebar--open': navOpen }" aria-label="主导航栏">
      <div class="brand">
        <span class="brand__mark" aria-hidden="true">
          <span class="brand__mark-core" />
        </span>
        <span class="brand__text">
          <span class="brand__name">SCOUTMIND</span>
          <span class="brand__sub">FM27 INTELLIGENCE</span>
        </span>
      </div>

      <nav class="nav" aria-label="主导航">
        <div v-for="group in NAV_GROUPS" :key="group.key" class="nav-group">
          <p class="nav-group__label">{{ group.label }}</p>
          <router-link
            v-for="item in group.items"
            :key="item.key"
            :to="item.to"
            class="nav__item"
            :class="{ 'nav__item--active': activeKey === item.key }"
            :aria-current="activeKey === item.key ? 'page' : undefined"
            :title="item.hint"
          >
            <span class="nav__icon"><AppIcon :name="item.icon" :size="17" /></span>
            <span class="nav__label">{{ item.label }}</span>
            <span class="nav__glow" aria-hidden="true" />
          </router-link>
        </div>
      </nav>

      <div class="sidebar__foot">
        <div class="sidebar__status">
          <span
            class="sidebar__dot"
            :class="{ 'sidebar__dot--demo': session.demoMode, 'sidebar__dot--idle': !session.demoMode && !session.hasRealScanData }"
            aria-hidden="true"
          />
          <span class="sidebar__status-text">{{ dataStatus }}</span>
        </div>
        <div class="sidebar__meta">记录 {{ formatInt(totalRecords) }}</div>
        <div class="sidebar__meta">v{{ session.version }} · LLM {{ session.agentLlm ? '在线' : '确定性模式' }}</div>
      </div>
    </aside>

    <div class="main">
      <header class="topbar">
        <div class="topbar__left">
          <button
            type="button"
            class="icon-btn topbar__menu"
            :aria-expanded="navOpen"
            aria-controls="primary-sidebar"
            aria-label="打开导航"
            @click="toggleNav"
          >
            <span class="hamburger" aria-hidden="true"><i /><i /><i /></span>
          </button>
          <div class="topbar__titles">
            <span class="topbar__eyebrow">{{ activeGroupLabel }}</span>
            <span class="topbar__title">{{ pageTitle }}</span>
          </div>
        </div>

        <div class="topbar__right">
          <span class="sync-chip" :title="`最近导入：${lastSyncLabel}`">
            <span class="sync-chip__dot" :class="{ 'sync-chip__dot--demo': session.demoMode }" aria-hidden="true" />
            <span class="sync-chip__text">{{ lastSyncLabel }}</span>
          </span>

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

          <button
            type="button"
            class="icon-btn"
            :class="{ 'icon-btn--spin': session.loading }"
            aria-label="刷新元信息"
            title="刷新元信息"
            @click="refreshSession"
          >
            <AppIcon name="refresh" :size="16" />
          </button>

          <router-link class="icon-btn" to="/watchlist" aria-label="关注与提醒" title="关注与提醒">
            <AppIcon name="watchlist" :size="16" />
          </router-link>

          <el-popover v-model:visible="settingsOpen" placement="bottom-end" :width="336" trigger="click">
            <template #reference>
              <button type="button" class="icon-btn" aria-label="设置：接口与令牌" title="设置">
                <AppIcon name="settings" :size="16" />
              </button>
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

          <button type="button" class="avatar" aria-label="本机分析员" title="本机分析员">
            {{ analystInitials }}
          </button>
        </div>
      </header>

      <main id="main-content" class="content">
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

          <router-view v-slot="{ Component }">
            <transition name="page" mode="out-in">
              <component :is="Component" />
            </transition>
          </router-view>
        </div>
      </main>
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

.skip-link {
  position: absolute;
  top: -48px;
  left: var(--sm-space-4);
  z-index: 100;
  padding: var(--sm-space-2) var(--sm-space-3);
  border-radius: var(--sm-radius-sm);
  background: var(--sm-accent-cyan);
  color: #04121c;
  font-size: var(--sm-fs-xs);
  font-weight: var(--sm-fw-semibold);
  transition: top var(--sm-dur-1) var(--sm-ease-out);
}

.skip-link:focus {
  top: var(--sm-space-3);
  text-decoration: none;
}

/* ---------- 侧栏 ---------- */

.sidebar {
  position: relative;
  display: flex;
  flex-direction: column;
  min-height: 0;
  padding: var(--sm-space-4) var(--sm-space-3);
  background:
    linear-gradient(180deg, rgba(34, 211, 238, 0.07) 0%, transparent 22%),
    linear-gradient(180deg, #071020 0%, #050b15 62%, #04080f 100%);
  border-right: 1px solid var(--sm-border);
  color: var(--sm-sidebar-text);
}

/* 侧栏右缘的一道冷光，强化「控制台」边界。 */
.sidebar::after {
  content: '';
  position: absolute;
  inset: 0 0 0 auto;
  width: 1px;
  background: linear-gradient(180deg, transparent, rgba(34, 211, 238, 0.45) 22%, rgba(167, 139, 250, 0.35) 64%, transparent);
  pointer-events: none;
}

.brand {
  display: flex;
  align-items: center;
  gap: var(--sm-space-3);
  padding: var(--sm-space-1) var(--sm-space-2) var(--sm-space-5);
}

.brand__mark {
  position: relative;
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  flex: 0 0 auto;
  border-radius: 11px;
  background: var(--sm-gradient-accent);
  box-shadow: 0 0 22px -6px rgba(34, 211, 238, 0.75);
}

.brand__mark::before {
  content: '';
  position: absolute;
  inset: 3px;
  border-radius: 8px;
  border: 1px solid rgba(5, 10, 19, 0.55);
}

.brand__mark-core {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #04121c;
  box-shadow: 0 0 0 3px rgba(5, 10, 19, 0.28);
}

.brand__text {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.brand__name {
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-sm);
  font-weight: 700;
  letter-spacing: 0.18em;
}

.brand__sub {
  color: var(--sm-text-3);
  font-size: 9px;
  letter-spacing: 0.16em;
}

.nav {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-3);
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  padding-right: 2px;
}

.nav-group {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.nav-group__label {
  padding: 0 var(--sm-space-3) var(--sm-space-1);
  color: var(--sm-text-3);
  font-size: 9px;
  font-weight: var(--sm-fw-semibold);
  letter-spacing: var(--sm-tracking-wide);
  text-transform: uppercase;
}

.nav__item {
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--sm-space-3);
  padding: 8px var(--sm-space-3);
  border-radius: var(--sm-radius-sm);
  color: var(--sm-sidebar-text);
  font-size: var(--sm-fs-sm);
  text-decoration: none;
  transition:
    color var(--sm-dur-1) var(--sm-ease-out),
    background-color var(--sm-dur-1) var(--sm-ease-out);
}

.nav__item:hover {
  background: rgba(34, 211, 238, 0.07);
  color: var(--sm-text-primary);
  text-decoration: none;
}

.nav__item--active {
  background: linear-gradient(90deg, rgba(34, 211, 238, 0.16), rgba(77, 141, 255, 0.12) 48%, rgba(167, 139, 250, 0.08));
  color: var(--sm-text-primary);
  font-weight: var(--sm-fw-medium);
  box-shadow: inset 0 0 0 1px rgba(34, 211, 238, 0.18);
}

.nav__item--active::before {
  content: '';
  position: absolute;
  top: 8px;
  bottom: 8px;
  left: 0;
  width: 2px;
  border-radius: 2px;
  background: var(--sm-gradient-accent);
  box-shadow: 0 0 10px rgba(34, 211, 238, 0.8);
}

.nav__icon {
  display: grid;
  place-items: center;
  width: 18px;
  color: inherit;
  opacity: 0.9;
}

.nav__item--active .nav__icon {
  color: var(--sm-accent-cyan);
  opacity: 1;
}

.nav__label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.nav__glow {
  display: none;
}

.sidebar__foot {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-top: var(--sm-space-3);
  padding: var(--sm-space-3);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-md);
  background: rgba(10, 20, 34, 0.62);
  font-size: var(--sm-fs-2xs);
  color: var(--sm-text-3);
}

.sidebar__status {
  display: flex;
  align-items: center;
  gap: var(--sm-space-2);
  margin-bottom: 2px;
  color: var(--sm-text-2);
  font-size: var(--sm-fs-xs);
}

.sidebar__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--sm-success);
  animation: sm-pulse-dot 2.4s var(--sm-ease-in-out) infinite;
}

.sidebar__dot--demo {
  background: var(--sm-warn);
}

.sidebar__dot--idle {
  background: var(--sm-text-3);
  animation: none;
}

.sidebar__meta {
  line-height: 1.7;
}

/* ---------- 主列 ---------- */

.main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  background-color: transparent;
}

.topbar {
  position: relative;
  z-index: 20;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sm-space-4);
  flex: 0 0 var(--sm-topbar-height);
  height: var(--sm-topbar-height);
  padding: 0 var(--sm-space-5);
  border-bottom: 1px solid var(--sm-border);
  background: rgba(7, 14, 25, 0.72);
  backdrop-filter: blur(var(--sm-blur-glass)) saturate(150%);
  -webkit-backdrop-filter: blur(var(--sm-blur-glass)) saturate(150%);
}

.topbar__left {
  display: flex;
  align-items: center;
  gap: var(--sm-space-3);
  min-width: 0;
}

.topbar__menu {
  display: none;
}

.topbar__titles {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.topbar__eyebrow {
  color: var(--sm-text-3);
  font-size: 9px;
  font-weight: var(--sm-fw-semibold);
  letter-spacing: var(--sm-tracking-wide);
  text-transform: uppercase;
}

.topbar__title {
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-md);
  font-weight: var(--sm-fw-semibold);
  letter-spacing: 0.01em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.topbar__right {
  display: flex;
  align-items: center;
  gap: var(--sm-space-2);
  min-width: 0;
}

.topbar__save {
  width: 188px;
}

.sync-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 168px;
  padding: 4px var(--sm-space-2);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-pill);
  background: rgba(12, 23, 39, 0.7);
  color: var(--sm-text-2);
  font-size: var(--sm-fs-2xs);
  white-space: nowrap;
}

.sync-chip__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--sm-success);
  animation: sm-pulse-dot 2.4s var(--sm-ease-in-out) infinite;
}

.sync-chip__dot--demo {
  background: var(--sm-warn);
}

.sync-chip__text {
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 图标按钮：顶栏与抽屉共用。 */
.icon-btn {
  display: inline-grid;
  place-items: center;
  width: 30px;
  height: 30px;
  padding: 0;
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-sm);
  background: rgba(12, 23, 39, 0.66);
  color: var(--sm-text-2);
  cursor: pointer;
  transition:
    color var(--sm-dur-1) var(--sm-ease-out),
    border-color var(--sm-dur-1) var(--sm-ease-out),
    background-color var(--sm-dur-1) var(--sm-ease-out);
}

.icon-btn:hover {
  border-color: var(--sm-border-glow);
  background: rgba(34, 211, 238, 0.1);
  color: var(--sm-text-primary);
  text-decoration: none;
}

.icon-btn--spin :deep(svg) {
  animation: sm-spin 1s linear infinite;
}

@keyframes sm-spin {
  to {
    transform: rotate(360deg);
  }
}

.avatar {
  display: inline-grid;
  place-items: center;
  width: 30px;
  height: 30px;
  padding: 0;
  border: 1px solid rgba(34, 211, 238, 0.35);
  border-radius: 50%;
  background: linear-gradient(135deg, rgba(34, 211, 238, 0.24), rgba(167, 139, 250, 0.28));
  color: var(--sm-text-primary);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.04em;
  cursor: pointer;
}

.hamburger {
  display: inline-flex;
  flex-direction: column;
  gap: 3px;
  width: 14px;
}

.hamburger i {
  display: block;
  height: 1.5px;
  border-radius: 2px;
  background: currentColor;
}

.content {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
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

/* 路由切换：淡入上移，out-in 防止两页同时占位。 */
.page-enter-active,
.page-leave-active {
  transition:
    opacity var(--sm-dur-2) var(--sm-ease-out),
    transform var(--sm-dur-2) var(--sm-ease-out);
}

.page-enter-from {
  opacity: 0;
  transform: translateY(6px);
}

.page-leave-to {
  opacity: 0;
}

/* ---------- 设置弹层 ---------- */

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

.scrim {
  display: none;
}

/* ---------- 平板：图标轨 ---------- */

@media (max-width: 1199px) {
  .shell {
    grid-template-columns: var(--sm-sidebar-width-rail) minmax(0, 1fr);
  }

  .sidebar {
    padding: var(--sm-space-4) var(--sm-space-2);
  }

  .brand {
    justify-content: center;
    padding: 0 0 var(--sm-space-4);
  }

  .brand__text,
  .nav-group__label,
  .nav__label,
  .sidebar__foot {
    display: none;
  }

  .nav__item {
    justify-content: center;
    padding: 9px;
  }

  .nav-group {
    gap: var(--sm-space-1);
  }

  .nav {
    gap: var(--sm-space-2);
  }
}

/* ---------- 移动端：抽屉 ---------- */

@media (max-width: 900px) {
  .shell {
    grid-template-columns: minmax(0, 1fr);
  }

  .sidebar {
    position: fixed;
    top: 0;
    bottom: 0;
    left: 0;
    z-index: 60;
    width: 272px;
    padding: var(--sm-space-4) var(--sm-space-3);
    transform: translateX(-100%);
    transition: transform var(--sm-dur-3) var(--sm-ease-out);
    box-shadow: var(--sm-shadow-float);
    visibility: hidden;
  }

  .sidebar--open {
    transform: none;
    visibility: visible;
  }

  .brand {
    justify-content: flex-start;
    padding: var(--sm-space-1) var(--sm-space-2) var(--sm-space-5);
  }

  .brand__text,
  .nav-group__label,
  .nav__label,
  .sidebar__foot {
    display: flex;
  }

  .sidebar__foot {
    display: flex;
  }

  .nav__item {
    justify-content: flex-start;
    padding: 8px var(--sm-space-3);
  }

  .scrim {
    display: block;
    position: fixed;
    inset: 0;
    z-index: 55;
    background: rgba(3, 8, 16, 0.66);
    backdrop-filter: blur(2px);
  }

  .topbar__menu {
    display: inline-grid;
  }

  .sync-chip {
    display: none;
  }
}

@media (max-width: 640px) {
  .topbar {
    padding: 0 var(--sm-space-3);
    gap: var(--sm-space-2);
  }

  .content__inner {
    padding: var(--sm-space-4) var(--sm-space-3) calc(var(--sm-space-5) + var(--sm-safe-bottom));
  }

  .topbar__save {
    width: 128px;
  }

  .topbar__eyebrow {
    display: none;
  }

  .topbar__right {
    gap: 6px;
  }

  .icon-btn,
  .avatar {
    width: 28px;
    height: 28px;
  }
}

@media (max-width: 430px) {
  .topbar__title {
    font-size: var(--sm-fs-sm);
  }

  .topbar__save {
    width: 112px;
  }

  .topbar__right .icon-btn[title='关注与提醒'] {
    display: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .sidebar {
    transition: none;
  }

  .page-enter-active,
  .page-leave-active {
    transition: none;
  }

  .icon-btn--spin :deep(svg),
  .sidebar__dot,
  .sync-chip__dot {
    animation: none;
  }
}
</style>
