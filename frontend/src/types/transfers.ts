/** Types for §8 转会 (`/transfers`, `/transfers/stats`, `/transfers/similar`, `/transfers/valuation`). */

import type { CoverageMap, DataSource } from './common'

/** `transfer_type` enum from DATA_PROTOCOL.md §3. */
export type TransferType =
  | 'permanent'
  | 'loan'
  | 'free'
  | 'end_of_contract'
  | 'clause_release'
  | 'swap'
  | 'youth_promotion'
  | 'other'

/** `status` enum from DATA_PROTOCOL.md §3. */
export type TransferStatus = 'completed' | 'pending' | 'future' | 'cancelled' | 'failed' | 'unknown'

/** `fee_components[].type` enum from DATA_PROTOCOL.md §3. */
export type FeeComponentType =
  | 'base_fee'
  | 'installment'
  | 'addon'
  | 'signing_bonus'
  | 'agent_fee'
  | 'loan_fee'
  | 'sell_on'
  | 'buy_back'
  | 'wage_contribution'

/** `fee_components[].status` enum from DATA_PROTOCOL.md §3. */
export type FeeComponentStatus = 'paid' | 'scheduled' | 'triggered' | 'untriggered' | 'conditional_unknown' | 'unknown'

/** One fee component of a transfer, shown in the expanded row. */
export interface FeeComponent {
  type: FeeComponentType
  amount: number | null
  status: FeeComponentStatus
  due_date: string | null
  condition?: string | null
}

/** One row of `GET /transfers`. */
export interface Transfer {
  id: number
  player_instance_id: number | null
  player_name: string
  from_club: string | null
  to_club: string | null
  transfer_type: TransferType | null
  status: TransferStatus | null
  transfer_date: string | null
  base_fee: number | null
  fee_paid: number | null
  addons_potential: number | null
  effective_fee: number | null
  currency: string
  player_age_at_transfer: number | null
  player_ca_at_transfer: number | null
  player_pa_at_transfer: number | null
  contract_remaining_months: number | null
  season: string | null
  source: DataSource
  confidence: number | null
  fee_components: FeeComponent[] | null
}

/** `GET /transfers` payload. */
export interface TransferListResponse {
  items: Transfer[]
  total: number
  coverage: CoverageMap
}

/** Filters accepted by `GET /transfers`. */
export interface TransferFilters {
  status?: TransferStatus | 'all'
  transfer_type?: TransferType
  from_date?: string
  to_date?: string
  club_id?: number
  position_group?: string
  min_fee?: number
  max_fee?: number
  min_age?: number
  max_age?: number
  sort?: string
}

/** Query of `GET /transfers`. */
export interface TransferListQuery extends TransferFilters {
  save_id?: number
  limit?: number
  offset?: number
}

/** Filters accepted by `GET /transfers/stats`. */
export interface TransferStatsQuery {
  save_id?: number
  position_group?: string
  min_age?: number
  max_age?: number
  min_ca?: number
  max_ca?: number
  from_date?: string
  to_date?: string
  club_id?: number
  league?: string
}

/** One histogram bucket of `GET /transfers/stats` → `distribution`. */
export interface DistributionBucket {
  bucket_start: number
  bucket_end: number
  count: number
}

/** `GET /transfers/stats` payload. */
export interface TransferStatsResponse {
  sample_size: number
  currency: string
  median: number | null
  p25: number | null
  p75: number | null
  mean: number | null
  min: number | null
  max: number | null
  distribution: DistributionBucket[]
  filters: Record<string, string | number | null>
  coverage: CoverageMap
  algorithm_version: string
  excluded: {
    incomplete: number | null
    non_completed: number | null
  }
  warnings: string[]
}

/** Target summary of `GET /transfers/similar`. */
export interface SimilarTarget {
  instance_id: number
  name: string
  age: number | null
  position_group: string | null
  ca: number | null
  pa: number | null
}

/** One similarity factor, exposed in the expanded comparable row. */
export interface SimilarityFactor {
  key: string
  value: number | string | null
  target: number | string | null
  distance: number | null
  weight: number | null
}

/** One comparable transfer row. */
export interface SimilarTransferItem {
  transfer_id: number
  transfer: Transfer
  similarity: number | null
  factors: SimilarityFactor[]
}

/** `GET /transfers/similar` payload. */
export interface SimilarTransfersResponse {
  target: SimilarTarget
  items: SimilarTransferItem[]
  effective_weights: Record<string, number | null>
  missing_fields: string[]
  sample_size: number
  data_gaps: string[]
}

/** `GET /transfers/similar` query. */
export interface SimilarTransfersQuery {
  instance_id: number
  limit?: number
}
