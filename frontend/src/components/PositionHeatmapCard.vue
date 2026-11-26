/**
 * 阵容位置深度热力图：矩阵布局，一格一个位置，颜色表示覆盖情况。
 *
 * 数据来自 `GET /squad/depth`；主力按 CA 排序后的第一人，替补为第二人。
 * 空位置与缺少 CA 的情况都有明确文案，不补 0。
 */

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { asApiError, type ApiError } from '../api/client'
import { getSquadDepth } from '../api/squad'
import type { DepthRow, SquadMember } from '../types/squad'
import { EMPTY, formatInt } from '../utils/format'
import EmptyState from './EmptyState.vue'
import ErrorState from './ErrorState.vue'
import LoadingBlock from './LoadingBlock.vue'
import SectionCard from './SectionCard.vue'

const props = defineProps<{ saveId: number | null }>()

const router = useRouter()
const rows = ref<DepthRow[]>([])
const squadSize = ref(0)
const missingPosition = ref(0)
const loading = ref(false)
const error = ref<ApiError | null>(null)
let seq = 0

/** 位置 → 球员中心筛选组，点击格子直接查看该区域球员。 */
const SLOT_GROUPS: Record<string, string> = {
  GK: 'GK',
  CB: 'DF',
  LB: 'DF',
  RB: 'DF',
  DM: 'MF',
  CM: 'MF',
  AM: 'MF',
  LW: 'FW',
  RW: 'FW',
  ST: 'FW',
}

const slots = computed(() => rows.value.filter((row) => row.slot !== 'UNKNOWN'))

const holes = computed(() => slots.value.filter((row) => row.count === 0).length)

async function load(): Promise<void> {
  const current = ++seq
  loading.value = true
  error.value = null
  try {
    const response = await getSquadDepth(props.saveId ?? undefined)
    if (current !== seq) return
    rows.value = response.items
    squadSize.value = response.squad_size
    missingPosition.value = response.missing_position
  } catch (caught) {
    if (current !== seq) return
    error.value = asApiError(caught)
    rows.value = []
  } finally {
    if (current === seq) loading.value = false
  }
}

function starter(row: DepthRow): SquadMember | null {
  return row.players[0] ?? null
}

function backup(row: DepthRow): SquadMember | null {
  return row.players[1] ?? null
}

function memberLabel(member: SquadMember | null): string {
  if (!member) return '无'
  return `${member.name} · CA ${member.ca ?? EMPTY}`
}

function tone(row: DepthRow): string {
  if (row.count === 0) return 'empty'
  if (row.count < row.required) return 'thin'
  return 'ok'
}

function openSlot(row: DepthRow): void {
  const group = SLOT_GROUPS[row.slot]
  void router.push({ path: '/players', query: group ? { position_group: group } : {} })
}

watch(() => props.saveId, load, { immediate: true })
</script>

<template>
  <SectionCard
    title="位置深度热力图"
    subtitle="每个位置的可用人数、主力与替补；颜色越亮表示覆盖越充足"
  >
    <LoadingBlock v-if="loading && rows.length === 0" :rows="4" compact label="正在加载阵容位置" />
    <ErrorState v-else-if="error" :error="error" compact title="阵容位置加载失败" @retry="load" />
    <EmptyState
      v-else-if="slots.length === 0"
      title="还没有阵容数据"
      description="指定「我的俱乐部」并导入扫描后，这里会显示每个位置的人手情况。"
      compact
    />
    <template v-else>
      <div class="heatmap-summary">
        <span>阵容人数 <strong>{{ formatInt(squadSize) }}</strong></span>
        <span>空缺位置 <strong>{{ formatInt(holes) }}</strong></span>
        <span v-if="missingPosition > 0">位置未知 <strong>{{ formatInt(missingPosition) }}</strong></span>
      </div>

      <div class="heatmap" role="list" aria-label="阵容位置深度矩阵">
        <button
          v-for="row in slots"
          :key="row.slot"
          type="button"
          role="listitem"
          class="slot"
          :class="`slot--${tone(row)}`"
          :aria-label="`${row.slot_name}：${row.count} 人，查看该位置球员`"
          @click="openSlot(row)"
        >
          <span class="slot__head">
            <span class="slot__name">{{ row.slot_name }}</span>
            <span class="slot__count">{{ row.count }}/{{ row.required }}</span>
          </span>
          <span class="slot__line">
            <span class="slot__tag">主力</span>
            <span class="slot__text">{{ memberLabel(starter(row)) }}</span>
          </span>
          <span class="slot__line">
            <span class="slot__tag">替补</span>
            <span class="slot__text">{{ memberLabel(backup(row)) }}</span>
          </span>
          <span class="slot__status">{{ row.status }}</span>
        </button>
      </div>
    </template>
    <template #footer>
      主力 / 替补按当前能力（CA）排序；缺少 CA 的球员显示为「—」，不参与能力比较。点击位置可查看该区域球员。
    </template>
  </SectionCard>
</template>

<style scoped>
.heatmap-summary {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sm-space-4);
  margin-bottom: var(--sm-space-3);
  color: var(--sm-text-2);
  font-size: var(--sm-fs-xs);
}

.heatmap-summary strong {
  color: var(--sm-text-primary);
}

.heatmap {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: var(--sm-space-2);
}

.slot {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
  padding: var(--sm-space-2) var(--sm-space-3);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-md);
  background: rgba(12, 23, 39, 0.55);
  color: var(--sm-text-primary);
  text-align: left;
  cursor: pointer;
  transition:
    border-color var(--sm-dur-1) var(--sm-ease-out),
    background-color var(--sm-dur-1) var(--sm-ease-out);
}

.slot:hover {
  border-color: var(--sm-border-glow);
}

.slot--ok {
  border-color: rgba(52, 211, 153, 0.32);
  background: linear-gradient(160deg, rgba(52, 211, 153, 0.14), rgba(12, 23, 39, 0.6));
}

.slot--thin {
  border-color: rgba(245, 181, 68, 0.34);
  background: linear-gradient(160deg, rgba(245, 181, 68, 0.12), rgba(12, 23, 39, 0.6));
}

.slot--empty {
  border-color: rgba(251, 113, 133, 0.38);
  background: linear-gradient(160deg, rgba(251, 113, 133, 0.14), rgba(12, 23, 39, 0.6));
}

.slot__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--sm-space-2);
}

.slot__name {
  font-size: var(--sm-fs-sm);
  font-weight: 600;
}

.slot__count {
  color: var(--sm-text-2);
  font-size: var(--sm-fs-xs);
}

.slot__line {
  display: flex;
  align-items: baseline;
  gap: 5px;
  min-width: 0;
}

.slot__tag {
  flex: 0 0 auto;
  color: var(--sm-text-3);
  font-size: 9px;
}

.slot__text {
  overflow: hidden;
  color: var(--sm-text-2);
  font-size: var(--sm-fs-2xs);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.slot__status {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}

@media (max-width: 1366px) {
  .heatmap {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
}

@media (max-width: 900px) {
  .heatmap {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
