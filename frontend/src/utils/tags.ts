/**
 * 全局标签语义目录（V4.0-04）。
 *
 * 目标：同一状态在所有页面使用同一名称与同一语义色；内部技术字段默认不出现在普通用户界面。
 * 标签分四类：
 *   business —— 业务标签（重点关注、引援目标等，必须有真实业务依据）
 *   runtime  —— 运行状态（同步、扫描、任务执行结果）
 *   risk     —— 风险与需要用户确认的问题
 *   internal —— 内部技术信息（只在开发者诊断区域展示）
 *
 * 这里只做展示层归一化，不改变任何后端字段、数据表或 API。
 */

export type TagCategory = 'business' | 'runtime' | 'risk' | 'internal'

export type TagTone = 'success' | 'info' | 'warning' | 'danger' | 'neutral' | 'brand'

export interface TagDefinition {
  /** 稳定键，页面与测试都使用它。 */
  key: string
  /** 普通用户看到的中文名称。 */
  label: string
  category: TagCategory
  tone: TagTone
}

const define = (key: string, label: string, category: TagCategory, tone: TagTone): TagDefinition => ({
  key,
  label,
  category,
  tone,
})

/** 规范标签目录。新增标签必须先在这里登记，禁止页面内临时造词。 */
export const TAG_CATALOG: Record<string, TagDefinition> = {
  // ---------- 业务标签 ----------
  focus: define('focus', '重点关注', 'business', 'brand'),
  watching: define('watching', '已关注', 'business', 'info'),
  potential: define('potential', '潜力球员', 'business', 'info'),
  target: define('target', '引援目标', 'business', 'brand'),
  core: define('core', '核心球员', 'business', 'success'),
  sellable: define('sellable', '可出售', 'business', 'warning'),
  observe: define('observe', '值得观察', 'business', 'neutral'),
  loan_target: define('loan_target', '租借目标', 'business', 'info'),
  loan_listed: define('loan_listed', '可租借', 'business', 'info'),
  release_listed: define('release_listed', '解约挂牌', 'business', 'warning'),
  contract_expiring: define('contract_expiring', '合同即将到期', 'risk', 'warning'),
  ai_inferred: define('ai_inferred', 'AI 推测机会', 'business', 'info'),
  demo_case: define('demo_case', '演示案例', 'business', 'neutral'),
  real_case: define('real_case', '真实案例', 'business', 'success'),
  user_club: define('user_club', '玩家俱乐部', 'business', 'brand'),

  // ---------- 运行状态 ----------
  syncing: define('syncing', '正在同步', 'runtime', 'info'),
  synced: define('synced', '已同步', 'runtime', 'success'),
  sync_failed: define('sync_failed', '同步失败', 'runtime', 'danger'),
  analyzing: define('analyzing', '正在分析', 'runtime', 'info'),
  analysis_done: define('analysis_done', '分析完成', 'runtime', 'success'),
  scanning: define('scanning', '正在扫描', 'runtime', 'info'),
  resumable: define('resumable', '可继续', 'runtime', 'neutral'),
  ready: define('ready', '已就绪', 'runtime', 'success'),
  checking: define('checking', '正在检查', 'runtime', 'info'),
  needs_attention: define('needs_attention', '需要处理', 'runtime', 'warning'),
  unavailable: define('unavailable', '暂不可用', 'runtime', 'danger'),
  not_synced: define('not_synced', '未同步', 'runtime', 'neutral'),
  demo: define('demo', '演示数据', 'runtime', 'warning'),
  game_running: define('game_running', '游戏运行中', 'runtime', 'success'),
  game_stopped: define('game_stopped', '游戏未运行', 'runtime', 'neutral'),
  recognized: define('recognized', '已识别', 'runtime', 'success'),
  unrecognized: define('unrecognized', '待确认', 'runtime', 'warning'),
  heartbeat_ok: define('heartbeat_ok', '心跳有效', 'runtime', 'success'),
  heartbeat_stale: define('heartbeat_stale', '心跳超时', 'runtime', 'warning'),
  online: define('online', '在线', 'runtime', 'success'),
  offline: define('offline', '离线', 'runtime', 'neutral'),
  ok: define('ok', '正常', 'runtime', 'success'),
  attention: define('attention', '需留意', 'runtime', 'warning'),
  warn: define('warn', '需关注', 'runtime', 'warning'),
  error: define('error', '异常', 'runtime', 'danger'),
  pass: define('pass', '通过', 'runtime', 'success'),
  fail: define('fail', '未通过', 'runtime', 'danger'),
  skip: define('skip', '已跳过', 'runtime', 'neutral'),
  succeeded: define('succeeded', '成功', 'runtime', 'success'),
  partial: define('partial', '部分成功', 'runtime', 'warning'),
  failed: define('failed', '失败', 'runtime', 'danger'),
  queued: define('queued', '排队中', 'runtime', 'neutral'),
  running: define('running', '运行中', 'runtime', 'info'),
  cancel_requested: define('cancel_requested', '取消请求中', 'runtime', 'warning'),
  cancelled: define('cancelled', '已取消', 'runtime', 'neutral'),
  rejected: define('rejected', '已拒绝', 'runtime', 'danger'),
  completed: define('completed', '已完成', 'runtime', 'success'),
  pending: define('pending', '待完成', 'runtime', 'warning'),
  future: define('future', '未来生效', 'runtime', 'info'),
  unknown: define('unknown', '未知', 'runtime', 'neutral'),
  observed: define('observed', '已观测', 'runtime', 'success'),
  assumed: define('assumed', '推定', 'runtime', 'warning'),
  inferred: define('inferred', '推断', 'runtime', 'info'),
  sufficient: define('sufficient', '样本充足', 'runtime', 'success'),
  insufficient: define('insufficient', '样本不足', 'runtime', 'neutral'),
  negotiation_draft: define('negotiation_draft', '谈判草稿', 'runtime', 'neutral'),
  negotiation_active: define('negotiation_active', '谈判中', 'runtime', 'info'),
  negotiation_agreed: define('negotiation_agreed', '已同意', 'runtime', 'success'),
  negotiation_rejected: define('negotiation_rejected', '谈判已拒绝', 'runtime', 'danger'),
  negotiation_cancelled: define('negotiation_cancelled', '谈判已取消', 'runtime', 'neutral'),
  needs_review: define('needs_review', '待审核', 'runtime', 'warning'),
  resolved_manual: define('resolved_manual', '人工确认', 'runtime', 'success'),
  excluded: define('excluded', '已排除', 'runtime', 'neutral'),
  review_required: define('review_required', '需复核', 'runtime', 'warning'),
  resolved: define('resolved', '自动确认', 'runtime', 'success'),
  resolved_auto: define('resolved_auto', '规则确认', 'runtime', 'success'),
  ai_llm: define('ai_llm', 'AI 大模型', 'runtime', 'info'),
  ai_rules: define('ai_rules', '本地规则', 'runtime', 'neutral'),
  enabled: define('enabled', '已启用', 'runtime', 'success'),
  disabled: define('disabled', '未启用', 'runtime', 'neutral'),

  // ---------- 风险与确认 ----------
  needs_confirmation: define('needs_confirmation', '需要你确认', 'risk', 'warning'),
  identity_conflict: define('identity_conflict', '身份冲突', 'risk', 'danger'),
  identity_unverified: define('identity_unverified', '身份待确认', 'risk', 'warning'),
  conflict: define('conflict', '冲突', 'risk', 'danger'),
  verified: define('verified', '已确认', 'risk', 'success'),
  candidate: define('candidate', '候选', 'risk', 'warning'),
  discovered: define('discovered', '已发现', 'risk', 'info'),
  invalidated: define('invalidated', '已失效', 'risk', 'neutral'),
  contract_risk: define('contract_risk', '合同风险', 'risk', 'danger'),
  data_incomplete: define('data_incomplete', '数据不完整', 'risk', 'warning'),
  anomaly: define('anomaly', '存在异常', 'risk', 'danger'),
  listed: define('listed', '已挂牌', 'risk', 'warning'),
  not_for_sale: define('not_for_sale', '非卖品', 'risk', 'danger'),
  unread: define('unread', '未读', 'risk', 'brand'),
  risk_low: define('risk_low', '低风险', 'risk', 'success'),
  risk_medium: define('risk_medium', '中风险', 'risk', 'warning'),
  risk_high: define('risk_high', '高风险', 'risk', 'danger'),
  contract_expiry: define('contract_expiry', '合同到期', 'risk', 'warning'),
  value_change: define('value_change', '身价变化', 'risk', 'info'),
  pa_threshold: define('pa_threshold', 'PA 阈值', 'risk', 'info'),
  youth: define('youth', 'U21 关注', 'risk', 'info'),
  transfer: define('transfer', '转会动态', 'risk', 'info'),
  reliability_fact: define('reliability_fact', '事实依据', 'business', 'success'),
  reliability_computed: define('reliability_computed', '计算结果', 'business', 'brand'),
  reliability_inference: define('reliability_inference', '推断结论', 'business', 'warning'),
  reliability_unavailable: define('reliability_unavailable', '无法获得', 'business', 'neutral'),

  // ---------- 内部技术信息（默认隐藏） ----------
  scan_id: define('scan_id', '扫描编号', 'internal', 'neutral'),
  revision: define('revision', '修订号', 'internal', 'neutral'),
  identity_mapping: define('identity_mapping', '身份映射', 'internal', 'neutral'),
  reconciliation: define('reconciliation', '数据核对', 'internal', 'neutral'),
  raw_record: define('raw_record', '原始记录', 'internal', 'neutral'),
  source_hash: define('source_hash', '源指纹', 'internal', 'neutral'),
  database_version: define('database_version', '数据库版本', 'internal', 'neutral'),
  demo_mode: define('demo_mode', '演示模式', 'internal', 'neutral'),
  instance_id: define('instance_id', '实例编号', 'internal', 'neutral'),
  snapshot: define('snapshot', '快照', 'internal', 'neutral'),
  source: define('source', '数据来源', 'internal', 'neutral'),
  fingerprint: define('fingerprint', '存档指纹', 'internal', 'neutral'),
  generation: define('generation', '写入代次', 'internal', 'neutral'),
  session_id: define('session_id', '会话编号', 'internal', 'neutral'),
  evidence: define('evidence', '证据级别', 'internal', 'neutral'),
  game_build: define('game_build', '游戏构建号', 'internal', 'neutral'),
  scan_task: define('scan_task', '扫描任务', 'internal', 'neutral'),
}

/**
 * 历史文案 / 自由文本 → 规范键。
 * 只归一化已知语义；未知自由文本原样保留，避免丢失用户自己填写的标签。
 */
export const TAG_ALIASES: Record<string, string> = {
  // 关注名单自由文本
  重点关注: 'focus',
  普通关注: 'watching',
  已关注: 'watching',
  核心培养: 'core',
  重点培养: 'core',
  核心: 'core',
  待观察: 'observe',
  重点观察: 'observe',
  值得观察: 'observe',
  出售候选: 'sellable',
  出售观察: 'sellable',
  可出售: 'sellable',
  租借目标: 'loan_target',
  潜力新星: 'potential',
  潜力球员: 'potential',
  引援候选: 'target',
  引援目标: 'target',
  合同风险: 'contract_risk',
  需要你确认: 'needs_confirmation',
  玩家俱乐部: 'user_club',
  // 数据状态
  '已有真实扫描数据': 'synced',
  '尚无真实扫描数据': 'not_synced',
  '演示数据': 'demo',
  'demo_mode = true': 'demo',
  '正常': 'ok',
  '需留意': 'attention',
  '需关注': 'warn',
  '异常': 'error',
  '通过': 'pass',
  '未通过': 'fail',
  '已跳过': 'skip',
  '已识别': 'recognized',
  '待确认': 'unrecognized',
  '运行中': 'running',
  '未运行': 'game_stopped',
  '心跳有效': 'heartbeat_ok',
  '心跳超时/未知': 'heartbeat_stale',
  '已连接': 'online',
  '已断开': 'offline',
  '在线': 'online',
  '离线': 'offline',
  '已启用': 'enabled',
  '未启用': 'disabled',
  '样本充足': 'sufficient',
  '样本不足': 'insufficient',
  '可继续': 'resumable',
  '已确认': 'verified',
  '已发现': 'discovered',
  '候选': 'candidate',
  '冲突': 'conflict',
  '已失效': 'invalidated',
  '未知': 'unknown',
  '成功': 'succeeded',
  '部分成功': 'partial',
  '失败': 'failed',
  '排队中': 'queued',
  '取消请求中': 'cancel_requested',
  '已取消': 'cancelled',
  '已拒绝': 'rejected',
  '已完成': 'completed',
  '待完成': 'pending',
  '未来生效': 'future',
  '已观测': 'observed',
  '推定': 'assumed',
  '推断': 'inferred',
  '合同到期': 'contract_expiry',
  '身价变化': 'value_change',
  'PA 阈值': 'pa_threshold',
  'U21 关注': 'youth',
  '转会动态': 'transfer',
  '已挂牌': 'listed',
  '非卖品': 'not_for_sale',
  '未读': 'unread',
}

/** 内部技术标签键；`visibleTags` 默认过滤。 */
export const INTERNAL_TAG_KEYS = new Set(
  Object.values(TAG_CATALOG)
    .filter((tag) => tag.category === 'internal')
    .map((tag) => tag.key),
)

/**
 * 把任意标签文本解析为规范定义。
 * 未知文本保持原样并归入业务类的中性色，保证用户自填标签不丢失。
 */
export function resolveTag(raw: string | null | undefined): TagDefinition | null {
  if (raw === null || raw === undefined) return null
  const text = String(raw).trim()
  if (!text) return null
  const direct = TAG_CATALOG[text] ?? TAG_CATALOG[text.toLowerCase()]
  if (direct) return direct
  const alias = TAG_ALIASES[text]
  if (alias && TAG_CATALOG[alias]) return TAG_CATALOG[alias]
  return { key: text, label: text, category: 'business', tone: 'neutral' }
}

/** 某个标签文本是否属于内部技术信息。 */
export function isInternalTag(raw: string | null | undefined): boolean {
  const definition = resolveTag(raw)
  return definition?.category === 'internal'
}

/**
 * 普通界面使用的标签列表：过滤空值、内部技术标签并按语义去重。
 * @param tags 后端或页面提供的原始标签。
 * @param options.diagnostics 开发者诊断区域传 `true`，内部标签才会出现。
 */
export function visibleTags(
  tags: ReadonlyArray<string | null | undefined> | null | undefined,
  options: { diagnostics?: boolean } = {},
): TagDefinition[] {
  if (!tags) return []
  const seen = new Set<string>()
  const result: TagDefinition[] = []
  for (const raw of tags) {
    const definition = resolveTag(raw)
    if (!definition) continue
    if (definition.category === 'internal' && !options.diagnostics) continue
    if (seen.has(definition.key)) continue
    seen.add(definition.key)
    result.push(definition)
  }
  return result
}

/** 风险等级（low / medium / high）→ 语义标签。 */
export function riskTag(level: string | null | undefined): TagDefinition {
  if (level === 'low') return TAG_CATALOG.risk_low
  if (level === 'medium') return TAG_CATALOG.risk_medium
  if (level === 'high') return TAG_CATALOG.risk_high
  return TAG_CATALOG.unknown
}

/** 合同剩余月数 → 语义标签（≤6 高风险，≤12 提醒）。 */
export function contractTag(months: number | null | undefined): TagDefinition {
  if (months === null || months === undefined) return TAG_CATALOG.unknown
  if (months <= 6) return TAG_CATALOG.risk_high
  if (months <= 12) return TAG_CATALOG.risk_medium
  return TAG_CATALOG.risk_low
}
