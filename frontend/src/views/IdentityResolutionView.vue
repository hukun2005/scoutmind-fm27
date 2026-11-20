<template>
  <section class="identity">
    <PageHeader
      title="身份复核中心"
      subtitle="同 UID 出现不同姓名或生日时的待处理冲突；系统只给建议，合并必须人工确认"
    >
      <template #actions>
        <el-button size="small" :loading="loading" @click="reload">刷新</el-button>
      </template>
    </PageHeader>

    <div class="identity__counters">
      <KpiCard label="待处理" :value="formatInt(counts.open)" hint="需要人工确认" />
      <KpiCard label="已解决" :value="formatInt(counts.resolved)" hint="确认同一人或不同人" />
      <KpiCard label="暂缓" :value="formatInt(counts.deferred)" hint="保留证据，稍后再看" />
    </div>

    <SectionCard title="筛选" dense>
      <div class="identity__filters">
        <el-select v-model="statusFilter" size="small" style="width: 150px" @change="reload">
          <el-option label="待处理" value="open" />
          <el-option label="已解决" value="resolved" />
          <el-option label="暂缓" value="deferred" />
          <el-option label="全部" value="all" />
        </el-select>
        <el-select v-model="sort" size="small" style="width: 190px" @change="reload">
          <el-option label="置信度从高到低" value="confidence_desc" />
          <el-option label="置信度从低到高" value="confidence_asc" />
          <el-option label="最新优先" value="created_desc" />
          <el-option label="最早优先" value="created_asc" />
        </el-select>
        <el-input
          v-model="reasonFilter"
          size="small"
          placeholder="冲突类型（可选）"
          style="width: 220px"
          clearable
          @change="reload"
        />
      </div>
    </SectionCard>

    <div class="identity__layout">
      <SectionCard title="冲突列表" dense class="identity__list">
        <DataTable
          :columns="columns"
          :rows="items"
          row-key="id"
          :loading="loading"
          :error="error"
          :total="total"
          :page="page"
          :page-size="pageSize"
          show-pagination
          @update:page="onPage"
          @update:page-size="onPageSize"
          @row-click="selectRow"
        />
      </SectionCard>

      <SectionCard v-if="detail" :title="`冲突 #${detail.id}`" dense class="identity__detail">
        <div class="identity__detail-body">
          <el-alert :title="detail.suggestion.reason" type="info" :closable="false" show-icon />
          <div class="identity__compare">
            <div v-for="side in sides" :key="side.key" class="identity__side">
              <h4>{{ side.label }}</h4>
              <dl>
                <dt>姓名</dt><dd>{{ displayText(side.player?.full_name) }}</dd>
                <dt>生日</dt><dd>{{ displayText(side.player?.birth_date) }}</dd>
                <dt>国籍</dt><dd>{{ displayText(side.player?.nationality) }}</dd>
                <dt>实例</dt><dd>{{ formatInt(side.player?.instance_count ?? 0) }}</dd>
                <dt>快照</dt><dd>{{ formatInt(side.player?.snapshot_count ?? 0) }}</dd>
                <dt>来源</dt>
                <dd>
                  <span v-if="!side.player?.sources.length">未知</span>
                  <span v-for="source in side.player?.sources" :key="source.import_job_id" class="identity__source">
                    {{ sourceLabel(source.source) }} · {{ formatDateTime(source.received_at) }}
                  </span>
                </dd>
              </dl>
            </div>
          </div>

          <div class="identity__actions">
            <el-input v-model="note" size="small" placeholder="处理备注（会写入审计）" />
            <div class="identity__buttons">
              <el-button type="primary" size="small" :loading="resolving" @click="decide('same')">
                确认同一人（合并）
              </el-button>
              <el-button size="small" :loading="resolving" @click="decide('different')">确认不同人</el-button>
              <el-button size="small" :loading="resolving" @click="decide('defer')">暂不处理</el-button>
            </div>
          </div>

          <div class="identity__history">
            <h4>操作历史</h4>
            <p v-if="!detail.history.length" class="identity__muted">还没有人工操作记录。</p>
            <ul v-else>
              <li v-for="entry in detail.history" :key="entry.id">
                {{ formatDateTime(entry.created_at) }} · {{ entry.action }} · {{ entry.note || '无备注' }}
              </li>
            </ul>
          </div>
        </div>
      </SectionCard>
      <EmptyState v-else title="选择一条冲突查看双方证据" hint="左侧列表来自当前存档的冲突记录" class="identity__detail" />
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { asApiError, type ApiError } from '../api/client'
import { getIdentityConflict, listIdentityConflicts, resolveIdentityConflict } from '../api/identity'
import DataTable from '../components/DataTable.vue'
import EmptyState from '../components/EmptyState.vue'
import KpiCard from '../components/KpiCard.vue'
import PageHeader from '../components/PageHeader.vue'
import SectionCard from '../components/SectionCard.vue'
import type { ConflictDetail, ConflictDecision, ConflictListItem } from '../types/identity'
import type { TableColumn } from '../types/table'
import { displayText, formatDateTime, formatInt, formatPercent } from '../utils/format'
import { sourceLabel } from '../utils/labels'

const items = ref<ConflictListItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const error = ref<ApiError | null>(null)
const counts = ref({ open: 0, resolved: 0, deferred: 0 })

const statusFilter = ref<'open' | 'resolved' | 'deferred' | 'all'>('open')
const sort = ref<'confidence_desc' | 'confidence_asc' | 'created_desc' | 'created_asc'>('confidence_desc')
const reasonFilter = ref('')

const detail = ref<ConflictDetail | null>(null)
const note = ref('')
const resolving = ref(false)

const columns: TableColumn<ConflictListItem>[] = [
  { prop: 'uid', label: 'UID', width: 120 },
  { prop: 'existing', label: '既有身份', formatter: (row) => displayText(row.existing.name) },
  { prop: 'incoming', label: '新记录', formatter: (row) => displayText(row.incoming.name) },
  { prop: 'reason', label: '冲突类型', width: 200 },
  { prop: 'confidence', label: '置信度', width: 100, formatter: (row) => formatPercent(row.confidence) },
  { prop: 'status', label: '状态', width: 100 },
  { prop: 'suggestion', label: '系统建议', width: 110, formatter: (row) => row.suggestion.decision },
]

const sides = computed(() =>
  detail.value
    ? [
        { key: 'existing', label: '既有身份', player: detail.value.existing },
        { key: 'incoming', label: '新记录', player: detail.value.incoming },
      ]
    : [],
)

async function reload(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const response = await listIdentityConflicts({
      status: statusFilter.value,
      sort: sort.value,
      reason: reasonFilter.value || undefined,
      page: page.value,
      page_size: pageSize.value,
    })
    items.value = response.items
    total.value = response.total
    counts.value = response.counts
  } catch (failure) {
    error.value = asApiError(failure)
  } finally {
    loading.value = false
  }
}

async function selectRow(row: ConflictListItem): Promise<void> {
  note.value = ''
  try {
    detail.value = await getIdentityConflict(row.id)
  } catch (failure) {
    ElMessage.error(asApiError(failure).message)
  }
}

async function decide(decision: ConflictDecision): Promise<void> {
  if (!detail.value) return
  resolving.value = true
  try {
    const response = await resolveIdentityConflict(detail.value.id, decision, {
      keep: 'existing',
      note: note.value || undefined,
    })
    ElMessage.success(response.note)
    detail.value = await getIdentityConflict(detail.value.id)
    await reload()
  } catch (failure) {
    ElMessage.error(asApiError(failure).message)
  } finally {
    resolving.value = false
  }
}

function onPage(value: number): void {
  page.value = value
  void reload()
}

function onPageSize(value: number): void {
  pageSize.value = value
  page.value = 1
  void reload()
}

onMounted(reload)
</script>

<style scoped>
.identity__counters {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
  margin-bottom: 12px;
}
.identity__filters {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.identity__layout {
  display: grid;
  grid-template-columns: minmax(0, 3fr) minmax(320px, 2fr);
  gap: 12px;
}
@media (max-width: 1100px) {
  .identity__layout {
    grid-template-columns: 1fr;
  }
}
.identity__compare {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
  margin: 12px 0;
}
.identity__side dl {
  display: grid;
  grid-template-columns: 60px 1fr;
  gap: 4px 8px;
  margin: 0;
  font-size: 13px;
}
.identity__side dt {
  color: var(--el-text-color-secondary);
}
.identity__side dd {
  margin: 0;
}
.identity__source {
  display: block;
  font-size: 12px;
}
.identity__actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 12px 0;
}
.identity__buttons {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.identity__history ul {
  padding-left: 18px;
  margin: 6px 0;
  font-size: 13px;
}
.identity__muted {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
</style>
