<template>
  <SectionCard title="自动历史快照" subtitle="同存档同游戏日期默认只保留正式采集；同日补充扫描单独标记 revision" dense>
    <div class="capture">
      <div class="capture__stats">
        <div class="capture__stat"><span>采集记录</span><strong>{{ summary?.total ?? 0 }}</strong></div>
        <div class="capture__stat"><span>已完成</span><strong>{{ summary?.counts.completed ?? 0 }}</strong></div>
        <div class="capture__stat"><span>重试中</span><strong>{{ summary?.counts.retry_pending ?? 0 }}</strong></div>
        <div class="capture__stat"><span>失败</span><strong>{{ summary?.counts.failed ?? 0 }}</strong></div>
      </div>
      <p v-if="summary?.latest" class="capture__latest">
        最近：{{ summary.latest.game_date || '日期未确定' }} · {{ statusLabel(summary.latest.status) }}
        <span v-if="summary.latest.error_message"> · {{ summary.latest.error_message }}</span>
      </p>
      <p v-else class="capture__muted">还没有自动采集记录。桌面代理登记采集任务后会显示在这里。</p>
      <table v-if="runs.length" class="capture__table">
        <thead><tr><th>game_date</th><th>状态</th><th>尝试</th><th>快照补充</th><th>更新时间</th></tr></thead>
        <tbody>
          <tr v-for="run in runs" :key="run.id">
            <td>{{ run.game_date || '—' }}</td>
            <td>{{ statusLabel(run.status) }}</td>
            <td>{{ run.attempt_count }}/{{ run.max_attempts }}</td>
            <td>{{ run.supplemental ? `revision ${run.revision}` : '正式' }}</td>
            <td>{{ formatDateTime(run.updated_at) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </SectionCard>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getCaptureRuns, getCaptureSummary } from '../api/captures'
import SectionCard from './SectionCard.vue'
import type { CaptureRun, CaptureSummary } from '../types/captures'
import { formatDateTime } from '../utils/format'

const summary = ref<CaptureSummary | null>(null)
const runs = ref<CaptureRun[]>([])
const statusLabel = (status: string) => ({
  monitoring: '监视中', date_detected: '发现日期', scan_queued: '已排队',
  scanning: '扫描中', importing: '导入中', completed: '已完成',
  retry_pending: '等待重试', failed: '失败', cancelled: '已取消', paused: '已暂停',
} as Record<string, string>)[status] ?? status

onMounted(async () => {
  try {
    const [summaryResponse, runsResponse] = await Promise.all([getCaptureSummary(), getCaptureRuns(8)])
    summary.value = summaryResponse
    runs.value = runsResponse.items
  } catch {
    // DataView already reports the session/API error; keep this panel passive.
  }
})
</script>

<style scoped>
.capture { display: flex; flex-direction: column; gap: 8px; padding: 0 var(--sm-space-4) var(--sm-space-3); }
.capture__stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }
.capture__stat { display: flex; flex-direction: column; padding: 8px 10px; border: 1px solid var(--sm-border); border-radius: var(--sm-radius-md); background: var(--sm-surface-2); }
.capture__stat span { color: var(--sm-text-3); font-size: var(--sm-fs-xs); }
.capture__stat strong { font-size: var(--sm-fs-lg); }
.capture__latest, .capture__muted { margin: 0; color: var(--sm-text-2); font-size: var(--sm-fs-sm); }
.capture__muted { color: var(--sm-text-3); }
.capture__table { width: 100%; border-collapse: collapse; font-size: var(--sm-fs-sm); }
.capture__table th, .capture__table td { padding: 5px 8px; border-bottom: 1px solid var(--sm-border); text-align: left; }
</style>
