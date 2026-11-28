/** 展示型通用类型：结论面板与紧凑指标条共用，避免 SFC 内部导出类型。 */

export type InsightTone = 'info' | 'success' | 'warning' | 'danger' | 'neutral'

export interface InsightItem {
  /** 结论维度，例如「最大问题」「推荐动作」。 */
  label?: string
  /** 结论正文。 */
  text: string
  /** 单条状态色；省略时继承面板 tone。 */
  tone?: InsightTone
}

export type StatTone = 'default' | 'accent' | 'success' | 'warning' | 'danger'

export interface StatItem {
  label: string
  value: string
  /** 指标解释或口径，例如「当前存档」。 */
  hint?: string
  tone?: StatTone
}
