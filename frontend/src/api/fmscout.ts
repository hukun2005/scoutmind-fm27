/** FMSuperScout 适配层调用（`/imports/fmscout*`）。 */

import type {
  FmscoutAdapterInfo,
  FmscoutImportResponse,
  FmscoutPreviewResponse,
} from '../types/fmscout'
import { apiGet, apiUpload } from './client'

/**
 * `GET /imports/fmscout/adapter` — 上游身份、许可证与字段策略。
 * @returns 适配器说明。
 */
export function getFmscoutAdapter(): Promise<FmscoutAdapterInfo> {
  return apiGet<FmscoutAdapterInfo>('/imports/fmscout/adapter')
}

/**
 * `POST /imports/fmscout/preview` — 只转换并返回映射报告，不写数据库。
 * @param file FMSuperScout 导出的 dump 文件。
 * @returns 映射报告与转换后的样例。
 */
export function previewFmscoutDump(file: File): Promise<FmscoutPreviewResponse> {
  const form = new FormData()
  form.append('file', file, file.name)
  return apiUpload<FmscoutPreviewResponse>('/imports/fmscout/preview', form)
}

/**
 * `POST /imports/fmscout` — 转换并幂等导入一份 dump。
 * @param file FMSuperScout 导出的 dump 文件。
 * @param saveId 可选存档覆盖。
 * @returns 映射报告与导入结果。
 */
export function importFmscoutDump(file: File, saveId?: number): Promise<FmscoutImportResponse> {
  const form = new FormData()
  form.append('file', file, file.name)
  const query = saveId ? `?save_id=${saveId}` : ''
  return apiUpload<FmscoutImportResponse>(`/imports/fmscout${query}`, form)
}
