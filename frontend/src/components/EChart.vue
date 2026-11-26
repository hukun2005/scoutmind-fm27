/** Reusable ECharts host: init once, follow `option` changes, resize with the container. */

<script setup lang="ts">
import * as echarts from 'echarts'
import type { EChartsOption } from 'echarts'
import { onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'

const emit = defineEmits<{ (event: 'chart-click', payload: unknown): void }>()

const props = withDefaults(
  defineProps<{
    /** Complete ECharts option; rebuilt by the caller from API data. */
    option: EChartsOption
    /** CSS height of the chart host. */
    height?: string
    /** Accessible description of what the chart shows. */
    ariaLabel?: string
  }>(),
  { height: '260px', ariaLabel: '统计图表' },
)

const host = ref<HTMLDivElement | null>(null)
const chart = shallowRef<echarts.ECharts | null>(null)
let observer: ResizeObserver | null = null

/** Apply the current option; `notMerge` prevents stale series from previous data. */
function render(): void {
  if (!chart.value) return
  chart.value.setOption(props.option, { notMerge: true })
  // ECharts generates an aria description from the series data (accessibility baseline).
  chart.value.setOption({ aria: { enabled: true } })
}

onMounted(() => {
  if (!host.value) return
  chart.value = echarts.init(host.value, undefined, { renderer: 'canvas' })
  chart.value.on('click', (params) => emit('chart-click', params))
  render()
  observer = new ResizeObserver(() => {
    chart.value?.resize()
  })
  observer.observe(host.value)
})

onBeforeUnmount(() => {
  observer?.disconnect()
  observer = null
  chart.value?.dispose()
  chart.value = null
})

watch(
  () => props.option,
  () => {
    render()
  },
  { deep: true },
)
</script>

<template>
  <div
    ref="host"
    class="sm-chart"
    :style="{ height }"
    role="img"
    :aria-label="ariaLabel"
  />
</template>

<style scoped>
.sm-chart {
  width: 100%;
  min-width: 0;
}
</style>
