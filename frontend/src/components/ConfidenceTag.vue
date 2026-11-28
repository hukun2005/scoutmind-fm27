/** Confidence tag: renders the API `confidence` label with the global semantic palette. */

<script setup lang="ts">
import { computed } from 'vue'
import AppTag from './AppTag.vue'
import { confidenceLabel } from '../utils/labels'
import type { TagTone } from '../utils/tags'

const props = withDefaults(
  defineProps<{
    /** `low` | `medium` | `high` from valuation or agent answers. */
    confidence: string | null | undefined
    /** Prefix text, for example `置信度`. */
    label?: string
    /** Hide the prefix and render only the value. */
    bare?: boolean
  }>(),
  { label: '置信度', bare: false },
)

const tone = computed<TagTone>(() => {
  if (props.confidence === 'high') return 'success'
  if (props.confidence === 'medium') return 'warning'
  if (props.confidence === 'low') return 'info'
  return 'neutral'
})

const text = computed(() => `${props.bare ? '' : `${props.label} `}${confidenceLabel(props.confidence)}`)
</script>

<template>
  <AppTag class="confidence-tag" :label="text" :tone="tone" />
</template>

<style scoped>
.confidence-tag {
  font-variant-numeric: tabular-nums;
}
</style>
