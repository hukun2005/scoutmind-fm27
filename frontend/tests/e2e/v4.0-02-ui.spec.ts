import { test, expect, type Page } from '@playwright/test'

/**
 * V4.0-02 UI/UX 契约：球员工作台、转会决策中心、AI 三工作台与游戏管理的结论层改造。
 *
 * 全部接口使用本地 mock，不依赖后端与真实 FM27 数据；断言只覆盖界面契约，
 * 不代表真实数据验收（真实数据验收状态见 docs/reports/V4.0-02-UI-UX-REPORT.md）。
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

function playerDetail(id: number) {
  const summary = players.find((player) => player.instance_id === id) ?? players[0]
  return {
    summary: { ...summary, height_cm: id === 12 ? 183 : 178, foot: id === 12 ? 'right' : 'left' },
    attributes: [
      { key: 'finishing', name: '射门', category: 'technical', value: 16 },
      { key: 'passing', name: '传球', category: 'technical', value: 14 },
      { key: 'composure', name: '镇定', category: 'mental', value: 15 },
      { key: 'determination', name: '意志力', category: 'mental', value: 17 },
      { key: 'pace', name: '速度', category: 'physical', value: 16 },
      { key: 'strength', name: '强壮', category: 'physical', value: 14 },
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

const directorContext = {
  save: { id: 1, name: '测试存档' },
  club: { id: 1, name: 'Northbridge United', league: 'Premier Division', nation: 'England' },
  data_updated_at: '2026-11-27T08:00:00Z',
  data_completeness: 0.72,
  coverage: {},
  counts: { players: 2, snapshots: 4, transfers: 2, statistics: 0, watchlist: 1 },
  data_gaps: ['没有赛季统计，产出与主力地位无法判断'],
  generated_at: '2026-11-27T08:00:00Z',
}

const directorAnswer = {
  intent: 'analysis',
  intent_label: '球队分析',
  conclusion: 'Northbridge United 当前最需要补强 ST。',
  sections: [
    {
      key: 'depth',
      title: '位置深度',
      reliability: 'computed',
      bullets: ['中锋只有 1 名可用球员', '左后卫 1 名'],
      table: { columns: ['位置', '人数'], rows: [['ST', '1']] },
    },
  ],
  recommendations: [
    {
      instance_id: 12,
      name: 'Mario Bianchi',
      age: 24,
      position: 'ST',
      club: 'Northbridge United',
      ca: 152,
      pa: 168,
      market_value: 35_000_000,
      score: 86,
      reason: '当前唯一可用的中锋，但缺少替补。',
      actions: [{ label: '查看球员', target: '/players/12' }],
    },
  ],
  player_cards: [
    {
      instance_id: 12,
      name: 'Mario Bianchi',
      age: 24,
      position: 'ST',
      club: 'Northbridge United',
      ca: 152,
      pa: 168,
      market_value: 35_000_000,
      source_tool: 'director',
    },
  ],
  data_gaps: ['没有赛季统计，产出与主力地位无法判断'],
  citations: [{ tool: 'squad_overview', summary: '2 人，1 个补强优先级' }],
  disclaimers: ['结论是本地数据分析，不包含游戏内未提供的训练、伤病与战术指令。'],
  mode: 'deterministic-rules',
  director: true,
  generated_at: '2026-11-27T10:00:00',
}

const hubStatus = {
  game: {
    running: true,
    detected: true,
    pid: 1,
    version: '27.1',
    exe_path: null,
    message: '',
    compatibility: 'supported',
    compatibility_message: '',
  },
  save: { id: 1, name: '测试存档', recognized: true, identity_status: 'verified', can_sync: true, message: '' },
  records: { players: 2, clubs: 1, transfers: 2, snapshots: 4 },
  last_sync: { finished_at: '2026-11-27T08:00:00Z' },
  health: { status: 'ok', issues: [] },
  needs_confirmation: { unresolved_players: 0, identity_conflicts: 0, quarantined_rows: 0, total: 0 },
  repairs: {},
}

const dataHealth = {
  save: { id: 1, name: '测试存档', game_date: '2026-07-01' },
  players: { count: 2, linked: 2, unlinked: 0, missing_source_field: 0 },
  clubs: { count: 1, linked_players: 2 },
  transfers: { count: 2, completed: 2 },
  opportunities: { active: 1, confirmed: 1, inferred: 0 },
  status: { level: 'ok', label: '数据完整', reasons: [] },
  last_updated_at: '2026-11-27T08:00:00Z',
  background: { active: 0, latest: null },
  can_repair: false,
  notes: [],
}

const recruitmentItem = {
  player: { instance_id: 12, name: 'Mario Bianchi', age: 24, position: 'ST', club: 'Northbridge United', market_value: 35_000_000 },
  score: 86,
  grade: 'S',
  grade_label: '重点推荐',
  score_coverage: 0.9,
  dimensions: [],
  strengths: ['射门 16', '速度 16'],
  risks: ['合同只剩 2 年'],
  cost_estimate: { market_value: 35_000_000, wage: 80_000, contract_end: '2029-06-30' },
}

const transfers = [
  {
    id: 1,
    player_instance_id: 12,
    player_name: 'Mario Bianchi',
    from_club: 'Kingsport City',
    to_club: 'Northbridge United',
    transfer_type: 'permanent',
    status: 'completed',
    transfer_date: '2026-07-01',
    base_fee: 20_000_000,
    fee_paid: 20_000_000,
    addons_potential: null,
    effective_fee: 20_000_000,
    currency: 'EUR',
    player_age_at_transfer: 23,
    player_ca_at_transfer: 150,
    player_pa_at_transfer: 168,
    contract_remaining_months: 24,
    season: '2026/27',
    source: 'manual_import',
    confidence: 1,
    fee_components: null,
  },
]

const transferStats = {
  sample_size: 1,
  currency: 'EUR',
  median: 20_000_000,
  p25: 20_000_000,
  p75: 20_000_000,
  mean: 20_000_000,
  min: 20_000_000,
  max: 20_000_000,
  distribution: [],
  filters: {},
  coverage: {},
  algorithm_version: 'transfer-price-1',
  excluded: { incomplete: 0, non_completed: 0 },
  warnings: [],
}

async function mockApi(page: Page): Promise<void> {
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname
    const method = route.request().method()
    const json = (body: unknown) => route.fulfill({ json: body })

    if (path.endsWith('/meta/bootstrap')) return json(meta)
    if (path.endsWith('/meta/saves')) return json({ items: meta.saves })
    if (path.endsWith('/system/data-health')) return json(dataHealth)
    if (path.endsWith('/system/onboarding')) {
      return json({ status: 'ready', data: { has_players: true }, summary: {}, actions: [] })
    }
    if (path.endsWith('/data-hub/status')) return json(hubStatus)
    if (path.endsWith('/imports')) return json({ items: [], total: 0, limit: 5, offset: 0 })
    if (path.endsWith('/analytics/overview')) {
      return json({ save_id: 1, save: meta.saves[0], players: 2, snapshots: 4, transfers: 2, clubs: 1, coverage: {} })
    }
    if (path.endsWith('/compatibility')) return json({ items: [], reader_versions: [] })
    if (path.endsWith('/clubs/search')) return json({ items: [], total: 0 })
    if (path.endsWith('/clubs')) return json({ items: [], total: 0 })
    if (/\/clubs\/\d+\/transfer-profile$/.test(path)) {
      return json({ club_id: 1, name: 'Northbridge United', league: 'Premier Division', nation: 'England' })
    }

    if (/^\/api\/v1\/players\/\d+$/.test(path)) {
      return json(playerDetail(Number.parseInt(path.split('/').pop() ?? '12', 10)))
    }
    if (/^\/api\/v1\/players\/\d+\/history$/.test(path)) {
      return json({ points: [], coverage: { points: null, attributes: null } })
    }
    if (/^\/api\/v1\/players\/\d+\/development$/.test(path)) {
      return json({
        summary: { snapshots: 2, ca_delta: null, market_value_delta: null, minutes_delta: null, window_start: null, window_end: null },
        records: [],
        attributions: [],
        data_gaps: [],
      })
    }
    if (/^\/api\/v1\/players\/\d+\/status$/.test(path)) {
      return json({ current: null, history: [], missing: [] })
    }
    if (path.endsWith('/players')) {
      return json({ items: players, total: players.length, coverage: { ca: 1, pa: 1, market_value: 1 } })
    }

    if (path.endsWith('/agent/director/context')) return json(directorContext)
    if (path.endsWith('/agent/director/ask') && method === 'POST') return json(directorAnswer)

    if (path.endsWith('/recruitment/search')) {
      return json({
        items: [recruitmentItem],
        total: 1,
        data_gaps: [],
        grade_rules: 'S≥85 / A≥75 / B≥65 / C≥55 / D<55。',
      })
    }
    if (path.endsWith('/recruitment/hidden-value')) {
      return json({ items: [], total: 0, rules: { evaluated: [], unavailable: [] }, method: 'rules', algorithm_version: 'recruitment-1' })
    }
    if (path.endsWith('/recruitment/shortlists')) return json({ items: [], total: 0 })

    if (path.endsWith('/transfers/stats')) return json(transferStats)
    if (path.endsWith('/transfers/categories')) return json({ categories: [], total: 0, currency: 'EUR', algorithm_version: 'x' })
    if (path.endsWith('/transfers/review')) return json({ summary: null, items: [], note: null })
    if (path.endsWith('/transfers/similar')) return json({ items: [], total: 0, weights: {}, effective_weights: {}, message: null })
    if (path.endsWith('/transfers/valuation')) {
      return json({ low: null, mid: null, high: null, sample_size: 0, method: null, algorithm_version: null, confidence: null, insufficient_sample: true, coverage: null })
    }
    if (path.endsWith('/transfers')) return json({ items: transfers, total: transfers.length, coverage: { fee: 1 } })

    if (path.endsWith('/scouting/roles')) return json({ items: [] })
    if (path.endsWith('/watchlist/lists')) return json({ items: [{ id: 1, name: '默认关注', count: 0, is_default: true }], total: 1 })
    if (path.endsWith('/watchlist')) return json({ items: [], total: 0, lists: [] })

    return json({})
  })
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.clear()
    window.localStorage.setItem('scoutmind.onboardingDismissed', '1')
  })
  await mockApi(page)
})

test('球员探索：结论层与紧凑指标优先，低频筛选收进「更多筛选」', async ({ page }) => {
  await page.goto('/players')

  await expect(page.getByRole('heading', { name: '球员探索', level: 1 })).toBeVisible()
  await expect(page.getByRole('heading', { name: '球探概览' })).toBeVisible()
  await expect(page.getByText('规则生成')).toBeVisible()
  await expect(page.locator('.stat-strip').first()).toBeVisible()
  await expect(page.getByText('Mario Bianchi').first()).toBeVisible()

  const advanced = page.locator('details.sm-details').first()
  await expect(advanced).not.toHaveAttribute('open', '')
  await advanced.locator('summary').click()
  await expect(advanced.getByText('潜力上限', { exact: true })).toBeVisible()
})

test('球员详情：规则生成的决策摘要与四个分组锚点', async ({ page }) => {
  await page.goto('/players/12')

  await expect(page.getByRole('heading', { name: '决策摘要' })).toBeVisible()
  await expect(page.getByText('以上为规则生成摘要，不替代球探判断；缺失字段不参与计算')).toBeVisible()

  const nav = page.getByRole('navigation', { name: '球员详情区块' })
  await expect(nav.getByRole('link', { name: '能力' })).toBeVisible()
  await expect(nav.getByRole('link', { name: '表现与成长' })).toBeVisible()
  await expect(nav.getByRole('link', { name: '转会与估值' })).toBeVisible()
  await expect(nav.getByRole('link', { name: '状态与合同' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '表现与成长' })).toBeVisible()
})

test('球员对比：差异结论在前，领先值有标记', async ({ page }) => {
  await page.goto('/compare?ids=12,13')

  await expect(page.getByRole('heading', { name: '差异结论' })).toBeVisible()
  await expect(page.locator('.compare-cell__lead').first()).toBeVisible()
  await expect(page.getByText('领先').first()).toBeVisible()
  await expect(page.getByRole('heading', { name: '资料与能力对比' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '能力属性雷达' })).toBeVisible()
})

test('引援机会：结论、优先机会卡（理由/风险/成本/覆盖率）与完整表格', async ({ page }) => {
  await page.goto('/recruitment')

  await expect(page.getByRole('heading', { name: '引援结论' })).toBeVisible()
  const card = page.locator('.opp-card').first()
  await expect(card).toBeVisible()
  await expect(card.getByText('风险')).toBeVisible()
  await expect(card.getByText('成本')).toBeVisible()
  await expect(card.getByText(/评分覆盖率/)).toBeVisible()
  await expect(card.getByText('重点推荐')).toBeVisible()
  await expect(page.getByRole('heading', { name: '候选球员' })).toBeVisible()
})

test('转会情报：摘要、可观测事件与资金流向契约仍在', async ({ page }) => {
  await page.goto('/transfers')

  await expect(page.getByRole('heading', { name: '转会情报摘要' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '最近可观测交易' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '转会资金流向' })).toBeVisible()
  await expect(page.getByText('Mario Bianchi').first()).toBeVisible()
})

test('AI 足球总监：任务卡生成结构化报告，不暴露内部 JSON', async ({ page }) => {
  await page.goto('/director')

  await expect(page.getByRole('heading', { name: '总监简报' })).toBeVisible()
  await page.getByRole('button', { name: '分析我的球队阵容' }).click()

  const report = page.locator('.director-answer')
  await expect(report.getByText('任务目标')).toBeVisible()
  await expect(report.getByText('依据分析')).toBeVisible()
  await expect(report.getByText('下一步', { exact: true })).toBeVisible()
  await expect(page.getByText('本地规则引擎', { exact: true })).toBeVisible()
  await expect(report.getByText('来源与声明', { exact: false })).toBeVisible()
  await expect(report).not.toContainText('{"')
})

test('游戏数据：同步状态结论优先，高级数据工具默认折叠', async ({ page }) => {
  await page.goto('/data')

  await expect(page.getByRole('heading', { name: '同步状态' })).toBeVisible()
  await expect(page.locator('.stat-strip').first()).toBeVisible()
  await expect(page.getByText('FM27 正在运行（版本 27.1）')).toBeVisible()
  await expect(page.getByRole('heading', { name: '文件导入' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '数据状态' })).toBeVisible()

  await expect(page.getByText('开发者诊断（高级）')).toBeVisible()
  await expect(page.getByText('FMSuperScout 接入')).toBeHidden()
})
