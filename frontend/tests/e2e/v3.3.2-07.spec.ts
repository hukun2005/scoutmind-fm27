import { test, expect, type Page, type Route } from '@playwright/test'

/**
 * V3.3.2-07 普通用户体验：首次启动引导、数据中心健康卡片、扫描进度与学习状态。
 * 全部接口使用 page.route Mock，不依赖真实后端与真实存档数据。
 */

const meta = {
  product: 'ScoutMind',
  version: '3.3.2',
  demo_mode: false,
  auth_required: false,
  active_save_id: 1,
  saves: [
    {
      id: 1,
      name: '测试存档',
      game_version: '27.1',
      game_build: '26620374',
      created_at: '2026-11-01T00:00:00Z',
      is_active: true,
      player_count: 4,
      snapshot_count: 8,
      transfer_count: 0,
      last_import_at: '2026-11-26T10:00:00Z',
    },
  ],
  data_sources: [],
  capabilities: {
    live_reader: true,
    save_parser: true,
    agent_llm: false,
    watchlist: true,
    transfer_intelligence: true,
  },
  warnings: [],
}

const emptyOnboarding = {
  save: { id: 1, name: '测试存档', game_version: '27.1', status: 'ready' },
  checks: [
    { key: 'database', label: '本地数据库', status: 'ready', detail: '已连接 SQLite' },
    { key: 'backend', label: '本地服务', status: 'ready' },
    { key: 'live_reader', label: '游戏读取器', status: 'unavailable', detail: '未检测到读取器' },
  ],
  status: 'needs_attention',
  data: {
    has_players: false,
    player_count: 0,
    club_count: 0,
    linked_players: 0,
    unlinked_players: 0,
    opportunity_count: 0,
    transfer_count: 0,
    last_updated_at: null,
    recoverable_tasks: [],
    pending_checks: [],
  },
  summary: {
    player_count: 0,
    club_count: 0,
    opportunity_count: 0,
    last_updated_at: null,
    save_status: '还没有导入数据',
  },
  actions: [
    { key: 'import', label: '开始导入', enabled: true },
    { key: 'scan', label: '重新扫描', enabled: true },
    { key: 'data', label: '查看数据状态', enabled: true },
  ],
}

const readyOnboarding = {
  ...emptyOnboarding,
  status: 'ready',
  data: {
    ...emptyOnboarding.data,
    has_players: true,
    player_count: 4,
    club_count: 2,
  },
  summary: {
    player_count: 4,
    club_count: 2,
    opportunity_count: 1,
    last_updated_at: '2026-11-27T08:00:00Z',
    save_status: '已有可用数据',
  },
}

const dataHealth = {
  save: { id: 1, name: '测试存档', game_date: '2026-07-01' },
  players: { count: 4, linked: 3, unlinked: 1, missing_source_field: 1 },
  clubs: { count: 2, linked_players: 3 },
  transfers: { count: 0, completed: 0 },
  opportunities: { active: 1, confirmed: 1, inferred: 0 },
  status: { level: 'warn', label: '部分缺失', reasons: ['有 1 名球员缺少俱乐部归属'] },
  last_updated_at: '2026-11-27T08:00:00Z',
  background: { active: 0, latest: { task_id: 'task-1', status: 'COMPLETED', message: '上次扫描已完成' } },
  can_repair: true,
  notes: ['无法确认俱乐部归属的球员保持 MISSING_SOURCE_FIELD'],
}

const diagnostics = {
  checks: [
    { key: 'duplicate_imports', label: '重复导入', status: 'pass', count: 0 },
    { key: 'orphan_clubs', label: '悬空俱乐部引用', status: 'pass', count: 0 },
    { key: 'stale_scan', label: '扫描新鲜度', status: 'warn', detail: '上次扫描已超过 7 天' },
  ],
  summary: { pass: 2, warn: 1, fail: 0 },
  repairable: ['club_links'],
}

const repairResponse = {
  dry_run: false,
  executed: [{ target: 'club_links', scanned: 4, linked: 1, failed: 0 }],
  skipped: [{ target: 'player_identity', reason: '不确定身份不允许自动修复' }],
  health: dataHealth,
  message: '已完成可安全修复的项目',
}

const hubStatus = {
  game: {
    running: false,
    detected: true,
    pid: null,
    version: null,
    exe_path: null,
    message: '未检测到 Football Manager 27',
    compatibility: 'unknown',
    compatibility_message: '',
  },
  save: { id: 1, name: '测试存档', recognized: true, identity_status: 'verified', can_sync: true, message: '' },
  records: { players: 4, clubs: 2, transfers: 0, snapshots: 8 },
  last_sync: null,
  health: { status: 'attention', issues: [] },
  needs_confirmation: { unresolved_players: 1, identity_conflicts: 0, quarantined_rows: 0, total: 1 },
  repairs: {},
}

const fmscoutAdapter = {
  adapter: 'fmsuperscout',
  version: '1.0.0',
  upstream: { name: 'FMSuperScout', url: 'https://example.com', license: 'MIT', note: '测试适配器' },
  mapped_fields: [],
  absent_fields: [],
  ignored_fields: [],
  attribute_map: {},
  unmapped_attributes: [],
}

const saveSummary = {
  save: { id: 1, name: '测试存档' },
  coverage: { players: 4, snapshots: 8, transfers: 0, clubs: 2 },
  last_import: null,
}

const overview = {
  save_id: 1,
  user_club_id: 3,
  player_count: 4,
  players_with_wage: 4,
  players_with_contract: 3,
  unknown_contract_fields: 1,
  transfer_count: 0,
  recent_transfers_30d: 0,
  loan_count: 0,
  clause_count: 0,
  identity_conflicts: 0,
  last_sync_at: '2026-11-26T10:00:00',
  offers: 0,
  negotiations: {},
  negotiations_total: 0,
  capabilities: { auto_transfer_history: false, auto_contract: true, auto_loan_terms: false, auto_budget: false },
  message: '当前存档有 4 名球员。',
}

const opportunitySummary = {
  save_id: 1,
  scan_version: 'transfer-radar-2',
  last_scan_at: '2026-11-27T08:00:00Z',
  counts: { listed: 1, loan_listed: 0, release_listed: 0, contract_expiring: 0, ai_inferred: 0, new_24h: 1 },
  groups: { strong: 1 },
  group_labels: {},
  top_recommendations: [],
  alerts_unread: 0,
  capabilities: {},
  unsupported_fields: [],
  auto_scan: null,
}

const runningTask = {
  task_id: 'task-1',
  save_id: 1,
  task_type: 'FULL_SCAN',
  status: 'RUNNING',
  status_key: 'RUNNING',
  current_stage: '分析球员状态',
  eta_seconds: 300,
  heartbeat_at: '2026-11-27T12:00:02',
  resumable: true,
  progress: 50,
  total: 100,
  processed: 50,
  matched: 12,
  failed: 0,
  started_at: '2026-11-27T12:00:00',
  finished_at: null,
  error_code: null,
  error_message: null,
  created_by: 'local',
  source_snapshot_id: 1,
  attempt_count: 1,
  checkpoint: {},
  result: {},
  message: '正在更新转会情报',
  cancel_requested: false,
}

const learningStatus = {
  save_id: 1,
  available: true,
  data_version: 'cases:3:feedback:1:2026-11-27T10:00:00Z',
  totals: { cases: 3, completed_transfers: 2, negotiation_cases: 1, demo_cases: 0 },
  by_type: { permanent: 2, loan: 1 },
  confidence: { level: 'preliminary', label: '初步参考', sample_size: 3, note: '样本仍然有限' },
  patterns: [
    {
      key: 'installments',
      sample_size: 2,
      confidence: { level: 'preliminary', label: '初步参考', sample_size: 2 },
      summary: '分期付款在成交中多次出现',
    },
  ],
  message: null,
}

interface MockOptions {
  onboarding?: 'empty' | 'ready'
  scan?: boolean
}

async function mockApi(page: Page, options: MockOptions = {}) {
  const calls: Array<{ path: string; method: string; body: unknown }> = []

  await page.route('**/api/v1/**', async (route: Route) => {
    const url = new URL(route.request().url())
    const path = url.pathname
    const method = route.request().method()
    const json = (body: unknown) => route.fulfill({ json: body })
    const body = route.request().postData() ? JSON.parse(route.request().postData() as string) : null
    calls.push({ path, method, body })

    if (path.endsWith('/meta/bootstrap')) return json(meta)
    if (path.endsWith('/meta/saves')) return json({ items: meta.saves })

    if (path.endsWith('/system/onboarding')) {
      return json(options.onboarding === 'empty' ? emptyOnboarding : readyOnboarding)
    }
    if (path.endsWith('/system/data-health')) return json(dataHealth)
    if (path.endsWith('/system/diagnostics') && method === 'POST') return json(diagnostics)
    if (path.endsWith('/system/repair') && method === 'POST') return json(repairResponse)

    if (path.endsWith('/data-hub/status')) return json(hubStatus)
    if (path.endsWith('/imports/fmscout/adapter')) return json(fmscoutAdapter)
    if (path.endsWith('/imports')) return json({ items: [], total: 0, limit: 50, offset: 0 })
    if (path.endsWith('/saves/1/summary')) return json(saveSummary)
    if (path.endsWith('/analytics/overview')) return json({ save_id: 1, coverage: {}, data_gaps: [] })
    if (path.endsWith('/compatibility')) return json({ items: [], reader_versions: [] })

    if (path.endsWith('/transfer-director/overview')) return json(overview)
    if (path.endsWith('/transfer-director/club-summary')) return json({ club_id: 3, club_name: 'Northbridge United' })
    if (path.endsWith('/transfer-director/negotiations')) return json({ items: [], total: 0 })
    if (path.endsWith('/transfer-director/opportunities/summary')) return json(opportunitySummary)
    if (path.endsWith('/transfer-director/opportunities')) {
      return json({ items: [], total: 0, limit: 20, offset: 0 })
    }
    if (path.endsWith('/transfer-director/alerts')) return json({ items: [], unread: 0 })
    if (path.endsWith('/transfer-director/club-links/health')) {
      return json({
        save_id: 1,
        status: 'OK',
        total_players: 4,
        linked: 4,
        states: {},
        state_labels: {},
        state_notes: {},
        club_link_rate: 1,
        link_rate_of_total: 1,
        latest_observed_linked: 4,
        sources: {},
        clubs: { total: 2, with_players: 2, valid: 2 },
        opportunities: { total: 1, with_club: 1 },
      })
    }
    if (path.endsWith('/transfer-director/clubs/5/habits')) {
      return json({
        club_id: 5,
        club_name: 'Kingsport City',
        available: false,
        direction: 'selling',
        observations: { completed: 0, loans: 0, free: 0, installments: 0, addons: 0, buyout: 0 },
        patterns: [],
        confidence: { level: 'none', label: '暂无参考', sample_size: 0 },
        message: '暂无足够数据',
      })
    }
    if (path.endsWith('/transfer-director/clubs/5/players')) {
      return json({ club_id: 5, club_name: 'Kingsport City', items: [], total: 0, limit: 12, offset: 0 })
    }
    if (path.endsWith('/transfer-director/clubs')) {
      return json({ items: [], total: 0, limit: 200, offset: 0, unlinked_players: 0 })
    }
    if (path.endsWith('/transfer-director/strategy-cases')) {
      return json({ items: [], total: 0, available: true, message: null })
    }
    if (path.endsWith('/transfer-director/strategy-insights')) {
      return json({ save_id: 1, available: true, patterns: [], totals: {}, message: null, min_sample: 3 })
    }
    if (path.endsWith('/transfer-director/learning-status')) return json(learningStatus)

    if (path.endsWith('/transfer-director/scans/task-1') && method === 'GET') return json(runningTask)
    if (path.endsWith('/transfer-director/scans') && method === 'GET') {
      if (options.scan && url.searchParams.get('active_only') === 'true') {
        return json({ items: [runningTask], total: 1 })
      }
      return json({ items: [], total: 0 })
    }
    if (path.endsWith('/transfer-director/scans') && method === 'POST') {
      return route.fulfill({ status: 202, json: { task: runningTask, reused: true } })
    }

    if (path.endsWith('/transfers')) return json({ items: [], total: 0, coverage: {} })
    if (path.endsWith('/players')) return json({ items: [], total: 0, coverage: {} })
    return json({})
  })

  return calls
}

test.beforeEach(async ({ page }) => {
  // 只清理首次加载的存储；reload 时保留用户刚写入的引导状态。
  await page.addInitScript(() => {
    if (!window.sessionStorage.getItem('e2e-initialized')) {
      window.localStorage.clear()
      window.sessionStorage.setItem('e2e-initialized', '1')
    }
  })
})

/** Suppress the global onboarding dialog for tests that are not about it. */
async function suppressOnboarding(page: Page) {
  await page.addInitScript(() => window.localStorage.setItem('scoutmind.onboardingDismissed', '1'))
}

test('首次启动引导：无数据时给出导入入口，关闭后记住状态', async ({ page }) => {
  await mockApi(page, { onboarding: 'empty' })
  await page.goto('/data')

  await expect(page.getByText('欢迎使用 ScoutMind')).toBeVisible()
  await expect(page.getByText('开始导入')).toBeVisible()
  await expect(page.getByText('查看数据状态')).toBeVisible()
  await expect(page.getByText('还没有导入数据，可以先导入或扫描当前存档。')).toBeVisible()

  await page.getByRole('button', { name: '跳过引导' }).click()
  const dismissed = await page.evaluate(() => window.localStorage.getItem('scoutmind.onboardingDismissed'))
  expect(dismissed).toBe('1')

  await page.reload()
  await expect(page.getByText('欢迎使用 ScoutMind')).toHaveCount(0)
})

test('数据中心：健康卡片可一键检查，检查结果与原有导入区同时存在', async ({ page }) => {
  await suppressOnboarding(page)
  await mockApi(page, { onboarding: 'ready' })
  await page.goto('/data')

  const card = page.getByTestId('data-health-card')
  await expect(card).toBeVisible()
  await expect(card.getByText('测试存档')).toBeVisible()
  await expect(card.getByText('部分缺失')).toBeVisible()
  await expect(card.getByTestId('data-check')).toBeVisible()
  await expect(card.getByTestId('data-import')).toBeVisible()
  await expect(card.getByTestId('data-repair')).toBeVisible()

  await card.getByTestId('data-check').click()
  await expect(page.getByText('检查完成：2 项通过，1 项需要关注')).toBeVisible()
  await expect(card.getByText('重复导入')).toBeVisible()
  await expect(card.getByText('扫描新鲜度')).toBeVisible()
  await expect(card.getByText('需关注')).toBeVisible()

  // 既有导入区与数据状态区块保持可见。
  await expect(page.getByRole('heading', { name: '文件导入' })).toBeVisible()
  await expect(page.getByRole('button', { name: '导入数据' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '数据状态' })).toBeVisible()
})

test('扫描进度：显示当前阶段、已处理数量与预计剩余时间', async ({ page }) => {
  await suppressOnboarding(page)
  await mockApi(page, { onboarding: 'ready', scan: true })
  await page.goto('/transfer-director')

  await expect(page.getByText('当前阶段：分析球员状态')).toBeVisible()
  await expect(page.getByText(/已处理 50 \/ 100/)).toBeVisible()
  await expect(page.getByText('预计剩余约 5 分钟')).toBeVisible()
  await expect(page.getByText('可继续')).toBeVisible()
  await expect(page.getByRole('button', { name: '取消扫描' })).toBeVisible()
})

test('学习状态：展示案例样本数量与初步置信度文案', async ({ page }) => {
  await suppressOnboarding(page)
  await mockApi(page, { onboarding: 'ready' })
  await page.goto('/transfer-director?section=strategy')

  const learning = page.getByTestId('learning-status')
  await expect(learning).toBeVisible()
  await expect(learning.getByText('有效案例')).toBeVisible()
  await expect(learning.getByText('成交案例')).toBeVisible()
  await expect(learning).toContainText('初步参考')
  await expect(learning).toContainText('样本 3')
  await expect(learning).toContainText('cases:3:feedback:1')
  await expect(learning.getByText('分期付款在成交中多次出现')).toBeVisible()
})
