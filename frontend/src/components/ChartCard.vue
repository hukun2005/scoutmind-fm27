/** Chart container: loads, empties and footnotes handled outside the chart math. */

<script setup lang="ts">
import EmptyState from './EmptyState.vue'
import LoadingBlock from './LoadingBlock.vue'

withDefaults(
  defineProps<{
    /** Chart title. */
    title: string
    /** Explanation of the metric and its unit. */
    subtitle?: string
    /** Skeleton row count while data loads. */
    loadingRows?: number
    /** Whether data is currently loading. */
    loading?: boolean
    /** Render the empty state instead of the chart slot. */
    empty?: boolean
    /** Empty-state heading. */
    emptyTitle?: string
    /** Empty-state explanation, including which filter produced no data. */
    emptyDescription?: string
    /** Visual tone of the empty state; `insufficient` marks a sample-size refusal. */
    emptyVariant?: 'empty' | 'insufficient' | 'error'
    /** Sample size / coverage / algorithm version line. */
    footnote?: string
  }>(),
  {
    subtitle: '',
    loadingRows: 6,
    loading: false,
    empty: false,
    emptyTitle: '暂无可用数据',
    emptyDescription: '',
    emptyVariant: 'empty',
    footnote: '',
  },
)
</script>

<template>
  <section class="chart-card">
    <header class="chart-card__head">
      <div class="chart-card__titles">
        <h2 class="chart-card__title">{{ title }}</h2>
        <p v-if="subtitle" class="chart-card__subtitle">{{ subtitle }}</p>
      </div>
      <div v-if="$slots.actions" class="chart-card__actions">
        <slot name="actions" />
      </div>
    </header>
    <div class="chart-card__body">
      <LoadingBlock v-if="loading" :rows="loadingRows" compact label="正在加载图表数据" />
      <EmptyState
        v-else-if="empty"
        :title="emptyTitle"
        :description="emptyDescription"
        :variant="emptyVariant"
        compact
      />
      <slot v-else />
    </div>
    <p v-if="footnote" class="chart-card__footnote">{{ footnote }}</p>
  </section>
</template>

<style scoped>
.chart-card {
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: var(--sm-surface);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-lg);
  box-shadow: var(--sm-shadow-1);
}

.chart-card__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--sm-space-3);
  padding: var(--sm-space-3) var(--sm-space-4) 0;
}

.chart-card__titles {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.chart-card__title {
  color: var(--sm-text);
  font-size: var(--sm-fs-md);
  font-weight: var(--sm-fw-semibold);
}

.chart-card__subtitle {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-xs);
}

.chart-card__actions {
  display: flex;
  align-items: center;
  gap: var(--sm-space-2);
}

.chart-card__body {
  padding: var(--sm-space-2) var(--sm-space-3) var(--sm-space-3);
  min-width: 0;
}

.chart-card__footnote {
  padding: 0 var(--sm-space-4) var(--sm-space-3);
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
  line-height: 1.5;
}
</style>
