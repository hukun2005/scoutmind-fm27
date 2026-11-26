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

const TEXT_2 = '#9db0c9'
const TEXT_3 = '#7689a3'
const BORDER = 'rgba(122, 162, 220, 0.18)'
const SPLIT = 'rgba(122, 162, 220, 0.1)'

/** 系统是否要求减少动态效果；图表据此关闭入场动画。 */
function reducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/** 系列颜色：与设计 Token 的强调色一致，保证跨页面可识别。 */
export const CHART_COLORS = {
  ca: '#4d8dff',
  pa: '#6b7f9b',
  value: '#34d399',
  minutes: '#4d8dff',
  appearances: '#f5b544',
  fee: '#4d8dff',
  blue: '#4d8dff',
  cyan: '#22d3ee',
  violet: '#a78bfa',
} as const

/** 深色画布上的统一 tooltip 外观。 */
const TOOLTIP_STYLE = {
  backgroundColor: 'rgba(8, 16, 28, 0.96)',
  borderColor: 'rgba(122, 162, 220, 0.28)',
  borderWidth: 1,
  padding: [8, 10] as [number, number],
  textStyle: { color: '#eef5ff', fontSize: 12 },
  extraCssText: 'border-radius:10px;box-shadow:0 18px 40px -24px rgba(2,7,16,.9);',
}

/** Date label of a history point: game date when present, otherwise the observation date. */
function pointLabel(point: PlayerHistoryPoint): string {
  const raw = point.game_date ?? point.observed_at
  return raw ? raw.slice(0, 10) : '—'
}

/** 共享的坐标轴 / 图例 / 提示框外观。 */
function baseFrame(): Pick<EChartsOption, 'grid' | 'legend' | 'tooltip' | 'animationDuration' | 'animationEasing'> {
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
    tooltip: { trigger: 'axis', confine: true, ...TOOLTIP_STYLE },
    animationDuration: reducedMotion() ? 0 : 320,
    animationEasing: 'cubicOut',
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
    splitLine: { lineStyle: { color: SPLIT } },
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

/** 雷达图配色；比较人数超过颜色数时循环使用。 */
const RADAR_COLORS = ['#22d3ee', '#4d8dff', '#a78bfa', '#34d399', '#f5b544'] as const

/**
 * Player comparison radar, the screen the recruitment report is built around.
 * @param dimensions Axis labels shared by every series (for example the six score dimensions).
 * @param series One entry per compared player; `null` values are drawn as zero and must be labelled by the caller.
 * @returns Radar chart option sized for the dark canvas.
 */
export function buildRadarChart(dimensions: string[], series: RadarSeries[]): EChartsOption {
  return {
    animationDuration: reducedMotion() ? 0 : 420,
    animationEasing: 'cubicOut',
    tooltip: { trigger: 'item', confine: true, ...TOOLTIP_STYLE },
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
 * 阵容六维雷达：只绘制后端给出数值的维度，`null` 维度由调用方在脚注中说明。
 * @param components `GET /squad/overview` → `components`。
 * @returns 0–100 单系列雷达图。
 */
export function buildSquadRadar(components: Array<{ label: string; value: number | null }>): EChartsOption {
  const usable = components.filter((entry): entry is { label: string; value: number } => entry.value !== null)
  return {
    animationDuration: reducedMotion() ? 0 : 420,
    animationEasing: 'cubicOut',
    tooltip: { trigger: 'item', confine: true, ...TOOLTIP_STYLE },
    radar: {
      indicator: usable.map((entry) => ({ name: entry.label, max: 100 })),
      radius: '64%',
      center: ['50%', '50%'],
      splitNumber: 4,
      axisName: { color: TEXT_2, fontSize: 11 },
      splitLine: { lineStyle: { color: BORDER } },
      splitArea: { areaStyle: { color: ['rgba(255,255,255,0.015)', 'rgba(34,211,238,0.035)'] } },
      axisLine: { lineStyle: { color: BORDER } },
    },
    series: [
      {
        type: 'radar',
        symbolSize: 4,
        data: [
          {
            name: '阵容评分',
            value: usable.map((entry) => Number(entry.value.toFixed(1))),
            lineStyle: { width: 2, color: CHART_COLORS.cyan },
            itemStyle: { color: CHART_COLORS.cyan },
            areaStyle: { color: 'rgba(34, 211, 238, 0.16)' },
          },
        ],
      },
    ],
  }
}

/**
 * 阵容年龄结构：实际占比柱 + 后端给出的理想占比参考线。
 * @param buckets `GET /squad/overview` → `age_structure.buckets`。
 * @returns 百分比柱线组合图。
 */
export function buildAgeDistribution(
  buckets: Array<{ bucket: string; count: number; share: number; ideal_share: number }>,
): EChartsOption {
  return {
    ...baseFrame(),
    tooltip: {
      trigger: 'axis',
      confine: true,
      ...TOOLTIP_STYLE,
      valueFormatter: (value: unknown) => `${value}%`,
    },
    xAxis: { ...categoryAxis(buckets.map((bucket) => bucket.bucket)), boundaryGap: true },
    yAxis: valueAxis('占比 %', { min: 0 }),
    series: [
      {
        name: '实际占比',
        type: 'bar' as const,
        barMaxWidth: 34,
        data: buckets.map((bucket) => Number((bucket.share * 100).toFixed(1))),
        itemStyle: {
          borderRadius: [4, 4, 0, 0] as [number, number, number, number],
          color: {
            type: 'linear' as const,
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: '#22d3ee' },
              { offset: 1, color: 'rgba(37, 99, 235, 0.35)' },
            ],
          },
        },
      },
      {
        name: '理想占比',
        type: 'line' as const,
        symbol: 'circle' as const,
        symbolSize: 5,
        data: buckets.map((bucket) => Number((bucket.ideal_share * 100).toFixed(1))),
        lineStyle: { width: 1.5, type: 'dashed' as const, color: CHART_COLORS.violet },
        itemStyle: { color: CHART_COLORS.violet },
      },
    ],
  }
}

/**
 * 位置结构：各位置现有球员数与模板需求人数。
 * @param rows `GET /squad/overview` → `depth`。
 * @returns 横向双系列条形图。
 */
export function buildPositionDistribution(rows: Array<{ slot: string; slot_name: string; count: number; required: number }>): EChartsOption {
  const items = rows.filter((row) => row.slot !== 'UNKNOWN')
  return {
    ...baseFrame(),
    grid: { left: 4, right: 16, top: 12, bottom: 30, containLabel: true },
    xAxis: valueAxis('人数', { min: 0 }),
    yAxis: {
      type: 'category' as const,
      data: items.map((row) => row.slot_name || row.slot),
      axisLabel: { color: TEXT_3, fontSize: 11 },
      axisTick: { show: false },
      axisLine: { lineStyle: { color: BORDER } },
    },
    series: [
      {
        name: '现有',
        type: 'bar' as const,
        barMaxWidth: 11,
        data: items.map((row) => row.count),
        itemStyle: { color: CHART_COLORS.blue, borderRadius: [0, 4, 4, 0] as [number, number, number, number] },
      },
      {
        name: '需求',
        type: 'bar' as const,
        barMaxWidth: 11,
        data: items.map((row) => row.required),
        itemStyle: { color: 'rgba(167, 139, 250, 0.5)', borderRadius: [0, 4, 4, 0] as [number, number, number, number] },
      },
    ],
  }
}


/**
 * 把一个直方图区间格式化为同一单位的范围（`0–916 万`，而不是 `0–915.86 万`）。
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

