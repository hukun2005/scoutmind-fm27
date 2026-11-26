/**
 * Role score badge with a data-coverage indicator.
 * A score below full coverage is still shown, but the missing-data chip makes the
 * incomplete input explicit instead of hiding it.
 */

<script setup lang="ts">
import { computed } from 'vue'
import { EMPTY, formatPercent } from '../utils/format'

const props = withDefaults(
  defineProps<{
    /** Role score from `/scouting/evaluate` or `/scouting/search`. */
    score: number | null | undefined
    /** Attribute coverage ratio behind the score. */
    coverage?: number | null
    /** Show the coverage chip when coverage is below 100%. */
    showCoverage?: boolean
    /** Visual size. */
    size?: 'sm' | 'md'
  }>(),
  { coverage: null, showCoverage: true, size: 'md' },
)

const absent = computed(() => props.score === null || props.score === undefined)

/** Colour band of the score. */
const band = computed<'high' | 'good' | 'mid' | 'low'>(() => {
  const score = props.score ?? 0
  if (score >= 80) return 'high'
  if (score >= 65) return 'good'
  if (score >= 50) return 'mid'
  return 'low'
})

/** True when the backend reported partial attribute coverage. */
const partialCoverage = computed(
  () => props.coverage !== null && props.coverage !== undefined && props.coverage < 1,
)
</script>

<template>
  <span class="score-badge" :class="[`score-badge--${band}`, `score-badge--${size}`]">
    <span class="score-badge__value" :class="{ 'sm-null': absent }" :title="absent ? '评分不可用（样本或属性缺失）' : `评分 ${score}`">
      {{ absent ? EMPTY : score?.toFixed(1) }}
    </span>
    <span
      v-if="showCoverage && partialCoverage"
      class="score-badge__coverage"
      :title="`参与计算的属性覆盖：${formatPercent(coverage)}`"
    >
      覆盖 {{ formatPercent(coverage) }}
    </span>
  </span>
</template>

<style scoped>
.score-badge {
  display: inline-flex;
  align-items: baseline;
  gap: var(--sm-space-2);
}

.score-badge__value {
  display: inline-block;
  min-width: 46px;
  padding: 1px 8px;
  border: 1px solid transparent;
  border-radius: var(--sm-radius-pill);
  font-variant-numeric: tabular-nums;
  font-weight: var(--sm-fw-semibold);
  text-align: right;
}

.score-badge--sm .score-badge__value {
  min-width: 38px;
  font-size: var(--sm-fs-xs);
}

.score-badge--high .score-badge__value {
  border-color: rgba(52, 211, 153, 0.32);
  background: var(--sm-success-weak);
  color: #6ee7b7;
}

.score-badge--good .score-badge__value {
  border-color: rgba(77, 141, 255, 0.32);
  background: var(--sm-accent-weak);
  color: #93c5fd;
}

.score-badge--mid .score-badge__value {
  border-color: rgba(245, 181, 68, 0.32);
  background: var(--sm-warn-weak);
  color: #fcd34d;
}

.score-badge--low .score-badge__value {
  border-color: rgba(122, 162, 220, 0.22);
  background: var(--sm-neutral-weak);
  color: var(--sm-neutral);
}

.score-badge__coverage {
  color: var(--sm-warn);
  font-size: var(--sm-fs-2xs);
  white-space: nowrap;
}
</style>
