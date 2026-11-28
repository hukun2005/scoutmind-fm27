/**
 * Shared data table.
 *
 * Renders a native table element instead of Element Plus' table component so
 * column widths, sticky headers, sorting indicators and keyboard activation stay
 * under our control; Element Plus supplies the surrounding controls (pagination,
 * loading overlay). Views only declare columns and cells.
 */

<script setup lang="ts" generic="TRow extends object">
import { computed, ref, watch } from 'vue'
import type { ApiError } from '../api/client'
import type { TableColumn, TableSortPayload } from '../types/table'
import { EMPTY } from '../utils/format'
import EmptyState from './EmptyState.vue'
import ErrorState from './ErrorState.vue'
import LoadingBlock from './LoadingBlock.vue'

const props = withDefaults(
  defineProps<{
    /** Column definitions, rendered in order. */
    columns: TableColumn<TRow>[]
    /** Rows returned by the API (already paged by the server). */
    rows: readonly TRow[]
    /** Row property holding a stable key, or a key function. */
    rowKey?: string | ((row: TRow) => string)
    /** First load in progress; renders a skeleton instead of the table. */
    loading?: boolean
    /** Normalized failure; replaces the table with a retry panel. */
    error?: ApiError | null
    /** Total row count reported by the server. */
    total?: number
    /** Current 1-based page. */
    page?: number
    /** Rows per page. */
    pageSize?: number
    /** Page size options. */
    pageSizes?: number[]
    /** Render the pagination footer. */
    showPagination?: boolean
    /** Empty-state heading. */
    emptyTitle?: string
    /** Empty-state explanation (why there is no data, what to change). */
    emptyDescription?: string
    /** Dense row height. */
    dense?: boolean
    /** Emit `row-click` and make rows focusable. */
    clickable?: boolean
    /** Enable the expand column; content comes from the `expand` slot. */
    expandable?: boolean
    /** Initial server sort indicator. */
    initialSort?: { prop: string; order: 'ascending' | 'descending' } | null
    /** Extra class per row. */
    rowClass?: (row: TRow, index: number) => string
    /** Maximum table height before vertical scrolling. */
    maxHeight?: number | string
    /** Accessible table caption. */
    caption?: string
  }>(),
  {
    rowKey: 'id',
    loading: false,
    error: null,
    total: 0,
    page: 1,
    pageSize: 50,
    pageSizes: () => [25, 50, 100, 200],
    showPagination: false,
    emptyTitle: '暂无数据',
    emptyDescription: '',
    dense: false,
    clickable: false,
    expandable: false,
    initialSort: null,
    rowClass: undefined,
    maxHeight: undefined,
    caption: '',
  },
)

const emit = defineEmits<{
  (event: 'update:page', value: number): void
  (event: 'update:pageSize', value: number): void
  (event: 'sort-change', payload: TableSortPayload): void
  (event: 'row-click', row: TRow): void
  (event: 'expand-change', row: TRow, expanded: boolean): void
  (event: 'retry'): void
}>()

const sortProp = ref<string>(props.initialSort?.prop ?? '')
const sortOrder = ref<'ascending' | 'descending' | null>(props.initialSort?.order ?? null)
const expandedKeys = ref<string[]>([])

/** Scroll container style with the configured maximum height. */
const scrollStyle = computed(() => {
  if (props.maxHeight === undefined) return {}
  return { maxHeight: typeof props.maxHeight === 'number' ? `${props.maxHeight}px` : props.maxHeight }
})

/** Stable key of a row, falling back to its index when no key is configured. */
function keyOf(row: TRow, index: number): string {
  if (typeof props.rowKey === 'function') return props.rowKey(row)
  const value = Reflect.get(row, props.rowKey)
  return value === undefined || value === null ? String(index) : String(value)
}

/** Text fallback for a column without a formatter. */
function scalarText(value: unknown): string {
  if (value === null || value === undefined) return EMPTY
  if (typeof value === 'string') return value.trim() === '' ? EMPTY : value
  if (typeof value === 'number') return Number.isFinite(value) ? String(value) : EMPTY
  if (typeof value === 'boolean') return value ? '是' : '否'
  return EMPTY
}

/** Default cell text; `—` for every absent value. */
function cellText(row: TRow, column: TableColumn<TRow>): string {
  if (column.formatter) return column.formatter(row)
  return scalarText(Reflect.get(row, column.prop))
}

/** Width used for a column: explicit width, then minimum width, then 96px. */
function columnWidth(column: TableColumn<TRow>): string {
  return `${column.width ?? column.minWidth ?? 96}px`
}

/** `aria-sort` value for a header cell. */
function ariaSort(column: TableColumn<TRow>): 'ascending' | 'descending' | 'none' | undefined {
  if (!column.sortable) return undefined
  if (sortProp.value !== column.prop) return 'none'
  return sortOrder.value === 'ascending' ? 'ascending' : 'descending'
}

/** Direction glyph of a sorted column; unsorted columns show no glyph. */
function sortGlyph(column: TableColumn<TRow>): string {
  if (sortProp.value !== column.prop || sortOrder.value === null) return ''
  return sortOrder.value === 'ascending' ? '↑' : '↓'
}

/** Cycle ascending → descending → cleared for a sortable column. */
function toggleSort(column: TableColumn<TRow>): void {
  if (!column.sortable) return
  let nextOrder: 'ascending' | 'descending' | null
  if (sortProp.value !== column.prop) {
    sortProp.value = column.prop
    nextOrder = 'ascending'
  } else if (sortOrder.value === 'ascending') {
    nextOrder = 'descending'
  } else if (sortOrder.value === 'descending') {
    nextOrder = null
  } else {
    nextOrder = 'ascending'
  }
  sortOrder.value = nextOrder
  emit('sort-change', { prop: column.prop, order: nextOrder })
}

/** Open/close one expandable row and notify the screen. */
function toggleExpand(row: TRow, index: number): void {
  const key = keyOf(row, index)
  const isExpanded = expandedKeys.value.includes(key)
  expandedKeys.value = isExpanded
    ? expandedKeys.value.filter((item) => item !== key)
    : [...expandedKeys.value, key]
  emit('expand-change', row, !isExpanded)
}

/** Whether the row is expanded. */
function isExpanded(row: TRow, index: number): boolean {
  return expandedKeys.value.includes(keyOf(row, index))
}

function onRowClick(row: TRow): void {
  if (!props.clickable) return
  emit('row-click', row)
}

/** Enter/Space activates a focused row. */
function onRowKeydown(event: KeyboardEvent, row: TRow): void {
  if (!props.clickable) return
  if (event.key !== 'Enter' && event.key !== ' ') return
  event.preventDefault()
  emit('row-click', row)
}

function onPageChange(value: number): void {
  emit('update:page', value)
}

function onPageSizeChange(value: number): void {
  emit('update:pageSize', value)
}

/** Collapse expanded rows when the dataset changes (page, filters, sort). */
watch(
  () => props.rows,
  () => {
    expandedKeys.value = []
  },
)
</script>

<template>
  <div class="sm-table" :class="{ 'sm-table--dense': dense, 'sm-table--clickable': clickable }">
    <div v-if="$slots.toolbar" class="sm-table__toolbar">
      <slot name="toolbar" />
    </div>

    <ErrorState v-if="error" :error="error" compact @retry="emit('retry')" />

    <LoadingBlock v-else-if="loading && rows.length === 0" :rows="6" compact />

    <template v-else>
      <slot v-if="rows.length === 0" name="empty">
        <EmptyState
          v-if="rows.length === 0"
          :title="emptyTitle"
          :description="emptyDescription"
          compact
        />
      </slot>
      <div v-else v-loading="loading" class="sm-table__scroll" :style="scrollStyle">
        <table class="sm-table__grid">
          <caption v-if="caption" class="sm-sr-only">{{ caption }}</caption>
          <colgroup>
            <col v-if="expandable" style="width: 40px" />
            <col v-for="column in columns" :key="column.prop" :style="{ width: columnWidth(column) }" />
          </colgroup>
          <thead>
            <tr>
              <th v-if="expandable" scope="col" class="sm-table__expand-head">
                <span class="sm-sr-only">展开明细</span>
              </th>
              <th
                v-for="column in columns"
                :key="column.prop"
                scope="col"
                :style="{ textAlign: column.headerAlign ?? column.align ?? 'left' }"
                :title="column.title ?? column.label"
                :aria-sort="ariaSort(column)"
              >
                <button
                  v-if="column.sortable"
                  type="button"
                  class="sm-table__sort"
                  :class="{ 'sm-table__sort--active': sortProp === column.prop }"
                  :title="`按${column.label}排序`"
                  @click="toggleSort(column)"
                >
                  <span class="sm-table__header">{{ column.label }}</span>
                  <span class="sm-table__sort-glyph" aria-hidden="true">{{ sortGlyph(column) }}</span>
                </button>
                <span v-else class="sm-table__header">{{ column.label }}</span>
              </th>
            </tr>
          </thead>
          <tbody v-for="(row, rowIndex) in rows" :key="keyOf(row, rowIndex)">
            <tr
              class="sm-table__row"
              :class="[rowClass ? rowClass(row, rowIndex) : '', { 'sm-table__row--clickable': clickable }]"
              :tabindex="clickable ? 0 : undefined"
              @click="onRowClick(row)"
              @keydown="onRowKeydown($event, row)"
            >
              <td v-if="expandable" class="sm-table__expand-cell">
                <button
                  type="button"
                  class="sm-table__expand"
                  :aria-expanded="isExpanded(row, rowIndex)"
                  :aria-label="isExpanded(row, rowIndex) ? '收起明细' : '展开明细'"
                  @click.stop="toggleExpand(row, rowIndex)"
                >
                  {{ isExpanded(row, rowIndex) ? '▾' : '▸' }}
                </button>
              </td>
              <td
                v-for="column in columns"
                :key="column.prop"
                :style="{ textAlign: column.align ?? 'left' }"
                :class="column.showOverflowTooltip ? 'sm-table__ellipsis' : ''"
              >
                <slot name="cell" :row="row" :column="column" :index="rowIndex" :value="cellText(row, column)">
                  {{ cellText(row, column) }}
                </slot>
              </td>
            </tr>
            <tr v-if="expandable && isExpanded(row, rowIndex)" class="sm-table__expansion">
              <td :colspan="columns.length + 1">
                <slot name="expand" :row="row" />
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="showPagination" class="sm-table__footer">
        <el-pagination
          :current-page="page"
          :page-size="pageSize"
          :page-sizes="pageSizes"
          :total="total"
          background
          size="small"
          layout="total, sizes, prev, pager, next, jumper"
          @current-change="onPageChange"
          @size-change="onPageSizeChange"
        />
      </div>
    </template>
  </div>
</template>

<style scoped>
.sm-table__scroll {
  overflow: auto;
  border-top: 1px solid var(--sm-border);
  border-bottom: 1px solid var(--sm-border);
}

.sm-table__grid {
  width: 100%;
  table-layout: fixed;
  border-collapse: separate;
  border-spacing: 0;
  font-size: var(--sm-fs-sm);
}

.sm-table__grid th,
.sm-table__grid td {
  padding: 7px var(--sm-space-3);
  border-bottom: 1px solid var(--sm-border);
  vertical-align: middle;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sm-table--dense .sm-table__grid th,
.sm-table--dense .sm-table__grid td {
  padding: 4px var(--sm-space-3);
}

.sm-table__grid thead th {
  position: sticky;
  top: 0;
  z-index: 1;
  background: var(--sm-surface-2);
  color: var(--sm-text-2);
  font-size: var(--sm-fs-2xs);
  font-weight: var(--sm-fw-semibold);
  letter-spacing: var(--sm-tracking-label);
  text-transform: uppercase;
  white-space: nowrap;
  border-bottom-color: var(--sm-border-strong);
}

.sm-table__grid tbody:last-child tr:last-child td {
  border-bottom: 0;
}

.sm-table__row {
  transition: background-color var(--sm-dur-1) var(--sm-ease-out);
}

.sm-table__row:hover td {
  background: var(--sm-surface-hover);
}

.sm-table__row--clickable {
  cursor: pointer;
}

.sm-table__row:focus-visible {
  outline: 2px solid var(--sm-accent-cyan);
  outline-offset: -2px;
}

.sm-table__header {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: bottom;
}

.sm-table__sort {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 0;
  border: 0;
  background: none;
  color: inherit;
  font: inherit;
  cursor: pointer;
}

.sm-table__sort-glyph {
  color: var(--sm-text-3);
  font-size: 10px;
}

.sm-table__sort--active .sm-table__sort-glyph {
  color: var(--sm-accent-cyan);
}

.sm-table__expand-head,
.sm-table__expand-cell {
  padding-right: 0;
  padding-left: var(--sm-space-2);
}

.sm-table__expand {
  width: 20px;
  height: 20px;
  padding: 0;
  border: 1px solid var(--sm-border-strong);
  border-radius: var(--sm-radius-xs);
  background: var(--sm-surface);
  color: var(--sm-text-2);
  font-size: 10px;
  line-height: 1;
  cursor: pointer;
}

.sm-table__expand:hover {
  border-color: var(--sm-accent-cyan);
  color: var(--sm-accent-cyan);
}

.sm-table__expansion > td {
  padding: var(--sm-space-3) var(--sm-space-4);
  background: var(--sm-surface-2);
  white-space: normal;
}

.sm-table__ellipsis {
  white-space: nowrap;
  text-overflow: ellipsis;
}
</style>
