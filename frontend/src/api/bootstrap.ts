/** §2 健康与元信息 endpoints. */

import type { BootstrapMeta, HealthResponse } from '../types/bootstrap'
import { apiGet } from './client'

/**
 * `GET /health` — cheap liveness probe; does not require a token.
 * @returns Backend status and version.
 */
export function getHealth(): Promise<HealthResponse> {
  return apiGet<HealthResponse>('/health')
}

/**
 * `GET /meta/bootstrap` — saves, capabilities, data sources and warnings.
 * @returns Bootstrap metadata driving the whole shell.
 */
export function getBootstrap(): Promise<BootstrapMeta> {
  return apiGet<BootstrapMeta>('/meta/bootstrap')
}
