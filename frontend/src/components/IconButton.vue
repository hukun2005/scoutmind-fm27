/**
 * 统一图标按钮：强制提供无障碍名称与浏览器 Tooltip。
 *
 * 视觉样式由调用方的共享类（`.icon-btn` 等）决定，本组件只收敛交互语义：
 *   - `label` 必填，同时写入 aria-label 与 title；
 *   - 有 `to` 时渲染 router-link，否则渲染 button；
 *   - 装饰性图标由子元素自行设置 aria-hidden。
 */

<script setup lang="ts">
withDefaults(
  defineProps<{
    /** 无障碍名称，也是 Tooltip 文案。 */
    label: string
    /** 传入时渲染为路由链接。 */
    to?: string
    disabled?: boolean
  }>(),
  { to: undefined, disabled: false },
)

const emit = defineEmits<{ (event: 'click', payload: MouseEvent): void }>()
</script>

<template>
  <router-link
    v-if="to"
    :to="to"
    class="sm-icon-button"
    :aria-label="label"
    :title="label"
    data-icon-button
  >
    <slot />
  </router-link>
  <button
    v-else
    type="button"
    class="sm-icon-button"
    :aria-label="label"
    :title="label"
    :disabled="disabled"
    data-icon-button
    @click="emit('click', $event)"
  >
    <slot />
  </button>
</template>

<style scoped>
.sm-icon-button {
  display: inline-grid;
  place-items: center;
  padding: 0;
  border: 0;
  background: none;
  color: inherit;
  font: inherit;
  cursor: pointer;
}

.sm-icon-button:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}
</style>
