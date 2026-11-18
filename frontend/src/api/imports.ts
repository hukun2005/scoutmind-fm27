/** §4 导入 endpoints. */

import type { ImportJob, ImportListResponse, ScanImportResponse } from '../types/imports'
import type { Paged } from '../types/common'
import { apiGet, apiUpload } from './client'

/**
 * `GET /imports` — import history of one save.
 * @param query Save filter plus paging.
 * @returns Paged import jobs.
 */
export function listImports(query: { save_id?: number; limit?: number; offset?: number }): Promise<ImportListResponse> {
  return apiGet<ImportListResponse>('/imports', query)
}

/**
 * `POST /imports/scan` — upload a scan payload (`.json` or `.ndjson`) as multipart `file`.
 * @param file File chosen in the drag & drop zone.
 * @returns Import result, including per-row errors.
 */
export function uploadScan(file: File): Promise<ScanImportResponse> {
  const form = new FormData()
  form.append('file', file, file.name)
  return apiUpload<ScanImportResponse>('/imports/scan', form)
}

/** Re-export used by the data screen's job table. */
export type ImportHistory = Paged<ImportJob>
