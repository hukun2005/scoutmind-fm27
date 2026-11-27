import { test, expect, type Page, type Route } from '@playwright/test'

/**
 * V3.3.2-08 在线持续学习：学习状态、重点俱乐部、最近动态与暂停/恢复。
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
      transfer_count: 2,
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

const overview = {
  save_id: 1,
  user_club_id: 3,
  player_count: 4,
  players_with_wage: 4,
  players_with_contract: 3,
  unknown_contract_fields: 1,
  transfer_count: 2,
  recent_transfers_30d: 2,
  loan_count: 0,
  clause_count: 0,
  identity_conflicts: 0,
  last_sync_at: '2026-11-26T10:00:00',
  offers: 0,
  negotiations: {},
  negotiations_total: 0,
  capabilities: { auto_transfer_history: true, auto_contract: true, auto_loan_terms: false, auto_budget: false },
  message: '当前存档有 4 名球员。',
}

const opportunitySummary = {
  save_id: 1,
  scan_version: 'transfer-radar-2',
  last_scan_at: '2026-11-27T08:00:00Z',
  counts: { listed: 1, loan_listed: 0, release_listed: 0, contract_expiring: 0, ai_inferred: 0, new_24h: 1 },
  groups: {},
  group_labels: {},
  top_recommendations: [],
  alerts_unread: 0,
  capabilities: {},
  unsupported_fields: [],
  auto_scan: null,
}

const learningStatus = {
  save_id: 1,
  available: true,
  data_version: 'cases:3:feedback:1',
  totals: { cases: 3, completed_transfers: 2, negotiation_cases: 1, demo_cases: 0 },
  by_type: { permanent: 2, loan: 1 },
  confidence: { level: 'preliminary', label: '初步参考', sample_size: 3, note: '' },
  patterns: [],
  message: null,
}

const onlineStatus = {
  save_id: 1,
  status: 'MONITORING',
  status_label: '正在监视转会市场',
  enabled: true,
  paused: false,
  save_name: '测试存档',
  last_monitor_at: '2026-11-27T09:00:00Z',
  last_event_at: '2026-11-27T08:59:00Z',
  last_learning_at: '2026-11-27T09:00:05Z',
  counts: { events_observed: 12, events_confirmed: 4, confirmed_transfers: 3, global_clubs: 8, focus_clubs: 1 },
  latest_error: null,
  coverage: {
    transfer_history_available: true,
    native_reader_transfers: false,
    offers_available: false,
    note: '原生读取器不提供转会历史；只有导入的成交记录会计入学习',
  },
  engine_version: 'transfer-learning-1',
}

const focusClubs = {
  items: [
    {
      club_id: 5,
      club_name: 'Kingsport City',
      league: 'Premier League',
      priority: 'focus',
      sample_size: 4,
      confidence: { level: 'limited', label: '有限参考', sample_size: 4 },
      buying: { completed: 1, loans: 0 },
      selling: { completed: 3, loans: 0 },
      trade_counts: { buying: 1, selling: 3, loans: 0 },
      promotion_reason: '与用户俱乐部发生过交易',
      last_transaction_at: '2026-11-27T08:59:00Z',
    },
  ],
  total: 1,
}

const activity = {
  items: [
    {
      activity_id: 1,
      activity_type: 'event_detected',
      title: '已确认一笔永久转会',
      created_at: '2026-11-27T09:00:00Z',
      club_id: 5,
      event_id: 10,
      detail: {},
    },
  ],
  total: 1,
}

async function mockApi(page: Page, options: { coverageMissing?: boolean } = {}) {
  const calls: Array<{ path: string; method: string }> = []
  let paused = false
  await page.route('**/api/v1/**', async (route: Route) => {
    const url = new URL(route.request().url())
    const path = url.pathname
    const method = route.request().method()
    const json = (body: unknown) => route.fulfill({ json: body })
    calls.push({ path, method })

    if (path.endsWith('/meta/bootstrap')) return json(meta)
    if (path.endsWith('/meta/saves')) return json({ items: meta.saves })
    if (path.endsWith('/system/onboarding')) return json({ status: 'ready' })
    if (path.endsWith('/transfer-director/overview')) return json(overview)
    if (path.endsWith('/transfer-director/club-summary')) return json({ club_id: 3, club_name: 'Northbridge United' })
    if (path.endsWith('/transfer-director/negotiations')) return json({ items: [], total: 0 })
    if (path.endsWith('/transfer-director/opportunities/summary')) return json(opportunitySummary)
    if (path.endsWith('/transfer-director/opportunities')) return json({ items: [], total: 0 })
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
        opportunities: { total: 0, with_club: 0 },
      })
    }
    if (path.endsWith('/transfer-director/clubs')) return json({ items: [], total: 0 })
    if (path.endsWith('/transfer-director/strategy-cases')) return json({ items: [], total: 0, available: true })
    if (path.endsWith('/transfer-director/strategy-insights')) {
      return json({ save_id: 1, available: true, patterns: [], totals: {}, message: null })
    }
    if (path.endsWith('/transfer-director/learning-status')) return json(learningStatus)
    if (path.endsWith('/transfer-director/scans')) return json({ items: [], total: 0 })

    if (path.endsWith('/transfer-learning/status')) {
      const base = {
        ...onlineStatus,
        enabled: !paused,
        paused,
        status: paused ? 'PAUSED' : 'MONITORING',
        status_label: paused ? '自动学习已暂停' : '正在监视转会市场',
      }
      return json(
        options.coverageMissing
          ? {
              ...base,
              coverage: {
                ...onlineStatus.coverage,
                transfer_history_available: false,
                note: '尚未导入真实转会记录；在线学习只统计挂牌与球员变化',
              },
            }
          : base,
      )
    }
    if (path.endsWith('/transfer-learning/focus-clubs')) return json(focusClubs)
    if (path.endsWith('/transfer-learning/activity')) return json(activity)
    if (path.endsWith('/transfer-learning/pause') && method === 'POST') {
      paused = true
      return json({ status: 'PAUSED', enabled: false })
    }
    if (path.endsWith('/transfer-learning/resume') && method === 'POST') {
      paused = false
      return json({ status: 'MONITORING', enabled: true, started: null })
    }

    if (path.endsWith('/transfers')) return json({ items: [], total: 0, coverage: {} })
    if (path.endsWith('/players')) return json({ items: [], total: 0, coverage: {} })
    return json({})
  })
  return calls
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem('scoutmind.onboardingDismissed', '1')
  })
})

test('在线学习：展示状态、事件计数、重点俱乐部与最近动态', async ({ page }) => {
  await mockApi(page)
  await page.goto('/transfer-director?section=strategy')

  const card = page.getByTestId('online-learning-status')
  await expect(card).toBeVisible()
  await expect(card.getByText('在线持续学习')).toBeVisible()
  await expect(card.getByText('正在监视转会市场')).toBeVisible()
  await expect(card.getByText('已观察事件')).toBeVisible()
  await expect(card.getByText('12')).toBeVisible()
  await expect(card.getByText('已确认交易')).toBeVisible()
  await expect(card.getByText('Kingsport City')).toBeVisible()
  await expect(card.getByText('已确认一笔永久转会')).toBeVisible()
  await expect(card.getByText('有限参考')).toBeVisible()
  // 不向普通用户暴露开发阈值。
  await expect(card.getByText('0.85')).toHaveCount(0)
  await expect(card.getByText('transfer-learning-1')).toHaveCount(0)
})

test('在线学习：暂停后按钮切换为恢复', async ({ page }) => {
  const calls = await mockApi(page)
  await page.goto('/transfer-director?section=strategy')

  const card = page.getByTestId('online-learning-status')
  await expect(card.getByRole('button', { name: '暂停' })).toBeVisible()
  await card.getByRole('button', { name: '暂停' }).click()
  await expect.poll(() => calls.some((call) => call.path.endsWith('/transfer-learning/pause'))).toBe(true)
  await expect(card.getByRole('button', { name: '恢复' })).toBeVisible()
})

test('在线学习：无真实转会记录时说明学习来源限制', async ({ page }) => {
  await mockApi(page, { coverageMissing: true })
  await page.goto('/transfer-director?section=strategy')

  const card = page.getByTestId('online-learning-status')
  await expect(card.getByText('尚未导入真实转会记录', { exact: false })).toBeVisible()
})
