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

const TEXT_2 = '#a6b2c4'
const TEXT_3 = '#7a8698'
const BORDER = '#232d3c'

/** Series colours reused across screens; chosen for contrast on the dark canvas. */
export const CHART_COLORS = {
  ca: '#4d8dff',
  pa: '#7a8698',
  value: '#35c98a',
  minutes: '#4d8dff',
  appearances: '#e6a93c',
  fee: '#4d8dff',
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
    splitLine: { lineStyle: { color: '#1d2632' } },
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
        areaStyle: { color: 'rgba(53, 201, 138, 0.12)' },
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

/** One player's radar series: a label plus one 0-100 value per axis. */
export interface RadarSeries {
  name: string
  values: (number | null)[]
}

/** Radar palette; cycles when more players are compared than colours. */
const RADAR_COLORS = ['#4d8dff', '#35c98a', '#e6a93c', '#f06a63', '#a97bff'] as const

/**
 * Player comparison radar, the screen the recruitment report is built around.
 * @param dimensions Axis labels shared by every series (for example the six score dimensions).
 * @param series One entry per compared player; `null` values are drawn as zero and must be labelled by the caller.
 * @returns Radar chart option sized for the dark canvas.
 */
export function buildRadarChart(dimensions: string[], series: RadarSeries[]): EChartsOption {
  return {
    animationDuration: 240,
    tooltip: { trigger: 'item', confine: true },
    legend: {
      bottom: 0,
      left: 'center',
      itemWidth: 10,
      itemHeight: 10,
      itemGap: 12,
      textStyle: { color: TEXT_2, fontSize: 11 },
    },
    radar: {
      indicator: dimensions.map((name) => ({ name, max: 100 })),
      radius: '62%',
      center: ['50%', '46%'],
      splitNumber: 4,
      axisName: { color: TEXT_3, fontSize: 11 },
      splitLine: { lineStyle: { color: BORDER } },
      splitArea: { areaStyle: { color: ['rgba(255,255,255,0.02)', 'rgba(255,255,255,0.05)'] } },
      axisLine: { lineStyle: { color: BORDER } },
    },
    series: [
      {
        type: 'radar',
        symbolSize: 4,
        data: series.map((entry, index) => ({
          name: entry.name,
          value: entry.values.map((value) => (value === null ? 0 : Number(value.toFixed(2)))),
          lineStyle: { width: 2, color: RADAR_COLORS[index % RADAR_COLORS.length] },
          itemStyle: { color: RADAR_COLORS[index % RADAR_COLORS.length] },
          areaStyle: { opacity: 0.12 },
        })),
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

