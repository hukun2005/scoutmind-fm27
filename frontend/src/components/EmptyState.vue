/** 空 / 样本不足 / 错误占位。任何区域都不留空白。 */

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    /** 主信息，例如「没有符合筛选条件的球员」。 */
    title: string
    /** 为什么为空、下一步可以做什么。 */
    description?: string
    /** 兼容旧调用：与 description 同义，description 优先。 */
    hint?: string
    /** 视觉语气；`insufficient` 表示样本量不足的明确拒绝。 */
    variant?: 'empty' | 'error' | 'insufficient'
    /** 表格内使用的紧凑形态。 */
    compact?: boolean
  }>(),
  { description: '', hint: '', variant: 'empty', compact: false },
)

/** 说明文案：新代码用 description，旧页面用 hint。 */
const descriptionText = computed(() => props.description || props.hint)
</script>

<template>
  <div class="empty-state" :class="[`empty-state--${variant}`, { 'empty-state--compact': compact }]">
    <span class="empty-state__orb" aria-hidden="true">
      <i />
    </span>
    <div class="empty-state__body">
      <p class="empty-state__title">{{ title }}</p>
      <p v-if="descriptionText" class="empty-state__description">{{ descriptionText }}</p>
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
  background:
    radial-gradient(320px 120px at 0% 0%, rgba(53, 106, 230, 0.05), transparent 70%),
    var(--sm-surface-2);
}

.empty-state--compact {
  padding: var(--sm-space-3);
}

.empty-state--error {
  border-color: rgba(251, 113, 133, 0.4);
  background: var(--sm-danger-weak);
}

.empty-state--insufficient {
  border-color: rgba(245, 181, 68, 0.4);
  background: var(--sm-warn-weak);
}

/* 空心圆环 + 中心点：比纯色竖条更像「信号缺失」而不是报错。 */
.empty-state__orb {
  position: relative;
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  flex: 0 0 auto;
  border: 1px solid var(--sm-border-strong);
  border-radius: 50%;
  background: var(--sm-surface-2);
}

.empty-state__orb::before {
  content: '';
  position: absolute;
  inset: 6px;
  border: 1px dashed var(--sm-border-strong);
  border-radius: 50%;
}

.empty-state__orb i {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--sm-text-3);
}

.empty-state--error .empty-state__orb {
  border-color: rgba(251, 113, 133, 0.5);
}

.empty-state--error .empty-state__orb i {
  background: var(--sm-danger);
}

.empty-state--insufficient .empty-state__orb {
  border-color: rgba(245, 181, 68, 0.5);
}

.empty-state--insufficient .empty-state__orb i {
  background: var(--sm-warn);
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
