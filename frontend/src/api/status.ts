/** 球员状态、候选转会与真实数据审查接口（P0-1 / P0-4）。 */

import type {
  CandidateListResponse,
  CandidateRow,
  PlayerStatus,
  ValidationResponse,
} from '../types/status'
import { apiGet, apiPost, apiUpload } from './client'

/**
 * `GET /players/{instance_id}/status` — 挂牌、伤病、租借与待生效转会的时间线。
 * @param instanceId 球员实例 ID。
 * @returns 当前状态、历史、变化、租借与数据缺口。
 */
export function getPlayerStatus(instanceId: number): Promise<PlayerStatus> {
  return apiGet<PlayerStatus>(`/players/${instanceId}/status`)
}

/**
 * `GET /transfers/candidates` — 快照对比发现的俱乐部变化。
 * @param query 状态筛选（默认只取待确认）。
 * @returns 候选事件列表。
 */
export function listTransferCandidates(query: { save_id?: number; status?: string; limit?: number }): Promise<CandidateListResponse> {
  return apiGet<CandidateListResponse>('/transfers/candidates', query)
}

/**
 * `POST /transfers/candidates/{id}/confirm` — 确认候选，必要时生成一笔无金额的已完成交易。
 * @param candidateId 候选事件 ID。
 * @param body 可选的交易日期与金额。
 * @returns 更新后的候选与交易 ID。
 */
export function confirmTransferCandidate(
  candidateId: number,
  body: { transfer_date?: string; fee?: number; transfer_id?: number },
): Promise<{ candidate: CandidateRow; transfer_id: number | null }> {
  return apiPost(`/transfers/candidates/${candidateId}/confirm`, body)
}

/**
 * `POST /transfers/candidates/{id}/dismiss` — 标记为误报。
 * @param candidateId 候选事件 ID。
 * @param reason 误报原因。
 * @returns 更新后的候选。
 */
export function dismissTransferCandidate(candidateId: number, reason?: string): Promise<{ candidate: CandidateRow }> {
  return apiPost(`/transfers/candidates/${candidateId}/dismiss`, { reason })
}

/**
 * `POST /imports/fmscout/validate` — 真实数据审查报告，不写库。
 * @param file FMSuperScout 导出的 dump。
 * @returns 分节报告与结论。
 */
export function validateFmscoutDump(file: File): Promise<ValidationResponse> {
  const form = new FormData()
  form.append('file', file, file.name)
  return apiUpload<ValidationResponse>('/imports/fmscout/validate', form)
}
