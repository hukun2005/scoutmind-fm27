/**
 * Null-safe display formatting.
 *
 * Rule of the product: `null` is unknown and must render as `—`; a real `0` is
 * data and must render as `0`. Every helper here obeys that distinction.
 */

import dayjs from 'dayjs'

/** Placeholder used for every absent value. */
export const EMPTY = '—'

/** Currency symbol used for the documented default currency (`EUR`). */
const CURRENCY_SYMBOLS: Record<string, string> = {
  EUR: '€',
  GBP: '£',
  USD: '$',
  CNY: '¥',
  RMB: '¥',
  JPY: '¥',
}

/** Remove trailing zeros from a fixed-point string (`1.20` → `1.2`, `3.00` → `3`). */
function trimZeros(text: string): string {
  if (!text.includes('.')) return text
  return text.replace(/\.?0+$/, '')
}

/** Numeric input accepted by display formatters; decimal API fields may arrive as strings. */
export type NumericInput = number | string | null | undefined

/**
 * Coerce a wire value to a finite number.
 * @param value Number, numeric string, or absent value.
 * @returns The number, or `null` when the value is absent or not numeric.
 */
export function toFiniteNumber(value: NumericInput): number | null {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  if (typeof value === 'string') {
    const trimmed = value.trim()
    if (trimmed === '') return null
    const parsed = Number(trimmed)
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

/** Group the integer part with commas. */
function groupThousands(value: number): string {
  const [integer, fraction] = Math.abs(value).toFixed(0).split('.')
  const grouped = integer.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  const sign = value < 0 ? '-' : ''
  return fraction ? `${sign}${grouped}.${fraction}` : `${sign}${grouped}`
}

/** Symbol for a currency code; unknown codes fall back to the raw code. */
export function currencySymbol(currency?: string | null): string {
  const code = (currency ?? 'EUR').toUpperCase()
  return CURRENCY_SYMBOLS[code] ?? code
}

/**
 * Render text, substituting `—` for absent values.
 * @param value Any displayable scalar.
 * @returns The text or `—`.
 */
export function displayText(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return EMPTY
  const text = String(value).trim()
  return text.length === 0 ? EMPTY : text
}

/**
 * Compact Chinese number with 万 / 亿 units.
 * @param value Number in base units.
 * @returns For example `4200 万`, `12.4 亿`, `850`.
 */
export function formatCompactNumber(value: number): string {
  const abs = Math.abs(value)
  if (abs >= 100_000_000) return `${trimZeros((value / 100_000_000).toFixed(2))} 亿`
  if (abs >= 10_000) return `${trimZeros((value / 10_000).toFixed(2))} 万`
  return trimZeros(value.toFixed(0))
}

/**
 * Integer with thousands separators.
 * @param value Number or `null`.
 * @returns For example `1,240`; `—` when absent.
 */
export function formatInt(value: NumericInput): string {
  const numeric = toFiniteNumber(value)
  if (numeric === null) return EMPTY
  return groupThousands(numeric)
}

/**
 * Fixed-point decimal, trailing zeros trimmed.
 * @param value Number or `null`.
 * @param digits Maximum fraction digits.
 */
export function formatDecimal(value: NumericInput, digits = 2): string {
  const numeric = toFiniteNumber(value)
  if (numeric === null) return EMPTY
  return trimZeros(numeric.toFixed(digits))
}

/**
 * Compact Chinese money value without a currency symbol (currency belongs in the
 * column header or tooltip): 亿 with up to two decimals, 万 rounded to an integer
 * above 100 万 and to one decimal below.
 * @param value Amount in the record's currency.
 * @returns For example `6516 万`, `1.2 亿`, `2.1 万`, `850`.
 */
export function formatMoney(value: NumericInput): string {
  const numeric = toFiniteNumber(value)
  if (numeric === null) return EMPTY
  return compactMoney(numeric)
}

/** Shared 万/亿 compaction used by money formatters (no thousands separators). */
function compactMoney(value: number): string {
  const abs = Math.abs(value)
  if (abs >= 100_000_000) return `${trimZeros((value / 100_000_000).toFixed(2))} 亿`
  if (abs >= 10_000) {
    const wan = value / 10_000
    if (Math.abs(wan) >= 100) return `${Math.round(wan)} 万`
    return `${trimZeros(wan.toFixed(1))} 万`
  }
  return String(Math.round(value))
}

/**
 * Exact money with separators and currency, used in tooltips (`title`) next to
 * compact cell text.
 * @param value Amount in the record's currency.
 * @param currency ISO code.
 */
export function formatMoneyExact(value: NumericInput, currency?: string | null): string {
  const numeric = toFiniteNumber(value)
  if (numeric === null) return EMPTY
  return `${groupThousands(numeric)} ${currencySymbol(currency)}`
}

/**
 * Signed money delta, for development panels.
 * @param value Delta in the record's currency.
 */
export function formatSignedMoney(value: NumericInput): string {
  const numeric = toFiniteNumber(value)
  if (numeric === null) return EMPTY
  const prefix = numeric > 0 ? '+' : ''
  return `${prefix}${compactMoney(numeric)}`
}

/**
 * Signed integer, for CA/PA or minute deltas.
 * @param value Delta or `null`.
 */
export function formatSignedInt(value: NumericInput): string {
  const numeric = toFiniteNumber(value)
  if (numeric === null) return EMPTY
  return `${numeric > 0 ? '+' : ''}${groupThousands(numeric)}`
}

/**
 * Ratio (`0.93`) as a percentage (`93%`).
 * @param value Ratio where `1` means 100%.
 * @param digits Maximum fraction digits.
 */
export function formatPercent(value: NumericInput, digits = 1): string {
  const numeric = toFiniteNumber(value)
  if (numeric === null) return EMPTY
  return `${trimZeros((numeric * 100).toFixed(digits))}%`
}

/**
 * Ratio clamped to a CSS width percentage.
 * @param value Ratio where `1` means 100%.
 * @returns Width in percent, `0` when absent.
 */
export function toPercentWidth(value: NumericInput): number {
  const numeric = toFiniteNumber(value)
  if (numeric === null) return 0
  return Math.min(100, Math.max(0, numeric * 100))
}

/**
 * Game date (`YYYY-MM-DD`); ISO timestamps are rendered in local time.
 * @param value Date string or `null`.
 */
export function formatDate(value: string | null | undefined): string {
  if (!value) return EMPTY
  const parsed = dayjs(value)
  return parsed.isValid() ? parsed.format('YYYY-MM-DD') : EMPTY
}

/**
 * UTC timestamp as local `YYYY-MM-DD HH:mm`.
 * @param value ISO-8601 timestamp or `null`.
 */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return EMPTY
  const parsed = dayjs(value)
  return parsed.isValid() ? parsed.format('YYYY-MM-DD HH:mm') : EMPTY
}

/**
 * Short local time (`HH:mm`) for conversation timestamps.
 * @param value ISO-8601 timestamp or `null`.
 */
export function formatTime(value: string | null | undefined): string {
  if (!value) return EMPTY
  const parsed = dayjs(value)
  return parsed.isValid() ? parsed.format('HH:mm') : EMPTY
}

/**
 * Contract length in months.
 * @param months Remaining months or `null`.
 */
export function formatMonths(months: NumericInput): string {
  const numeric = toFiniteNumber(months)
  if (numeric === null) return EMPTY
  return `${numeric} 个月`
}

/**
 * One attribute value on the 1–20 scale.
 * @param value Attribute value or `null`.
 */
export function formatScale(value: NumericInput): string {
  const numeric = toFiniteNumber(value)
  if (numeric === null) return EMPTY
  return String(numeric)
}

/**
 * Human-readable byte count for raw payload paths' metadata.
 * @param bytes Size in bytes or `null`.
 */
export function formatBytes(bytes: NumericInput): string {
  const numeric = toFiniteNumber(bytes)
  if (numeric === null) return EMPTY
  if (numeric < 1024) return `${numeric} B`
  if (numeric < 1024 * 1024) return `${trimZeros((numeric / 1024).toFixed(1))} KB`
  return `${trimZeros((numeric / (1024 * 1024)).toFixed(1))} MB`
}
