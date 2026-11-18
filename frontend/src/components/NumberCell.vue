/**
 * Null-safe numeric cell: right aligned, tabular figures, `—` for unknown values.
 * The full precision value is exposed through `title` for verification.
 */

<script setup lang="ts">
import { computed } from 'vue'
import {
  formatDecimal,
  formatInt,
  formatMoney,
  formatMoneyExact,
  formatPercent,
  formatSignedMoney,
} from '../utils/format'

type NumberKind = 'int' | 'decimal' | 'money' | 'percent' | 'signed-money'

const props = withDefaults(
  defineProps<{
    /** Value from the API; `null` renders `—`. */
    value: number | null | undefined
    /** Formatting family. */
    kind?: NumberKind
    /** Currency code used only in the exact-value tooltip. */
    currency?: string | null
    /** Fraction digits for decimal/percent formats. */
    digits?: number
    /** Optional unit suffix, for example `个月`. */
    unit?: string
  }>(),
  { kind: 'int', currency: null, digits: undefined, unit: undefined },
)

const absent = computed(() => props.value === null || props.value === undefined || Number.isNaN(props.value))

const text = computed(() => {
  switch (props.kind) {
    case 'money':
      return formatMoney(props.value)
    case 'signed-money':
      return formatSignedMoney(props.value)
    case 'percent':
      return formatPercent(props.value, props.digits ?? 1)
    case 'decimal':
      return formatDecimal(props.value, props.digits ?? 2)
    default:
      return formatInt(props.value)
  }
})

/** Exact value for the hover tooltip, so compact 万/亿 text stays verifiable. */
const title = computed(() => {
  if (absent.value) return '无数据（API 返回 null）'
  if (props.kind === 'money' || props.kind === 'signed-money') {
    return formatMoneyExact(props.value, props.currency)
  }
  return text.value
})
</script>

<template>
  <span class="sm-num" :class="{ 'sm-null': absent }" :title="title">
    {{ text }}<span v-if="unit && !absent" class="sm-num__unit">{{ unit }}</span>
  </span>
</template>

<style scoped>
.sm-num__unit {
  margin-left: 2px;
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}
</style>
