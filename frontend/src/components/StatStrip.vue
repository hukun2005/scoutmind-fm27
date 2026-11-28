/**
 * 紧凑指标条：用分隔线而不是独立卡片呈现同级关键数字。
 *
 * `value` 允许字符串（如「—」「3 名」），缺失必须由调用方显式传 `—` 或「暂无数据」，
 * 组件不做 0 兜底，避免把未知值伪装成真实数据。
 */

<script setup lang="ts">
import type { StatItem } from '../types/ui'

withDefaults(
  defineProps<{
    items: StatItem[]
    /** 更小的字号与间距，用于页面顶部信息带。 */
    dense?: boolean
  }>(),
  { dense: false },
)
</script>

<template>
  <div class="stat-strip" :class="{ 'stat-strip--dense': dense }" role="group" aria-label="关键指标">
    <div v-for="item in items" :key="item.label" class="stat-strip__item">
      <span class="stat-strip__label">{{ item.label }}</span>
      <span class="stat-strip__value" :class="`stat-strip__value--${item.tone ?? 'default'}`">{{ item.value }}</span>
      <span v-if="item.hint" class="stat-strip__hint">{{ item.hint }}</span>
    </div>
  </div>
</template>

<style scoped>
.stat-strip {
  display: grid;
  grid-auto-flow: column;
  grid-auto-columns: minmax(0, 1fr);
  margin: 0;
  padding: var(--sm-space-1) 0;
  border-top: 1px solid var(--sm-border);
  border-bottom: 1px solid var(--sm-border);
  overflow-x: auto;
}

.stat-strip__item {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
  padding: var(--sm-space-2) var(--sm-space-4);
  border-left: 1px solid var(--sm-border);
}

.stat-strip__item:first-child {
  border-left: 0;
  padding-left: 0;
}

.stat-strip__label {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
  font-weight: var(--sm-fw-medium);
  letter-spacing: var(--sm-tracking-label);
  white-space: nowrap;
}

.stat-strip__value {
  margin: 0;
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-xl);
  font-weight: var(--sm-fw-semibold);
  font-variant-numeric: tabular-nums;
  line-height: var(--sm-lh-tight);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.stat-strip__value--accent {
  color: var(--sm-accent-cyan);
}

.stat-strip__value--success {
  color: var(--sm-status-success);
}

.stat-strip__value--warning {
  color: var(--sm-status-warning);
}

.stat-strip__value--danger {
  color: var(--sm-status-danger);
}

.stat-strip__hint {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
  line-height: 1.4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.stat-strip--dense .stat-strip__item {
  padding: var(--sm-space-1) var(--sm-space-3);
}

.stat-strip--dense .stat-strip__value {
  font-size: var(--sm-fs-lg);
}

@media (max-width: 900px) {
  .stat-strip {
    grid-auto-flow: row;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  }

  .stat-strip__item {
    border-left: 0;
    border-top: 1px solid var(--sm-border);
    padding: var(--sm-space-2) 0;
  }

  .stat-strip__item:first-child {
    border-top: 0;
  }
}
</style>
