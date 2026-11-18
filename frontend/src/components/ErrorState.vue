/** Failure state with the normalized API error, its code and a retry action. */

<script setup lang="ts">
import { computed } from 'vue'
import { ApiError } from '../api/client'
import EmptyState from './EmptyState.vue'

const props = withDefaults(
  defineProps<{
    /** Normalized failure; `null` renders nothing. */
    error: ApiError | null
    /** Override the default heading. */
    title?: string
    /** Retry button label. */
    retryLabel?: string
    /** Compact spacing for panel-sized failures. */
    compact?: boolean
    /** Show the retry button (disable for failures the user cannot retry). */
    showRetry?: boolean
  }>(),
  { title: '加载失败', retryLabel: '重试', compact: false, showRetry: true },
)

const emit = defineEmits<{ (event: 'retry'): void }>()

const description = computed(() => {
  const error = props.error
  if (!error) return ''
  const parts: string[] = [error.message]
  if (error.isNetworkError) {
    parts.push('开发环境请先启动后端：uvicorn app.main:app --port 8000，并确认 vite 代理指向 127.0.0.1:8000。')
  }
  if (error.isUnauthorized) {
    parts.push('在右上角「设置」中填入后端 SCOUTMIND_API_TOKEN 对应的令牌后重试。')
  }
  return parts.join(' ')
})

const codeText = computed(() => {
  const error = props.error
  if (!error) return ''
  const status = error.status === null ? '无响应' : `HTTP ${error.status}`
  return `${error.code} · ${status}`
})
</script>

<template>
  <div v-if="error" class="error-state">
    <EmptyState variant="error" :title="title" :description="description" :compact="compact">
      <el-button v-if="showRetry" size="small" type="primary" @click="emit('retry')">{{ retryLabel }}</el-button>
      <span class="error-state__code sm-mono">{{ codeText }}</span>
    </EmptyState>
  </div>
</template>

<style scoped>
.error-state {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-2);
}

.error-state__code {
  align-self: center;
  color: var(--sm-danger);
}
</style>
