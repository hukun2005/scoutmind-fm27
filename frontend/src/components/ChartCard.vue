/** 图表容器：加载、空数据与脚注在图表计算之外统一处理。 */

<script setup lang="ts">
import EmptyState from './EmptyState.vue'
import LoadingBlock from './LoadingBlock.vue'

withDefaults(
  defineProps<{
    /** 图表标题。 */
    title: string
    /** 指标口径与单位说明。 */
    subtitle?: string
    /** 加载时的骨架行数。 */
    loadingRows?: number
    /** 是否正在加载。 */
    loading?: boolean
    /** 用空状态替代图表插槽。 */
    empty?: boolean
    /** 空状态标题。 */
    emptyTitle?: string
    /** 空状态说明：哪一个筛选条件导致无数据。 */
    emptyDescription?: string
    /** 空状态语气；`insufficient` 表示样本量不足的明确拒绝。 */
    emptyVariant?: 'empty' | 'insufficient' | 'error'
    /** 样本量 / 覆盖率 / 算法版本脚注。 */
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
  position: relative;
  display: flex;
  flex-direction: column;
  min-width: 0;
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-lg);
  background: var(--sm-surface);
  box-shadow: var(--sm-shadow-1);
}

.chart-card::before {
  content: '';
  position: absolute;
  inset: 0 0 auto;
  height: 1px;
  border-radius: var(--sm-radius-lg) var(--sm-radius-lg) 0 0;
  background: linear-gradient(90deg, rgba(53, 106, 230, 0.35), rgba(53, 106, 230, 0.08) 42%, transparent);
  opacity: 0.55;
  pointer-events: none;
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
  display: flex;
  align-items: center;
  gap: var(--sm-space-2);
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-md);
  font-weight: var(--sm-fw-semibold);
  letter-spacing: 0.01em;
}

/* 标题前的渐变小方块，统一所有图表的视觉锚点。 */
.chart-card__title::before {
  content: '';
  width: 3px;
  height: 13px;
  border-radius: 2px;
  background: var(--sm-gradient-accent);
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
