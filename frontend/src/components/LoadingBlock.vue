/** Loading skeleton with an accessible label. */

<script setup lang="ts">
withDefaults(
  defineProps<{
    /** Skeleton rows. */
    rows?: number
    /** Accessible description read by assistive technology. */
    label?: string
    /** Hide the label line above the skeleton. */
    compact?: boolean
  }>(),
  { rows: 5, label: '正在加载数据', compact: false },
)
</script>

<template>
  <div class="loading-block" role="status" :aria-label="label">
    <span v-if="!compact" class="loading-block__label">{{ label }}</span>
    <el-skeleton :rows="rows" animated />
  </div>
</template>

<style scoped>
.loading-block {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-2);
  padding: var(--sm-space-2) 0;
}

.loading-block__label {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-xs);
}
</style>
