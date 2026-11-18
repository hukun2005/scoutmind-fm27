/** Chinese labels for enum values defined by `docs/API.md` and `docs/DATA_PROTOCOL.md`. */

import type { FeeComponentStatus, FeeComponentType, TransferStatus, TransferType } from '../types/transfers'

/** Provenance labels. */
export const SOURCE_LABELS: Record<string, string> = {
  fm27_live_reader: '实时读取器',
  fm_save_parser: '存档解析',
  manual: '手工录入',
  ocr: 'OCR 识别',
  external: '外部数据',
  estimated: '估算值',
  synthetic_fixture: '演示数据',
}

/**
 * Label of a `source` field.
 * @param source Wire value.
 */
export function sourceLabel(source: string | null | undefined): string {
  if (!source) return '—'
  return SOURCE_LABELS[source] ?? source
}

/** Position codes shown next to the Chinese label. */
export const POSITION_LABELS: Record<string, string> = {
  GK: '门将',
  SW: '清道夫',
  DR: '右后卫',
  DC: '中后卫',
  DL: '左后卫',
  WBR: '右翼卫',
  WBL: '左翼卫',
  DM: '后腰',
  MC: '中场',
  MR: '右中场',
  ML: '左中场',
  AMC: '前腰',
  AMR: '右边锋',
  AML: '左边锋',
  ST: '前锋',
  CF: '中锋',
}

/**
 * Chinese label for a position code, keeping the code visible.
 * @param position Position code such as `DM`.
 * @returns For example `后腰 (DM)`.
 */
export function positionLabel(position: string | null | undefined): string {
  if (!position) return '—'
  const label = POSITION_LABELS[position.toUpperCase()]
  return label ? `${label} (${position})` : position
}

/** Position groups used by filters and role templates. */
export const POSITION_GROUPS: Array<{ value: string; label: string }> = [
  { value: 'GK', label: '门将' },
  { value: 'DF', label: '后卫' },
  { value: 'MF', label: '中场' },
  { value: 'FW', label: '前锋' },
]

/**
 * Label of a position group value.
 * @param group Wire value such as `MF`.
 */
export function positionGroupLabel(group: string | null | undefined): string {
  if (!group) return '—'
  return POSITION_GROUPS.find((item) => item.value === group)?.label ?? group
}

/** Known FM27 position codes offered by the player filters. */
export const POSITION_OPTIONS: Array<{ value: string; label: string }> = Object.keys(POSITION_LABELS).map((code) => ({
  value: code,
  label: `${POSITION_LABELS[code]} (${code})`,
}))

/** Attribute category labels (`GET /players/{id}` → `attributes[].category`). */
export const ATTRIBUTE_CATEGORY_LABELS: Record<string, string> = {
  technical: '技术',
  mental: '精神',
  physical: '身体',
  goalkeeper: '门将',
  goalkeeping: '门将',
  set_piece: '定位球',
}

/**
 * Label of an attribute category.
 * @param category Wire value.
 */
export function attributeCategoryLabel(category: string | null | undefined): string {
  if (!category) return '其他'
  return ATTRIBUTE_CATEGORY_LABELS[category] ?? category
}

/** Coverage field labels used by every statistics surface. */
export const COVERAGE_LABELS: Record<string, string> = {
  ca: 'CA 覆盖',
  pa: 'PA 覆盖',
  market_value: '身价覆盖',
  wage: '工资覆盖',
  contract_end: '合同覆盖',
  contract_remaining_months: '合同剩余覆盖',
  fee: '费用覆盖',
  attributes: '属性覆盖',
  transfer_date: '成交日期覆盖',
  ca_at_transfer: '成交时 CA 覆盖',
  players: '球员覆盖',
  transfers: '转会覆盖',
  snapshots: '快照覆盖',
  clubs: '俱乐部覆盖',
  minutes: '出场时间覆盖',
  appearances: '出场次数覆盖',
}

/**
 * Label of a coverage key.
 * @param key Coverage field name.
 */
export function coverageLabel(key: string): string {
  return COVERAGE_LABELS[key] ?? key.replace(/_/g, ' ')
}

/** Transfer type labels. */
export const TRANSFER_TYPE_LABELS: Record<TransferType, string> = {
  permanent: '永久转会',
  loan: '租借',
  free: '自由转会',
  end_of_contract: '合同到期',
  clause_release: '解约金',
  swap: '球员交换',
  youth_promotion: '青训提拔',
  other: '其他',
}

/** Transfer status labels. */
export const TRANSFER_STATUS_LABELS: Record<TransferStatus, string> = {
  completed: '已完成',
  pending: '待完成',
  future: '未来生效',
  cancelled: '已取消',
  failed: '失败',
  unknown: '未知',
}

/** Fee component labels. */
export const FEE_COMPONENT_LABELS: Record<FeeComponentType, string> = {
  base_fee: '基础转会费',
  installment: '分期付款',
  addon: '附加条款',
  signing_bonus: '签字费',
  agent_fee: '经纪费用',
  loan_fee: '租借费',
  sell_on: '二次转会分成',
  buy_back: '回购条款',
  wage_contribution: '工资分担',
}

/** Fee component status labels. */
export const FEE_STATUS_LABELS: Record<FeeComponentStatus, string> = {
  paid: '已支付',
  scheduled: '已排期',
  triggered: '已触发',
  untriggered: '未触发',
  conditional_unknown: '条件未知',
  unknown: '未知',
}

/**
 * Label of a transfer type.
 * @param type Wire value.
 */
export function transferTypeLabel(type: string | null | undefined): string {
  if (!type) return '—'
  return TRANSFER_TYPE_LABELS[type as TransferType] ?? type
}

/**
 * Label of a transfer status.
 * @param status Wire value.
 */
export function transferStatusLabel(status: string | null | undefined): string {
  if (!status) return '—'
  return TRANSFER_STATUS_LABELS[status as TransferStatus] ?? status
}

/** Common FM27 attribute keys → Chinese labels (used where the API returns bare keys, e.g. role weights). */
export const ATTRIBUTE_LABELS: Record<string, string> = {
  finishing: '射门',
  dribbling: '盘带',
  passing: '传球',
  tackling: '抢断',
  marking: '盯人',
  crossing: '传中',
  heading: '头球',
  technique: '技术',
  first_touch: '停球',
  long_shots: '远射',
  free_kick_taking: '任意球',
  penalty_taking: '点球',
  corners: '角球',
  throw_ins: '界外球',
  pace: '速度',
  acceleration: '加速',
  agility: '灵活',
  balance: '平衡',
  strength: '力量',
  stamina: '耐力',
  natural_fitness: '体质',
  jumping_reach: '弹跳',
  vision: '视野',
  anticipation: '预判',
  composure: '冷静',
  concentration: '专注',
  decisions: '决断',
  determination: '决心',
  work_rate: '工作投入',
  teamwork: '团队合作',
  leadership: '领导力',
  off_the_ball: '无球跑动',
  positioning: '位置感',
  aggression: '侵略性',
  bravery: '勇敢',
  flair: '想象力',
  consistency: '稳定性',
  important_matches: '大赛发挥',
  handling: '手控球',
  reflexes: '反应',
  one_on_ones: '一对一',
  command_of_area: '禁区控制',
  kicking: '开球',
  rushing_out: '出击',
  communication: '沟通',
  eccentricity: '冒险度',
  punching: '击球',
  aerial_reach: '制空',
}

/**
 * Label of an attribute key.
 * @param key Attribute key such as `off_the_ball`.
 */
export function attributeLabel(key: string): string {
  return ATTRIBUTE_LABELS[key] ?? key.replace(/_/g, ' ')
}

/** Valuation method labels. */
export const VALUATION_METHOD_LABELS: Record<string, string> = {
  similar_transfers_quantile: '相似成交分位数',
  similar_transfers: '相似成交',
  insufficient_sample: '样本不足',
}

/** Similar-transfer factor labels (`/transfers/similar` → factors[].key and effective_weights). */
export const SIMILARITY_FACTOR_LABELS: Record<string, string> = {
  age: '年龄',
  ca: 'CA',
  pa: 'PA',
  position: '位置',
  position_group: '位置组',
  contract: '合同',
  contract_remaining_months: '合同剩余',
  fee: '费用',
  league: '联赛',
  reputation: '声望',
}

/**
 * Label of a similarity factor / effective weight key.
 * @param key Factor key from the API.
 */
export function similarityFactorLabel(key: string): string {
  return SIMILARITY_FACTOR_LABELS[key] ?? key.replace(/_/g, ' ')
}

/** Valuation basis adjustment labels. */
export const VALUATION_ADJUSTMENT_LABELS: Record<string, string> = {
  market_value_ratio: '身价系数',
  contract_factor: '合同系数',
  age_factor: '年龄系数',
  position_factor: '位置系数',
}

/**
 * Label of a valuation adjustment key.
 * @param key Adjustment key from `basis.adjustment`.
 */
export function valuationAdjustmentLabel(key: string): string {
  return VALUATION_ADJUSTMENT_LABELS[key] ?? key.replace(/_/g, ' ')
}

/**
 * Label of a valuation method.
 * @param method Wire value.
 */
export function valuationMethodLabel(method: string | null | undefined): string {
  if (!method) return '—'
  return VALUATION_METHOD_LABELS[method] ?? method
}

/** Confidence labels. */
export const CONFIDENCE_LABELS: Record<string, string> = {
  low: '低',
  medium: '中',
  high: '高',
}

/**
 * Chinese label of a confidence value.
 * @param confidence Wire value.
 */
export function confidenceLabel(confidence: string | null | undefined): string {
  if (!confidence) return '—'
  return CONFIDENCE_LABELS[confidence] ?? confidence
}

/** Import job status labels (`GET /imports` → status). */
export const IMPORT_STATUS_LABELS: Record<string, string> = {
  succeeded: '成功',
  partial: '部分成功',
  failed: '失败',
  running: '处理中',
  pending: '等待中',
  duplicate: '重复（未写入）',
}

/**
 * Label of an import job status.
 * @param status Wire value such as `partial`.
 */
export function importStatusLabel(status: string | null | undefined): string {
  if (!status) return '—'
  return IMPORT_STATUS_LABELS[status] ?? status
}

/** Alert type labels; unknown types keep their raw value. */
export const ALERT_TYPE_LABELS: Record<string, string> = {
  contract_expiry: '合同到期',
  value_change: '身价变化',
  pa_threshold: 'PA 阈值',
  youth: 'U21 关注',
  u21: 'U21 关注',
  transfer: '转会动态',
}

/**
 * Label of an alert type.
 * @param type Wire value.
 */
export function alertTypeLabel(type: string | null | undefined): string {
  if (!type) return '—'
  return ALERT_TYPE_LABELS[type] ?? type
}

/** Alert severity labels. */
export const SEVERITY_LABELS: Record<string, string> = {
  low: '低',
  medium: '中',
  high: '高',
}

/**
 * Label of an alert severity.
 * @param severity Wire value.
 */
export function severityLabel(severity: string | null | undefined): string {
  if (!severity) return '—'
  return SEVERITY_LABELS[severity] ?? severity
}

/** Development attribution classes. */
export const ATTRIBUTION_LABELS: Record<string, { title: string; hint: string }> = {
  fact: { title: '事实', hint: '数据源直接记录的观测结果' },
  correlation: { title: '相关性', hint: '两个变量同向变化，不代表因果' },
  speculation: { title: '推测', hint: '数据源未提供该指标，无法验证' },
}

/**
 * Title of an attribution kind.
 * @param kind Wire value (`fact` | `correlation` | `speculation`).
 */
export function attributionTitle(kind: string | null | undefined): string {
  if (!kind) return '未分类'
  return ATTRIBUTION_LABELS[kind]?.title ?? kind
}

/**
 * Hint of an attribution kind.
 * @param kind Wire value.
 */
export function attributionHint(kind: string | null | undefined): string {
  if (!kind) return ''
  return ATTRIBUTION_LABELS[kind]?.hint ?? ''
}

/** Agent answer mode labels. */
export const AGENT_MODE_LABELS: Record<string, string> = {
  deterministic: '确定性规则',
  llm: '大模型',
}

/**
 * Label of an agent answer mode.
 * @param mode Wire value (`deterministic` | `llm`).
 */
export function agentModeLabel(mode: string | null | undefined): string {
  if (!mode) return '—'
  return AGENT_MODE_LABELS[mode] ?? mode
}

/** Watchlist tag suggestions; free text is still allowed. */
export const WATCHLIST_TAG_OPTIONS = ['核心培养', '待观察', '租借目标', '出售候选', '合同风险']

/** Transfer sort options exposed by the transfers table. */
export const TRANSFER_SORT_OPTIONS: Array<{ value: string; label: string }> = [
  { value: '-transfer_date', label: '日期 ↓' },
  { value: 'transfer_date', label: '日期 ↑' },
  { value: '-effective_fee', label: '费用 ↓' },
  { value: 'effective_fee', label: '费用 ↑' },
]
