/** 统计头：样本量与分位数，始终附带口径说明。 */

<script setup lang="ts">
withDefaults(
  defineProps<{
    /** 左到右渲染的统计单元格。 */
    items: Array<{ label: string; value: string; hint?: string }>
    /** 样本量、覆盖率、算法版本与排除项的脚注。 */
    footnote?: string
    /** 统计加载中显示骨架。 */
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
  padding: 0 var(--sm-space-3);
  border-left: 1px solid var(--sm-border);
}

.stat-header__cell:first-child {
  padding-left: 0;
  border-left: 0;
}

.stat-header__label {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
  letter-spacing: 0.01em;
}

.stat-header__value {
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-xl);
  font-weight: var(--sm-fw-semibold);
  text-align: right;
  line-height: var(--sm-lh-tight);
  letter-spacing: -0.01em;
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

@media (max-width: 640px) {
  .stat-header__grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    row-gap: var(--sm-space-3);
  }

  .stat-header__cell:nth-child(odd) {
    padding-left: 0;
    border-left: 0;
  }
}
</style>
