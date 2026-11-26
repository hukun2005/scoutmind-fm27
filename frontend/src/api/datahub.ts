/**
 * §V3.3.0 数据中心 endpoints（自动识别 / 自动修复 / 一键导入）。
 *
 * 与数据引擎工作流共享契约，界面不假设旧接口行为。
 */

import type { DataHubCapabilities, DataHubImportReport, DataHubStatus } from '../types/datahub'
import { apiGet, http } from './client'
/**
 * `GET /data-hub/status` — 游戏连接、存档、记录数、健康与待确认数量。
 * @returns 数据中心状态面板所需的全部真实数据。
 */
export function getDataHubStatus(): Promise<DataHubStatus> {
  return apiGet<DataHubStatus>('/data-hub/status')
}

/**
 * `GET /data-hub/capabilities` — 引擎支持的来源、格式与修复级别。
 */
export function getDataHubCapabilities(): Promise<DataHubCapabilities> {
  return apiGet<DataHubCapabilities>('/data-hub/capabilities')
}

/**
 * `POST /data-hub/import` — 一键导入（识别、校验、修复、去重、验证）。
 * @param file 用户选择的扫描文件。
 * @param options `dry_run` 只做预检不写库；`save_id` 指定目标存档。
 * @returns 导入报告；`BLOCKED` 由调用方按失败展示。
 */
export async function importDataFile(
  file: File,
  options: { dryRun?: boolean; operationId?: string; saveId?: number | null; save_id?: number | null } = {},
): Promise<DataHubImportReport> {
  const form = new FormData()
  form.append('file', file, file.name)
  const response = await http.post<DataHubImportReport>('/data-hub/import', form, {
    // 大文件导入需要更长的等待时间；服务端仍有并发与体积限制。
    timeout: 180000,
    params: {
      dry_run: options.dryRun === true ? true : undefined,
      filename: file.name,
      operation_id: options.operationId,
      save_id: options.save_id ?? options.saveId ?? undefined,
    },
  })
  return response.data
}
