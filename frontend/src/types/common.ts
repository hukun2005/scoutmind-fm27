/**
 * Cross-cutting wire types defined by `docs/API.md` §1.
 *
 * Missing values are always `null` on the wire and must render as `—`. These
 * types intentionally keep optional business fields nullable so the UI never
 * needs a truthiness guess to distinguish "unknown" from a real zero.
 */

/** Provenance of a player/transfer record, per §1 数据来源标记. */
export type DataSource =
  | 'fm27_live_reader'
  | 'fm_save_parser'
  | 'manual'
  | 'ocr'
  | 'external'
  | 'estimated'
  | 'synthetic_fixture'

/** Confidence labels returned by valuation, agent answers and similar-transfer lookups. */
export type ConfidenceLevel = 'low' | 'medium' | 'high'

/**
 * Coverage map: field name → ratio in `[0, 1]`.
 * Keys differ per endpoint (`ca`, `fee`, `contract_end`, …), so the map stays open.
 */
export type CoverageMap = Record<string, number | null>

/** Envelope used by every list endpoint (`{items, total}`). */
export interface Paged<TItem> {
  items: TItem[]
  total: number
}

/** Error body returned for all non-2xx responses, per §1 错误. */
export interface ApiErrorBody {
  error: {
    code: string
    message: string
    details?: Record<string, unknown>
  }
}

/** Sort direction accepted by list endpoints that use the `-` prefix convention. */
export type SortDirection = 'asc' | 'desc'

/** `limit`/`offset` paging accepted by every list endpoint (default 50, max 200). */
export interface PageQuery {
  limit?: number
  offset?: number
}

/** Sample metadata displayed next to statistics surfaces. */
export interface SampleMeta {
  sample_size: number | null
  coverage: CoverageMap | null
  algorithm_version: string | null
}
