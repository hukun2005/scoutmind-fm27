/** Coverage bar: field coverage ratio with an explicit unknown state. */

<script setup lang="ts">
import { computed } from 'vue'
import { EMPTY, formatPercent, toPercentWidth } from '../utils/format'

const props = withDefaults(
  defineProps<{
    /** Human label of the covered field. */
    label: string
    /** Ratio in `[0, 1]`, or `null` when the backend reports no coverage. */
    value: number | null | undefined
    /** Explanation shown under the bar. */
    hint?: string
    /** Compact row height for dense panels. */
    dense?: boolean
  }>(),
  { hint: '', dense: false },
)

const absent = computed(() => props.value === null || props.value === undefined)
const width = computed(() => toPercentWidth(props.value))
const tone = computed(() => {
  const value = props.value ?? 0
  if (value >= 0.9) return 'good'
  if (value >= 0.6) return 'mid'
  return 'low'
})
</script>

<template>
  <div class="coverage" :class="{ 'coverage--dense': dense }">
    <div class="coverage__head">
      <span class="coverage__label">{{ label }}</span>
      <span
        class="coverage__value"
        :class="{ 'sm-null': absent }"
        role="progressbar"
        :aria-valuemin="0"
        :aria-valuemax="100"
        :aria-valuenow="absent ? 0 : Math.round(width)"
        :aria-label="`${label}：${absent ? '无数据' : formatPercent(value)}`"
      >
        {{ absent ? EMPTY : formatPercent(value) }}
      </span>
    </div>
    <div class="coverage__track" aria-hidden="true">
      <div class="coverage__fill" :class="`coverage__fill--${tone}`" :style="{ width: `${width}%` }" />
    </div>
    <p v-if="hint" class="coverage__hint">{{ hint }}</p>
  </div>
</template>

<style scoped>
.coverage {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-1);
  min-width: 0;
}

.coverage__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--sm-space-2);
}

.coverage__label {
  color: var(--sm-text-2);
  font-size: var(--sm-fs-xs);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.coverage__value {
  color: var(--sm-text);
  font-size: var(--sm-fs-xs);
  font-variant-numeric: tabular-nums;
  font-weight: var(--sm-fw-medium);
}

.coverage__track {
  height: 6px;
  background: var(--sm-border-subtle);
  border-radius: var(--sm-radius-pill);
  overflow: hidden;
  box-shadow: inset 0 0 0 1px rgba(23, 32, 51, 0.04);
}

.coverage--dense .coverage__track {
  height: 4px;
}

.coverage__fill {
  height: 100%;
  border-radius: var(--sm-radius-pill);
  transition: width var(--sm-dur-3) var(--sm-ease-out);
}

.coverage__fill--good {
  background: linear-gradient(90deg, #16865b, #3aa87a);
}

.coverage__fill--mid {
  background: linear-gradient(90deg, #b7791f, #cc9a57);
}

.coverage__fill--low {
  background: linear-gradient(90deg, #c2414b, #d47b82);
}

.coverage__hint {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}
</style>
