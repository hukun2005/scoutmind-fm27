<script setup lang="ts">
/**
 * 球员详情抽屉（V4.0-03，Premium Light）。
 *
 * 只读取真实接口：`/players/{id}`、`/players/{id}/status` 与 `/transfers/valuation`。
 * 缺失字段显示“—/未知”，不做插值、不虚构适配度；角色适配在完整档案中计算。
 */

import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { asApiError, type ApiError } from '../api/client'
import { getPlayer } from '../api/players'
import { getPlayerStatus } from '../api/status'
import { getValuation } from '../api/transfers'
import AppIcon from './AppIcon.vue'
import AppTag from './AppTag.vue'
import type { PlayerAttribute, PlayerDetail, Valuation } from '../types/players'
import type { PlayerStatus } from '../types/status'
import { visibleTags } from '../utils/tags'
import {
  EMPTY,
  displayText,
  formatDate,
  formatDateTime,
  formatDecimal,
  formatInt,
  formatMoney,
  formatPercent,
} from '../utils/format'
import {
  attributeCategoryLabel,
  confidenceLabel,
  positionGroupLabel,
  positionLabel,
  sourceLabel,
  valuationMethodLabel,
} from '../utils/labels'

const props = defineProps<{
  instanceId: number | null
  watched: boolean
  watchPending: boolean
  compareActive: boolean
  hasPrev: boolean
  hasNext: boolean
}>()

const emit = defineEmits<{
  (event: 'close'): void
  (event: 'toggle-watch'): void
  (event: 'toggle-compare'): void
  (event: 'prev'): void
  (event: 'next'): void
}>()

const detail = ref<PlayerDetail | null>(null)
const status = ref<PlayerStatus | null>(null)
const valuation = ref<Valuation | null>(null)
const loading = ref(false)
const error = ref<ApiError | null>(null)
const showAllAttributes = ref(false)
let token = 0

/** 抽屉打开时锁定内容区滚动，关闭后恢复。 */
let scrollHost: HTMLElement | null = null
let previousOverflow = ''

watch(
  () => props.instanceId,
  (id) => {
    showAllAttributes.value = false
    if (id === null) {
      detail.value = null
      status.value = null
      valuation.value = null
      return
    }
    void load(id)
  },
  { immediate: true },
)

watch(
  () => props.instanceId !== null,
  (open) => {
    if (typeof document === 'undefined') return
    if (open) {
      scrollHost = document.querySelector('.content')
      if (scrollHost) {
        previousOverflow = scrollHost.style.overflow
        scrollHost.style.overflow = 'hidden'
      }
    } else if (scrollHost) {
      scrollHost.style.overflow = previousOverflow
      scrollHost = null
    }
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  if (scrollHost) scrollHost.style.overflow = previousOverflow
})

/** 三个接口并行读取；旧请求的回包不会写入当前球员。 */
async function load(id: number): Promise<void> {
  const current = ++token
  loading.value = true
  error.value = null
  detail.value = null
  status.value = null
  valuation.value = null
  try {
    const [profile, availability, estimate] = await Promise.allSettled([
      getPlayer(id),
      getPlayerStatus(id),
      getValuation(id),
    ])
    if (current !== token) return
    if (profile.status === 'fulfilled') detail.value = profile.value
    else {
      error.value = asApiError(profile.reason)
      return
    }
    status.value = availability.status === 'fulfilled' ? availability.value : null
    valuation.value = estimate.status === 'fulfilled' ? estimate.value : null
  } catch (caught) {
    if (current === token) error.value = asApiError(caught)
  } finally {
    if (current === token) loading.value = false
  }
}

const summary = computed(() => detail.value?.summary ?? null)

/** 副标题只拼接真实存在的字段，缺失项不显示占位符。 */
const identityLine = computed(() => {
  const parts = [positionLabel(summary.value?.position?.split(',')[0]?.trim())]
  const group = positionGroupLabel(summary.value?.position_group)
  if (group !== EMPTY) parts.push(group)
  if (summary.value?.club) parts.push(summary.value.club)
  return parts.filter((part) => part && part !== EMPTY).join(' · ')
})

const bioLine = computed(() => {
  const parts: string[] = []
  if (summary.value?.nationality) parts.push(summary.value.nationality)
  parts.push(summary.value?.age === null || summary.value?.age === undefined ? '年龄未知' : `${summary.value.age} 岁`)
  parts.push(
    summary.value?.height_cm === null || summary.value?.height_cm === undefined
      ? '身高未知'
      : `${summary.value.height_cm} cm`,
  )
  parts.push(footLabel.value)
  return parts.join(' · ')
})

const initials = computed(() => {
  const name = summary.value?.name?.trim() ?? ''
  if (!name) return EMPTY
  const parts = name.split(/\s+/).filter(Boolean)
  if (parts.length >= 2) return `${parts[0]!.charAt(0)}${parts[1]!.charAt(0)}`.toUpperCase()
  return name.slice(0, 2).toUpperCase()
})

const footLabel = computed(() => {
  const foot = summary.value?.foot
  if (!foot) return EMPTY
  return { left: '左脚', right: '右脚', both: '双脚' }[foot] ?? foot
})

/** 合同剩余月数；无日期时为 null，不按 0 处理。 */
const contractMonths = computed<number | null>(() => {
  const end = summary.value?.contract_end
  if (!end) return null
  const endAt = new Date(end).getTime()
  if (Number.isNaN(endAt)) return null
  return Math.floor((endAt - Date.now()) / (1000 * 60 * 60 * 24 * 30.44))
})

/** 属性按类别分组，保持接口顺序。 */
const attributeGroups = computed(() => {
  const groups = new Map<string, PlayerAttribute[]>()
  for (const attribute of detail.value?.attributes ?? []) {
    const key = attribute.category || 'other'
    const bucket = groups.get(key)
    if (bucket) bucket.push(attribute)
    else groups.set(key, [attribute])
  }
  return Array.from(groups.entries()).map(([category, items]) => ({
    category,
    label: attributeCategoryLabel(category),
    items,
    average:
      items.filter((item) => item.value !== null).length > 0
        ? items.reduce((sum, item) => sum + (item.value ?? 0), 0) /
          items.filter((item) => item.value !== null).length
        : null,
  }))
})

/** 默认只展示技术/精神/身体三组，其余按需展开。 */
const primaryGroups = computed(() =>
  attributeGroups.value.filter((group) => ['technical', 'mental', 'physical'].includes(group.category)),
)
const extraGroups = computed(() =>
  attributeGroups.value.filter((group) => !['technical', 'mental', 'physical'].includes(group.category)),
)

/** 状态标志三值渲染：未知不写成否。 */
function triState(value: boolean | null | undefined): string {
  if (value === null || value === undefined) return '未知'
  return value ? '是' : '否'
}

const statusSnapshot = computed(() => status.value?.current ?? null)
const isInjured = computed(() => statusSnapshot.value?.injury?.injured === true)
const isListed = computed(
  () => statusSnapshot.value?.flags?.listed === true || statusSnapshot.value?.flags?.loan_listed === true,
)

/** 风险提示：只由已加载的真实字段推导，缺失明确写“未知”。 */
const risks = computed<Array<{ tone: 'warning' | 'danger' | 'neutral'; text: string }>>(() => {
  const items: Array<{ tone: 'warning' | 'danger' | 'neutral'; text: string }> = []
  const months = contractMonths.value
  if (months !== null && months < 0) items.push({ tone: 'danger', text: `合同已于 ${formatDate(summary.value?.contract_end)} 到期` })
  else if (months !== null && months < 12) items.push({ tone: 'warning', text: `合同约 ${months} 个月后到期，不足 12 个月` })
  else if (months === null) items.push({ tone: 'neutral', text: '合同到期日缺失，无法判断合同风险' })
  if (isInjured.value) items.push({ tone: 'danger', text: '当前状态标记为伤停' })
  if (isListed.value) items.push({ tone: 'warning', text: '当前状态标记为挂牌（出售或出租）' })
  const completeness = summary.value?.data_completeness
  if (completeness !== null && completeness !== undefined && completeness < 0.6) {
    items.push({ tone: 'warning', text: `关键字段完整度 ${formatPercent(completeness)}，低于 60%` })
  }
  if ((detail.value?.attributes?.length ?? 0) === 0) {
    items.push({ tone: 'neutral', text: '属性明细缺失，无法评估技术/精神/身体结构' })
  }
  if (valuation.value?.insufficient_sample) {
    items.push({ tone: 'neutral', text: '可比成交样本不足，未生成估值' })
  }
  if (items.length === 0) items.push({ tone: 'neutral', text: '基于现有字段未发现风险信号' })
  return items
})

/** 估值摘要：只显示接口真实返回的中位与置信度。 */
const valuationText = computed(() => {
  const value = valuation.value
  if (!value) return '估值不可用'
  if (value.insufficient_sample) return '样本不足，未估值'
  if (value.mid === null) return '估值中位缺失'
  const currency = value.currency ?? 'EUR'
  const confidence = value.confidence ? ` · 置信度 ${confidenceLabel(value.confidence)}` : ''
  const method = value.method ? ` · ${valuationMethodLabel(value.method)}` : ''
  return `相似成交中位 ${formatMoney(value.mid)} ${currency}${confidence}${method}`
})

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape' && props.instanceId !== null) emit('close')
}

watch(
  () => props.instanceId,
  (id) => {
    if (typeof window === 'undefined') return
    if (id !== null) window.addEventListener('keydown', onKeydown)
    else window.removeEventListener('keydown', onKeydown)
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  if (typeof window !== 'undefined') window.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <Teleport to="body">
    <Transition name="pd-fade">
      <div v-if="instanceId !== null" class="pd-root">
        <div class="pd-scrim" @click="emit('close')" />
        <aside class="pd-panel" role="dialog" aria-modal="true" aria-label="球员详情">
          <header class="pd-head">
            <div class="pd-head__nav">
              <button type="button" class="pd-icon" :disabled="!hasPrev" aria-label="上一位球员" title="上一位球员" @click="emit('prev')">
                <AppIcon name="chevron-left" :size="16" />
              </button>
              <button type="button" class="pd-icon" :disabled="!hasNext" aria-label="下一位球员" title="下一位球员" @click="emit('next')">
                <AppIcon name="chevron-right" :size="16" />
              </button>
            </div>
            <button type="button" class="pd-icon pd-head__close" aria-label="关闭球员详情" title="关闭" @click="emit('close')">
              <AppIcon name="close" :size="16" />
            </button>
          </header>

          <div v-if="loading" class="pd-loading" aria-busy="true">
            <div class="pd-skeleton pd-skeleton--avatar" />
            <div class="pd-skeleton pd-skeleton--title" />
            <div class="pd-skeleton pd-skeleton--line" />
            <div class="pd-skeleton pd-skeleton--block" />
          </div>

          <div v-else-if="error" class="pd-error">
            <p class="pd-error__title">球员档案加载失败</p>
            <p class="pd-error__text">{{ error.message }}</p>
            <button v-if="instanceId !== null" type="button" class="pd-btn pd-btn--primary" @click="load(instanceId)">
              重试
            </button>
          </div>

          <div v-else-if="summary" class="pd-body">
            <section class="pd-identity">
              <div class="pd-avatar" aria-hidden="true">{{ initials }}</div>
              <div class="pd-identity__text">
                <h2 class="pd-name">{{ displayText(summary.name) }}</h2>
                <p class="pd-sub">{{ identityLine }}</p>
                <p class="pd-sub pd-sub--faint">{{ bioLine }}</p>
              </div>
            </section>

            <section class="pd-kpis">
              <div><span>CA</span><strong>{{ formatInt(summary.ca) }}</strong></div>
              <div><span>PA</span><strong>{{ formatInt(summary.pa) }}</strong></div>
              <div><span>身价</span><strong>{{ formatMoney(summary.market_value) }}</strong></div>
              <div><span>周薪</span><strong>{{ formatMoney(summary.wage) }}</strong></div>
            </section>

            <section class="pd-section">
              <h3>能力结构</h3>
              <p v-if="primaryGroups.length === 0" class="pd-muted">属性明细缺失，无法展示能力结构。</p>
              <div v-else class="pd-groups">
                <div v-for="group in primaryGroups" :key="group.category" class="pd-group">
                  <div class="pd-group__head">
                    <span>{{ group.label }}</span>
                    <strong>{{ group.average === null ? EMPTY : formatDecimal(group.average, 1) }}</strong>
                  </div>
                  <div class="pd-group__bar">
                    <span :style="{ width: `${((group.average ?? 0) / 20) * 100}%` }" />
                  </div>
                  <ul class="pd-attrs">
                    <li
                      v-for="attribute in showAllAttributes ? group.items : group.items.slice(0, 5)"
                      :key="attribute.key"
                    >
                      <span class="pd-attrs__name">{{ attribute.name }}</span>
                      <span class="pd-attrs__value">{{ formatInt(attribute.value) }}</span>
                    </li>
                  </ul>
                </div>
              </div>
              <button
                v-if="attributeGroups.length > 0"
                type="button"
                class="pd-link"
                @click="showAllAttributes = !showAllAttributes"
              >
                {{ showAllAttributes ? '收起属性明细' : '展开全部属性' }}
              </button>
              <div v-if="showAllAttributes && extraGroups.length > 0" class="pd-groups pd-groups--extra">
                <div v-for="group in extraGroups" :key="group.category" class="pd-group">
                  <div class="pd-group__head">
                    <span>{{ group.label }}</span>
                    <strong>{{ group.average === null ? EMPTY : formatDecimal(group.average, 1) }}</strong>
                  </div>
                  <ul class="pd-attrs">
                    <li v-for="attribute in group.items" :key="attribute.key">
                      <span class="pd-attrs__name">{{ attribute.name }}</span>
                      <span class="pd-attrs__value">{{ formatInt(attribute.value) }}</span>
                    </li>
                  </ul>
                </div>
              </div>
            </section>

            <section class="pd-section">
              <h3>合同与市场</h3>
              <dl class="pd-facts">
                <div><dt>合同到期</dt><dd>{{ formatDate(summary.contract_end) }}</dd></div>
                <div>
                  <dt>剩余合同</dt>
                  <dd>{{ contractMonths === null ? EMPTY : `${contractMonths} 个月` }}</dd>
                </div>
                <div><dt>身价</dt><dd>{{ formatMoney(summary.market_value) }}</dd></div>
                <div><dt>周薪</dt><dd>{{ formatMoney(summary.wage) }}</dd></div>
                <div class="pd-facts__wide"><dt>估值</dt><dd>{{ valuationText }}</dd></div>
              </dl>
            </section>

            <section class="pd-section">
              <h3>状态与风险</h3>
              <dl class="pd-facts">
                <div><dt>挂牌出售</dt><dd>{{ triState(statusSnapshot?.flags?.listed) }}</dd></div>
                <div><dt>挂牌出租</dt><dd>{{ triState(statusSnapshot?.flags?.loan_listed) }}</dd></div>
                <div><dt>伤停</dt><dd>{{ triState(statusSnapshot?.injury?.injured) }}</dd></div>
                <div><dt>数据完整度</dt><dd>{{ formatPercent(summary.data_completeness) }}</dd></div>
              </dl>
              <ul class="pd-risks">
                <li v-for="risk in risks" :key="risk.text" :class="`pd-risks--${risk.tone}`">{{ risk.text }}</li>
              </ul>
            </section>

            <section class="pd-section">
              <h3>适配与档案</h3>
              <p class="pd-muted">
                角色适配需要在完整档案中选择角色后计算，避免用固定模板代替球探判断。
              </p>
              <p class="pd-muted pd-muted--tiny">
                来源 {{ sourceLabel(summary.source) }} · 最近观测 {{ formatDateTime(summary.observed_at) }} · 快照
                {{ formatInt(detail?.snapshot_count) }} 次
              </p>
              <div v-if="detail?.tags?.length" class="pd-tags">
                <AppTag
                  v-for="tag in visibleTags(detail.tags)"
                  :key="tag.key"
                  :tag="tag.key"
                  :label="tag.label"
                  surface="light"
                />
              </div>
              <p v-if="detail?.notes" class="pd-note">{{ detail.notes }}</p>
            </section>
          </div>

          <footer v-if="summary && !loading && !error" class="pd-foot">
            <button
              type="button"
              class="pd-btn"
              :class="{ 'pd-btn--active': watched }"
              :disabled="watchPending"
              @click="emit('toggle-watch')"
            >
              {{ watched ? '已关注' : '关注' }}
            </button>
            <button
              type="button"
              class="pd-btn"
              :class="{ 'pd-btn--active': compareActive }"
              @click="emit('toggle-compare')"
            >
              {{ compareActive ? '已加入对比' : '加入对比' }}
            </button>
            <router-link
              v-if="instanceId !== null"
              class="pd-btn pd-btn--primary"
              :to="`/players/${instanceId}`"
              @click="emit('close')"
            >
              打开完整档案
            </router-link>
          </footer>
        </aside>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.pd-root {
  --pd-surface: #ffffff;
  --pd-surface-2: #f5f7fa;
  --pd-text: #172334;
  --pd-text-2: #68778a;
  --pd-text-3: #94a1b1;
  --pd-primary: #2563eb;
  --pd-primary-weak: #eff4ff;
  --pd-border: #e4eaf1;
  --pd-warn: #b45309;
  --pd-danger: #b91c1c;
  position: fixed;
  inset: 0;
  z-index: 1200;
  color-scheme: light;
  font-family: var(--sm-font-sans);
}

.pd-scrim {
  position: absolute;
  inset: 0;
  background: rgba(23, 35, 52, 0.34);
  backdrop-filter: blur(2px);
}

.pd-panel {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  display: flex;
  flex-direction: column;
  width: min(580px, 94vw);
  background: var(--pd-surface);
  border-left: 1px solid var(--pd-border);
  box-shadow: -24px 0 60px -32px rgba(23, 35, 52, 0.35);
  color: var(--pd-text);
}

.pd-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px 4px;
}

.pd-head__nav {
  display: flex;
  gap: 6px;
}

.pd-icon {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  padding: 0;
  border: 1px solid var(--pd-border);
  border-radius: 8px;
  background: var(--pd-surface);
  color: var(--pd-text-2);
  font-size: 17px;
  line-height: 1;
  cursor: pointer;
}

.pd-icon:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.pd-icon:hover:not(:disabled) {
  border-color: #c9d5e6;
  color: var(--pd-text);
}

.pd-body {
  flex: 1 1 auto;
  overflow-y: auto;
  padding: 4px 20px 24px;
}

.pd-identity {
  display: flex;
  gap: 14px;
  align-items: center;
  padding: 8px 0 16px;
}

.pd-avatar {
  display: grid;
  place-items: center;
  width: 56px;
  height: 56px;
  flex: 0 0 auto;
  border-radius: 16px;
  background: linear-gradient(160deg, #e8f0ff, #dfe9f9);
  color: #2c4a7c;
  font-size: 18px;
  font-weight: 700;
  letter-spacing: 0.04em;
}

.pd-name {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
  letter-spacing: -0.01em;
}

.pd-sub {
  margin: 2px 0 0;
  color: var(--pd-text-2);
  font-size: 12px;
}

.pd-sub--faint {
  color: var(--pd-text-3);
}

.pd-kpis {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  padding: 12px;
  border: 1px solid var(--pd-border);
  border-radius: 12px;
  background: var(--pd-surface-2);
}

.pd-kpis div {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.pd-kpis span {
  color: var(--pd-text-3);
  font-size: 11px;
}

.pd-kpis strong {
  font-size: 16px;
  font-variant-numeric: tabular-nums;
}

.pd-section {
  padding: 18px 0 4px;
  border-bottom: 1px solid var(--pd-border);
}

.pd-section:last-of-type {
  border-bottom: 0;
}

.pd-section h3 {
  margin: 0 0 10px;
  font-size: 13px;
  font-weight: 600;
  color: var(--pd-text);
}

.pd-groups {
  display: grid;
  gap: 12px;
}

.pd-group {
  padding: 10px 12px;
  border: 1px solid var(--pd-border);
  border-radius: 10px;
}

.pd-group__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  color: var(--pd-text-2);
  font-size: 12px;
}

.pd-group__head strong {
  color: var(--pd-text);
  font-size: 14px;
}

.pd-group__bar {
  height: 4px;
  margin: 6px 0 8px;
  border-radius: 999px;
  background: #e8eef7;
  overflow: hidden;
}

.pd-group__bar span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: #3b82f6;
}

.pd-attrs {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 4px 12px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.pd-attrs li {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  color: var(--pd-text-2);
  font-size: 12px;
}

.pd-attrs__value {
  color: var(--pd-text);
  font-variant-numeric: tabular-nums;
}

.pd-groups--extra {
  margin-top: 12px;
}

.pd-link {
  margin-top: 8px;
  padding: 0;
  border: 0;
  background: none;
  color: var(--pd-primary);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

.pd-facts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px 16px;
  margin: 0;
}

.pd-facts div {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.pd-facts__wide {
  grid-column: 1 / -1;
}

.pd-facts dt {
  color: var(--pd-text-3);
  font-size: 11px;
}

.pd-facts dd {
  margin: 0;
  color: var(--pd-text);
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}

.pd-risks {
  margin: 12px 0 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 6px;
}

.pd-risks li {
  padding: 7px 10px;
  border-radius: 8px;
  font-size: 12px;
  background: var(--pd-surface-2);
  color: var(--pd-text-2);
}

.pd-risks--warning {
  background: #fff7ed !important;
  color: var(--pd-warn) !important;
}

.pd-risks--danger {
  background: #fef2f2 !important;
  color: var(--pd-danger) !important;
}

.pd-muted {
  margin: 0 0 6px;
  color: var(--pd-text-2);
  font-size: 12px;
  line-height: 1.6;
}

.pd-muted--tiny {
  color: var(--pd-text-3);
  font-size: 11px;
}

.pd-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.pd-note {
  margin: 8px 0 0;
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--pd-surface-2);
  color: var(--pd-text-2);
  font-size: 12px;
}

.pd-foot {
  display: flex;
  gap: 8px;
  padding: 12px 20px;
  border-top: 1px solid var(--pd-border);
  background: var(--pd-surface);
}

.pd-btn {
  flex: 1 1 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 36px;
  padding: 0 12px;
  border: 1px solid var(--pd-border);
  border-radius: 9px;
  background: var(--pd-surface);
  color: var(--pd-text);
  font-size: 13px;
  font-weight: 500;
  text-decoration: none;
  cursor: pointer;
}

.pd-btn:hover {
  border-color: #c9d5e6;
  text-decoration: none;
}

.pd-btn--active {
  border-color: #bfd3f7;
  background: var(--pd-primary-weak);
  color: #1d4ed8;
}

.pd-btn--primary {
  border-color: #2563eb;
  background: #2563eb;
  color: #ffffff;
}

.pd-btn--primary:hover {
  background: #1d4ed8;
  color: #ffffff;
}

.pd-loading {
  padding: 24px 20px;
  display: grid;
  gap: 12px;
}

.pd-skeleton {
  border-radius: 10px;
  background: linear-gradient(90deg, #eef2f7 25%, #f6f8fb 50%, #eef2f7 75%);
  background-size: 200% 100%;
  animation: pd-shimmer 1.4s ease-in-out infinite;
}

.pd-skeleton--avatar {
  width: 56px;
  height: 56px;
  border-radius: 16px;
}

.pd-skeleton--title {
  width: 55%;
  height: 22px;
}

.pd-skeleton--line {
  width: 80%;
  height: 14px;
}

.pd-skeleton--block {
  height: 160px;
}

.pd-error {
  padding: 32px 20px;
}

.pd-error__title {
  margin: 0 0 6px;
  font-size: 15px;
  font-weight: 600;
}

.pd-error__text {
  margin: 0 0 14px;
  color: var(--pd-text-2);
  font-size: 13px;
}

@keyframes pd-shimmer {
  0% {
    background-position: 160% 0;
  }
  100% {
    background-position: -60% 0;
  }
}

.pd-fade-enter-active,
.pd-fade-leave-active {
  transition: opacity 160ms ease;
}

.pd-fade-enter-active .pd-panel,
.pd-fade-leave-active .pd-panel {
  transition: transform 220ms cubic-bezier(0.22, 1, 0.36, 1);
}

.pd-fade-enter-from,
.pd-fade-leave-to {
  opacity: 0;
}

.pd-fade-enter-from .pd-panel,
.pd-fade-leave-to .pd-panel {
  transform: translateX(24px);
}

@media (max-width: 640px) {
  .pd-panel {
    width: 100vw;
  }

  .pd-attrs {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (prefers-reduced-motion: reduce) {
  .pd-fade-enter-active,
  .pd-fade-leave-active,
  .pd-fade-enter-active .pd-panel,
  .pd-fade-leave-active .pd-panel {
    transition: none;
  }

  .pd-skeleton {
    animation: none;
  }
}
</style>
