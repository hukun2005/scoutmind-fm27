/**
 * 系统设置：普通用户只需要看到版本、游戏连接、存储位置、备份说明、外观与关于。
 *
 * 令牌、后端地址等内部配置收进「开发者选项」，默认折叠。
 * 备份与更新只陈述真实状态，不提供没有后端支撑的假按钮。
 */

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getHealth } from '../api/bootstrap'
import { getDataHubStatus } from '../api/datahub'
import { asApiError, type ApiError } from '../api/client'
import type { HealthResponse } from '../types/bootstrap'
import type { DataHubStatus } from '../types/datahub'
import PageHeader from '../components/PageHeader.vue'
import SectionCard from '../components/SectionCard.vue'
import AppLogo from '../components/AppLogo.vue'
import { useSessionStore } from '../stores/session'
import { useOnboardingStore } from '../stores/onboarding'
import { displayText, formatInt } from '../utils/format'
import { getMotionPreference, setMotionPreference, type MotionPreference } from '../utils/preferences'

const session = useSessionStore()
const onboarding = useOnboardingStore()

const health = ref<HealthResponse | null>(null)
const hub = ref<DataHubStatus | null>(null)
const hubUnavailable = ref(false)
const loading = ref(false)
const loadError = ref<ApiError | null>(null)

const desktop = ref<ScoutMindDesktopInfo | null>(null)
const desktopUnavailable = ref(false)

const tokenDraft = ref(session.token)
const motion = ref<MotionPreference>(getMotionPreference())

/** 游戏连接文案。 */
const gameText = computed(() => {
  if (hubUnavailable.value) return '数据中心接口暂不可用'
  const game = hub.value?.game
  if (!game) return '状态未知'
  if (game.running) return game.version ? `已连接 · 版本 ${game.version}` : '已连接'
  if (game.detected) return '未检测到 Football Manager 27'
  return game.message || '无法检测'
})

/** 数据存储位置：桌面版显示真实数据目录，浏览器模式给出说明。 */
const storagePath = computed(() => {
  if (desktop.value) return desktop.value.dataDir
  if (desktopUnavailable.value) return '浏览器模式：由本机后端管理数据目录'
  return '正在读取桌面信息…'
})

/** 备份说明。 */
const backupHint = computed(() =>
  desktop.value
    ? '退出 ScoutMind 后，把数据目录整体复制到安全位置即可完成备份；恢复时把备份目录放回原位置再启动。'
    : '桌面版会把数据保存在本机数据目录。浏览器模式下请通过桌面版进行备份与恢复。',
)

/** 版本号：优先桌面版版本，其次后端版本。 */
const versionText = computed(() => desktop.value?.version ?? session.version)

/** 记录数摘要。 */
const recordsText = computed(() => {
  const records = hub.value?.records
  if (!records) return '—'
  return `球员 ${formatInt(records.players)} · 转会 ${formatInt(records.transfers)} · 俱乐部 ${formatInt(records.clubs)}`
})

/** 加载健康状态与数据中心状态。 */
async function load(): Promise<void> {
  loading.value = true
  loadError.value = null
  try {
    health.value = await getHealth()
  } catch (caught) {
    loadError.value = asApiError(caught)
  }
  try {
    hub.value = await getDataHubStatus()
    hubUnavailable.value = false
  } catch {
    hub.value = null
    hubUnavailable.value = true
  }
  loading.value = false
}

/** 读取桌面外壳信息；浏览器中静默跳过。 */
async function loadDesktop(): Promise<void> {
  const bridge = window.scoutmindDesktop
  if (!bridge) {
    desktopUnavailable.value = true
    return
  }
  try {
    desktop.value = await bridge.getInfo()
  } catch {
    desktopUnavailable.value = true
  }
}

/** 复制存储路径。 */
async function copyPath(): Promise<void> {
  const text = desktop.value?.dataDir
  if (!text) {
    ElMessage.warning('当前没有可复制的数据目录')
    return
  }
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('数据目录已复制')
  } catch {
    ElMessage.warning('复制失败，请手动选中路径复制')
  }
}

/** 切换界面动效。 */
function onMotionChange(value: string | number | boolean): void {
  const next: MotionPreference = value === true ? 'reduced' : 'auto'
  motion.value = next
  setMotionPreference(next)
  ElMessage.success(next === 'reduced' ? '已关闭界面动效' : '界面动效将跟随系统设置')
}

/** 保存 API 令牌。 */
async function saveToken(): Promise<void> {
  session.applyToken(tokenDraft.value)
  await session.load()
  ElMessage.success(tokenDraft.value ? '令牌已保存' : '令牌已清除')
}

/** 清除 API 令牌。 */
function clearToken(): void {
  tokenDraft.value = ''
  session.applyToken('')
  void session.load()
  ElMessage.success('令牌已清除')
}

onMounted(() => {
  void load()
  void loadDesktop()
})
</script>

<template>
  <div class="sm-page">
    <PageHeader title="系统设置" description="查看版本、游戏连接与数据位置，调整界面外观。">
      <template #actions>
        <el-button size="small" :loading="loading" @click="load">刷新</el-button>
      </template>
    </PageHeader>

    <el-alert
      v-if="loadError"
      type="error"
      :closable="false"
      show-icon
      :title="loadError.isNetworkError ? '无法连接本地服务' : '部分设置无法读取'"
    >
      <span class="sm-text-xs">{{ loadError.message }}</span>
    </el-alert>

    <div class="sm-grid sm-grid--2">
      <SectionCard title="软件版本" subtitle="当前运行的 ScoutMind FM27">
        <dl class="kv">
          <div><dt>版本</dt><dd>v{{ versionText }}</dd></div>
          <div><dt>产品</dt><dd>{{ displayText(desktop?.product ?? session.product) }}</dd></div>
          <div><dt>运行方式</dt><dd>{{ desktop ? 'Windows 桌面版 · 完全本地运行' : '浏览器界面 · 连接本机服务' }}</dd></div>
        </dl>
      </SectionCard>

      <SectionCard title="游戏连接" subtitle="Football Manager 27 与本机服务的连接状态">
        <dl class="kv">
          <div>
            <dt>游戏</dt>
            <dd>
              <span class="dot" :class="hub?.game.running ? 'dot--ok' : 'dot--idle'" aria-hidden="true" />
              {{ gameText }}
            </dd>
          </div>
          <div><dt>当前存档</dt><dd>{{ displayText(hub?.save.name ?? session.activeSave?.name) }}</dd></div>
          <div><dt>后端服务</dt><dd>{{ health ? '运行中' : '未连接' }}<span v-if="health" class="sm-text-2xs sm-text-faint"> · {{ health.database }}</span></dd></div>
        </dl>
      </SectionCard>

      <SectionCard title="数据存储位置" subtitle="所有数据保存在本机，不会上传">
        <p class="path">{{ storagePath }}</p>
        <div class="row">
          <el-button size="small" :disabled="!desktop" @click="copyPath">复制路径</el-button>
          <span class="sm-text-2xs sm-text-faint">记录：{{ recordsText }}</span>
        </div>
      </SectionCard>

      <SectionCard title="备份与恢复" subtitle="由数据目录整体备份">
        <p class="sm-hint">{{ backupHint }}</p>
        <p v-if="desktop" class="sm-text-2xs sm-text-faint">日志目录：{{ desktop.logsDir }}</p>
      </SectionCard>

      <SectionCard title="外观" subtitle="深色专业界面">
        <dl class="kv">
          <div><dt>主题</dt><dd>深色（固定）</dd></div>
          <div>
            <dt>界面动效</dt>
            <dd>
              <el-switch
                :model-value="motion === 'reduced'"
                active-text="关闭"
                inactive-text="跟随系统"
                inline-prompt
                @update:model-value="onMotionChange"
              />
            </dd>
          </div>
        </dl>
        <p class="sm-text-2xs sm-text-faint">关闭后仍保留全部功能，只停止过渡与微光动画。</p>
      </SectionCard>

      <SectionCard title="更新信息" subtitle="通过安装包更新">
        <dl class="kv">
          <div><dt>当前版本</dt><dd>v{{ versionText }}</dd></div>
          <div><dt>更新方式</dt><dd>运行新版本安装包覆盖安装</dd></div>
        </dl>
        <p class="sm-text-2xs sm-text-faint">本地版不联网检查更新，也不会自动下载。</p>
      </SectionCard>
    </div>

    <SectionCard title="关于 ScoutMind" subtitle="专业足球情报软件">
      <div class="about-brand">
        <AppLogo variant="app" :size="56" />
        <div class="about-brand__text">
          <p class="about-brand__name">ScoutMind FM27</p>
          <p class="about-brand__tagline">Football Intelligence &amp; AI Sporting Director Platform</p>
        </div>
      </div>
      <p class="sm-hint">
        ScoutMind FM27 把复杂的球队数据整理成容易理解的页面：球员、阵容、引援、转会、成长与 AI 分析都在本地完成，
        不需要网络，也不会上传你的存档。
      </p>
      <div class="row">
        <el-button size="small" @click="onboarding.reopen()">重新打开首次启动引导</el-button>
      </div>
    </SectionCard>

    <details class="sm-details">
      <summary>开发者选项（内部配置）</summary>
      <div class="sm-details__body developer">
        <div class="dev-block">
          <p class="dev-title">接口令牌</p>
          <p class="sm-hint">
            后端配置了 SCOUTMIND_API_TOKEN 时，请求需要携带令牌。令牌只保存在本机浏览器。
          </p>
          <div class="row">
            <el-input
              v-model="tokenDraft"
              type="password"
              show-password
              size="small"
              placeholder="粘贴访问令牌"
              aria-label="访问令牌"
            />
            <el-button size="small" type="primary" @click="saveToken">保存</el-button>
            <el-button size="small" @click="clearToken">清除</el-button>
          </div>
          <p class="sm-text-2xs sm-text-faint">
            当前状态：{{ session.token ? '已配置' : '未配置' }}
            <span v-if="session.authRequired" class="dev-danger"> · 后端返回 401</span>
          </p>
        </div>

        <div class="dev-block">
          <p class="dev-title">诊断入口</p>
          <div class="row row--wrap">
            <router-link class="dev-link" to="/data">数据与导入诊断</router-link>
            <router-link class="dev-link" to="/governance">数据治理</router-link>
            <router-link class="dev-link" to="/identity">身份复核</router-link>
            <router-link class="dev-link" to="/save-identity">存档身份</router-link>
          </div>
        </div>

        <div class="dev-block">
          <p class="dev-title">服务地址</p>
          <p class="sm-text-2xs sm-text-faint">
            接口前缀 /api/v1；桌面版由本地服务提供：{{ desktop?.backend.url ?? 'http://127.0.0.1:8000' }}
          </p>
        </div>
      </div>
    </details>
  </div>
</template>

<style scoped>
.about-brand {
  display: flex;
  align-items: center;
  gap: var(--sm-space-4);
  margin-bottom: var(--sm-space-3);
  padding-bottom: var(--sm-space-3);
  border-bottom: 1px solid var(--sm-border);
}

.about-brand__text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.about-brand__name {
  margin: 0;
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-lg);
  font-weight: var(--sm-fw-semibold);
  letter-spacing: 0.02em;
}

.about-brand__tagline {
  margin: 0;
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
  letter-spacing: 0.04em;
}

.kv {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-2);
  margin: 0;
}

.kv > div {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sm-space-3);
  padding-bottom: var(--sm-space-2);
  border-bottom: 1px solid var(--sm-border);
}

.kv > div:last-child {
  padding-bottom: 0;
  border-bottom: 0;
}

.kv dt {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-xs);
}

.kv dd {
  display: inline-flex;
  align-items: center;
  gap: var(--sm-space-2);
  margin: 0;
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-sm);
  text-align: right;
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--sm-text-3);
}

.dot--ok {
  background: var(--sm-success);
  box-shadow: 0 0 8px rgba(52, 211, 153, 0.7);
}

.path {
  padding: var(--sm-space-2) var(--sm-space-3);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-sm);
  background: rgba(6, 16, 29, 0.8);
  color: var(--sm-text);
  font-family: var(--sm-font-mono);
  font-size: var(--sm-fs-xs);
  word-break: break-all;
}

.row {
  display: flex;
  align-items: center;
  gap: var(--sm-space-2);
  margin-top: var(--sm-space-2);
  flex-wrap: wrap;
}

.row--wrap {
  flex-wrap: wrap;
}

.developer {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-4);
  padding-top: var(--sm-space-3);
}

.dev-block {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-2);
}

.dev-title {
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-sm);
  font-weight: var(--sm-fw-semibold);
}

.dev-danger {
  color: var(--sm-danger);
}

.dev-link {
  padding: 3px var(--sm-space-2);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-sm);
  color: var(--sm-text-2);
  font-size: var(--sm-fs-xs);
}

.dev-link:hover {
  border-color: var(--sm-border-glow);
  color: var(--sm-text-primary);
  text-decoration: none;
}
</style>
