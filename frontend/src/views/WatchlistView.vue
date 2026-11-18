/** 成长追踪：关注名单、标签编辑与规则提醒。 */

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { asApiError, type ApiError } from '../api/client'
import {
  addWatchlistItem,
  deleteWatchlistItem,
  listAlerts,
  listWatchlist,
  markAlertRead,
  patchWatchlistItem,
  refreshWatchlist,
} from '../api/watchlist'
import DataTable from '../components/DataTable.vue'
import EmptyState from '../components/EmptyState.vue'
import ErrorState from '../components/ErrorState.vue'
import NumberCell from '../components/NumberCell.vue'
import PageHeader from '../components/PageHeader.vue'
import SectionCard from '../components/SectionCard.vue'
import type { Alert, WatchlistItem } from '../types/watchlist'
import type { TableColumn } from '../types/table'
import { useSessionStore } from '../stores/session'
import { EMPTY, displayText, formatDateTime, formatInt } from '../utils/format'
import { alertTypeLabel, positionLabel, severityLabel, WATCHLIST_TAG_OPTIONS } from '../utils/labels'

const router = useRouter()
const session = useSessionStore()

const items = ref<WatchlistItem[]>([])
const loading = ref(false)
const error = ref<ApiError | null>(null)

const alerts = ref<Alert[]>([])
const alertsLoading = ref(false)
const alertsError = ref<ApiError | null>(null)
const unreadOnly = ref(true)

const addOpen = ref(false)
const addSubmitting = ref(false)
const addError = ref<ApiError | null>(null)
const addForm = reactive<{ instanceId: number | undefined; tag: string; note: string }>({
  instanceId: undefined,
  tag: '',
  note: '',
})

const editOpen = ref(false)
const editSubmitting = ref(false)
const editError = ref<ApiError | null>(null)
const editTarget = ref<WatchlistItem | null>(null)
const editForm = reactive<{ tag: string; note: string }>({ tag: '', note: '' })

const refreshBusy = ref(false)

const columns: TableColumn<WatchlistItem>[] = [
  { prop: 'player', label: '球员', minWidth: 150, formatter: (row) => displayText(row.player?.name) },
  { prop: 'position', label: '位置', width: 116, formatter: (row) => positionLabel(row.player?.position ?? null) },
  { prop: 'age', label: '年龄', width: 70, align: 'right' },
  { prop: 'ca', label: 'CA', width: 66, align: 'right' },
  { prop: 'pa', label: 'PA', width: 66, align: 'right' },
  { prop: 'market_value', label: '身价（€）', width: 110, align: 'right' },
  { prop: 'tag', label: '标签', width: 120 },
  { prop: 'note', label: '备注', minWidth: 160, showOverflowTooltip: true },
  { prop: 'added_at', label: '加入时间', width: 140 },
  { prop: 'actions', label: '操作', width: 132, align: 'right' },
]

const unreadCount = computed(() => alerts.value.filter((alert) => alert.read_at === null).length)

/** Query signature: any change reloads both panels. */
const signature = computed(() =>
  JSON.stringify({
    saveId: session.activeSaveId,
    revision: session.dataRevision,
    unreadOnly: unreadOnly.value,
  }),
)

/** Load the watchlist rows. */
async function loadItems(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const response = await listWatchlist(session.activeSaveId ?? undefined)
    items.value = response.items ?? []
    session.markSources(items.value.map((item) => item.player?.source))
  } catch (caught) {
    error.value = asApiError(caught)
    items.value = []
  } finally {
    loading.value = false
  }
}

/** Load the alert feed. */
async function loadAlerts(): Promise<void> {
  alertsLoading.value = true
  alertsError.value = null
  try {
    const response = await listAlerts(session.activeSaveId ?? undefined, unreadOnly.value)
    alerts.value = response.items ?? []
  } catch (caught) {
    alertsError.value = asApiError(caught)
    alerts.value = []
  } finally {
    alertsLoading.value = false
  }
}

/** Reload both panels. */
async function reload(): Promise<void> {
  await Promise.all([loadItems(), loadAlerts()])
}

/** Run the rule-based refresh and report the counts the backend returned. */
async function runRefresh(): Promise<void> {
  refreshBusy.value = true
  try {
    const result = await refreshWatchlist()
    ElMessage.success(`规则刷新完成：新增关注 ${formatInt(result.created)} 条，生成提醒 ${formatInt(result.alerts)} 条`)
    await reload()
  } catch (caught) {
    ElMessage.error(`规则刷新失败：${asApiError(caught).message}`)
  } finally {
    refreshBusy.value = false
  }
}

/** Open the add dialog with a clean form. */
function openAdd(): void {
  addForm.instanceId = undefined
  addForm.tag = ''
  addForm.note = ''
  addError.value = null
  addOpen.value = true
}

/** Submit the add dialog. */
async function submitAdd(): Promise<void> {
  if (addForm.instanceId === undefined) {
    addError.value = asApiError(new Error('请填写球员实例 ID'))
    return
  }
  addSubmitting.value = true
  addError.value = null
  try {
    await addWatchlistItem({
      instance_id: addForm.instanceId,
      tag: addForm.tag.trim() === '' ? undefined : addForm.tag.trim(),
      note: addForm.note.trim() === '' ? undefined : addForm.note.trim(),
    })
    addOpen.value = false
    ElMessage.success('已加入关注名单')
    await loadItems()
  } catch (caught) {
    addError.value = asApiError(caught)
  } finally {
    addSubmitting.value = false
  }
}

/** Open the tag dialog for one row. */
function openEdit(item: WatchlistItem): void {
  editTarget.value = item
  editForm.tag = item.tag ?? ''
  editForm.note = item.note ?? ''
  editError.value = null
  editOpen.value = true
}

/** Persist tag and note changes. */
async function submitEdit(): Promise<void> {
  const target = editTarget.value
  if (!target) return
  editSubmitting.value = true
  editError.value = null
  try {
    const updated = await patchWatchlistItem(target.id, {
      tag: editForm.tag.trim() === '' ? undefined : editForm.tag.trim(),
      note: editForm.note.trim() === '' ? undefined : editForm.note.trim(),
    })
    items.value = items.value.map((item) => (item.id === updated.id ? updated : item))
    editOpen.value = false
    ElMessage.success('标签已更新')
  } catch (caught) {
    editError.value = asApiError(caught)
  } finally {
    editSubmitting.value = false
  }
}

/** Remove one row after confirmation. */
async function removeItem(item: WatchlistItem): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确认将「${displayText(item.player?.name)}」从关注名单中移除？`,
      '移除关注',
      { type: 'warning', confirmButtonText: '移除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await deleteWatchlistItem(item.id)
    items.value = items.value.filter((row) => row.id !== item.id)
    ElMessage.success('已移除')
  } catch (caught) {
    ElMessage.error(`移除失败：${asApiError(caught).message}`)
  }
}

/** Mark one alert as read. */
async function readAlert(alert: Alert): Promise<void> {
  try {
    await markAlertRead(alert.id)
    if (unreadOnly.value) alerts.value = alerts.value.filter((row) => row.id !== alert.id)
    else alerts.value = alerts.value.map((row) => (row.id === alert.id ? { ...row, read_at: new Date().toISOString() } : row))
  } catch (caught) {
    ElMessage.error(`标记失败：${asApiError(caught).message}`)
  }
}

/** Navigate to the player referenced by an alert or a row. */
function openPlayer(instanceId: number | null | undefined): void {
  if (instanceId === null || instanceId === undefined) return
  void router.push(`/players/${instanceId}`)
}

watch(signature, () => void reload(), { immediate: true })
</script>

<template>
  <div class="sm-page">
    <PageHeader
      title="成长追踪"
      description="关注名单与规则提醒。提醒由后端规则（U21、PA 阈值、身价变化、合同到期）生成，前端不推断。"
    >
      <template #meta>
        <span class="sm-text-xs sm-text-faint">
          关注 {{ formatInt(items.length) }} 人 · 未读提醒 {{ formatInt(unreadCount) }} 条
        </span>
      </template>
      <template #actions>
        <el-button size="small" :loading="refreshBusy" @click="runRefresh">按规则刷新</el-button>
        <el-button size="small" type="primary" @click="openAdd">按实例 ID 添加</el-button>
      </template>
    </PageHeader>

    <SectionCard title="关注名单" subtitle="标签与备注保存在后端，可随时编辑" flush>
      <DataTable
        :columns="columns"
        :rows="items"
        :loading="loading"
        :error="error"
        row-key="id"
        :empty-title="items.length === 0 ? '关注名单为空' : '暂无数据'"
        empty-description="可以按球员实例 ID 添加，或在球员详情页打开「关注名单」开关；「按规则刷新」会依据 U21、PA 阈值等规则批量生成关注。"
        @retry="loadItems"
      >
        <template #cell="{ row, column }">
          <template v-if="column.prop === 'player'">
            <button type="button" class="player-link" @click="openPlayer(row.instance_id)">
              {{ displayText(row.player?.name) }}
            </button>
          </template>
          <template v-else-if="column.prop === 'age'">
            <NumberCell :value="row.player?.age ?? null" unit="岁" />
          </template>
          <template v-else-if="column.prop === 'ca'">
            <NumberCell :value="row.player?.ca ?? null" />
          </template>
          <template v-else-if="column.prop === 'pa'">
            <NumberCell :value="row.player?.pa ?? null" />
          </template>
          <template v-else-if="column.prop === 'market_value'">
            <NumberCell :value="row.player?.market_value ?? null" kind="money" />
          </template>
          <template v-else-if="column.prop === 'tag'">
            <el-tag v-if="row.tag" size="small" type="info" disable-transitions>{{ row.tag }}</el-tag>
            <span v-else class="sm-null">—</span>
          </template>
          <template v-else-if="column.prop === 'note'">
            <span :title="row.note ?? ''">{{ displayText(row.note) }}</span>
          </template>
          <template v-else-if="column.prop === 'added_at'">
            {{ formatDateTime(row.added_at) }}
          </template>
          <template v-else-if="column.prop === 'actions'">
            <el-button link size="small" @click="openEdit(row)">编辑标签</el-button>
            <el-button link size="small" type="danger" @click="removeItem(row)">移除</el-button>
          </template>
          <template v-else>
            {{ column.formatter ? column.formatter(row) : EMPTY }}
          </template>
        </template>
      </DataTable>
    </SectionCard>

    <SectionCard title="提醒" subtitle="合同到期、身价变化与 PA 阈值由后端规则生成">
      <template #actions>
        <el-switch
          v-model="unreadOnly"
          size="small"
          active-text="仅未读"
          inactive-text="全部"
          aria-label="筛选未读提醒"
        />
        <el-button size="small" :loading="alertsLoading" @click="loadAlerts">刷新</el-button>
      </template>

      <ErrorState v-if="alertsError" :error="alertsError" compact @retry="loadAlerts" />
      <div v-else-if="alertsLoading && alerts.length === 0" class="sm-stack">
        <el-skeleton :rows="4" animated />
      </div>
      <EmptyState
        v-else-if="alerts.length === 0"
        :title="unreadOnly ? '没有未读提醒' : '没有提醒'"
        :description="
          unreadOnly
            ? '切换到「全部」可以查看已读提醒；规则尚未运行时可先执行「按规则刷新」。'
            : '后端规则没有生成任何提醒。合同到期、身价变化等阈值由后端配置决定。'
        "
        compact
      />
      <ul v-else class="alert-list">
        <li v-for="alert in alerts" :key="alert.id" class="alert" :class="{ 'alert--unread': alert.read_at === null }">
          <span class="alert__severity" :class="`alert__severity--${alert.severity ?? 'low'}`">
            {{ severityLabel(alert.severity) }}
          </span>
          <div class="alert__body">
            <div class="alert__title">
              {{ alert.title }}
              <el-tag size="small" type="info" disable-transitions>{{ alertTypeLabel(alert.type) }}</el-tag>
            </div>
            <p class="alert__message">{{ alert.message }}</p>
            <p class="alert__meta">
              {{ formatDateTime(alert.created_at) }}
              <template v-if="alert.read_at === null"> · 未读</template>
              <template v-else> · 已读</template>
              <template v-if="alert.instance_id !== null"> · 实例 {{ alert.instance_id }}</template>
            </p>
          </div>
          <div class="alert__actions">
            <el-button
              v-if="alert.instance_id !== null"
              link
              size="small"
              @click="openPlayer(alert.instance_id)"
            >
              查看球员
            </el-button>
            <el-button v-if="alert.read_at === null" link size="small" @click="readAlert(alert)">标记已读</el-button>
          </div>
        </li>
      </ul>
    </SectionCard>

    <el-dialog v-model="addOpen" title="按实例 ID 添加关注" width="420px">
      <div class="dialog-form">
        <label class="dialog-field">
          <span class="sm-label">球员实例 ID</span>
          <el-input-number
            v-model="addForm.instanceId"
            :min="1"
            :controls="false"
            placeholder="例如 11"
            class="dialog-field__number"
          />
        </label>
        <label class="dialog-field">
          <span class="sm-label">标签（可选）</span>
          <el-select v-model="addForm.tag" filterable allow-create default-first-option clearable placeholder="选择或输入标签">
            <el-option v-for="tag in WATCHLIST_TAG_OPTIONS" :key="tag" :label="tag" :value="tag" />
          </el-select>
        </label>
        <label class="dialog-field">
          <span class="sm-label">备注（可选）</span>
          <el-input v-model="addForm.note" type="textarea" :rows="2" placeholder="记录观察理由" />
        </label>
        <ErrorState v-if="addError" :error="addError" compact />
        <p class="sm-text-2xs sm-text-faint">
          实例 ID 可在球员中心的表格或球员详情页找到；后端按 instance_id 匹配球员。
        </p>
      </div>
      <template #footer>
        <el-button size="small" @click="addOpen = false">取消</el-button>
        <el-button size="small" type="primary" :loading="addSubmitting" @click="submitAdd">添加</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="editOpen" title="编辑标签" width="420px">
      <div class="dialog-form">
        <label class="dialog-field">
          <span class="sm-label">球员</span>
          <span class="sm-text-sm">{{ displayText(editTarget?.player?.name) }}</span>
        </label>
        <label class="dialog-field">
          <span class="sm-label">标签</span>
          <el-select v-model="editForm.tag" filterable allow-create default-first-option clearable placeholder="选择或输入标签">
            <el-option v-for="tag in WATCHLIST_TAG_OPTIONS" :key="tag" :label="tag" :value="tag" />
          </el-select>
        </label>
        <label class="dialog-field">
          <span class="sm-label">备注</span>
          <el-input v-model="editForm.note" type="textarea" :rows="3" placeholder="记录观察理由" />
        </label>
        <ErrorState v-if="editError" :error="editError" compact />
      </div>
      <template #footer>
        <el-button size="small" @click="editOpen = false">取消</el-button>
        <el-button size="small" type="primary" :loading="editSubmitting" @click="submitEdit">保存</el-button>
      </template>
    </el-dialog>

    <p class="page-note">
      本页不计算派生指标：标签、提醒与关注规则均由后端生成。球员身价默认 EUR，数据完整度请查看球员详情。
    </p>
  </div>
</template>

<style scoped>
.alert-list {
  display: flex;
  flex-direction: column;
  margin: 0;
  padding: 0;
  list-style: none;
}

.alert {
  display: grid;
  grid-template-columns: 56px minmax(0, 1fr) auto;
  gap: var(--sm-space-3);
  align-items: start;
  padding: var(--sm-space-3) 0;
  border-bottom: 1px solid var(--sm-border);
}

.alert:last-child {
  border-bottom: 0;
}

.alert--unread .alert__title {
  color: var(--sm-text);
  font-weight: var(--sm-fw-medium);
}

.alert__severity {
  display: inline-flex;
  justify-content: center;
  padding: 1px 6px;
  border-radius: var(--sm-radius-sm);
  background: var(--sm-neutral-weak);
  color: var(--sm-neutral);
  font-size: var(--sm-fs-2xs);
}

.alert__severity--high {
  background: var(--sm-danger-weak);
  color: var(--sm-danger);
}

.alert__severity--medium {
  background: var(--sm-warn-weak);
  color: var(--sm-warn);
}

.alert__severity--low {
  background: var(--sm-neutral-weak);
  color: var(--sm-neutral);
}

.alert__body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.alert__title {
  display: flex;
  align-items: center;
  gap: var(--sm-space-2);
  color: var(--sm-text-2);
  font-size: var(--sm-fs-sm);
}

.alert__message {
  color: var(--sm-text-2);
  font-size: var(--sm-fs-xs);
  line-height: 1.6;
}

.alert__meta {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}

.alert__actions {
  display: flex;
  gap: var(--sm-space-1);
  align-items: center;
}

.dialog-form {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-3);
}

.dialog-field {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-1);
}

.dialog-field__number {
  width: 100%;
}

.player-link {
  padding: 0;
  border: 0;
  background: none;
  color: var(--sm-accent);
  font: inherit;
  font-weight: var(--sm-fw-medium);
  cursor: pointer;
}

.player-link:hover {
  text-decoration: underline;
}

.page-note {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}
</style>

