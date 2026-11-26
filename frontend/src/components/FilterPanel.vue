/**
 * 筛选面板：常用条件平铺，低频条件收进「更多筛选」。
 *
 * 默认只暴露高频筛选；高级条件折叠但不删除，保持原有业务能力。
 * 插槽：
 * - 默认插槽：常用筛选（放在 .sm-filters 网格里）；
 * - `advanced`：低频筛选，默认折叠；
 * - `actions`：右侧操作（重置、刷新等）。
 */

<script setup lang="ts">
withDefaults(
  defineProps<{
    /** 面板标题，例如「筛选球员」。 */
    title?: string
    /** 标题下的一句说明。 */
    hint?: string
    /** 折叠入口文案。 */
    advancedLabel?: string
    /** 是否默认展开高级筛选。 */
    advancedOpen?: boolean
  }>(),
  { title: '筛选', hint: '', advancedLabel: '更多筛选', advancedOpen: false },
)
</script>

<template>
  <section class="filter-panel">
    <header class="filter-panel__head">
      <div class="filter-panel__titles">
        <h2 class="filter-panel__title">{{ title }}</h2>
        <p v-if="hint" class="sm-hint">{{ hint }}</p>
      </div>
      <div v-if="$slots.actions" class="filter-panel__actions">
        <slot name="actions" />
      </div>
    </header>

    <div class="sm-filters">
      <slot />
    </div>

    <details v-if="$slots.advanced" class="sm-details" :open="advancedOpen">
      <summary>{{ advancedLabel }}</summary>
      <div class="sm-details__body">
        <div class="sm-filters">
          <slot name="advanced" />
        </div>
      </div>
    </details>
  </section>
</template>

<style scoped>
.filter-panel {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-3);
  padding: var(--sm-space-4);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-lg);
  background:
    linear-gradient(170deg, rgba(20, 35, 56, 0.42) 0%, rgba(9, 18, 32, 0.9) 60%),
    var(--sm-surface);
  box-shadow: var(--sm-shadow-1);
}

.filter-panel__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--sm-space-3);
  flex-wrap: wrap;
}

.filter-panel__titles {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-1);
  min-width: 0;
}

.filter-panel__title {
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-md);
  font-weight: var(--sm-fw-semibold);
}

.filter-panel__actions {
  display: flex;
  align-items: center;
  gap: var(--sm-space-2);
  flex-wrap: wrap;
}
</style>
