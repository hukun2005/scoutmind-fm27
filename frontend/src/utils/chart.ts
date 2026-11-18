/**
 * ECharts option builders shared by the dashboard, player detail and transfer screens.
 *
 * Money series are expressed in 万 / 亿 so axis labels and tooltips stay readable
 * without per-chart formatter functions; every unit is named on the axis.
 */

import type { EChartsOption } from 'echarts'
import type { TrendPoint } from '../types/analytics'
import type { PlayerHistoryPoint } from '../types/players'
import type { DistributionBucket } from '../types/transfers'

const TEXT_2 = '#59616f'
const TEXT_3 = '#8b94a3'
const BORDER = '#e2e5ea'

/** Series colours reused across screens. */
export const CHART_COLORS = {
  ca: '#2b62d9',
  pa: '#8b94a3',
  value: '#17774f',
  minutes: '#2b62d9',
  appearances: '#9a5f12',
  fee: '#2b62d9',
} as const

/** Date label of a history point: game date when present, otherwise the observation date. */
function pointLabel(point: PlayerHistoryPoint): string {
  const raw = point.game_date ?? point.observed_at
  return raw ? raw.slice(0, 10) : '—'
}

/** Shared axis/grid furniture. */
function baseFrame(): Pick<EChartsOption, 'grid' | 'legend' | 'tooltip' | 'animationDuration'> {
  return {
    grid: { left: 4, right: 12, top: 30, bottom: 26, containLabel: true },
    legend: {
      bottom: 0,
      left: 'center',
      itemWidth: 10,
      itemHeight: 10,
      itemGap: 12,
      textStyle: { color: TEXT_2, fontSize: 11 },
    },
    tooltip: { trigger: 'axis', confine: true },
    animationDuration: 240,
  }
}

/** Category axis with muted labels. */
function categoryAxis(labels: string[]) {
  return {
    type: 'category' as const,
    data: labels,
    boundaryGap: false,
    axisLabel: { color: TEXT_3, fontSize: 11, hideOverlap: true },
    axisTick: { show: false },
    axisLine: { lineStyle: { color: BORDER } },
  }
}

/** Value axis with optional unit name. */
function valueAxis(name: string, options?: { min?: number; max?: number }) {
  return {
    type: 'value' as const,
    name,
    nameTextStyle: { color: TEXT_3, fontSize: 11, padding: [0, 0, 4, 0] as [number, number, number, number] },
    min: options?.min,
    max: options?.max,
    axisLabel: { color: TEXT_3, fontSize: 11 },
    splitLine: { lineStyle: { color: '#eef0f3' } },
    axisLine: { show: false },
  }
}

/**
 * CA/PA against market value, one point per snapshot.
 * @param points `GET /players/{id}/history` points in observation order.
 * @returns Two-axis line chart option.
 */
export function buildGrowthChart(points: PlayerHistoryPoint[]): EChartsOption {
  const labels = points.map(pointLabel)
  return {
    ...baseFrame(),
    xAxis: categoryAxis(labels),
    yAxis: [valueAxis('CA / PA', { min: 0 }), valueAxis('身价（万 €）')],
    series: [
      {
        name: 'CA',
        type: 'line' as const,
        symbolSize: 5,
        connectNulls: false,
        data: points.map((point) => point.ca),
        lineStyle: { width: 2, color: CHART_COLORS.ca },
        itemStyle: { color: CHART_COLORS.ca },
      },
      {
        name: 'PA',
        type: 'line' as const,
        symbolSize: 4,
        connectNulls: false,
        data: points.map((point) => point.pa),
        lineStyle: { width: 1, type: 'dashed' as const, color: CHART_COLORS.pa },
        itemStyle: { color: CHART_COLORS.pa },
      },
      {
        name: '身价（万 €）',
        type: 'line' as const,
        yAxisIndex: 1,
        symbolSize: 5,
        connectNulls: false,
        data: points.map((point) =>
          point.market_value === null ? null : Math.round(point.market_value / 10_000),
        ),
        lineStyle: { width: 2, color: CHART_COLORS.value },
        itemStyle: { color: CHART_COLORS.value },
      },
    ],
  }
}

/**
 * Minutes played and appearances over the same snapshots.
 * @param points History points in observation order.
 * @returns Bar + line chart with a secondary axis.
 */
export function buildAppearanceChart(points: PlayerHistoryPoint[]): EChartsOption {
  const labels = points.map(pointLabel)
  return {
    ...baseFrame(),
    xAxis: { ...categoryAxis(labels), boundaryGap: true },
    yAxis: [valueAxis('分钟'), valueAxis('次数')],
    series: [
      {
        name: '出场分钟',
        type: 'bar' as const,
        barMaxWidth: 22,
        data: points.map((point) => point.minutes_played),
        itemStyle: { color: CHART_COLORS.minutes, opacity: 0.85 },
      },
      {
        name: '出场次数',
        type: 'line' as const,
        yAxisIndex: 1,
        symbolSize: 5,
        connectNulls: false,
        data: points.map((point) => point.appearances),
        lineStyle: { width: 2, color: CHART_COLORS.appearances },
        itemStyle: { color: CHART_COLORS.appearances },
      },
    ],
  }
}

/**
 * Fee histogram from `GET /transfers/stats` → `distribution`.
 * @param buckets Backend buckets (amounts in the record currency).
 * @returns Bar chart option.
 */
export function buildFeeHistogram(buckets: DistributionBucket[]): EChartsOption {
  const labels = buckets.map((bucket) => formatBucketRange(bucket.bucket_start, bucket.bucket_end))
  return {
    grid: { left: 4, right: 4, top: 24, bottom: 4, containLabel: true },
    tooltip: { trigger: 'axis', confine: true },
    animationDuration: 200,
    xAxis: {
      ...categoryAxis(labels),
      boundaryGap: true,
      axisLabel: { color: TEXT_3, fontSize: 11, hideOverlap: true, rotate: buckets.length > 8 ? 30 : 0 },
    },
    yAxis: valueAxis('笔数', { min: 0 }),
    series: [
      {
        name: '成交笔数',
        type: 'bar' as const,
        barMaxWidth: 26,
        data: buckets.map((bucket) => bucket.count),
        itemStyle: { color: CHART_COLORS.fee, opacity: 0.85 },
      },
    ],
  }
}

/**
 * Portfolio trend from `GET /analytics/overview` → `trend`.
 * @param trend Points in date order.
 * @returns Two-axis line chart option (total value in 亿, CA average).
 */
export function buildTrendChart(trend: TrendPoint[]): EChartsOption {
  const labels = trend.map((point) => point.date)
  return {
    ...baseFrame(),
    xAxis: categoryAxis(labels),
    yAxis: [valueAxis('CA 均值'), valueAxis('总身价（亿 €）')],
    series: [
      {
        name: '总身价（亿 €）',
        type: 'line' as const,
        yAxisIndex: 1,
        symbolSize: 4,
        connectNulls: false,
        data: trend.map((point) =>
          point.value_total === null ? null : Number((point.value_total / 100_000_000).toFixed(2)),
        ),
        lineStyle: { width: 2, color: CHART_COLORS.value },
        itemStyle: { color: CHART_COLORS.value },
        areaStyle: { color: 'rgba(23, 119, 79, 0.08)' },
      },
      {
        name: 'CA 均值',
        type: 'line' as const,
        symbolSize: 4,
        connectNulls: false,
        data: trend.map((point) => point.ca_avg),
        lineStyle: { width: 2, color: CHART_COLORS.ca },
        itemStyle: { color: CHART_COLORS.ca },
      },
    ],
  }
}

/**
 * Format one histogram bucket as a single-unit range so both bounds share the same
 * unit (`0–916 万`, not `0–915.86 万`).
 * @param start Lower bound in the record currency.
 * @param end Upper bound in the record currency.
 * @returns Readable range label.
 */
function formatBucketRange(start: number, end: number): string {
  const magnitude = Math.max(Math.abs(start), Math.abs(end))
  const [unit, divisor] = magnitude >= 100_000_000 ? ['亿', 100_000_000] : magnitude >= 10_000 ? ['万', 10_000] : ['', 1]
  const format = (value: number): string => {
    const scaled = value / divisor
    const digits = Math.abs(scaled) < 10 && divisor > 1 ? 1 : 0
    return `${Number(scaled.toFixed(digits))}${unit}`
  }
  return `${format(start)}–${format(end)}`
}

