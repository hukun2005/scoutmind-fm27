import { test, expect, type Page, type Route } from '@playwright/test'

/**
 * V3.3.2-05.2 转会雷达后台扫描与俱乐部关联 UI 契约。
 * 全部接口使用 page.route Mock，不依赖真实后端。
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
  capabilities: { live_reader: true, save_parser: true, agent_llm: false, watchlist: true, transfer_intelligence: true },
  warnings: [],
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

const opportunityItem = {
  opportunity_id: 1,
  instance_id: 12,
  player_name: 'Mario Bianchi',
  club_id: 5,
  club_name: 'Kingsport City',
  position: 'ST',
  age: 24,
  market_value: 35_000_000,
  wage: 45_000,
  contract_end: '2028-06-30',
  contract_remaining_months: 19,
  contract_bucket: '24m',
  listed: true,
  loan_listed: false,
  set_for_release: false,
  opportunity_type: 'listed',
  verified_status: 'confirmed',
  confidence: 1.0,
  source: 'player_availability',
  is_primary: true,
  scores: { ability: 80, squad_fit: 75, opportunity: 85, financial: null, overall: 82.3, confidence: 0.85 },
  recommendation_group: 'strong',
  detail: { signals: [], bucket: '24m', remaining_months: 19 },
  types: ['listed'],
  first_seen_at: '2026-11-27T08:00:00Z',
  last_seen_at: '2026-11-27T08:00:00Z',
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

const healthMissing = {
  save_id: 1,
  status: 'PARTIAL_SOURCE',
  total_players: 4,
  linked: 1,
  states: { LINKED: 1, NO_CLUB: 0, UNRESOLVED: 0, INVALID_REFERENCE: 0, MISSING_SOURCE_FIELD: 3 },
  state_labels: {},
  state_notes: {},
  club_link_rate: 1.0,
  link_rate_of_total: 0.25,
  latest_observed_linked: 1,
  sources: { player_club_field: 1 },
  clubs: { total: 2, with_players: 2, valid: 2 },
  opportunities: { total: 1, with_club: 1 },
}

const clubRows = [
  {
    club_id: 5,
    uid: 'club-5',
    name: 'Kingsport City',
    nation: 'England',
    league: 'Premier League',
    reputation: 7000,
    source: 'payload',
    confidence: 1.0,
    players: 4,
    opportunities: { listed: 1 },
    opportunities_total: 1,
  },
  {
    club_id: 6,
    uid: 'club-6',
    name: 'Old Town',
    nation: 'England',
    league: 'Championship',
    reputation: 5000,
    source: 'payload',
    confidence: 1.0,
    players: 0,
    opportunities: {},
    opportunities_total: 0,
  },
]

const clubPlayerRows = [
  {
    instance_id: 12,
    player_name: 'Mario Bianchi',
    club_id: 5,
    club_name: 'Kingsport City',
    position: 'ST',
    age: 24,
    market_value: 35_000_000,
    contract_end: '2028-06-30',
    overall_score: 82.3,
    opportunity_types: ['listed'],
    club_link_source: 'player_club_field',
  },
]

type TaskStatus = 'PENDING' | 'RUNNING' | 'CANCELLING' | 'COMPLETED' | 'CANCELLED' | 'FAILED' | 'PARTIAL'

interface TaskOptions {
  statuses: TaskStatus[]
  result?: Record<string, unknown>
  errorMessage?: string | null
  activeOnList?: boolean
}

function taskPayload(status: TaskStatus, options: TaskOptions) {
  return {
    task_id: 'task-1',
    save_id: 1,
    task_type: 'FULL_SCAN',
    status,
    progress: status === 'COMPLETED' ? 100 : 50,
    total: 4,
    processed: status === 'COMPLETED' ? 4 : 2,
    matched: 1,
    failed: 0,
    started_at: '2026-11-27T12:00:00',
    finished_at: status === 'COMPLETED' ? '2026-11-27T12:00:03' : null,
    error_code: null,
    error_message: options.errorMessage ?? null,
    created_by: 'local',
    source_snapshot_id: 1,
    attempt_count: 1,
    checkpoint: {},
    result: options.result ?? {},
    message:
      status === 'COMPLETED'
        ? '转会情报更新完成'
        : status === 'CANCELLING'
          ? '正在取消扫描'
          : status === 'CANCELLED'
            ? '扫描已取消'
            : status === 'FAILED'
              ? '本次转会情报更新未能完成，系统可以安全重试'
              : '正在更新转会情报',
    cancel_requested: status === 'CANCELLING',
  }
}

async function mockApi(page: Page, options: TaskOptions & { resumeActive?: boolean } = { statuses: ['COMPLETED'] }) {
  const calls: Array<{ path: string; method: string; body: unknown; query: Record<string, string> }> = []
  const statuses = [...options.statuses]
  let scanPolls = 0
  let cancelled = false

  const handler = async (route: Route) => {
    const url = new URL(route.request().url())
    const path = url.pathname
    const method = route.request().method()
    const json = (body: unknown) => route.fulfill({ json: body })
    const body = route.request().postData() ? JSON.parse(route.request().postData() as string) : null
    const query = Object.fromEntries(url.searchParams.entries())
    calls.push({ path, method, body, query })

    if (path.endsWith('/meta/bootstrap')) return json(meta)
    if (path.endsWith('/meta/saves')) return json({ items: meta.saves })
    if (path.endsWith('/transfer-director/overview')) return json(overview)
    if (path.endsWith('/transfer-director/club-summary')) return json({ club_id: 3, club_name: 'Northbridge United' })
    if (path.endsWith('/transfer-director/negotiations')) return json({ items: [], total: 0 })
    if (path.endsWith('/transfer-director/opportunities/summary')) return json(opportunitySummary)
    if (path.endsWith('/transfer-director/opportunities')) {
      return json({ items: [opportunityItem], total: 1, limit: 20, offset: 0 })
    }
    if (path.endsWith('/transfer-director/alerts')) return json({ items: [], unread: 0 })
    if (path.endsWith('/transfer-director/club-links/health')) return json(healthMissing)
    if (path.endsWith('/transfer-director/club-links/repair') && method === 'POST') {
      return json({
        save_id: 1,
        dry_run: false,
        rule_id: 'v3.3.2-05.2',
        scanned: 4,
        linked: 1,
        already_linked: 1,
        backfilled_snapshot: 0,
        backfilled_assignment: 0,
        repaired_reference: 0,
        cleared_invalid: 0,
        unresolved: 0,
        failed: 0,
        duration_ms: 12,
      })
    }
    if (path.endsWith('/transfer-director/clubs/5/players')) {
      return json({ club_id: 5, club_name: 'Kingsport City', items: clubPlayerRows, total: 1, limit: 12, offset: 0 })
    }
    if (path.endsWith('/transfer-director/clubs')) {
      return json({
        items: clubRows,
        total: clubRows.length,
        limit: 200,
        offset: 0,
        unlinked_players: 3,
      })
    }
    if (path.endsWith('/transfer-director/scans') && method === 'POST') {
      const first = statuses[0] ?? 'RUNNING'
      return route.fulfill({ status: 202, json: { task: taskPayload(first, options), reused: false } })
    }
    if (path.endsWith('/transfer-director/scans') && method === 'GET') {
      if (query.active_only === 'true') {
        if (options.resumeActive) {
          return json({ items: [taskPayload('RUNNING', options)], total: 1 })
        }
        return json({ items: [], total: 0 })
      }
      return json({ items: [], total: 0 })
    }
    if (path.endsWith('/transfer-director/scans/task-1/cancel') && method === 'POST') {
      cancelled = true
      return json(taskPayload('CANCELLING', options))
    }
    if (path.endsWith('/transfer-director/scans/task-1')) {
      if (cancelled) return json(taskPayload('CANCELLED', options))
      const status = statuses[Math.min(scanPolls, statuses.length - 1)]
      scanPolls += 1
      return json(taskPayload(status, options))
    }
    if (path.endsWith('/transfer-director/strategy-cases')) return json({ items: [], total: 0, available: true, message: null })
    if (path.endsWith('/transfer-director/strategy-insights')) {
      return json({ save_id: 1, available: true, patterns: [], totals: {}, message: null, min_sample: 3 })
    }
    if (path.endsWith('/players')) return json({ items: [], total: 0, coverage: {} })
    if (path.endsWith('/transfers')) return json({ items: [], total: 0, coverage: {} })
    return json({})
  }

  await page.route('**/api/v1/**', handler)
  return calls
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => window.localStorage.clear())
})

test('俱乐部字段缺失：显示真实原因并可安全修复', async ({ page }) => {
  const calls = await mockApi(page)
  await page.goto('/transfer-director')

  await expect(page.getByText('当前存档有大量球员缺少俱乐部字段')).toBeVisible()
  await expect(page.getByText('系统不会按姓名猜测俱乐部')).toBeVisible()
  await expect(page.getByText('来源未提供字段 3 人')).toBeVisible()

  await page.getByRole('button', { name: '修复俱乐部关联' }).click()
  await expect(page.getByText(/俱乐部关联修复完成/)).toBeVisible()
  const repair = calls.find((call) => call.path.endsWith('/transfer-director/club-links/repair'))
  expect(repair?.body).toMatchObject({ dry_run: false })
})

test('后台扫描：显示进度、完成后刷新', async ({ page }) => {
  const calls = await mockApi(page, {
    statuses: ['PENDING', 'RUNNING', 'COMPLETED'],
    result: { created: 3, updated: 1, deactivated: 0 },
  })
  await page.goto('/transfer-director')

  await page.getByRole('button', { name: '刷新转会情报' }).click()
  await expect(page.getByText(/已处理/)).toBeVisible()
  await expect(page.getByText('正在更新转会情报')).toBeVisible()
  await expect(page.getByText(/扫描完成/)).toBeVisible({ timeout: 10000 })
  expect(calls.some((call) => call.method === 'POST' && call.path.endsWith('/transfer-director/scans'))).toBeTruthy()
})

test('后台扫描：可以取消且保留已完成数据', async ({ page }) => {
  await mockApi(page, { statuses: ['RUNNING', 'RUNNING'] })
  await page.goto('/transfer-director')

  await page.getByRole('button', { name: '刷新转会情报' }).click()
  await expect(page.getByText('正在更新转会情报')).toBeVisible()
  await page.getByRole('button', { name: '取消扫描' }).click()
  await expect(page.getByText('扫描已取消，已完成的批次已保留')).toBeVisible({ timeout: 10000 })
})

test('刷新页面会恢复正在运行的任务进度', async ({ page }) => {
  await mockApi(page, { statuses: ['RUNNING'], resumeActive: true })
  await page.goto('/transfer-director')
  await expect(page.getByText('正在更新转会情报')).toBeVisible()
  await expect(page.getByText(/已处理/)).toBeVisible()
})

test('俱乐部聚合：筛选机会并下钻球员', async ({ page }) => {
  const calls = await mockApi(page)
  await page.goto('/transfer-director')

  await page.locator('.club-filter').click()
  await page.getByText('Kingsport City（4）').click()
  await expect
    .poll(() =>
      calls.some(
        (call) =>
          call.path.endsWith('/transfer-director/opportunities') && call.query.club_id === '5',
      ),
    )
    .toBe(true)

  await page.locator('.club-panel').getByRole('cell', { name: 'Kingsport City' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByText('Mario Bianchi')).toBeVisible()
  await expect(dialog.getByText('已挂牌')).toBeVisible()

  await page.locator('.club-state-select').click()
  await page.locator('.el-select-dropdown__item').filter({ hasText: '已挂牌' }).last().click()
  await expect
    .poll(() =>
      calls.some(
        (call) => call.path.endsWith('/transfer-director/clubs/5/players') && call.query.state === 'listed',
      ),
    )
    .toBe(true)
})
