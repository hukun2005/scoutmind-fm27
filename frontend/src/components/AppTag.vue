/**
 * 统一标签组件。
 *
 * - 文案与语义色来自 `utils/tags.ts`，同一状态在任何页面都长得一样；
 * - 内部技术标签默认不渲染，只有开发者诊断区域显式设置 `allow-internal`；
 * - 始终显示文字，颜色只做辅助，不单独表达状态；
 * - 长文案省略显示，避免撑破表格与卡片布局。
 */

<script setup lang="ts">
import { computed } from 'vue'
import { resolveTag, type TagTone } from '../utils/tags'

const props = withDefaults(
  defineProps<{
    /** 原始标签文本或规范键。 */
    tag?: string | null
    /** 覆盖显示文案（例如带数量的“已确认 3”）。 */
    label?: string
    /** 覆盖语义色；不传时使用目录定义。 */
    tone?: TagTone
    /** 显示尺寸。 */
    size?: 'sm' | 'md'
    /** 所在表面：全应用统一浅色主题。 */
    surface?: 'light'
    /** 是否显示状态圆点。 */
    dot?: boolean
    /** 仅在开发者诊断区域开启：允许渲染内部技术标签。 */
    allowInternal?: boolean
  }>(),
  { tag: null, label: undefined, tone: undefined, size: 'sm', surface: 'light', dot: true, allowInternal: false },
)

const definition = computed(() => resolveTag(props.tag))
const hidden = computed(() => definition.value?.category === 'internal' && !props.allowInternal)
const text = computed(() => props.label ?? definition.value?.label ?? '')
const tone = computed<TagTone>(() => props.tone ?? definition.value?.tone ?? 'neutral')
const category = computed(() => definition.value?.category ?? 'business')
</script>

<template>
  <span
    v-if="!hidden && text"
    class="app-tag"
    :class="[`app-tag--${tone}`, `app-tag--${size}`, `app-tag--on-${surface}`]"
    :data-tag-category="category"
    :title="text"
  >
    <span v-if="dot" class="app-tag__dot" aria-hidden="true" />
    <span class="app-tag__text">{{ text }}</span>
  </span>
</template>

<style scoped>
.app-tag {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  max-width: 100%;
  border: 1px solid transparent;
  border-radius: var(--sm-radius-pill, 999px);
  font-weight: var(--sm-fw-medium, 500);
  line-height: 1.45;
  white-space: nowrap;
  vertical-align: middle;
}

.app-tag--sm {
  padding: 1px 8px;
  font-size: 11px;
}

.app-tag--md {
  padding: 2px 10px;
  font-size: 12px;
}

.app-tag__dot {
  width: 5px;
  height: 5px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: currentColor;
  opacity: 0.85;
}

.app-tag__text {
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Premium Light 表面：低饱和底色 + 深色文字 */
.app-tag--on-light.app-tag--success {
  background: #ecfdf3;
  border-color: #bbf7d0;
  color: #15803d;
}

.app-tag--on-light.app-tag--info {
  background: #eff6ff;
  border-color: #bfdbfe;
  color: #1d4ed8;
}

.app-tag--on-light.app-tag--warning {
  background: #fffbeb;
  border-color: #fde68a;
  color: #b45309;
}

.app-tag--on-light.app-tag--danger {
  background: #fef2f2;
  border-color: #fecaca;
  color: #b91c1c;
}

.app-tag--on-light.app-tag--neutral {
  background: #f1f5f9;
  border-color: #e2e8f0;
  color: #475569;
}

.app-tag--on-light.app-tag--brand {
  background: #eef2ff;
  border-color: #c7d2fe;
  color: #3730a3;
}
</style>
