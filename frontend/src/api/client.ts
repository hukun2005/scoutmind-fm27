/**
 * Single axios instance for `docs/API.md` v1.
 *
 * Responsibilities:
 * - base URL `/api/v1` (the Vite dev server proxies `/api` to `127.0.0.1:8000`);
 * - `X-ScoutMind-Token` from localStorage on every request;
 * - normalization of every failure into {@link ApiError} so views never inspect
 *   axios internals;
 * - 401 notification so the session store can surface the token prompt.
 */

import axios from 'axios'
import type { AxiosRequestConfig } from 'axios'
import type { ApiErrorBody } from '../types/common'

/** localStorage key holding the optional `SCOUTMIND_API_TOKEN`. */
export const TOKEN_STORAGE_KEY = 'scoutmind.token'

/** Base path of the API; `docs/API.md` §1. */
export const API_BASE_URL = '/api/v1'

/** Normalized API failure. Every non-2xx response and every transport failure becomes one of these. */
export class ApiError extends Error {
  /** Backend `error.code`, or a locally derived code for transport failures. */
  readonly code: string
  /** HTTP status, or `null` when the request never reached the backend. */
  readonly status: number | null
  /** Backend `error.details`, empty when absent. */
  readonly details: Record<string, unknown>

  constructor(params: { code: string; message: string; status: number | null; details?: Record<string, unknown> }) {
    super(params.message)
    this.name = 'ApiError'
    this.code = params.code
    this.status = params.status
    this.details = params.details ?? {}
  }

  /** True when the requested entity does not exist. */
  get isNotFound(): boolean {
    return this.status === 404 || this.code === 'not_found'
  }

  /** True when the backend requires a valid `X-ScoutMind-Token`. */
  get isUnauthorized(): boolean {
    return this.status === 401 || this.code === 'unauthorized'
  }

  /** True when the backend could not be reached at all. */
  get isNetworkError(): boolean {
    return this.code === 'network_error'
  }
}

/** Listeners invoked whenever a request fails with 401. */
const unauthorizedListeners = new Set<() => void>()

/**
 * Register a 401 listener.
 * @param listener Callback invoked for every unauthorized response.
 * @returns Unsubscribe function.
 */
export function onUnauthorized(listener: () => void): () => void {
  unauthorizedListeners.add(listener)
  return () => {
    unauthorizedListeners.delete(listener)
  }
}

/** Read the persisted token; empty string when unset. */
export function getAuthToken(): string {
  try {
    return window.localStorage.getItem(TOKEN_STORAGE_KEY) ?? ''
  } catch {
    return ''
  }
}

/**
 * Persist or clear the token used for the `X-ScoutMind-Token` header.
 * @param token Token value; empty string clears it.
 */
export function setAuthToken(token: string): void {
  const trimmed = token.trim()
  try {
    if (trimmed) {
      window.localStorage.setItem(TOKEN_STORAGE_KEY, trimmed)
    } else {
      window.localStorage.removeItem(TOKEN_STORAGE_KEY)
    }
  } catch {
    // Private-mode storage failures must not break the session; the header is best-effort.
  }
}

/** Map an HTTP status to a stable code when the body carries none. */
function fallbackCode(status: number | null): string {
  if (status === 401) return 'unauthorized'
  if (status === 403) return 'forbidden'
  if (status === 404) return 'not_found'
  if (status === 409) return 'conflict'
  if (status === 422) return 'invalid_payload'
  if (status === 503) return 'unavailable'
  return status === null ? 'network_error' : 'http_error'
}

/** Human-readable Chinese message used when the backend body has none. */
function fallbackMessage(status: number | null): string {
  if (status === 401) return '缺少或无效的 X-ScoutMind-Token，请在设置中填入令牌。'
  if (status === 404) return '请求的数据不存在。'
  if (status === 409) return '请求与当前数据状态冲突。'
  if (status === 422) return '请求体不合法，请检查参数。'
  if (status === 503) return '数据库不可用，后端暂时无法处理请求。'
  if (status === null) return '无法连接后端（127.0.0.1:8000），请确认服务已启动。'
  return `后端返回错误（HTTP ${status}）。`
}

/** True for a non-array object usable as a details map. */
function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

/** Extract the documented error envelope without trusting its runtime type. */
function extractErrorBody(data: unknown): ApiErrorBody['error'] | null {
  if (!isRecord(data) || !('error' in data)) return null
  const body = data.error
  if (!isRecord(body)) return null
  const code = body.code
  const message = body.message
  if (typeof code !== 'string' || typeof message !== 'string') return null
  const details = isRecord(body.details) ? body.details : {}
  return { code, message, details }
}

/** Normalize axios/transport failures into {@link ApiError}. */
function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error
  if (axios.isAxiosError(error)) {
    const status = error.response?.status ?? null
    const body = extractErrorBody(error.response?.data)
    if (body) {
      return new ApiError({ code: body.code, message: body.message, status, details: body.details })
    }
    if (status === null) {
      return new ApiError({ code: 'network_error', message: fallbackMessage(null), status: null })
    }
    return new ApiError({ code: fallbackCode(status), message: fallbackMessage(status), status })
  }
  if (error instanceof Error) {
    return new ApiError({ code: 'unknown_error', message: error.message, status: null })
  }
  return new ApiError({ code: 'unknown_error', message: '发生未知错误。', status: null })
}

/**
 * Narrow any thrown value into {@link ApiError}.
 * @param error Value caught around a request.
 * @returns The normalized error.
 */
export function asApiError(error: unknown): ApiError {
  return toApiError(error)
}

/** Shared axios instance; every API module goes through it. */
export const http = axios.create({
  baseURL: API_BASE_URL,
  timeout: 20000,
  headers: { Accept: 'application/json' },
})

http.interceptors.request.use((config) => {
  const token = getAuthToken()
  if (token) config.headers.set('X-ScoutMind-Token', token)
  return config
})

http.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    const apiError = toApiError(error)
    if (apiError.isUnauthorized) {
      for (const listener of unauthorizedListeners) listener()
    }
    return Promise.reject(apiError)
  },
)

/** One serialized query value. */
export type QueryValue = string | number | boolean | null | undefined

/** Serialized query map. */
export type QueryParams = Record<string, QueryValue>

/** Drop absent filter values so the backend applies its documented defaults. */
export function compactParams(params?: object): QueryParams | undefined {
  if (!params) return undefined
  const result: QueryParams = {}
  for (const [key, value] of Object.entries(params)) {
    if (typeof value === 'object' && value !== null) continue
    if (value === undefined || value === null || value === '') continue
    result[key] = value
  }
  return result
}

/**
 * GET a typed payload.
 * @param url Path relative to `/api/v1`.
 * @param params Optional query values (a typed query interface); absent values are dropped.
 * @param config Extra axios options (for example a longer timeout).
 */
export async function apiGet<T>(
  url: string,
  params?: object,
  config?: AxiosRequestConfig,
): Promise<T> {
  const response = await http.get<T>(url, { params: compactParams(params), ...config })
  return response.data
}

/**
 * POST a JSON body and return the typed payload.
 * @param url Path relative to `/api/v1`.
 * @param body JSON body, if any.
 * @param config Extra axios options.
 */
export async function apiPost<T>(url: string, body?: unknown, config?: AxiosRequestConfig): Promise<T> {
  const response = await http.post<T>(url, body, config)
  return response.data
}

/**
 * PATCH a JSON body and return the typed payload.
 * @param url Path relative to `/api/v1`.
 * @param body JSON body.
 */
export async function apiPatch<T>(url: string, body: unknown): Promise<T> {
  const response = await http.patch<T>(url, body)
  return response.data
}

/**
 * DELETE a resource; the contract answers 204 with no body.
 * @param url Path relative to `/api/v1`.
 */
export async function apiDelete(url: string): Promise<void> {
  await http.delete(url)
}

/**
 * POST `multipart/form-data` (scan upload) and return the typed payload.
 * @param url Path relative to `/api/v1`.
 * @param form Pre-built form data containing the `file` field.
 */
export async function apiUpload<T>(url: string, form: FormData): Promise<T> {
  const response = await http.post<T>(url, form, { timeout: 120000 })
  return response.data
}
