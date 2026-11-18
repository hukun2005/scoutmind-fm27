/** Statistics header: sample size and quantiles, always with their provenance. */

<script setup lang="ts">
withDefaults(
  defineProps<{
    /** Statistic cells rendered left to right. */
    items: Array<{ label: string; value: string; hint?: string }>
    /** Footnote covering sample size, coverage, algorithm version and exclusions. */
    footnote?: string
    /** Show skeletons while statistics load. */
    loading?: boolean
  }>(),
  { footnote: '', loading: false },
)
</script>

<template>
  <div class="stat-header">
    <div class="stat-header__grid">
      <div v-for="item in items" :key="item.label" class="stat-header__cell">
        <span class="stat-header__label">{{ item.label }}</span>
        <el-skeleton v-if="loading" :rows="1" animated class="stat-header__skeleton" />
        <span v-else class="stat-header__value sm-num" :title="item.value">{{ item.value }}</span>
        <span v-if="item.hint" class="stat-header__hint">{{ item.hint }}</span>
      </div>
    </div>
    <p v-if="footnote" class="stat-header__footnote">{{ footnote }}</p>
    <p v-if="$slots.meta" class="stat-header__footnote"><slot name="meta" /></p>
  </div>
</template>

<style scoped>
.stat-header {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-2);
}

.stat-header__grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(132px, 1fr));
  gap: var(--sm-space-3);
}

.stat-header__cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  padding-right: var(--sm-space-3);
  border-right: 1px solid var(--sm-border);
}

.stat-header__cell:last-child {
  border-right: 0;
  padding-right: 0;
}

.stat-header__label {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}

.stat-header__value {
  color: var(--sm-text);
  font-size: var(--sm-fs-xl);
  font-weight: var(--sm-fw-semibold);
  text-align: right;
  line-height: var(--sm-lh-tight);
}

.stat-header__hint {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
  text-align: right;
}

.stat-header__skeleton {
  padding: var(--sm-space-1) 0;
}

.stat-header__footnote {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
  line-height: 1.5;
}
</style>
