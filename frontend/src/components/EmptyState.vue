/** Empty / insufficient / error placeholder. Never leaves a blank region. */

<script setup lang="ts">
withDefaults(
  defineProps<{
    /** Primary message, for example `没有符合筛选条件的球员`. */
    title: string
    /** Why the region is empty and what the user can do next. */
    description?: string
    /** Visual tone; `insufficient` marks an explicit sample-size refusal. */
    variant?: 'empty' | 'error' | 'insufficient'
    /** Compact variant for use inside tables. */
    compact?: boolean
  }>(),
  { description: '', variant: 'empty', compact: false },
)
</script>

<template>
  <div class="empty-state" :class="[`empty-state--${variant}`, { 'empty-state--compact': compact }]">
    <div class="empty-state__marker" aria-hidden="true" />
    <div class="empty-state__body">
      <p class="empty-state__title">{{ title }}</p>
      <p v-if="description" class="empty-state__description">{{ description }}</p>
      <div v-if="$slots.default" class="empty-state__actions">
        <slot />
      </div>
    </div>
  </div>
</template>

<style scoped>
.empty-state {
  display: flex;
  align-items: flex-start;
  gap: var(--sm-space-3);
  padding: var(--sm-space-5) var(--sm-space-4);
  border: 1px dashed var(--sm-border-strong);
  border-radius: var(--sm-radius-md);
  background: var(--sm-surface-2);
}

.empty-state--compact {
  padding: var(--sm-space-3);
  border-style: dashed;
}

.empty-state--error {
  border-color: rgba(179, 52, 42, 0.4);
  background: var(--sm-danger-weak);
}

.empty-state--insufficient {
  border-color: rgba(154, 95, 18, 0.4);
  background: var(--sm-warn-weak);
}

.empty-state__marker {
  width: 3px;
  align-self: stretch;
  border-radius: 2px;
  background: var(--sm-border-strong);
}

.empty-state--error .empty-state__marker {
  background: var(--sm-danger);
}

.empty-state--insufficient .empty-state__marker {
  background: #c08a2e;
}

.empty-state__body {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-1);
  min-width: 0;
}

.empty-state__title {
  color: var(--sm-text);
  font-size: var(--sm-fs-sm);
  font-weight: var(--sm-fw-medium);
}

.empty-state__description {
  color: var(--sm-text-2);
  font-size: var(--sm-fs-xs);
  line-height: 1.6;
}

.empty-state__actions {
  display: flex;
  gap: var(--sm-space-2);
  margin-top: var(--sm-space-2);
  flex-wrap: wrap;
}
</style>
