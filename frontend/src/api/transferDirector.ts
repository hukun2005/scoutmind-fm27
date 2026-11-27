/** V3.3.2-05 AI 转会总监 endpoints。 */

import { apiGet, apiPost } from './client'

export interface DirectorCapabilities {
  auto_transfer_history: boolean
  auto_contract: boolean
  auto_loan_terms: boolean
  auto_budget: boolean
}

export interface DirectorOverview {
  save_id: number
  user_club_id: number | null
  player_count: number
  players_with_wage: number
  players_with_contract: number
  unknown_contract_fields: number
  transfer_count: number
  recent_transfers_30d: number
  loan_count: number
  clause_count: number
  identity_conflicts: number
  last_sync_at: string | null
  offers: number
  negotiations: Record<string, number>
  negotiations_total: number
  capabilities: DirectorCapabilities
  message: string
}

export interface ContractInfo {
  club_id: number | null
  contract_end: string | null
  contract_start: string | null
  wage: number | null
  wage_period: string
  annual_wage: number | null
  remaining_months: number | null
  contract_status: string
  contract_type: string | null
  release_clause: number | null
  observed_at: string | null
  source: string | null
  confidence: number | null
  listed: boolean | null
  loan_listed: boolean | null
  not_for_sale: boolean | null
  missing_fields: string[]
  warnings: string[]
}

export interface TransferClause {
  clause_id: number
  transfer_id: number
  clause_type: string
  clause_value: number | null
  currency: string
  trigger_condition: string | null
  payment_schedule: string | null
  clause_status: string
  due_date: string | null
  source: string | null
  confidence: number | null
}

export interface TransferRow {
  transfer_id: number
  player_name: string
  from_club_name: string | null
  to_club_name: string | null
  transfer_type: string
  status: string
  transfer_date: string
  currency: string
  base_fee: number | null
  effective_fee: number | null
  addons_potential: number | null
  source: string | null
}

export interface ValuationSummary {
  low: number | null
  mid: number | null
  high: number | null
  sample_size: number
  confidence: string
  insufficient_sample: boolean
  method: string
  algorithm_version: string
  warnings: string[]
}

export interface Offer {
  offer_id?: number
  offer_type: string
  currency: string
  base_fee: number | null
  immediate_payment: number | null
  installments_total: number | null
  addons_potential: number | null
  total_committed: number | null
  potential_total: number | null
  sell_on_pct: number | null
  wage_impact: number | null
  loan_fee?: number | null
  wage_contribution_pct?: number | null
  buy_option_fee?: number | null
  buy_obligation_fee?: number | null
  loan_months?: number | null
  risk_level: string
  rationale: Record<string, unknown>
  algorithm_version?: string
  budget_feasible?: boolean | null
  status?: string
  source?: string
}

export interface OfferBundle {
  instance_id: number
  direction: 'purchase' | 'sale' | 'loan'
  currency: string
  available: boolean
  offers: Offer[]
  basis: Record<string, unknown>
  budget?: { provided: boolean; value: number | null }
  squad_impact?: Record<string, unknown>
  factors: Record<string, unknown>
  warnings: string[]
  missing_fields: string[]
  algorithm_version: string
}

export interface OpportunityScores {
  ability: number | null
  squad_fit: number | null
  opportunity: number | null
  financial: number | null
  overall: number | null
  confidence: number | null
}

export interface Opportunity {
  opportunity_id: number
  instance_id: number
  player_name: string | null
  club_id: number | null
  club_name: string | null
  position: string | null
  age: number | null
  market_value: number | null
  wage: number | null
  contract_end: string | null
  contract_remaining_months: number | null
  contract_bucket: string | null
  listed: boolean | null
  loan_listed: boolean | null
  set_for_release: boolean | null
  opportunity_type: string
  verified_status: 'confirmed' | 'inferred'
  confidence: number | null
  source: string
  is_primary: boolean
  scores: OpportunityScores
  recommendation_group: string | null
  detail: Record<string, unknown>
  types: string[]
  first_seen_at: string | null
  last_seen_at: string | null
}

export interface OpportunitySummary {
  save_id: number
  scan_version: string
  last_scan_at: string | null
  counts: {
    listed: number
    loan_listed: number
    release_listed: number
    contract_expiring: number
    ai_inferred: number
    new_24h: number
  }
  groups: Record<string, number>
  group_labels: Record<string, string>
  top_recommendations: Array<Record<string, unknown>>
  alerts_unread: number
  capabilities: Record<string, unknown>
  unsupported_fields: string[]
  auto_scan: Record<string, unknown> | null
}

export interface StrategyCase {
  case_id: string
  player_instance_id: number | null
  player_name: string | null
  player_position: string | null
  player_age: number | null
  player_value: number | null
  contract_remaining: number | null
  selling_club: string | null
  buying_club: string | null
  transfer_type: string
  transfer_status: string
  actual_fee: number | null
  base_fee: number | null
  effective_fee: number | null
  addons_potential: number | null
  installments: { count: number; amount: number | null } | null
  addons: { count: number; amount: number | null } | null
  loan_terms: Record<string, unknown> | null
  sell_on_clause: number | null
  deal_result: string
  data_source: string | null
  case_origin: 'imported' | 'demo' | 'negotiation'
  confidence: number | null
  observed_at: string | null
  match_pct?: number
  matched_features?: string[]
  differences?: string[]
}

export interface StrategyInsight {
  key: string
  label: string
  sample_size: number
  sufficient_sample: boolean
  case_ids: string[]
  summary: string
}

export interface TransferAlert {
  alert_id: number
  instance_id: number | null
  player_name: string | null
  type: string
  severity: string
  title: string
  message: string
  read_at: string | null
  created_at: string | null
}

export interface LoanInfo {
  available: boolean
  note?: string
  parent_club_name?: string | null
  loan_club_name?: string | null
  start_date?: string | null
  end_date?: string | null
  has_option?: boolean | null
  has_obligation?: boolean | null
  loan_fee?: number | null
  wage_contribution_pct?: number | null
  buy_option_fee?: number | null
  buy_obligation_fee?: number | null
  option_status?: string | null
  missing_fields?: string[]
}

export interface PlayerTransferAnalysis {
  instance_id: number
  save_id: number
  player: {
    name: string | null
    club_id: number | null
    club_name: string | null
    position: string | null
    age: number | null
    ca: number | null
    pa: number | null
    market_value: number | null
  }
  contract: ContractInfo
  availability: Record<string, unknown>
  loan: LoanInfo
  transfer_history: TransferRow[]
  clauses: TransferClause[]
  valuation: ValuationSummary
  purchase_preview: OfferBundle
  sale_preview: OfferBundle
  loan_preview?: OfferBundle
  missing_fields: string[]
  sources: Record<string, unknown>
}

export interface NegotiationEvent {
  event_id: number
  event_type: string
  amount: number | null
  data: Record<string, unknown>
  source?: string
  occurred_at: string | null
}

export interface Negotiation {
  negotiation_id: number
  instance_id: number
  offer_id: number | null
  direction: 'purchase' | 'sale' | 'loan'
  status: string
  round_count: number
  initial_ask: number | null
  user_offer: number | null
  counter_offer: number | null
  final_fee: number | null
  currency: string
  final_terms: Record<string, unknown>
  reject_reason: string | null
  source: string
  created_at: string | null
  completed_at: string | null
  events?: NegotiationEvent[]
}

export interface NegotiationReview {
  negotiation_id: number
  instance_id: number
  direction: string
  status: string
  outcome: string
  initial_valuation: ValuationSummary
  initial_offer: number | null
  final_fee: number | null
  delta: number | null
  delta_pct: number | null
  round_count: number
  counter_offer: number | null
  reject_reason: string | null
  final_terms: Record<string, unknown>
  completed_samples_in_save: number
  warnings: string[]
  algorithm_version: string
}

export function getDirectorOverview(): Promise<DirectorOverview> {
  return apiGet<DirectorOverview>('/transfer-director/overview')
}

export function getPlayerTransferAnalysis(instanceId: number): Promise<PlayerTransferAnalysis> {
  return apiGet<PlayerTransferAnalysis>(`/transfer-director/player/${instanceId}`)
}

export function generatePurchaseOffers(instanceId: number, budget?: number | null): Promise<OfferBundle> {
  return apiPost<OfferBundle>(`/transfer-director/player/${instanceId}/purchase-offers`, {
    budget: budget ?? null,
  })
}

export function generateSaleOffers(instanceId: number): Promise<OfferBundle> {
  return apiPost<OfferBundle>(`/transfer-director/player/${instanceId}/sale-offers`)
}

export function saveOffer(instanceId: number, payload: Record<string, unknown>): Promise<Offer> {
  return apiPost<Offer>(`/transfer-director/offers?instance_id=${instanceId}`, payload)
}

export function listNegotiations(params: { instance_id?: number; status?: string } = {}): Promise<{
  items: Negotiation[]
  total: number
}> {
  return apiGet('/transfer-director/negotiations', params)
}

export function createNegotiation(body: {
  instance_id: number
  direction: 'purchase' | 'sale' | 'loan'
  offer_id?: number | null
  initial_ask?: number | null
  note?: string | null
}): Promise<Negotiation> {
  return apiPost<Negotiation>('/transfer-director/negotiations', body)
}

export function getNegotiation(id: number): Promise<Negotiation> {
  return apiGet<Negotiation>(`/transfer-director/negotiations/${id}`)
}

export function appendNegotiationEvent(
  id: number,
  body: { event_type: string; amount?: number | null; data?: Record<string, unknown>; occurred_at?: string | null },
): Promise<{ duplicate: boolean; event: NegotiationEvent; negotiation: Negotiation }> {
  return apiPost(`/transfer-director/negotiations/${id}/events`, body)
}

export function reviewNegotiation(id: number): Promise<NegotiationReview> {
  return apiGet<NegotiationReview>(`/transfer-director/negotiations/${id}/review`)
}

export function getClubTransferSummary(clubId?: number): Promise<Record<string, unknown>> {
  return apiGet('/transfer-director/club-summary', { club_id: clubId })
}

export function generateLoanOffers(instanceId: number): Promise<OfferBundle> {
  return apiPost<OfferBundle>(`/transfer-director/player/${instanceId}/loan-offers`)
}

export function getOpportunitySummary(): Promise<OpportunitySummary> {
  return apiGet<OpportunitySummary>('/transfer-director/opportunities/summary')
}

export function listOpportunities(
  params: {
    type?: string
    club_id?: number
    position?: string
    age_min?: number
    age_max?: number
    group?: string
    search?: string
    sort?: string
    limit?: number
    offset?: number
  } = {},
): Promise<{ items: Opportunity[]; total: number; limit: number; offset: number }> {
  return apiGet('/transfer-director/opportunities', params)
}

export function getOpportunityDetail(
  instanceId: number,
): Promise<{ opportunity: Opportunity & { items?: Opportunity[] }; context: PlayerTransferAnalysis }> {
  return apiGet(`/transfer-director/opportunities/${instanceId}`)
}

export function refreshOpportunities(): Promise<Record<string, unknown>> {
  return apiPost('/transfer-director/opportunities/refresh')
}

export function listOpportunityEvents(
  params: { instance_id?: number; limit?: number; offset?: number } = {},
): Promise<{ items: Array<Record<string, unknown>>; total: number }> {
  return apiGet('/transfer-director/opportunity-events', params)
}

export function listTransferAlerts(
  params: { unread_only?: boolean; limit?: number } = {},
): Promise<{ items: TransferAlert[]; unread: number }> {
  return apiGet('/transfer-director/alerts', params)
}

export function markTransferAlertRead(alertId: number): Promise<Record<string, unknown>> {
  return apiPost(`/transfer-director/alerts/${alertId}/read`)
}

export function listStrategyCases(
  params: { transfer_type?: string; case_origin?: string; limit?: number; offset?: number } = {},
): Promise<{
  items: StrategyCase[]
  total: number
  available: boolean
  message: string | null
}> {
  return apiGet('/transfer-director/strategy-cases', params)
}

export function getSimilarStrategyCases(
  instanceId: number,
  limit = 10,
): Promise<{
  instance_id: number
  available: boolean
  items: StrategyCase[]
  total: number
  message: string | null
}> {
  return apiGet(`/transfer-director/strategy-cases/similar/${instanceId}`, { limit })
}

export function getStrategyInsights(): Promise<{
  save_id: number
  available: boolean
  patterns: StrategyInsight[]
  totals?: Record<string, number>
  message: string | null
  min_sample: number
}> {
  return apiGet('/transfer-director/strategy-insights')
}
