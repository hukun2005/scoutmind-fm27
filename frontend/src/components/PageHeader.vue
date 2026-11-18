/** View header: title, provenance line, back navigation and page-level actions. */

<script setup lang="ts">
import AppIcon from './AppIcon.vue'

withDefaults(
  defineProps<{
    /** Page title. */
    title: string
    /** One-line description of what the page answers. */
    description?: string
    /** Route to return to, rendering a back link. */
    backTo?: string
    /** Back link label. */
    backLabel?: string
  }>(),
  { description: '', backTo: '', backLabel: '返回' },
)
</script>

<template>
  <header class="page-header">
    <div class="page-header__left">
      <router-link v-if="backTo" class="page-header__back" :to="backTo">
        <AppIcon name="back" :size="14" />
        {{ backLabel }}
      </router-link>
      <h1 class="page-header__title">{{ title }}</h1>
      <p v-if="description" class="page-header__description">{{ description }}</p>
      <div v-if="$slots.meta" class="page-header__meta">
        <slot name="meta" />
      </div>
    </div>
    <div v-if="$slots.actions" class="page-header__actions">
      <slot name="actions" />
    </div>
  </header>
</template>

<style scoped>
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--sm-space-4);
  padding-bottom: var(--sm-space-1);
}

.page-header__left {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-1);
  min-width: 0;
}

.page-header__back {
  display: inline-flex;
  align-items: center;
  gap: var(--sm-space-1);
  color: var(--sm-text-2);
  font-size: var(--sm-fs-xs);
  width: fit-content;
}

.page-header__back:hover {
  color: var(--sm-accent);
  text-decoration: none;
}

.page-header__title {
  color: var(--sm-text);
  font-size: var(--sm-fs-xl);
  font-weight: var(--sm-fw-semibold);
  letter-spacing: -0.01em;
}

.page-header__description {
  color: var(--sm-text-2);
  font-size: var(--sm-fs-sm);
  max-width: 88ch;
}

.page-header__meta {
  display: flex;
  align-items: center;
  gap: var(--sm-space-2);
  flex-wrap: wrap;
  margin-top: var(--sm-space-1);
}

.page-header__actions {
  display: flex;
  align-items: center;
  gap: var(--sm-space-2);
  flex-wrap: wrap;
  justify-content: flex-end;
}
</style>
