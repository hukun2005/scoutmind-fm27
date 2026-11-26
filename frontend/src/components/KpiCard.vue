/** KPI 指标卡：指挥中心与各分析页共用的顶部数字卡。 */

<script setup lang="ts">
withDefaults(
  defineProps<{
    /** 指标名称。 */
    label: string
    /** 预格式化后的数值；不可用时为 `—`。 */
    value: string
    /** 数值下方的补充说明。 */
    hint?: string
    /** 需要关注时的高亮色。 */
    tone?: 'default' | 'accent' | 'warn' | 'danger'
    /** 用骨架替代数值。 */
    loading?: boolean
    /** 可选路由：整张卡片可点击。 */
    to?: string
    /** 指标单位或前缀（例如 €、%）。 */
    unit?: string
  }>(),
  { hint: '', tone: 'default', loading: false, to: '', unit: '' },
)
</script>

<template>
  <div class="kpi" :class="[`kpi--${tone}`, { 'kpi--link': Boolean(to) }]">
    <div class="kpi__body">
      <div class="kpi__label">{{ label }}</div>
      <el-skeleton v-if="loading" :rows="1" animated class="kpi__skeleton" />
      <div v-else class="kpi__value sm-num" :title="`${value}${unit}`">
        <span class="kpi__number">{{ value }}</span>
        <span v-if="unit" class="kpi__unit">{{ unit }}</span>
      </div>
      <div v-if="hint" class="kpi__hint">{{ hint }}</div>
      <slot />
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
  padding: var(--sm-space-3) var(--sm-space-4) var(--sm-space-3);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-lg);
  background:
    linear-gradient(160deg, rgba(24, 41, 65, 0.55) 0%, rgba(9, 18, 32, 0.92) 62%),
    var(--sm-surface);
  color: inherit;
  box-shadow: var(--sm-shadow-1);
  transition:
    border-color var(--sm-dur-2) var(--sm-ease-out),
    box-shadow var(--sm-dur-2) var(--sm-ease-out),
    transform var(--sm-dur-2) var(--sm-ease-out);
}

/* 顶部一道强调光线，颜色随 tone 变化。 */
.kpi::before {
  content: '';
  position: absolute;
  inset: 0 0 auto;
  height: 2px;
  border-radius: var(--sm-radius-lg) var(--sm-radius-lg) 0 0;
  background: linear-gradient(90deg, rgba(122, 162, 220, 0.35), rgba(122, 162, 220, 0.05));
  opacity: 0.7;
}

.kpi--accent::before {
  background: linear-gradient(90deg, var(--sm-accent-cyan), var(--sm-accent-blue) 55%, transparent);
  opacity: 1;
}

.kpi--warn::before {
  background: linear-gradient(90deg, var(--sm-status-warning), transparent);
  opacity: 1;
}

.kpi--danger::before {
  background: linear-gradient(90deg, var(--sm-status-danger), transparent);
  opacity: 1;
}

.kpi--link:hover {
  border-color: var(--sm-border-glow);
  box-shadow: var(--sm-glow-cyan);
  transform: translateY(-2px);
}

/* 拉伸链接：整张卡片可点击，锚点本身是键盘焦点目标。 */
.kpi__stretch {
  position: absolute;
  inset: 0;
  z-index: 1;
  border-radius: var(--sm-radius-lg);
}

.kpi__stretch:focus-visible {
  outline: 2px solid var(--sm-accent-cyan);
  outline-offset: 2px;
}

.kpi__body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.kpi__label {
  color: var(--sm-text-2);
  font-size: var(--sm-fs-xs);
  letter-spacing: 0.01em;
}

.kpi__value {
  display: flex;
  align-items: baseline;
  justify-content: flex-end;
  gap: 4px;
  min-width: 0;
  line-height: var(--sm-lh-tight);
}

.kpi__number {
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-2xl);
  font-weight: var(--sm-fw-semibold);
  letter-spacing: -0.02em;
  overflow: hidden;
  text-overflow: ellipsis;
}

.kpi--accent .kpi__number {
  background: var(--sm-gradient-text);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}

.kpi__unit {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-xs);
}

.kpi__hint {
  min-height: 14px;
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
  text-align: right;
}

.kpi__skeleton {
  padding: var(--sm-space-1) 0;
}

@media (prefers-reduced-motion: reduce) {
  .kpi--link:hover {
    transform: none;
  }
}
</style>
