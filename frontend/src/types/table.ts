/** Column and sort types for the shared `DataTable` wrapper. */

/** Cell alignment allowed by Element Plus tables. */
export type ColumnAlign = 'left' | 'center' | 'right'

/**
 * Declarative column definition.
 *
 * `formatter` produces the default cell text; a view can instead render a custom
 * cell through the `cell` slot and switch on `column.prop`.
 */
export interface TableColumn<TRow> {
  /** Row property name, also the column identity. */
  prop: string
  /** Header label (Chinese). */
  label: string
  /** Fixed width in px. */
  width?: number
  /** Minimum width in px; used for flexible columns. */
  minWidth?: number
  /** Body alignment. */
  align?: ColumnAlign
  /** Header alignment; defaults to `align`. */
  headerAlign?: ColumnAlign
  /** `true` sorts on the client, `'custom'` lets the server sort. */
  sortable?: boolean | 'custom'
  /** Default cell text; absent values must return `—`. */
  formatter?: (row: TRow) => string
  /** Full header text exposed through `title` when the label is long. */
  title?: string
  /** Pin the column while scrolling horizontally. */
  fixed?: boolean | 'left' | 'right'
  /** Extra class on the column. */
  className?: string
  /** Truncate overflowing cell text with an ellipsis plus a title attribute. */
  showOverflowTooltip?: boolean
}

/** Payload of the table `sort-change` event. */
export interface TableSortPayload {
  /** Column prop that was sorted. */
  prop: string
  /** Sort direction, or `null` when sorting was cleared. */
  order: 'ascending' | 'descending' | null
}
