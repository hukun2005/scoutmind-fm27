/** 数据与诊断：扫描上传、导入历史、覆盖度、兼容性与真实数据获取说明。 */

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { UploadRequestOptions } from 'element-plus'
import { ElMessage } from 'element-plus'
import { asApiError, type ApiError } from '../api/client'
import { getCompatibility, getOverview } from '../api/analytics'
import { listImports, uploadScan } from '../api/imports'
import { getFmscoutAdapter, importFmscoutDump, previewFmscoutDump } from '../api/fmscout'
import { validateFmscoutDump } from '../api/status'
import { getSaveSummary } from '../api/saves'
import CoverageBar from '../components/CoverageBar.vue'
import DataTable from '../components/DataTable.vue'
import EmptyState from '../components/EmptyState.vue'
import ErrorState from '../components/ErrorState.vue'
import PageHeader from '../components/PageHeader.vue'
import SectionCard from '../components/SectionCard.vue'
import type { CompatibilityItem, CompatibilityResponse, OverviewResponse } from '../types/analytics'
import type { ImportJob, ScanImportResponse } from '../types/imports'
import type {
  FmscoutAdapterInfo,
  FmscoutImportResponse,
  FmscoutReport,
  FmscoutSamplePlayer,
} from '../types/fmscout'
import type { ValidationResponse } from '../types/status'
import type { SaveSummary } from '../types/bootstrap'
import type { TableColumn } from '../types/table'
import { useSessionStore } from '../stores/session'
import {
  EMPTY,
  displayText,
  formatDateTime,
  formatInt,
  formatMoney,
  formatPercent,
} from '../utils/format'
import { coverageLabel, importStatusLabel, sourceLabel } from '../utils/labels'

const session = useSessionStore()

const imports = ref<ImportJob[]>([])
const importsLoading = ref(false)
const importsError = ref<ApiError | null>(null)

const summary = ref<SaveSummary | null>(null)
const summaryLoading = ref(false)
const summaryError = ref<ApiError | null>(null)

const overview = ref<OverviewResponse | null>(null)
const overviewLoading = ref(false)
const overviewError = ref<ApiError | null>(null)

const compatibility = ref<CompatibilityResponse | null>(null)
const compatibilityLoading = ref(false)
const compatibilityError = ref<ApiError | null>(null)

const uploading = ref(false)
const uploadResult = ref<ScanImportResponse | null>(null)
const uploadError = ref<ApiError | null>(null)

// ---------- FMSuperScout 适配层 ----------

const fmscoutInfo = ref<FmscoutAdapterInfo | null>(null)
const validation = ref<ValidationResponse | null>(null)
const fmscoutReport = ref<FmscoutReport | null>(null)
const fmscoutImport = ref<FmscoutImportResponse['import'] | null>(null)
const fmscoutPreviewPlayers = ref<FmscoutSamplePlayer[]>([])
const fmscoutBusy = ref(false)
const fmscoutError = ref<ApiError | null>(null)

/** Counts reported by the save summary (these are record counts, not ratios). */
const summaryCounts = computed(() => {
  const coverage = summary.value?.coverage
  if (!coverage) return []
  return [
    { label: '球员', value: coverage.players },
    { label: '快照', value: coverage.snapshots },
    { label: '转会', value: coverage.transfers },
    { label: '俱乐部', value: coverage.clubs },
  ]
})

const fieldCoverage = computed(() => Object.entries(overview.value?.coverage ?? {}))

const capabilities = computed(() => {
  const capabilitiesValue = session.capabilities
  return [
    { label: '实时读取器', enabled: capabilitiesValue.live_reader },
    { label: '存档解析', enabled: capabilitiesValue.save_parser },
    { label: 'LLM 回答', enabled: capabilitiesValue.agent_llm },
    { label: '关注名单', enabled: capabilitiesValue.watchlist },
    { label: '转会情报', enabled: capabilitiesValue.transfer_intelligence },
  ]
})

const importColumns: TableColumn<ImportJob>[] = [
  { prop: 'received_at', label: '接收时间', width: 146, formatter: (row) => formatDateTime(row.received_at) },
  { prop: 'source', label: '来源', width: 108, formatter: (row) => sourceLabel(row.source) },
  { prop: 'status', label: '状态', width: 88, formatter: (row) => importStatusLabel(row.status) },
  { prop: 'player_count', label: '球员', width: 76, align: 'right' },
  { prop: 'transfer_count', label: '交易', width: 76, align: 'right' },
  {
    prop: 'warnings',
    label: '警告',
    width: 76,
    align: 'right',
    formatter: (row) => (row.warnings.length === 0 ? '0' : String(row.warnings.length)),
  },
  { prop: 'scan_id', label: 'scan_id', width: 190, formatter: (row) => displayText(row.scan_id) },
  { prop: 'raw_payload_path', label: '原始报文', minWidth: 220, showOverflowTooltip: true, formatter: (row) => displayText(row.raw_payload_path) },
]

/** 预览用的样例球员列：证明适配层把哪些字段落到了协议上。 */
const fmscoutPreviewColumns: TableColumn<FmscoutSamplePlayer>[] = [
  { prop: 'name', label: '球员', minWidth: 160 },
  { prop: 'age', label: '年龄', width: 64, align: 'right' },
  { prop: 'position', label: '位置', width: 88 },
  { prop: 'ca', label: 'CA', width: 60, align: 'right' },
  { prop: 'pa', label: 'PA', width: 60, align: 'right' },
  { prop: 'market_value', label: '身价', width: 110, align: 'right', formatter: (row) => formatMoney(row.market_value) },
  { prop: 'wage', label: '工资', width: 100, align: 'right', formatter: (row) => formatMoney(row.wage) },
  { prop: 'contract_end', label: '合同到期', width: 108 },
  { prop: 'attributes', label: '属性数', width: 84, align: 'right', formatter: (row) => String(Object.keys(row.attributes).length) },
]

const compatibilityColumns: TableColumn<CompatibilityItem>[] = [  { prop: 'app_id', label: 'App ID', width: 110, formatter: (row) => displayText(row.app_id) },
  { prop: 'build_id', label: 'Build ID', width: 130, formatter: (row) => displayText(row.build_id) },
  { prop: 'plugin_version', label: '读取器版本', width: 150, formatter: (row) => displayText(row.plugin_version) },
  { prop: 'status', label: '状态', width: 100 },
  { prop: 'notes', label: '备注', minWidth: 220, formatter: (row) => displayText(row.notes) },
]

/** Coverage entries with an explicit value type for the template. */
function coverageEntries(map: Record<string, number | null> | null | undefined): Array<[string, number | null]> {
  return Object.entries(map ?? {})
}

/** Stable key for compatibility rows (app + build can repeat across plugin versions). */
function compatibilityKey(row: CompatibilityItem): string {
  return `${row.app_id ?? 'unknown'}-${row.build_id ?? 'unknown'}-${row.plugin_version ?? 'unknown'}`
}

/** Load import history, save summary and overview coverage. */
async function loadDataset(): Promise<void> {
  const saveId = session.activeSaveId
  importsLoading.value = true
  importsError.value = null
  summaryLoading.value = true
  summaryError.value = null
  overviewLoading.value = true
  overviewError.value = null

  await Promise.all([
    (async () => {
      try {
        const response = await listImports({ save_id: saveId ?? undefined, limit: 50 })
        imports.value = response.items ?? []
        session.markSources(imports.value.map((job) => job.source))
      } catch (caught) {
        importsError.value = asApiError(caught)
        imports.value = []
      } finally {
        importsLoading.value = false
      }
    })(),
    (async () => {
      if (saveId === null) {
        summary.value = null
        summaryLoading.value = false
        return
      }
      try {
        summary.value = await getSaveSummary(saveId)
      } catch (caught) {
        summaryError.value = asApiError(caught)
        summary.value = null
      } finally {
        summaryLoading.value = false
      }
    })(),
    (async () => {
      try {
        overview.value = await getOverview(saveId ?? undefined)
      } catch (caught) {
        overviewError.value = asApiError(caught)
        overview.value = null
      } finally {
        overviewLoading.value = false
      }
    })(),
  ])
}

/** Load the compatibility list. */
async function loadCompatibility(): Promise<void> {
  compatibilityLoading.value = true
  compatibilityError.value = null
  try {
    compatibility.value = await getCompatibility()
  } catch (caught) {
    compatibilityError.value = asApiError(caught)
    compatibility.value = null
  } finally {
    compatibilityLoading.value = false
  }
}

/** Upload one scan file through `POST /imports/scan` (multipart `file`). */
async function runUpload(file: File): Promise<void> {
  uploading.value = true
  uploadError.value = null
  uploadResult.value = null
  try {
    const result = await uploadScan(file)
    uploadResult.value = result
    if (result.duplicate) {
      ElMessage.warning(`该 scan_id 已导入过（duplicate=true），后端未写入任何数据`)
    } else if (result.status === 'partial') {
      ElMessage.warning(`导入部分成功：${formatInt(result.rows_rejected)} 行被拒绝，详见下方错误列表`)
    } else {
      ElMessage.success('导入完成')
    }
    await loadDataset()
    await session.load()
  } catch (caught) {
    uploadError.value = asApiError(caught)
    ElMessage.error(`导入失败：${uploadError.value.message}`)
  } finally {
    uploading.value = false
  }
}

/** Element Plus upload hook: take the raw file and post it manually. */
function handleUpload(options: UploadRequestOptions): Promise<void> {
  return runUpload(options.file)
}

/** Convert a dump and show the field-mapping report without writing anything. */
async function runFmscoutPreview(file: File): Promise<void> {
  fmscoutBusy.value = true
  fmscoutError.value = null
  fmscoutReport.value = null
  fmscoutImport.value = null
  fmscoutPreviewPlayers.value = []
  try {
    const result = await previewFmscoutDump(file)
    fmscoutReport.value = result.report
    fmscoutPreviewPlayers.value = result.sample_players
    ElMessage.success(`映射预览完成：可导入 ${formatInt(result.report.players_converted)} 名球员`)
  } catch (caught) {
    fmscoutError.value = asApiError(caught)
    ElMessage.error(`预览失败：${fmscoutError.value.message}`)
  } finally {
    fmscoutBusy.value = false
  }
}

/** Convert and import a dump; the backend deduplicates on the dump's content hash. */
async function runFmscoutImport(file: File): Promise<void> {
  fmscoutBusy.value = true
  fmscoutError.value = null
  try {
    const result = await importFmscoutDump(file, session.activeSaveId ?? undefined)
    fmscoutReport.value = result.report
    fmscoutImport.value = result.import
    fmscoutPreviewPlayers.value = []
    if (result.import.duplicate) {
      ElMessage.warning('这份导出已经导入过，后端未写入新数据')
    } else {
      ElMessage.success(
        `导入完成：新建 ${formatInt(result.import.players_created)} 名球员、${formatInt(result.import.snapshots_created)} 个快照`,
      )
    }
    await loadDataset()
    await session.load()
  } catch (caught) {
    fmscoutError.value = asApiError(caught)
    ElMessage.error(`导入失败：${fmscoutError.value.message}`)
  } finally {
    fmscoutBusy.value = false
  }
}

/** 真实数据审查（P0-1）：只读检查，不写库。 */
async function runFmscoutValidate(file: File): Promise<void> {
  fmscoutBusy.value = true
  fmscoutError.value = null
  validation.value = null
  try {
    validation.value = await validateFmscoutDump(file)
    const status = validation.value.verdict.status
    if (status === 'blocked') ElMessage.error('审查发现阻塞项，先不要导入')
    else if (status === 'review') ElMessage.warning('审查有需要复核的项，见下方报告')
    else ElMessage.success('审查通过，可以导入')
  } catch (caught) {
    fmscoutError.value = asApiError(caught)
    ElMessage.error(`审查失败：${fmscoutError.value.message}`)
  } finally {
    fmscoutBusy.value = false
  }
}

/** See {@link runFmscoutValidate}. */
function handleFmscoutValidate(options: UploadRequestOptions): Promise<void> {
  return runFmscoutValidate(options.file)
}

/** Upload hooks for the two FMSuperScout actions. */
function handleFmscoutPreview(options: UploadRequestOptions): Promise<void> {
  return runFmscoutPreview(options.file)
}

/** See {@link handleFmscoutPreview}. */
function handleFmscoutImport(options: UploadRequestOptions): Promise<void> {
  return runFmscoutImport(options.file)
}

/** Reload everything on this page. */
function reloadAll(): void {
  void loadDataset()
  void loadCompatibility()
  void loadFmscoutInfo()
}

watch(
  [() => session.activeSaveId, () => session.dataRevision],
  () => {
    void loadDataset()
  },
  { immediate: true },
)

void loadCompatibility()

/** Adapter metadata: upstream identity, license and the field policy. */
async function loadFmscoutInfo(): Promise<void> {
  try {
    fmscoutInfo.value = await getFmscoutAdapter()
  } catch {
    fmscoutInfo.value = null
  }
}

void loadFmscoutInfo()
</script>

<template>
  <div class="sm-page">
    <PageHeader
      title="数据与诊断"
      description="导入扫描报文、查看覆盖度与兼容性，并确认当前数据是否可用于真实决策。"
    >
      <template #meta>
        <el-tag size="small" :type="session.hasRealScanData ? 'success' : 'warning'" disable-transitions>
          {{ session.hasRealScanData ? '已有真实扫描数据' : '尚无真实扫描数据' }}
        </el-tag>
        <el-tag v-if="session.demoMode" size="small" type="warning" disable-transitions>demo_mode = true</el-tag>
        <span class="sm-text-xs sm-text-faint">
          后端版本 {{ session.version }} · 存档 {{ session.activeSave ? session.activeSave.name : EMPTY }}
        </span>
      </template>
      <template #actions>
        <el-button size="small" :loading="importsLoading" @click="reloadAll">刷新</el-button>
      </template>
    </PageHeader>

    <el-alert
      v-if="!session.hasRealScanData"
      type="warning"
      :closable="false"
      show-icon
      class="real-data-warning"
    >
      <template #title>
        <span class="sm-text-xs">
          当前没有真实 FM27 扫描数据：页面中的数值要么为空，要么来自 demo_mode 演示数据（source =
          synthetic_fixture），不可用于真实决策。
        </span>
      </template>
    </el-alert>

    <SectionCard title="上传扫描数据" subtitle="支持 .json 与 .ndjson（multipart 字段名 file）">
      <div class="upload-layout">
        <el-upload
          class="uploader"
          drag
          accept=".json,.ndjson,application/json,application/x-ndjson"
          :show-file-list="false"
          :disabled="uploading"
          :http-request="handleUpload"
        >
          <div class="uploader__inner">
            <p class="uploader__title">拖入扫描文件，或点击选择</p>
            <p class="uploader__hint">
              JSON 为单对象报文；NDJSON 首行为 header，其后每行一条实体。同一 scan_id 重复导入会返回
              duplicate=true 且不写入数据。
            </p>
          </div>
        </el-upload>

        <div class="upload-meta">
          <p class="sm-label">当前能力</p>
          <div class="capability-list">
            <el-tag
              v-for="capability in capabilities"
              :key="capability.label"
              size="small"
              :type="capability.enabled ? 'success' : 'info'"
              disable-transitions
            >
              {{ capability.label }} {{ capability.enabled ? '启用' : '未启用' }}
            </el-tag>
          </div>
          <p class="sm-text-2xs sm-text-faint">
            数据源记录数：{{ session.dataSources.length === 0 ? EMPTY : session.dataSources.map((entry) => `${sourceLabel(entry.source)} ${formatInt(entry.records)}`).join(' · ') }}
          </p>
        </div>
      </div>

      <div v-if="uploading" class="sm-stack upload-pending">
        <el-skeleton :rows="3" animated />
      </div>

      <ErrorState v-if="uploadError" :error="uploadError" compact :show-retry="false" />

      <div v-if="uploadResult" class="upload-result">
        <el-alert
          :type="uploadResult.duplicate ? 'warning' : uploadResult.status === 'partial' ? 'warning' : 'success'"
          :closable="false"
          show-icon
        >
          <template #title>
            <span class="sm-text-xs">
              导入任务 #{{ uploadResult.job_id }} · 状态 {{ importStatusLabel(uploadResult.status) }}
              <template v-if="uploadResult.duplicate"> · duplicate=true（未写入数据）</template>
            </span>
          </template>
        </el-alert>

        <div class="result-grid">
          <div class="result-cell">
            <span class="sm-label">新建球员</span>
            <span class="sm-num">{{ formatInt(uploadResult.players_created) }}</span>
          </div>
          <div class="result-cell">
            <span class="sm-label">更新球员</span>
            <span class="sm-num">{{ formatInt(uploadResult.players_updated) }}</span>
          </div>
          <div class="result-cell">
            <span class="sm-label">匹配实例</span>
            <span class="sm-num">{{ formatInt(uploadResult.instances_matched) }}</span>
          </div>
          <div class="result-cell">
            <span class="sm-label">新建快照</span>
            <span class="sm-num">{{ formatInt(uploadResult.snapshots_created) }}</span>
          </div>
          <div class="result-cell">
            <span class="sm-label">新建交易</span>
            <span class="sm-num">{{ formatInt(uploadResult.transfers_created) }}</span>
          </div>
          <div class="result-cell">
            <span class="sm-label">跳过交易</span>
            <span class="sm-num">{{ formatInt(uploadResult.transfers_skipped) }}</span>
          </div>
          <div class="result-cell">
            <span class="sm-label">拒绝行</span>
            <span class="sm-num">{{ formatInt(uploadResult.rows_rejected) }}</span>
          </div>
          <div class="result-cell">
            <span class="sm-label">scan_id</span>
            <span class="sm-mono">{{ displayText(uploadResult.scan_id) }}</span>
          </div>
        </div>

        <div v-if="Object.keys(uploadResult.coverage ?? {}).length > 0" class="result-coverage">
          <CoverageBar
            v-for="[key, value] in Object.entries(uploadResult.coverage ?? {})"
            :key="key"
            :label="coverageLabel(key)"
            :value="value"
            dense
          />
        </div>

        <ul v-if="uploadResult.warnings.length > 0" class="warnings-list">
          <li v-for="warning in uploadResult.warnings" :key="warning">{{ warning }}</li>
        </ul>

        <div v-if="uploadResult.errors.length > 0" class="errors">
          <p class="sm-label">被拒绝的行（{{ uploadResult.errors.length }}）</p>
          <table class="error-table">
            <thead>
              <tr>
                <th>行号</th>
                <th>实体</th>
                <th>错误码</th>
                <th>说明</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(error, index) in uploadResult.errors" :key="`${error.code}-${index}`">
                <td class="sm-num">{{ formatInt(error.row) }}</td>
                <td>{{ displayText(error.entity) }}</td>
                <td class="sm-mono">{{ error.code }}</td>
                <td>{{ error.message }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <template #footer>
        导入按 `docs/DATA_PROTOCOL.md` 校验：缺 save_local_uid/name 的行被拒绝并记录，不会用默认值填充；部分失败时
        status=partial。
      </template>
    </SectionCard>

    <SectionCard
      title="FMSuperScout 接入"
      subtitle="第三方开源读取器（MIT）导出的 dump 由适配层转换成本系统的扫描协议；只读文件，不改游戏、存档或对方数据，并给出字段映射报告"
    >
      <div class="fmscout">
        <div class="fmscout__actions">
          <el-upload
            class="fmscout__uploader"
            accept=".json,application/json"
            :show-file-list="false"
            :disabled="fmscoutBusy"
            :http-request="handleFmscoutPreview"
          >
            <el-button size="small" :loading="fmscoutBusy">预览字段映射</el-button>
          </el-upload>
          <el-upload
            class="fmscout__uploader"
            accept=".json,application/json"
            :show-file-list="false"
            :disabled="fmscoutBusy"
            :http-request="handleFmscoutImport"
          >
            <el-button size="small" type="primary" :loading="fmscoutBusy">转换并导入</el-button>
          </el-upload>
          <el-upload
            class="fmscout__uploader"
            accept=".json,application/json"
            :show-file-list="false"
            :disabled="fmscoutBusy"
            :http-request="handleFmscoutValidate"
          >
            <el-button size="small" :loading="fmscoutBusy">真实数据审查</el-button>
          </el-upload>
          <span class="sm-text-2xs sm-text-faint">
            也可以直接把 dump 文件拖到上方「上传扫描数据」，后端会自动识别来源
          </span>
        </div>

        <p v-if="fmscoutInfo" class="sm-text-2xs sm-text-faint">
          上游 <a :href="fmscoutInfo.upstream.url" target="_blank" rel="noreferrer">{{ fmscoutInfo.upstream.name }}</a>
          ·{{ fmscoutInfo.upstream.license }} ·适配器 v{{ fmscoutInfo.version }} ·{{ fmscoutInfo.upstream.note }}
        </p>

        <ErrorState v-if="fmscoutError" :error="fmscoutError" compact title="FMSuperScout 处理失败" />
        <EmptyState
          v-else-if="!fmscoutReport && !fmscoutBusy"
          title="还没有导入过 FMSuperScout 数据"
          description="在 FMSuperScout 里按 F9 导出，然后选择该 dump 文件预览或导入"
        />

        <div v-if="validation" class="fmscout__validation">
          <el-alert
            :type="validation.verdict.status === 'pass' ? 'success' : validation.verdict.status === 'review' ? 'warning' : 'error'"
            :closable="false"
            show-icon
            :title="`审查结论：${validation.verdict.status} · ${validation.verdict.ready_to_import ? '可以导入' : '先处理阻塞项'}`"
          >
            <ul v-if="validation.verdict.blockers.length > 0" class="fmscout__list">
              <li v-for="item in validation.verdict.blockers" :key="item">阻塞：{{ item }}</li>
            </ul>
            <ul v-if="validation.verdict.review.length > 0" class="fmscout__list">
              <li v-for="item in validation.verdict.review" :key="item">复核：{{ item }}</li>
            </ul>
          </el-alert>
          <div class="fmscout__sections">
            <div v-for="section in validation.sections" :key="section.id" class="fmscout__section">
              <p class="sm-label">{{ section.title }}</p>
              <ul class="fmscout__list">
                <li v-for="row in section.rows" :key="`${section.id}-${row.label}`">
                  <span>{{ row.label }}</span>
                  <strong class="sm-num">{{ row.value }}</strong>
                  <span v-if="row.detail" class="sm-text-2xs sm-text-faint">{{ row.detail }}</span>
                </li>
              </ul>
            </div>
          </div>
        </div>

        <template v-if="fmscoutReport">
          <div class="fmscout__summary">
            <span>导出时间 {{ displayText(fmscoutReport.dump_generated) }}</span>
            <span>球员 {{ formatInt(fmscoutReport.players_converted) }} / {{ formatInt(fmscoutReport.players_total) }}</span>
            <span>球队 {{ formatInt(fmscoutReport.clubs_converted) }}</span>
            <span>我的俱乐部 {{ displayText(fmscoutReport.user_club) }}</span>
            <span>映射属性 {{ formatInt(fmscoutReport.attributes_mapped) }}</span>
            <span v-if="fmscoutReport.players_skipped > 0">跳过幽灵记录 {{ formatInt(fmscoutReport.players_skipped) }}</span>
          </div>

          <div v-if="fmscoutImport" class="fmscout__result">
            <el-alert
              :type="fmscoutImport.duplicate ? 'warning' : 'success'"
              :closable="false"
              show-icon
              :title="
                fmscoutImport.duplicate
                  ? `这份导出已导入过（scan_id=${displayText(fmscoutImport.scan_id)}），未写入新数据`
                  : `导入完成：新建球员 ${formatInt(fmscoutImport.players_created)}、快照 ${formatInt(fmscoutImport.snapshots_created)}、拒绝 ${formatInt(fmscoutImport.rows_rejected)}`
              "
            />
          </div>

          <div class="fmscout__grid">
            <div>
              <p class="sm-label">已映射字段</p>
              <p class="sm-text-xs sm-text-2">{{ fmscoutReport.mapped_fields.join('、') || EMPTY }}</p>
            </div>
            <div>
              <p class="sm-label">导出中不存在的字段（相关功能显示为不可用）</p>
              <p class="sm-text-xs sm-text-2">{{ fmscoutReport.absent_fields.join('、') || EMPTY }}</p>
            </div>
            <div>
              <p class="sm-label">忽略的属性</p>
              <p class="sm-text-xs sm-text-2">{{ fmscoutReport.attributes_ignored.join('、') || EMPTY }}</p>
            </div>
            <div>
              <p class="sm-label">字段覆盖率</p>
              <p class="sm-text-xs sm-text-2">
                {{
                  Object.entries(fmscoutReport.coverage)
                    .map(([key, value]) => `${key} ${formatPercent(value, 0)}`)
                    .join(' · ') || EMPTY
                }}
              </p>
            </div>
          </div>

          <el-collapse v-if="fmscoutReport.ignored_fields.length > 0" class="fmscout__ignored">
            <el-collapse-item :title="`被忽略的字段（${fmscoutReport.ignored_fields.length}）`" name="ignored">
              <ul class="fmscout__list">
                <li v-for="item in fmscoutReport.ignored_fields" :key="item.field">
                  <span class="sm-mono">{{ item.field }}</span> — {{ item.reason }}
                </li>
              </ul>
            </el-collapse-item>
          </el-collapse>

          <ul v-if="fmscoutReport.warnings.length > 0" class="fmscout__list">
            <li v-for="warning in fmscoutReport.warnings" :key="warning">{{ warning }}</li>
          </ul>

          <DataTable
            v-if="fmscoutPreviewPlayers.length > 0"
            :columns="fmscoutPreviewColumns"
            :rows="fmscoutPreviewPlayers"
            row-key="save_local_uid"
            dense
            :show-pagination="false"
            caption="转换后的样例球员（预览模式不写库）"
          />
        </template>
      </div>
    </SectionCard>

    <div class="sm-grid sm-grid--wide-left">
      <SectionCard title="导入历史" subtitle="后端保留原始报文路径，便于重新解析" flush>
        <DataTable
          :columns="importColumns"
          :rows="imports"
          :loading="importsLoading"
          :error="importsError"
          row-key="id"
          expandable
          :empty-title="imports.length === 0 ? '还没有导入记录' : '暂无数据'"
          empty-description="导入第一份扫描文件后，这里会显示每次导入的状态、计数与警告。"
          @retry="loadDataset"
        >
          <template #expand="{ row }">
            <div class="import-detail">
              <p class="sm-text-2xs sm-text-faint">
                scan_id {{ displayText(row.scan_id) }} · 原始报文 {{ displayText(row.raw_payload_path) }} ·
                完成于 {{ formatDateTime(row.finished_at) }}
              </p>
              <ul v-if="row.warnings.length > 0" class="warnings-list">
                <li v-for="warning in row.warnings" :key="warning">{{ warning }}</li>
              </ul>
              <p v-else class="sm-text-2xs sm-text-faint">该任务没有警告。</p>
              <div v-if="row.coverage" class="import-coverage">
                <CoverageBar
                  v-for="[key, value] in coverageEntries(row.coverage)"
                  :key="key"
                  :label="coverageLabel(key)"
                  :value="value"
                  dense
                />
              </div>
            </div>
          </template>
        </DataTable>
      </SectionCard>

      <SectionCard title="数据覆盖度" subtitle="记录数与字段非空比例">
        <div v-if="summaryLoading && !summary" class="sm-stack">
          <el-skeleton :rows="4" animated />
        </div>
        <ErrorState v-else-if="summaryError" :error="summaryError" compact @retry="loadDataset" />
        <template v-else>
          <div class="coverage-counts">
            <div v-for="count in summaryCounts" :key="count.label" class="coverage-count">
              <span class="sm-label">{{ count.label }}</span>
              <span class="sm-num">{{ formatInt(count.value) }}</span>
            </div>
          </div>
          <p v-if="summaryCounts.length === 0" class="sm-text-2xs sm-text-faint">存档摘要中未返回记录数。</p>

          <hr class="sm-divider" />

          <div v-if="overviewLoading && !overview" class="sm-stack">
            <el-skeleton :rows="3" animated />
          </div>
          <ErrorState v-else-if="overviewError" :error="overviewError" compact @retry="loadDataset" />
          <div v-else-if="fieldCoverage.length === 0">
            <EmptyState
              title="字段覆盖度不可用"
              description="概览接口没有返回 coverage 字段，通常是因为尚未导入扫描数据。"
              compact
            />
          </div>
          <div v-else class="coverage-list">
            <CoverageBar
              v-for="[key, value] in fieldCoverage"
              :key="key"
              :label="coverageLabel(key)"
              :value="value"
              dense
            />
          </div>
        </template>
        <template #footer>
          最近导入 {{ formatDateTime(summary?.last_import?.finished_at ?? null) }} ·
          覆盖度低于 60% 时相关统计会不稳定
        </template>
      </SectionCard>
    </div>

    <SectionCard title="客户端兼容性" subtitle="读取器版本与游戏 build 的已知组合" flush>
      <DataTable
        :columns="compatibilityColumns"
        :rows="compatibility?.items ?? []"
        :loading="compatibilityLoading"
        :error="compatibilityError"
        :row-key="compatibilityKey"
        dense
        :empty-title="compatibilityLoading ? '正在加载' : '没有兼容性记录'"
        empty-description="后端 /compatibility 未返回任何记录；导入前请先用 Live Reader 的 probe 命令确认版本。"
        @retry="loadCompatibility"
      >
        <template #cell="{ row, column }">
          <template v-if="column.prop === 'status'">
            <el-tag
              size="small"
              :type="row.status === 'verified' ? 'success' : row.status === 'unsupported' ? 'danger' : 'warning'"
              disable-transitions
            >
              {{ row.status === 'verified' ? '已验证' : row.status === 'unsupported' ? '不支持' : row.status === 'candidate' ? '待验证' : row.status }}
            </el-tag>
          </template>
          <template v-else>
            {{ column.formatter ? column.formatter(row) : EMPTY }}
          </template>
        </template>
        <template #toolbar>
          <span class="sm-text-2xs sm-text-faint">读取器版本：</span>
          <el-tag
            v-for="version in compatibility?.reader_versions ?? []"
            :key="version"
            size="small"
            type="info"
            disable-transitions
          >
            {{ version }}
          </el-tag>
          <span v-if="(compatibility?.reader_versions ?? []).length === 0" class="sm-text-2xs sm-text-faint">未上报</span>
        </template>
      </DataTable>
    </SectionCard>

    <SectionCard title="如何生成真实数据" subtitle="Live Reader CLI 是当前唯一的真实数据来源">
      <div class="cli-layout">
        <div class="sm-stack sm-stack--tight">
          <p class="sm-label">命令</p>
          <pre class="sm-code">ScoutMind.LiveReader.exe status
ScoutMind.LiveReader.exe probe
ScoutMind.LiveReader.exe scan --out D:\scans\scan.json</pre>
          <p class="sm-text-2xs sm-text-faint">
            status 检查进程与读取器状态；probe 探测游戏 build 与兼容性；scan 输出符合 DATA_PROTOCOL v1 的扫描报文。
          </p>
        </div>
        <ol class="steps">
          <li>启动 FM27 并进入存档，保持游戏运行。</li>
          <li>运行 status / probe，确认版本出现在上方兼容性列表中。</li>
          <li>运行 scan 生成 .json（或 .ndjson）扫描文件。</li>
          <li>把文件拖入本页「上传扫描数据」，等待任务状态变为 succeeded / partial。</li>
          <li>回到概览与球员中心，确认球员数、快照数与覆盖度已更新。</li>
        </ol>
      </div>
      <template #footer>
        未导入扫描文件之前，界面不会显示任何伪造的球员或成交数据；demo_mode 下的 synthetic_fixture 记录会带横幅提示。
        派生的统计（分位数、估值、角色评分）都要求足够的真实样本。
      </template>
    </SectionCard>

    <p class="page-note">
      诊断提示：所有错误响应遵循 <code>{"error": {"code", "message", "details"}}</code> 结构；401 表示缺少
      X-ScoutMind-Token，503 表示数据库不可用。后端地址由 Vite 代理 <code>/api</code> → 127.0.0.1:8000 提供。
    </p>
  </div>
</template>

<style scoped>
.fmscout {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-3);
}

.fmscout__actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--sm-space-2);
}

.fmscout__uploader {
  display: inline-flex;
}

.fmscout__summary {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sm-space-4);
  padding: var(--sm-space-2) var(--sm-space-3);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-md);
  background: var(--sm-surface-2);
  font-size: var(--sm-fs-xs);
  color: var(--sm-text-2);
}

.fmscout__grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: var(--sm-space-3);
}

.fmscout__list {
  margin: 0;
  padding-left: var(--sm-space-4);
  font-size: var(--sm-fs-xs);
  line-height: 1.65;
  color: var(--sm-text-2);
}

.fmscout__validation {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-3);
}

.fmscout__sections {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: var(--sm-space-3);
}

.fmscout__section {
  padding: var(--sm-space-3);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-md);
  background: var(--sm-surface-2);
}

.fmscout__section .fmscout__list li {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--sm-space-2);
}

.fmscout__ignored {
  border-top: 1px solid var(--sm-border);
  padding-top: var(--sm-space-2);
}
.real-data-warning {
  margin-bottom: 0;
}

.upload-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.6fr) minmax(280px, 1fr);
  gap: var(--sm-space-4);
}

.uploader :deep(.el-upload-dragger) {
  padding: var(--sm-space-5) var(--sm-space-4);
  border-radius: var(--sm-radius-md);
  background: var(--sm-surface-2);
}

.uploader__title {
  color: var(--sm-text);
  font-size: var(--sm-fs-sm);
  font-weight: var(--sm-fw-medium);
}

.uploader__hint {
  margin-top: var(--sm-space-1);
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
  line-height: 1.6;
}

.upload-meta {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-2);
  min-width: 0;
}

.capability-list {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sm-space-1);
}

.upload-pending {
  margin-top: var(--sm-space-3);
}

.upload-result {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-3);
  margin-top: var(--sm-space-4);
  padding-top: var(--sm-space-3);
  border-top: 1px solid var(--sm-border);
}

.result-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(128px, 1fr));
  gap: var(--sm-space-2);
}

.result-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--sm-space-2);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-md);
  background: var(--sm-surface-2);
  font-size: var(--sm-fs-sm);
}

.result-cell .sm-num {
  font-weight: var(--sm-fw-semibold);
}

.result-coverage {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: var(--sm-space-2);
}

.warnings-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin: 0;
  padding-left: var(--sm-space-4);
  color: var(--sm-warn);
  font-size: var(--sm-fs-2xs);
  line-height: 1.6;
}

.errors {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-1);
}

.error-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--sm-fs-xs);
}

.error-table th,
.error-table td {
  padding: var(--sm-space-1) var(--sm-space-2);
  border-bottom: 1px solid var(--sm-border);
  text-align: left;
}

.error-table th {
  color: var(--sm-text-3);
  font-weight: var(--sm-fw-medium);
}

.import-detail {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-2);
}

.import-coverage {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: var(--sm-space-2);
}

.coverage-counts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--sm-space-2);
  margin-bottom: var(--sm-space-3);
}

.coverage-count {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--sm-space-2);
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-md);
  background: var(--sm-surface-2);
  font-size: var(--sm-fs-lg);
  font-weight: var(--sm-fw-semibold);
}

.coverage-list {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-2);
}

.cli-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr);
  gap: var(--sm-space-4);
}

.steps {
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-1);
  margin: 0;
  padding-left: var(--sm-space-4);
  color: var(--sm-text-2);
  font-size: var(--sm-fs-xs);
  line-height: 1.7;
}

.page-note {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
  line-height: 1.7;
}

.page-note code {
  padding: 0 3px;
  border-radius: 3px;
  background: var(--sm-surface-3);
  font-family: var(--sm-font-mono);
}

@media (max-width: 1180px) {
  .upload-layout,
  .cli-layout {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>

