/** 页面头部：眉标、标题、来源说明、返回链接与页面级操作。 */

<script setup lang="ts">
import AppIcon from './AppIcon.vue'

withDefaults(
  defineProps<{
    /** 页面标题。 */
    title: string
    /** 一句话说明该页面回答的问题。 */
    description?: string
    /** 模块眉标（全大写英文，例如 SQUAD INTELLIGENCE）。 */
    eyebrow?: string
    /** 返回目标路由，设置后渲染返回链接。 */
    backTo?: string
    /** 返回链接文案。 */
    backLabel?: string
  }>(),
  { description: '', eyebrow: '', backTo: '', backLabel: '返回' },
)
</script>

<template>
  <header class="page-header">
    <div class="page-header__left">
      <router-link v-if="backTo" class="page-header__back" :to="backTo">
        <AppIcon name="back" :size="14" />
        {{ backLabel }}
      </router-link>
      <span v-if="eyebrow" class="sm-eyebrow">{{ eyebrow }}</span>
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
  width: fit-content;
  color: var(--sm-text-2);
  font-size: var(--sm-fs-xs);
}

.page-header__back:hover {
  color: var(--sm-accent-cyan);
  text-decoration: none;
}

.page-header__title {
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-2xl);
  font-weight: var(--sm-fw-semibold);
  letter-spacing: -0.015em;
  line-height: var(--sm-lh-tight);
}

.page-header__description {
  max-width: 88ch;
  color: var(--sm-text-2);
  font-size: var(--sm-fs-sm);
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

@media (max-width: 720px) {
  .page-header {
    flex-direction: column;
    gap: var(--sm-space-3);
  }

  .page-header__title {
    font-size: var(--sm-fs-xl);
  }

  .page-header__actions {
    width: 100%;
    justify-content: flex-start;
  }
}
</style>
