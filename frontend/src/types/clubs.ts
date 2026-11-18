/** Types for §8 俱乐部 (`GET /clubs`, `GET /clubs/{club_id}/transfer-profile`). */

import type { CoverageMap } from './common'
import type { Transfer } from './transfers'

/** One club row of `GET /clubs`. Only the identity fields are guaranteed by the contract. */
export interface Club {
  club_id: number
  name: string
  nation: string | null
  league: string | null
  reputation: number | null
  is_user_club: boolean | null
  currency: string | null
}

/**
 * `GET /clubs` payload.
 *
 * `docs/API.md` documents the per-club profile but not the collection envelope,
 * so the client accepts either the paged envelope or a bare array.
 */
export type ClubListResponse = { items: Club[]; total: number } | Club[]

/** Aggregated buying or selling figures of a club profile. */
export interface ClubFlow {
  count: number | null
  total: number | null
  median: number | null
}

/** `GET /clubs/{club_id}/transfer-profile` payload. */
export interface ClubTransferProfile {
  club_id: number
  name: string
  nation: string | null
  league: string | null
  reputation: number | null
  is_user_club: boolean | null
  currency: string
  bought: ClubFlow
  sold: ClubFlow
  net_spend: number | null
  avg_profit_per_sale: number | null
  young_signing_ratio: number | null
  loan_in_count: number | null
  loan_out_count: number | null
  top_transfers: Transfer[]
  sample_size: number
  coverage: CoverageMap
}
