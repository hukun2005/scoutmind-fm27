/** Confidence tag: renders the API `confidence` label with a colour band. */

<script setup lang="ts">
import { computed } from 'vue'
import { confidenceLabel } from '../utils/labels'

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

type TagType = 'success' | 'warning' | 'info'

const tagType = computed<TagType>(() => {
  switch (props.confidence) {
    case 'high':
      return 'success'
    case 'medium':
      return 'warning'
    default:
      return 'info'
  }
})

const text = computed(() => confidenceLabel(props.confidence))
const absent = computed(() => !props.confidence)
</script>

<template>
  <el-tag class="confidence-tag" :type="tagType" size="small" disable-transitions>
    <span v-if="!bare">{{ label }} </span>
    <span :class="{ 'sm-null': absent }">{{ text }}</span>
  </el-tag>
</template>

<style scoped>
.confidence-tag {
  font-variant-numeric: tabular-nums;
}
</style>
