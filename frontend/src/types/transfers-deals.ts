/** V2 deal model, transaction taxonomy and review payloads (/transfers/cost, /transfers/deal-report, /transfers/review). */
// ---------- V2: deal model, taxonomy and review ----------

/** One transaction category with its accounting treatment. */
export interface TransactionCategory {
  key: string
  label: string
  treatment: string
  count: number
  /** Money actually paid in completed deals of this category (loans included). */
  known_amount: number
  /** Money that enters transfer-fee statistics; excludes loans, free deals and unfinished deals. */
  known_spend: number
  counts_in_stats: boolean
}

/** `GET /transfers/categories` payload. */
export interface TransactionSummary {
  categories: TransactionCategory[]
  total: number
  currency: string
  algorithm_version: string
}

/** One cost component with its provenance. */
export interface DealCostComponent {
  key: string
  label: string
  amount: number | null
  status: 'observed' | 'assumed' | 'unavailable' | 'conditional' | string
  note: string
}

/** Total-cost model of one recorded transfer or one prospective signing. */
export interface DealCost {
  transfer_id?: number
  instance_id?: number
  player_name?: string
  currency: string
  components: DealCostComponent[]
  total_known: number | null
  complete: boolean
  missing_components: string[]
  label: string
  assumptions?: { wage_period: string; contract_years: number; note: string }
  algorithm_version: string
}

/** Investment score block. */
export interface InvestmentScore {
  available: boolean
  score: number | null
  total_cost?: number | null
  expected_future_value?: number
  net_value?: number
  method?: string
  note?: string
  reason?: string
}

/** One row of the decision report. */
export interface DecisionRow {
  key: string
  label: string
  value: string
  raw: number | string | null
  basis: string
}

/** `POST /transfers/deal-report` payload. */
export interface DealReport {
  player: Record<string, unknown>
  score: number | null
  dimensions: {
    key: string
    label: string
    value: number | null
    weight: number
    source: string | null
    evidence: string
    missing: string[]
  }[]
  cost: DealCost
  investment: InvestmentScore
  rows: DecisionRow[]
  budget: number | null
  budget_note: string | null
  recommendation: { verdict: string; reasons: string[] }
  data_gaps: string[]
  algorithm_version: string
}

/** One reviewed deal of the managed club. */
export interface ReviewedDeal {
  transfer_id: number
  direction: 'in' | 'out' | string
  player: { instance_id: number | null; name: string; age_at_transfer: number | null; club: number | null }
  transfer_date: string
  fee: number | null
  currency: string
  status: { key: string; label: string; treatment: string; counts_in_stats: boolean }
  fee_percentile: number | null
  comparable_sample: number
  ca_delta_since: number | null
  value_delta_since: number | null
  current_value: number | null
  verdict: string
  evidence: string[]
}

/** `GET /transfers/review` payload. */
export interface TransferReview {
  club: { id: number; name: string; league: string | null } | null
  items: ReviewedDeal[]
  summary: {
    deals: number
    with_value_delta: number
    profitable: number
    median_value_delta: number | null
    by_age_band: { band: string; deals: number; median_delta: number | null }[]
    note: string
  } | null
  algorithm_version: string
  note: string
}
