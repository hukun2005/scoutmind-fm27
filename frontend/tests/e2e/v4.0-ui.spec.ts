import { test, expect, type Page } from '@playwright/test'

/**
 * V4.0 UI/UX 契约：导航精简、首页 AI 总监简报、阵容分析分层与未知值处理。
 *
 * 全部接口使用本地 mock，不依赖后端与真实 FM27 数据；断言只覆盖界面契约。
 */

const meta = {
  product: 'ScoutMind',
  version: '4.0.0',
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
      player_count: 18,
      snapshot_count: 2,
      transfer_count: 0,
      last_import_at: '2026-11-27T10:00:00Z',
    },
  ],
  data_sources: [{ source: 'fm27_live_reader', records: 18 }],
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
    player_id: 12,
    name: 'Mario Bianchi',
    age: 24,
    birth_date: null,
    nationality: 'Italy',
    position: 'ST',
    position_group: 'FW',
    club: 'Northbridge United',
    club_id: 1,
    ca: 152,
    pa: 168,
    market_value: 30_000_000,
    wage: null,
    contract_end: '2027-06-30',
    observed_at: '2026-11-27T10:00:00Z',
    data_completeness: 0.9,
    source: 'fm27_live_reader',
    is_watched: false,
  },
]

const depthRow = {
  slot: 'ST',
  slot_name: '中锋',
  count: 1,
  required: 2,
  importance: 3,
  coverage: 0.5,
  depth_quality: 0.4,
  status: '人手不足',
  suggestion: '仅有 1 名可用中锋，建议补强。',
  players: players.map((player) => ({
    instance_id: player.instance_id,
    name: player.name,
    position: player.position,
    slot: player.position,
    position_group: player.position_group,
    age: player.age,
    ca: player.ca,
    pa: player.pa,
    market_value: player.market_value,
    wage: player.wage,
    contract_end: player.contract_end,
    minutes_played: null,
    appearances: null,
    fit_score: 80,
    fit_role: null,
  })),
}

const squadOverview = {
  save_id: 1,
  club: { id: 1, name: 'Northbridge United', league: 'Premier Division', nation: 'England' },
  squad_size: 18,
  score: 78,
  profile: {
    key: 'balanced',
    name: '均衡评估',
    is_default: true,
    weights: { coverage: 0.2, depth: 0.2, age: 0.2, fit: 0.15, wage: 0.1, potential: 0.15 },
    overridden: false,
  },
  components: [
    { key: 'coverage', label: '阵容覆盖', value: 82, weight: 0.2, evidence: ['位置覆盖 9/10'], missing: [], available: true },
    { key: 'depth', label: '替补深度', value: 70, weight: 0.2, evidence: ['中锋只有 1 人'], missing: [], available: true },
    { key: 'age', label: '年龄结构', value: 64, weight: 0.2, evidence: ['平均年龄数据缺失'], missing: [], available: true },
    { key: 'fit', label: '战术适配', value: 75, weight: 0.15, evidence: ['角色评分均值 75'], missing: [], available: true },
    { key: 'wage', label: '工资结构', value: null, weight: 0.1, evidence: [], missing: ['缺少工资字段'], available: false },
    { key: 'potential', label: '潜力储备', value: 68, weight: 0.15, evidence: ['2 名高潜球员'], missing: [], available: true },
  ],
  depth: [depthRow],
  age_structure: { average_age: null, median_age: null, buckets: [], missing: ['缺少出生日期'] },
  wage_structure: {
    total: null,
    median: null,
    max: null,
    top3_share: null,
    earners: 0,
    top_earners: [],
    missing: ['缺少工资字段'],
  },
  contracts: {
    buckets: {
      '12m': [
        {
          instance_id: 12,
          name: 'Mario Bianchi',
          contract_end: '2027-06-30',
          age: 24,
          ca: 152,
          pa: 168,
          wage: null,
          market_value: 30_000_000,
        },
      ],
    },
    at_risk_count: 1,
    at_risk_names: ['Mario Bianchi'],
    missing: [],
  },
  weakness: [
    {
      slot: 'ST',
      slot_name: '中锋',
      severity: 2.5,
      count: 1,
      required: 2,
      status: '人手不足',
      suggestion: '仅有 1 名可用中锋，建议补强。',
      evidence: ['人数 1/2'],
    },
  ],
  succession: [],
  composition: { available: true, counts: { senior: 18 }, gaps: [], missing: [] },
  algorithm_version: 'squad-score-1',
  data_gaps: [],
}

const hiddenValue = {
  items: [
    {
      rule: 'cheap_upside',
      rule_label: '低价高潜',
      signal: 0.8,
      player: {
        instance_id: 55,
        name: 'Luca Ferri',
        age: 21,
        position: 'ST',
        slot: 'ST',
        slot_name: '中锋',
        position_group: 'FW',
        ca: 140,
        pa: 170,
        market_value: 8_000_000,
        wage: null,
        contract_end: null,
        club: 'Kingsport City',
      },
      evidence: ['身价低于同年龄中位数'],
      cost_estimate: { market_value: 8_000_000, wage: null, contract_end: null },
    },
  ],
  total: 1,
  rules: { evaluated: [], unavailable: [] },
  method: 'rules',
  algorithm_version: 'recruitment-1',
}

const analyticsOverview = {
  save: meta.saves[0],
  players: 18,
  snapshots: 2,
  transfers: 0,
  clubs: 2,
  completed_transfer_value: null,
  watchlist: 0,
  alerts: 0,
  coverage: { ca: 1, pa: 1, market_value: 0.8 },
  last_import: null,
  trend: [],
}

const hubStatus = {
  game: { running: true, detected: true, pid: 1, version: '27.1', exe_path: null, message: '', compatibility: 'supported', compatibility_message: '' },
  save: { id: 1, name: '测试存档', recognized: true, identity_status: 'verified', can_sync: true, message: '' },
  records: { players: 18, clubs: 2, transfers: 0, snapshots: 2 },
  last_sync: null,
  health: { status: 'ok', issues: [] },
  needs_confirmation: { unresolved_players: 0, identity_conflicts: 0, quarantined_rows: 0, total: 0 },
  repairs: {},
}

async function mockApi(page: Page): Promise<void> {
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname
    const json = (body: unknown) => route.fulfill({ json: body })

    if (path.endsWith('/meta/bootstrap')) return json(meta)
    if (path.endsWith('/data-hub/status')) return json(hubStatus)
    if (path.endsWith('/analytics/overview')) return json(analyticsOverview)
    if (path.endsWith('/squad/overview')) return json(squadOverview)
    if (path.endsWith('/squad/depth')) return json({ items: [depthRow], total: 1, squad_size: 18, missing_position: 0 })
    if (path.endsWith('/squad/profiles')) {
      return json({ items: [squadOverview.profile], total: 1, default_weights: squadOverview.profile.weights })
    }
    if (path.endsWith('/recruitment/hidden-value')) return json(hiddenValue)
    if (path.endsWith('/transfers/stats')) {
      return json({
        sample_size: 0,
        currency: 'EUR',
        median: null,
        p25: null,
        p75: null,
        mean: null,
        min: null,
        max: null,
        distribution: [],
        filters: {},
        coverage: {},
        algorithm_version: 'transfer-price-1',
        excluded: { incomplete: 0, non_completed: 0 },
        warnings: [],
      })
    }
    if (path.endsWith('/imports')) return json({ items: [], total: 0, limit: 5, offset: 0 })
    if (path.endsWith('/clubs/search')) return json({ items: [], total: 0 })
    if (/\/saves\/\d+\/user-club$/.test(path)) {
      return json({
        club: { id: 1, name: 'Northbridge United', league: 'Premier Division', nation: 'England' },
        source: 'manual',
        source_label: null,
        confidence: 1,
      })
    }
    if (path.endsWith('/players')) {
      return json({ items: players, total: players.length, coverage: { ca: 1, pa: 1, market_value: 0.8 } })
    }
    if (path.endsWith('/transfers')) return json({ items: [], total: 0 })
    return json({})
  })
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => window.localStorage.clear())
  await mockApi(page)
})

test('导航按任务分组，技术页面默认隐藏并可折叠展开', async ({ page }) => {
  await page.goto('/')

  const sidebar = page.getByRole('complementary', { name: '主导航栏' })
  await expect(sidebar.getByRole('link', { name: '球员探索' })).toBeVisible()
  await expect(sidebar.getByRole('link', { name: '引援机会' })).toBeVisible()
  await expect(sidebar.getByRole('link', { name: '游戏数据' })).toBeVisible()

  // 旧入口名与内部技术页不占用默认菜单。
  await expect(sidebar.getByRole('link', { name: '球员中心' })).toHaveCount(0)
  await expect(sidebar.getByRole('link', { name: '数据治理' })).toHaveCount(0)

  await sidebar.getByRole('button', { name: /高级诊断/ }).click()
  await expect(sidebar.getByRole('link', { name: '数据治理' })).toBeVisible()
})

test('侧栏可收起为图标轨，并记住选择', async ({ page }) => {
  await page.goto('/')

  await page.getByRole('button', { name: '收起侧栏' }).click()
  await expect(page.locator('.shell')).toHaveClass(/shell--rail/)
  await expect(page.getByRole('link', { name: '球员探索' })).toBeHidden()

  const saved = await page.evaluate(() => window.localStorage.getItem('scoutmind.navCollapsed'))
  expect(saved).toBe('1')

  await page.getByRole('button', { name: '展开侧栏' }).click()
  await expect(page.getByRole('link', { name: '球员探索' })).toBeVisible()
})

test('首页展示 AI 总监简报与可追溯的下一步', async ({ page }) => {
  await page.goto('/')

  await expect(page.getByRole('heading', { name: /欢迎回来/ })).toBeVisible()
  await expect(page.getByText('AI 总监简报')).toBeVisible()
  const brief = page.locator('.brief')
  await expect(brief.getByText('最大问题', { exact: true })).toBeVisible()
  await expect(brief.getByText('引援机会', { exact: true })).toBeVisible()
  await expect(brief.getByText('下一步', { exact: true })).toBeVisible()
  await expect(brief.getByText('Luca Ferri').first()).toBeVisible()
  await expect(page.getByText('阵容综合评分')).toBeVisible()
})

test('阵容分析：结论优先，位置深度与重点球员可见，缺失值不记为 0', async ({ page }) => {
  await page.goto('/squad')

  await expect(page.getByRole('heading', { name: '阵容分析', level: 1 })).toBeVisible()
  await expect(page.getByText('阵容诊断')).toBeVisible()
  await expect(page.getByText('补强优先级')).toBeVisible()
  await expect(page.getByRole('heading', { name: '位置深度热力图' })).toBeVisible()
  await expect(page.getByText('核心球员')).toBeVisible()
  await expect(page.getByText('合同风险球员')).toBeVisible()
  await expect(page.locator('.priority__text')).toContainText('仅有 1 名可用中锋，建议补强。')

  // 平均年龄缺失时给出原因，而不是显示 0。
  await expect(page.getByText('年龄数据缺失', { exact: true })).toBeVisible()
  await expect(page.getByText('缺失：缺少工资字段').first()).toBeVisible()
})
