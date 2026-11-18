/** V2 transfer endpoints: cost model, taxonomy, decision report and club deal review. */

import type { DealCost, DealReport, TransactionSummary, TransferReview } from '../types/transfers-deals'
import { apiGet, apiPost } from './client'

/**
 * `GET /transfers/categories` — transaction taxonomy with counts and accounting rules.
 * @param saveId Optional save override.
 * @returns Category rows.
 */
export function getTransactionSummary(saveId?: number): Promise<TransactionSummary> {
  return apiGet<TransactionSummary>('/transfers/categories', { save_id: saveId })
}

/**
 * `GET /transfers/review` — the managed club's completed deals reviewed against the market.
 * @param saveId Optional save override.
 * @param clubId Optional club override.
 * @returns Reviewed deals plus an aggregate summary.
 */
export function getTransferReview(saveId?: number, clubId?: number): Promise<TransferReview> {
  return apiGet<TransferReview>('/transfers/review', { save_id: saveId, club_id: clubId })
}

/**
 * `GET /transfers/{id}/cost` — total cost model of one recorded transfer.
 * @param transferId Transfer id.
 * @param wagePeriod Wage period assumption (`week` / `month` / `year`).
 * @param contractYears Contract length assumption.
 * @returns Cost components with provenance.
 */
export function getTransferCost(
  transferId: number,
  wagePeriod = 'week',
  contractYears?: number,
): Promise<DealCost> {
  return apiGet<DealCost>(`/transfers/${transferId}/cost`, {
    wage_period: wagePeriod,
    contract_years: contractYears,
  })
}

/**
 * `POST /transfers/deal-report` — decision report for a prospective signing.
 * @param body Instance id plus optional fee, budget and wage assumptions.
 * @returns Fit, cost, wage, age, resale rows and a recommendation.
 */
export function postDealReport(body: {
  instance_id: number
  save_id?: number
  fee?: number
  budget?: number
  wage_period?: string
  contract_years?: number
}): Promise<DealReport> {
  return apiPost<DealReport>('/transfers/deal-report', body)
}

/**
 * `GET /transfers/investment` — investment score at a given total cost.
 * @param instanceId Player instance id.
 * @param totalCost Total cost to compare against expected future value.
 * @returns Investment score block.
 */
export function getInvestmentScore(
  instanceId: number,
  totalCost?: number,
): Promise<{ available: boolean; score: number | null; reason?: string; note?: string; method?: string }> {
  return apiGet('/transfers/investment', { instance_id: instanceId, total_cost: totalCost })
}
