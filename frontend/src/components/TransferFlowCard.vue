/**
 * 转会资金流向：按币种分别展示买入、卖出、租借收支与净支出。
 * 只统计已完成交易；未完成、传闻与附加条款不进入金额。
 */

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { asApiError, type ApiError } from '../api/client'
import { getTransferFlow } from '../api/visualization'
import type { TransferFlowResponse, TransferFlowBucket } from '../types/visualization'
import { buildTransferFlow } from '../utils/chart'
import { formatInt } from '../utils/format'
import ChartCard from './ChartCard.vue'
import EChart from './EChart.vue'
import EmptyState from './EmptyState.vue'
import ErrorState from './ErrorState.vue'
import LoadingBlock from './LoadingBlock.vue'
import SectionCard from './SectionCard.vue'

const props = defineProps<{ saveId: number | null }>()

const data = ref<TransferFlowResponse | null>(null)
const loading = ref(false)
const error = ref<ApiError | null>(null)
let seq = 0

const buckets = computed(() => data.value?.currencies ?? [])

const excludedText = computed(() => {
  const excluded = data.value?.excluded ?? {}
  const entries = Object.entries(excluded).filter(([, count]) => count > 0)
  if (entries.length === 0) return ''
  const labels: Record<string, string> = { pending: '待完成', future: '未来生效', cancelled: '已取消', failed: '失败' }
  return entries.map(([status, count]) => `${labels[status] ?? status} ${formatInt(count)} 笔`).join(' · ')
})

async function load(): Promise<void> {
  const current = ++seq
  loading.value = true
  error.value = null
  try {
    const response = await getTransferFlow(props.saveId)
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

function countsText(bucket: TransferFlowBucket): string {
  const counts = bucket.counts
  const parts = [
    `买入 ${formatInt(counts.permanent_buy)} 笔`,
    `卖出 ${formatInt(counts.permanent_sell)} 笔`,
    `租入 ${formatInt(counts.loan_in)} 笔`,
    `租出 ${formatInt(counts.loan_out)} 笔`,
    `自由转会 ${formatInt(counts.free)} 笔`,
  ]
  if (bucket.unknown_fee > 0) parts.push(`费用未知 ${formatInt(bucket.unknown_fee)} 笔`)
  return parts.join(' · ')
}

watch(() => props.saveId, load, { immediate: true })
</script>

<template>
  <SectionCard
    title="转会资金流向"
    subtitle="按币种分开统计，只计入已完成交易；租借费用单列"
  >
    <LoadingBlock v-if="loading && !data" :rows="3" compact label="正在汇总转会资金" />
    <ErrorState v-else-if="error" :error="error" compact title="资金流向加载失败" @retry="load" />
    <EmptyState
      v-else-if="buckets.length === 0"
      title="暂无资金流向"
      :description="data?.note || '该存档没有可用于统计的已完成交易。'"
      compact
    />
    <div v-else class="flow-grid">
      <ChartCard
        v-for="bucket in buckets"
        :key="bucket.currency"
        :title="`资金流向 · ${bucket.currency}`"
        :subtitle="data?.club ? `视角：${data.club.name}` : '全部俱乐部'"
        :footnote="`${countsText(bucket)}${excludedText ? ` · 未计入：${excludedText}` : ''}`"
      >
        <EChart
          :option="buildTransferFlow(bucket)"
          height="260px"
          :aria-label="`${bucket.currency} 币种的转会资金流向`"
        />
      </ChartCard>
    </div>
    <template #footer>{{ data?.note }}</template>
  </SectionCard>
</template>

<style scoped>
.flow-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
  gap: var(--sm-space-3);
}
</style>
