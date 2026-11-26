/** 只读可视化统计 endpoints。 */

import type { TransferFlowResponse, ValueScatterResponse } from '../types/visualization'
import { apiGet } from './client'

/**
 * `GET /visualizations/value-scatter` — 年龄 / CA / PA / 身价散点。
 * @param saveId 当前存档。
 * @param clubId 可选俱乐部过滤。
 */
export function getValueScatter(saveId: number | null, clubId?: number | null): Promise<ValueScatterResponse> {
  return apiGet<ValueScatterResponse>('/visualizations/value-scatter', {
    save_id: saveId ?? undefined,
    club_id: clubId ?? undefined,
  })
}

/**
 * `GET /visualizations/transfer-flow` — 按币种的买入、卖出、租借与净支出。
 * @param saveId 当前存档。
 * @param clubId 可选视角俱乐部，缺省使用「我的俱乐部」。
 */
export function getTransferFlow(saveId: number | null, clubId?: number | null): Promise<TransferFlowResponse> {
  return apiGet<TransferFlowResponse>('/visualizations/transfer-flow', {
    save_id: saveId ?? undefined,
    club_id: clubId ?? undefined,
  })
}
