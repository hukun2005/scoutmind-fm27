/** 1–20 attribute bar used by the player detail attribute groups. */

<script setup lang="ts">
import { computed } from 'vue'
import { EMPTY } from '../utils/format'

const props = withDefaults(
  defineProps<{
    /** Attribute name in Chinese. */
    label: string
    /** Attribute value on the 1–20 scale. */
    value: number | null | undefined
    /** Show the raw key next to the label for traceability. */
    code?: string
  }>(),
  { code: '' },
)

const SEGMENTS = 20

const absent = computed(() => props.value === null || props.value === undefined)
const filled = computed(() => Math.max(0, Math.min(SEGMENTS, Math.round(props.value ?? 0))))

const band = computed(() => {
  const value = props.value ?? 0
  if (value >= 16) return 'elite'
  if (value >= 13) return 'good'
  if (value >= 9) return 'average'
  return 'weak'
})
</script>

<template>
  <div class="attr-bar" :class="[`attr-bar--${band}`, { 'attr-bar--absent': absent }]">
    <div class="attr-bar__head">
      <span class="attr-bar__label" :title="code ? `${label}（${code}）` : label">{{ label }}</span>
      <span class="attr-bar__value" :class="{ 'sm-null': absent }">{{ absent ? EMPTY : filled }}</span>
    </div>
    <div class="attr-bar__segments" aria-hidden="true">
      <span
        v-for="index in SEGMENTS"
        :key="index"
        class="attr-bar__segment"
        :class="{ 'attr-bar__segment--on': !absent && index <= filled }"
      />
    </div>
  </div>
</template>

<style scoped>
.attr-bar {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.attr-bar__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--sm-space-2);
}

.attr-bar__label {
  color: var(--sm-text-2);
  font-size: var(--sm-fs-xs);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.attr-bar__value {
  color: var(--sm-text);
  font-size: var(--sm-fs-xs);
  font-variant-numeric: tabular-nums;
  font-weight: var(--sm-fw-medium);
}

.attr-bar__segments {
  display: flex;
  gap: 2px;
}

.attr-bar__segment {
  flex: 1 1 auto;
  height: 5px;
  border-radius: 2px;
  background: #e7ecf2;
}

.attr-bar--elite .attr-bar__segment--on {
  background: linear-gradient(90deg, #16a36a, #34c58b);
}

.attr-bar--good .attr-bar__segment--on {
  background: linear-gradient(90deg, #356ae6, #5b8def);
}

.attr-bar--average .attr-bar__segment--on {
  background: linear-gradient(90deg, #d99124, #e6ad4d);
}

.attr-bar--weak .attr-bar__segment--on {
  background: linear-gradient(90deg, #dc5b5b, #e88a8a);
}

.attr-bar--absent .attr-bar__segments {
  opacity: 0.4;
}
</style>
