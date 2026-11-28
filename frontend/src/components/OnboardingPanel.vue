<script setup lang="ts">
/**
 * 首次启动智能引导：环境检查 → 数据准备 → 完成摘要。
 *
 * 只展示用户能理解的状态；内部错误不展示堆栈。可随时跳过，并可从设置重新打开。
 */

import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { createScan } from '../api/transferDirector'
import { asApiError } from '../api/client'
import { useOnboardingStore } from '../stores/onboarding'
import { formatInt } from '../utils/format'
import AppLogo from './AppLogo.vue'
import AppTag from './AppTag.vue'

const store = useOnboardingStore()
const router = useRouter()
const scanning = ref(false)

const STATUS_LABELS: Record<string, string> = {
  ready: '已就绪',
  checking: '正在检查',
  needs_attention: '需要处理',
  unavailable: '暂不可用',
}

const summary = computed(() => store.data?.summary ?? null)
const checks = computed(() => store.data?.checks ?? [])
const actions = computed(() => store.data?.actions ?? [])
const recoverable = computed(() => store.data?.data.recoverable_tasks ?? [])

function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? '正在检查'
}

function onVisible(value: boolean): void {
  if (!value) store.close()
}

function goData(): void {
  store.dismiss()
  void router.push('/data')
}

async function startScan(): Promise<void> {
  scanning.value = true
  try {
    const result = await createScan('FULL_SCAN')
    ElMessage.success(result.reused ? '已有扫描任务在进行中' : '扫描已开始，可在数据中心查看进度')
    store.dismiss()
  } catch (caught) {
    ElMessage.error(asApiError(caught).message)
  } finally {
    scanning.value = false
  }
}
</script>

<template>
  <el-dialog
    :model-value="store.visible"
    title="欢迎使用 ScoutMind"
    width="560px"
    data-testid="onboarding-panel"
    :close-on-click-modal="false"
    @update:model-value="onVisible"
  >
    <div v-loading="store.loading" class="onboarding">
      <div class="onboarding__brand">
        <AppLogo variant="app" :size="42" />
        <div>
          <p class="onboarding__brand-name">ScoutMind FM27</p>
          <p class="onboarding__brand-sub">足球情报与 AI 体育总监工作台</p>
        </div>
      </div>

      <el-alert
        v-if="store.error"
        type="warning"
        :closable="false"
        show-icon
        title="暂时无法完成环境检查"
      >
        <span class="sm-text-xs">{{ store.error.message }}</span>
      </el-alert>

      <section>
        <p class="step">第 1 步 · 环境检查</p>
        <ul class="checks">
          <li v-for="item in checks" :key="item.key" class="check">
            <span class="check__label">{{ item.label }}</span>
            <AppTag :tag="item.status" :label="statusLabel(item.status)" />
            <span v-if="item.detail" class="check__detail">{{ item.detail }}</span>
          </li>
        </ul>
      </section>

      <section>
        <p class="step">第 2 步 · 数据准备</p>
        <p class="sm-hint">
          {{ store.hasData ? '当前存档已有可用数据，不需要重复导入。' : '还没有导入数据，可以先导入或扫描当前存档。' }}
        </p>
        <div class="actions">
          <el-button
            v-for="action in actions"
            :key="action.key"
            size="small"
            :disabled="!action.enabled"
            :type="action.key === 'import' && !store.hasData ? 'primary' : 'default'"
            :loading="action.key === 'scan' && scanning"
            @click="action.key === 'scan' ? startScan() : goData()"
          >
            {{ action.label }}
          </el-button>
        </div>
        <p v-if="recoverable.length" class="sm-text-2xs sm-text-faint">
          有 {{ recoverable.length }} 个未完成的任务可以继续：{{ recoverable[0].message }}
        </p>
      </section>

      <section v-if="summary">
        <p class="step">第 3 步 · 完成</p>
        <dl class="summary">
          <div><dt>已导入球员</dt><dd>{{ formatInt(summary.player_count) }}</dd></div>
          <div><dt>已识别俱乐部</dt><dd>{{ formatInt(summary.club_count) }}</dd></div>
          <div><dt>转会机会</dt><dd>{{ formatInt(summary.opportunity_count) }}</dd></div>
          <div><dt>数据状态</dt><dd>{{ summary.save_status }}</dd></div>
        </dl>
      </section>
    </div>

    <template #footer>
      <el-button size="small" @click="store.dismiss()">跳过引导</el-button>
      <el-button size="small" type="primary" @click="store.dismiss()">进入主页</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.onboarding {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-4);
}

.onboarding__brand {
  display: flex;
  align-items: center;
  gap: var(--sm-space-3);
  padding-bottom: var(--sm-space-3);
  border-bottom: 1px solid var(--sm-border);
}

.onboarding__brand-name {
  margin: 0;
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-md);
  font-weight: var(--sm-fw-semibold);
}

.onboarding__brand-sub {
  margin: 2px 0 0;
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}

.step {
  margin: 0 0 var(--sm-space-2);
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-sm);
  font-weight: var(--sm-fw-semibold);
}

.checks {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.check {
  display: flex;
  align-items: center;
  gap: var(--sm-space-2);
  flex-wrap: wrap;
  padding-bottom: var(--sm-space-2);
  border-bottom: 1px solid var(--sm-border);
}

.check:last-child {
  border-bottom: 0;
}

.check__label {
  min-width: 88px;
  color: var(--sm-text-2);
  font-size: var(--sm-fs-xs);
}

.check__detail {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}

.actions {
  display: flex;
  gap: var(--sm-space-2);
  margin-top: var(--sm-space-2);
  flex-wrap: wrap;
}

.summary {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--sm-space-2);
  margin: 0;
}

.summary > div {
  padding: var(--sm-space-2) var(--sm-space-3);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-sm);
  background: var(--sm-surface-2);
}

.summary dt {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}

.summary dd {
  margin: 2px 0 0;
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-md);
  font-weight: var(--sm-fw-semibold);
}
</style>
