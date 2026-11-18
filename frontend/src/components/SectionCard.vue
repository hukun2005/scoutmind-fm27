/** Section container: titled panel with actions and an optional footer. */

<script setup lang="ts">
withDefaults(
  defineProps<{
    /** Section heading; omit for an untitled panel. */
    title?: string
    /** Short explanation under the heading. */
    subtitle?: string
    /** Remove body padding (tables and charts manage their own spacing). */
    flush?: boolean
    /** Reduce vertical spacing for dense dashboards. */
    dense?: boolean
  }>(),
  { title: '', subtitle: '', flush: false, dense: false },
)
</script>

<template>
  <section class="section-card" :class="{ 'section-card--dense': dense }">
    <header v-if="title || $slots.actions" class="section-card__head">
      <div class="section-card__titles">
        <h2 v-if="title" class="section-card__title">{{ title }}</h2>
        <p v-if="subtitle" class="section-card__subtitle">{{ subtitle }}</p>
      </div>
      <div v-if="$slots.actions" class="section-card__actions">
        <slot name="actions" />
      </div>
    </header>
    <div class="section-card__body" :class="{ 'section-card__body--flush': flush }">
      <slot />
    </div>
    <footer v-if="$slots.footer" class="section-card__footer">
      <slot name="footer" />
    </footer>
  </section>
</template>

<style scoped>
.section-card {
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: var(--sm-surface);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-lg);
  box-shadow: var(--sm-shadow-1);
}

.section-card__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--sm-space-3);
  padding: var(--sm-space-3) var(--sm-space-4);
  border-bottom: 1px solid var(--sm-border);
}

.section-card--dense .section-card__head {
  padding: var(--sm-space-2) var(--sm-space-3);
}

.section-card__titles {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.section-card__title {
  color: var(--sm-text);
  font-size: var(--sm-fs-md);
  font-weight: var(--sm-fw-semibold);
}

.section-card__subtitle {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-xs);
}

.section-card__actions {
  display: flex;
  align-items: center;
  gap: var(--sm-space-2);
  flex-wrap: wrap;
  justify-content: flex-end;
}

.section-card__body {
  padding: var(--sm-space-4);
  min-width: 0;
}

.section-card--dense .section-card__body {
  padding: var(--sm-space-3);
}

.section-card__body--flush {
  padding: 0;
}

.section-card__footer {
  padding: var(--sm-space-2) var(--sm-space-4) var(--sm-space-3);
  border-top: 1px solid var(--sm-border);
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}
</style>
