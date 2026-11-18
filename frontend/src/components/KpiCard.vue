/** KPI card used by the dashboard header row. */

<script setup lang="ts">
withDefaults(
  defineProps<{
    /** Metric name. */
    label: string
    /** Pre-formatted value; `—` when the metric is unavailable. */
    value: string
    /** Secondary explanation under the value. */
    hint?: string
    /** Accent for a metric that needs attention. */
    tone?: 'default' | 'accent' | 'warn' | 'danger'
    /** Show a skeleton instead of the value. */
    loading?: boolean
    /** Optional route: stretches a link across the whole card. */
    to?: string
  }>(),
  { hint: '', tone: 'default', loading: false, to: '' },
)
</script>

<template>
  <div class="kpi" :class="[`kpi--${tone}`, { 'kpi--link': Boolean(to) }]">
    <div class="kpi__body">
      <div class="kpi__label">{{ label }}</div>
      <el-skeleton v-if="loading" :rows="1" animated class="kpi__skeleton" />
      <div v-else class="kpi__value sm-num" :title="value">{{ value }}</div>
      <div v-if="hint" class="kpi__hint">{{ hint }}</div>
    </div>
    <router-link v-if="to" class="kpi__stretch" :to="to" :aria-label="`${label}：${value}`" />
  </div>
</template>

<style scoped>
.kpi {
  position: relative;
  display: flex;
  flex-direction: column;
  min-width: 0;
  padding: var(--sm-space-3) var(--sm-space-4);
  background: var(--sm-surface);
  border: 1px solid var(--sm-border);
  border-left: 3px solid var(--sm-border-strong);
  border-radius: var(--sm-radius-lg);
  color: inherit;
  box-shadow: var(--sm-shadow-1);
}

.kpi--accent {
  border-left-color: var(--sm-accent);
}

.kpi--warn {
  border-left-color: var(--sm-warn);
}

.kpi--danger {
  border-left-color: var(--sm-danger);
}

.kpi--link:hover {
  border-top-color: var(--sm-accent);
  border-right-color: var(--sm-accent);
  border-bottom-color: var(--sm-accent);
}

/* Stretched link: the whole card is clickable, the anchor is the focus target. */
.kpi__stretch {
  position: absolute;
  inset: 0;
  z-index: 1;
  border-radius: var(--sm-radius-lg);
}

.kpi__stretch:focus-visible {
  outline: 2px solid var(--sm-accent);
  outline-offset: 2px;
}

.kpi__body {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-1);
  min-width: 0;
}

.kpi__label {
  color: var(--sm-text-2);
  font-size: var(--sm-fs-xs);
}

.kpi__value {
  color: var(--sm-text);
  font-size: var(--sm-fs-2xl);
  font-weight: var(--sm-fw-semibold);
  letter-spacing: -0.01em;
  line-height: var(--sm-lh-tight);
  text-align: right;
  overflow: hidden;
  text-overflow: ellipsis;
}

.kpi__hint {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
  text-align: right;
  min-height: 14px;
}

.kpi__skeleton {
  padding: var(--sm-space-1) 0;
}
</style>
