import { test, expect, type Page } from '@playwright/test'

/**
 * V3.3.2 UI 契约：
 * 1) AI 足球总监工作台（上下文、快捷问题、结构化表格、球员卡片、加入关注）；
 * 2) 全局搜索关注分类、命中高亮与最近访问（Ctrl+K）。
 *
 * 全部接口使用 page.route Mock；真实后端联调在报告中标记 NOT_RUN / 由后端测试覆盖。
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
      transfer_count: 1,
      last_import_at: '2026-11-26T10:00:00Z',
    },
  ],
  data_sources: [],
  capabilities: { live_reader: true, save_parser: true, agent_llm: false, watchlist: true, transfer_intelligence: true },
  warnings: [],
}

const directorContext = {
  save: { id: 1, name: '测试存档' },
  club: { id: 3, name: 'Northbridge United', league: 'Premier Division', nation: 'England' },
  data_updated_at: '2026-11-26T10:00:00',
  data_completeness: 0.82,
  coverage: { ca: 1, pa: 1, market_value: 0.8, contract_end: 0.7 },
  counts: { players: 4, snapshots: 8, transfers: 1, statistics: 0, watchlist: 2 },
  data_gaps: ['没有赛季统计，产出与主力地位无法判断'],
  generated_at: '2026-11-27T10:00:00',
}

const directorAnswer = {
  intent: 'gaps',
  intent_label: '阵容补强',
  conclusion: 'Northbridge United 当前最需要补强 ST（缺口评分 78），其次是 CM。',
  sections: [
    {
      key: 'gaps',
      title: '补强优先级',
      reliability: 'computed',
      table: {
        columns: ['位置', '缺口评分', '人数/要求', '证据', '建议'],
        rows: [['ST', '78', '1/3', '主力 CA 低于联赛中位', '引进即战力前锋']],
      },
    },
    {
      key: 'risks',
      title: '风险与数据缺失',
      reliability: 'unavailable',
      bullets: ['没有赛季统计，无法判断主力地位'],
    },
  ],
  recommendations: [
    {
      instance_id: 12,
      name: 'Mario Bianchi',
      age: 24,
      position: 'ST',
      club: 'Kingsport City',
      ca: 152,
      pa: 168,
      market_value: 35_000_000,
      score: 81.2,
      reason: 'ST 缺口评分 78（1/3 人）：综合评分靠前',
      actions: [
        { label: '查看球员', target: '/players/12' },
        { label: '查看引援详情', target: '/recruitment?slot=ST' },
      ],
    },
  ],
  player_cards: [
    {
      instance_id: 12,
      name: 'Mario Bianchi',
      age: 24,
      position: 'ST',
      club: 'Kingsport City',
      ca: 152,
      pa: 168,
      market_value: 35_000_000,
      source_tool: 'director',
    },
  ],
  data_gaps: ['没有赛季统计，产出与主力地位无法判断'],
  citations: [{ tool: 'squad_overview', summary: '4 人，2 个补强优先级' }],
  disclaimers: ['结论是本地数据分析，不包含游戏内未提供的训练、伤病与战术指令。'],
  mode: 'deterministic-rules',
  director: true,
  generated_at: '2026-11-27T10:00:00',
}

const searchResult = {
  query: 'Mario',
  type: 'all',
  categories: {
    players: [
      {
        entity_type: 'player',
        entity_id: 12,
        display_name: 'Mario Bianchi',
        subtitle: 'ST · 24 岁 · Kingsport City',
        navigation_target: '/players/12',
        meta: { position: 'ST', age: 24, club: 'Kingsport City', ca: 152, pa: 168, save_id: 1, is_watched: true },
      },
    ],
    clubs: [],
    transfers: [],
    watchlist: [
      {
        entity_type: 'watchlist',
        entity_id: 12,
        display_name: 'Mario Bianchi',
        subtitle: '潜力新星 · ST · 24 岁',
        navigation_target: '/players/12',
        meta: { item_id: 10, instance_id: 12, list_id: 2, list_name: '潜力新星', status: 'preparing', tag: '核心', note: '左脚中锋' },
      },
    ],
  },
  total: 2,
  limits: { per_category: 8 },
}

async function mockApi(page: Page): Promise<{ posts: Array<{ path: string; body: unknown }> }> {
  const posts: Array<{ path: string; body: unknown }> = []
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname
    const json = (body: unknown) => route.fulfill({ json: body })
    const method = route.request().method()

    if (path.endsWith('/meta/bootstrap')) return json(meta)
    if (path.endsWith('/agent/director/context')) return json(directorContext)
    if (path.endsWith('/agent/director/ask') && method === 'POST') {
      posts.push({ path, body: JSON.parse(route.request().postData() ?? '{}') })
      return json(directorAnswer)
    }
    if (path.endsWith('/watchlist/items') && method === 'POST') {
      posts.push({ path, body: JSON.parse(route.request().postData() ?? '{}') })
      return json({ id: 11, instance_id: 12, list_id: 1, list_name: '默认关注', status: 'watching', tag: null, note: null })
    }
    if (path.endsWith('/watchlist/lists')) return json({ items: [{ id: 1, name: '默认关注', count: 0, is_default: true }], total: 1 })
    if (path.endsWith('/watchlist/alerts')) return json({ items: [], total: 0, unread: 0 })
    if (path.endsWith('/watchlist')) return json({ items: [], total: 0, lists: [] })
    if (path.endsWith('/search')) return json(searchResult)
    if (path.endsWith('/meta/saves')) return json({ items: meta.saves })
    return json({})
  })
  return { posts }
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => window.localStorage.clear())
})

test('AI 足球总监：上下文、快捷问题、结构化分析与加入关注', async ({ page }) => {
  const { posts } = await mockApi(page)
  await page.goto('/director')

  await expect(page.getByRole('heading', { name: 'AI 足球总监' })).toBeVisible()
  await expect(page.getByText('Northbridge United')).toBeVisible()
  await expect(page.getByText('Premier Division · England')).toBeVisible()

  await page.getByRole('button', { name: '我的球队最需要补强什么位置？' }).click()

  await expect(page.getByText('Northbridge United 当前最需要补强 ST')).toBeVisible()
  await expect(page.getByRole('cell', { name: 'ST' })).toBeVisible()
  await expect(page.getByText('Mario Bianchi').first()).toBeVisible()
  await expect(page.getByText('本地规则引擎')).toBeVisible()

  const ask = posts.find((item) => item.path.endsWith('/director/ask'))
  expect(ask?.body).toMatchObject({ question: '我的球队最需要补强什么位置？' })
  expect(ask?.body).not.toHaveProperty('save_id')

  await page.getByRole('button', { name: '加入关注' }).first().click()
  await expect(page.getByText('已加入关注名单：Mario Bianchi')).toBeVisible()
  const follow = posts.find((item) => item.path.endsWith('/watchlist/items'))
  expect(follow?.body).toMatchObject({ instance_id: 12 })
})

test('全局搜索：Ctrl+K、关注分类、命中高亮与最近访问', async ({ page }) => {
  await mockApi(page)
  await page.goto('/')
  await page.keyboard.press('Control+k')

  const input = page.getByRole('searchbox', { name: '搜索球员、俱乐部、转会或关注名单' })
  await expect(input).toBeVisible()
  await input.fill('Mario')

  await expect(page.getByText('关注', { exact: true }).last()).toBeVisible()
  await expect(page.locator('mark').first()).toHaveText(/Mario/i)
  await expect(page.getByText('潜力新星 · 准备引进 · 左脚中锋')).toBeVisible()

  await page.getByRole('button', { name: /Mario Bianchi/ }).last().click()
  await expect(page).toHaveURL(/\/players\/12$/)

  await page.keyboard.press('Control+k')
  await page.getByRole('searchbox', { name: '搜索球员、俱乐部、转会或关注名单' }).fill('')
  await expect(page.getByText('最近访问')).toBeVisible()
  await expect(page.getByRole('button', { name: /Mario Bianchi/ }).first()).toBeVisible()
})
