/**
 * 球员价值散点：年龄 × 身价，颜色与大小反映当前能力/潜力。
 * 只展示后端返回的身价非空球员；缺失身价不会被补成 0。
 */

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { asApiError, type ApiError } from '../api/client'
import { getValueScatter } from '../api/visualization'
import type { ValueScatterResponse } from '../types/visualization'
import { buildValueScatter } from '../utils/chart'
import { formatInt } from '../utils/format'
import ChartCard from './ChartCard.vue'
import EChart from './EChart.vue'
import ErrorState from './ErrorState.vue'

const props = defineProps<{ saveId: number | null; clubId?: number | null }>()

const router = useRouter()
const data = ref<ValueScatterResponse | null>(null)
const loading = ref(false)
const error = ref<ApiError | null>(null)
let seq = 0

const option = computed(() => buildValueScatter(data.value?.points ?? []))

const footnote = computed(() => {
  const payload = data.value
  if (!payload) return ''
  return `共 ${formatInt(payload.total)} 名球员，其中 ${formatInt(payload.with_value)} 名有身价；本次绘制 ${formatInt(payload.returned)} 个点。${payload.note}`
})

async function load(): Promise<void> {
  const current = ++seq
  loading.value = true
  error.value = null
  try {
    const response = await getValueScatter(props.saveId, props.clubId ?? undefined)
    if (current !== seq) return
    data.value = response
  } catch (caught) {
    if (current !== seq) return
    error.value = asApiError(caught)
    data.value = null
  } finally {
    if (current === seq) loading.value = false
  }
}

/** 点击散点跳到球员详情；没有实例 ID 时忽略。 */
function onClick(payload: unknown): void {
  const params = payload as { data?: unknown }
  const values = Array.isArray(params?.data) ? params.data : []
  const instanceId = values[5]
  if (typeof instanceId === 'number') void router.push(`/players/${instanceId}`)
}

watch(() => [props.saveId, props.clubId], load, { immediate: true })
</script>

<template>
  <ChartCard
    title="球员价值分布"
    subtitle="横轴年龄，纵轴身价；点越大、越亮表示当前能力越高"
    :loading="loading && !data"
    :empty="!loading && (!data || data.with_value === 0)"
    empty-title="暂无身价数据"
    empty-description="当前存档的球员身价为空，或尚未导入包含身价的扫描数据。缺失身价不会被当作 0。"
    :footnote="footnote"
  >
    <ErrorState v-if="error" :error="error" compact title="价值分布加载失败" @retry="load" />
    <EChart v-else :option="option" height="300px" aria-label="球员年龄与身价散点图" @chart-click="onClick" />
  </ChartCard>
</template>
