import { test, expect, type Page } from '@playwright/test'

/**
 * V3.3.1 界面契约回归：全局搜索、球员对比、位置热力图、价值散点与资金流向。
 *
 * 全部接口使用 page.route Mock，不依赖后端与真实 FM27 数据；真实联调标记 NOT_RUN。
 */

const meta = {
  product: 'ScoutMind',
  version: '3.3.1',
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
      player_count: 2,
      snapshot_count: 4,
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

const players = [
  {
    instance_id: 12,
    player_id: 1,
    name: 'Mario Bianchi',
    age: 24,
    birth_date: '2002-05-01',
    nationality: 'Italy',
    position: 'ST',
    position_group: 'FW',
    club: 'Northbridge United',
    club_id: 1,
    ca: 152,
    pa: 168,
    market_value: 35_000_000,
    wage: 80_000,
    contract_end: '2029-06-30',
    observed_at: '2026-11-01T12:00:00Z',
    data_completeness: 0.9,
    source: 'fm27_live_reader',
    is_watched: false,
  },
  {
    instance_id: 13,
    player_id: 2,
    name: 'Luca Verdi',
    age: 20,
    birth_date: '2006-03-01',
    nationality: 'Italy',
    position: 'AMC',
    position_group: 'MF',
    club: 'Northbridge United',
    club_id: 1,
    ca: 138,
    pa: 175,
    market_value: 22_000_000,
    wage: 35_000,
    contract_end: '2028-06-30',
    observed_at: '2026-11-01T12:00:00Z',
    data_completeness: 0.85,
    source: 'fm27_live_reader',
    is_watched: true,
  },
]

function detail(id: number) {
  const summary = players.find((player) => player.instance_id === id) ?? players[0]
  return {
    summary: {
      ...summary,
      height_cm: id === 12 ? 183 : 178,
      foot: id === 12 ? 'right' : 'left',
    },
    attributes: [
      { key: 'finishing', name: '射门', category: 'technical', value: 16 },
      { key: 'passing', name: '传球', category: 'technical', value: 14 },
      { key: 'dribbling', name: '盘带', category: 'technical', value: 15 },
      { key: 'composure', name: '镇定', category: 'mental', value: 15 },
      { key: 'vision', name: '视野', category: 'mental', value: 13 },
      { key: 'determination', name: '意志力', category: 'mental', value: 17 },
      { key: 'pace', name: '速度', category: 'physical', value: 16 },
      { key: 'strength', name: '强壮', category: 'physical', value: 14 },
      { key: 'stamina', name: '耐力', category: 'physical', value: 15 },
    ],
    snapshot_count: 2,
    first_seen: '2026-10-01',
    last_seen: '2026-11-01',
    latest_snapshot_id: 100 + id,
    valuation: null,
    tags: [],
    notes: null,
  }
}

const depthRows = [
  ['GK', '门将', 2, 2],
  ['CB', '中后卫', 2, 4],
  ['LB', '左后卫', 1, 2],
  ['RB', '右后卫', 2, 2],
  ['DM', '后腰', 1, 2],
  ['CM', '中前卫', 3, 3],
  ['AM', '前腰', 1, 1],
  ['LW', '左边锋', 2, 2],
  ['RW', '右边锋', 1, 2],
  ['ST', '中锋', 2, 2],
].map(([slot, slot_name, count, required], index) => ({
  slot,
  slot_name,
  count,
  required,
  importance: 0.8,
  coverage: Math.min(Number(count) / Number(required), 1),
  depth_quality: 0.7,
  status: Number(count) === 0 ? '空缺' : Number(count) < Number(required) ? '偏薄' : '充足',
  suggestion: '',
  players: Array.from({ length: Number(count) }, (_, item) => ({
    instance_id: 100 + index * 10 + item,
    name: `${slot_name}球员${item + 1}`,
    position: slot,
    slot,
    position_group: 'MF',
    age: 24,
    ca: 150 - item * 10,
    pa: 165,
    market_value: 20_000_000,
    wage: 40_000,
    contract_end: '2029-06-30',
    minutes_played: 1000,
    appearances: 15,
    fit_score: 82,
    fit_role: null,
  })),
}))

const stats = {
  sample_size: 4,
  currency: 'EUR',
  median: 20_000_000,
  p25: 10_000_000,
  p75: 30_000_000,
  mean: 21_000_000,
  min: 5_000_000,
  max: 35_000_000,
  distribution: [],
  filters: {},
  coverage: {},
  algorithm_version: 'transfer-price-1',
  excluded: { incomplete: 0, non_completed: 1 },
  warnings: [],
}

const overview = {
  save_id: 1,
  club: { id: 1, name: 'Northbridge United', league: 'Premier Division', nation: 'England' },
  squad_size: 18,
  score: 78,
  profile: { key: 'balanced', name: '均衡评估', weights: {} },
  components: [],
  depth: depthRows,
  age_structure: { average_age: 24, median_age: 24, buckets: [], missing: [] },
  wage_structure: { total: null, median: null, max: null, top3_share: null, earners: 0, top_earners: [], missing: [] },
  contracts: { buckets: {}, at_risk_count: 0, at_risk_names: [], missing: [] },
  weakness: [],
  succession: [],
  composition: { first_team: 18, reserve: 0, youth: 0, loaned_out: 0, loaned_in: 0, unknown: 0 },
  algorithm_version: 'squad-score-1',
  data_gaps: [],
}

/** 统一接口 Mock。 */
async function mockApi(page: Page): Promise<void> {
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname
    const json = (body: unknown) => route.fulfill({ json: body })

    if (path.endsWith('/meta/bootstrap')) return json(meta)
    if (path.endsWith('/search')) {
      const q = (url.searchParams.get('q') ?? '').trim()
      if (!q || !q.toLowerCase().includes('mario')) {
        return json({ query: q, type: 'all', categories: { players: [], clubs: [], transfers: [] }, total: 0, limits: { per_category: 8 } })
      }
      return json({
        query: q,
        type: url.searchParams.get('type') ?? 'all',
        categories: {
          players: [
            {
              entity_type: 'player',
              entity_id: 12,
              display_name: 'Mario Bianchi',
              subtitle: 'ST · 24 岁 · Northbridge United',
              navigation_target: '/players/12',
              meta: { position: 'ST', age: 24, club: 'Northbridge United', ca: 152, pa: 168 },
            },
          ],
          clubs: [
            {
              entity_type: 'club',
              entity_id: 1,
              display_name: 'Northbridge United',
              subtitle: 'England · Premier Division · 2 名球员',
              navigation_target: '/players?club_id=1',
              meta: { nation: 'England', league: 'Premier Division', player_count: 2 },
            },
          ],
          transfers: [
            {
              entity_type: 'transfer',
              entity_id: 88,
              display_name: 'Mario Bianchi',
              subtitle: 'Kingsport City → Northbridge United · 2026-07-01',
              navigation_target: '/transfers?query=Mario%20Bianchi',
              meta: { status: 'completed', transfer_type: 'permanent', from_club: 'Kingsport City', to_club: 'Northbridge United', currency: 'EUR', fee: 30_000_000 },
            },
          ],
        },
        total: 3,
        limits: { per_category: 8 },
      })
    }
    if (/\/players\/\d+$/.test(path)) {
      const id = Number(path.split('/').pop())
      return json(detail(id))
    }
    if (path.endsWith('/players')) {
      const watchOnly = url.searchParams.get('watchlist_only') === 'true'
      return json({ items: watchOnly ? [] : players, total: watchOnly ? 1 : players.length, coverage: { ca: 1, pa: 1, market_value: 1 } })
    }
    if (path.endsWith('/squad/depth')) {
      return json({ items: depthRows, total: depthRows.length, squad_size: 18, missing_position: 0 })
    }
    if (path.endsWith('/squad/overview')) return json(overview)
    if (path.endsWith('/squad/profiles')) {
      return json({ items: [], total: 0, default_weights: {} })
    }
    if (path.endsWith('/clubs/search')) {
      return json({ items: [{ id: 1, name: 'Northbridge United', nation: 'England', league: 'Premier Division', source: 'scan', confidence: 1 }], total: 1 })
    }
    if (/\/saves\/\d+\/user-club$/.test(path)) {
      return json({ club: { id: 1, name: 'Northbridge United', league: 'Premier Division', nation: 'England' }, source: 'manual', source_label: null, confidence: 1 })
    }
    if (path.endsWith('/clubs')) return json({ items: [], total: 0 })
    if (path.endsWith('/visualizations/value-scatter')) {
      return json({
        points: players.filter((player) => player.market_value !== null).map((player) => ({
          instance_id: player.instance_id,
          name: player.name,
          age: player.age,
          ca: player.ca,
          pa: player.pa,
          market_value: player.market_value,
          club: player.club,
          position: player.position,
        })),
        total: 2,
        with_value: 2,
        returned: 2,
        note: '仅包含身价非空的球员；按身价从高到低截断，最多 800 人',
      })
    }
    if (path.endsWith('/visualizations/transfer-flow')) {
      return json({
        club: { id: 1, name: 'Northbridge United' },
        currencies: [
          {
            currency: 'EUR',
            buy_total: 30_000_000,
            sell_total: 10_000_000,
            loan_in_fee: 500_000,
            loan_out_fee: 0,
            net: 20_500_000,
            counts: { permanent_buy: 1, permanent_sell: 1, loan_in: 1, loan_out: 0, free: 1 },
            unknown_fee: 0,
          },
        ],
        excluded: { pending: 1, future: 0, cancelled: 0, failed: 0 },
        note: '只统计 completed；租借费用单列；附加条款不计入已支付；不同币种不合并',
      })
    }
    if (path.endsWith('/transfers/stats')) return json(stats)
    if (path.endsWith('/transfers/categories')) return json({ items: [], total: 0, note: '' })
    if (path.endsWith('/transfers/review')) return json({ summary: {}, items: [], note: '' })
    if (path.endsWith('/transfers')) {
      return json({
        items: [
          {
            id: 88,
            player_instance_id: 12,
            player_name: 'Mario Bianchi',
            from_club_name: 'Kingsport City',
            to_club_name: 'Northbridge United',
            transfer_type: 'permanent',
            status: 'completed',
            transfer_date: '2026-07-01',
            season: '2026/27',
            currency: 'EUR',
            base_fee: 30_000_000,
            fee_paid: 30_000_000,
            addons_potential: null,
            effective_fee: 30_000_000,
            loan_fee: null,
            source: 'fm27_live_reader',
            confidence: 1,
            fee_components: [],
          },
        ],
        total: 1,
        coverage: { effective_fee: 1, transfer_date: 1 },
      })
    }
    if (path.endsWith('/analytics/overview')) return json({ trend: [], coverage: {}, data_gaps: [] })
    if (path.endsWith('/imports')) return json({ items: [], total: 0, limit: 5, offset: 0 })
    if (path.endsWith('/data-hub/status')) {
      return json({
        game: { running: false, detected: true, pid: null, version: null, exe_path: null, message: '', compatibility: 'unknown', compatibility_message: '' },
        save: { id: 1, name: '测试存档', recognized: true, identity_status: 'verified', can_sync: true, message: '' },
        records: { players: 2, clubs: 2, transfers: 1, snapshots: 4 },
        last_sync: null,
        health: { status: 'ok', issues: [] },
        needs_confirmation: { unresolved_players: 0, identity_conflicts: 0, quarantined_rows: 0, total: 0 },
        repairs: {},
      })
    }
    return json({})
  })
}

test.beforeEach(async ({ page }) => {
  await mockApi(page)
})

test('Ctrl+K 打开全局搜索并跳转球员详情', async ({ page }) => {
  await page.goto('/players')
  await expect(page.getByRole('heading', { name: '球员中心', level: 1 })).toBeVisible()
  await page.keyboard.press('Control+K')
  const input = page.getByPlaceholder('搜索球员、俱乐部或转会记录')
  await expect(input).toBeVisible()
  await input.fill('Mario')
  const dialog = page.getByRole('dialog')
  await expect(dialog.locator('.gs-result__name', { hasText: 'Mario Bianchi' }).first()).toBeVisible()
  await dialog.locator('.gs-result').first().click()
  await expect(page).toHaveURL(/\/players\/12$/)
})

test('搜索分类切换与无结果状态', async ({ page }) => {
  await page.goto('/players')
  await page.keyboard.press('Control+K')
  const dialog = page.getByRole('dialog')
  await page.getByPlaceholder('搜索球员、俱乐部或转会记录').fill('Mario')
  await page.getByRole('tab', { name: '俱乐部' }).click()
  await expect(dialog.locator('.gs-result__name', { hasText: 'Northbridge United' })).toBeVisible()
  await page.getByPlaceholder('搜索球员、俱乐部或转会记录').fill('zzz-no-match')
  await expect(dialog.getByText('没有找到结果')).toBeVisible()
})

test('球员对比页展示雷达、资料表和确定性摘要', async ({ page }) => {
  await page.goto('/compare?ids=12,13')
  await expect(page.getByRole('heading', { name: '球员对比', level: 1 })).toBeVisible()
  await expect(page.getByRole('heading', { name: '能力属性雷达' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '资料与能力对比' })).toBeVisible()
  await expect(page.getByText('Mario Bianchi').first()).toBeVisible()
  await expect(page.getByText('Luca Verdi').first()).toBeVisible()
  await expect(page.getByText(/当前能力最高/)).toBeVisible()
  await expect(page.getByText(/年龄最小/)).toBeVisible()
  // 移除一名球员后回到“至少选择 2 名”的提示。
  await page.getByRole('button', { name: '移除' }).first().click()
  await expect(page.getByText('至少选择 2 名球员')).toBeVisible()
})

test('球员中心可切换卡片视图并加入对比', async ({ page }) => {
  await page.goto('/players')
  await page.getByText('卡片', { exact: true }).click()
  await expect(page.getByText('Mario Bianchi').first()).toBeVisible()
  await page.getByRole('button', { name: '加入对比' }).first().click()
  await expect(page.getByRole('button', { name: /球员对比（1\/4）/ })).toBeVisible()
})

test('位置热力图展示人数、主力与空缺状态', async ({ page }) => {
  await page.goto('/squad')
  await expect(page.getByRole('heading', { name: '位置深度热力图' })).toBeVisible()
  await expect(page.getByRole('listitem', { name: /中锋：2 人/ })).toBeVisible()
  await expect(page.getByRole('listitem', { name: /左后卫：1 人/ })).toBeVisible()
})

test('转会页展示按币种拆分的资金流向', async ({ page }) => {
  await page.goto('/transfers')
  await expect(page.getByRole('heading', { name: '转会资金流向' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '资金流向 · EUR' })).toBeVisible()
  await expect(page.getByText(/买入 1 笔/)).toBeVisible()
})

for (const [width, height] of [
  [1280, 720],
  [1366, 768],
  [1440, 900],
  [1920, 1080],
] as const) {
  test(`${width}×${height} 下核心页面无横向溢出`, async ({ page }) => {
    await page.setViewportSize({ width, height })
    for (const path of ['/', '/players', '/compare?ids=12,13', '/squad', '/transfers']) {
      await page.goto(path)
      await page.waitForLoadState('networkidle')
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
      expect(overflow, `${path} 在 ${width}px 出现横向滚动`).toBeLessThanOrEqual(1)
    }
  })
}
