/** AI 足球总监 endpoints：工作台上下文与结构化分析。 */

import type { DirectorAnswer, DirectorContext } from '../types/director'
import { apiGet, apiPost } from './client'

/**
 * `GET /agent/director/context` — 当前存档的俱乐部、数据时间与完整度。
 * @param saveId 前端选中的存档；服务端会再次校验归属。
 */
export function getDirectorContext(saveId?: number | null): Promise<DirectorContext> {
  return apiGet<DirectorContext>('/agent/director/context', { save_id: saveId ?? undefined })
}

/**
 * `POST /agent/director/ask` — 用本地真实数据回答总监问题。
 * @param question 自然语言问题。
 * @param options 存档与可选球员上下文（请求体不接受 save_id）。
 */
export function askDirector(
  question: string,
  options: { saveId?: number | null; instanceId?: number } = {},
): Promise<DirectorAnswer> {
  return apiPost<DirectorAnswer>(
    '/agent/director/ask',
    { question, instance_id: options.instanceId },
    { params: { save_id: options.saveId ?? undefined }, timeout: 180000 },
  )
}
