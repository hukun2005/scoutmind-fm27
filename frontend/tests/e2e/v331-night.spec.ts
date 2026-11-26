import { test, expect, type Page } from '@playwright/test'

/**
 * V3.3.1 NIGHT COMPLETE 界面契约：关注名单多名单/状态、AI 球探助手球员卡片、
 * 引援推荐等级与阵容补强入口。
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
  capabilities: { live_reader: true, save_parser: true, agent_llm: false, watchlist: true, transfer_intelligence: true },
  warnings: [],
}

const groups = [
  { id: 1, name: '默认关注', count: 1, is_default: true },
  { id: 2, name: '潜力新星', count: 1, is_default: false },
]

function watchItem(overrides: Record<string, unknown> = {}) {
  return {
    id: 10,
    instance_id: 12,
    list_id: 2,
    list_name: '潜力新星',
    status: 'watching',
    tag: '核心培养',
    note: '左脚中锋',
    source: 'manual',
    added_at: '2026-11-26T10:00:00Z',
    player: {
      instance_id: 12,
      name: 'Mario Bianchi',
      age: 24,
      position: 'ST',
      club: 'Northbridge United',
      ca: 152,
      pa: 168,
      market_value: 35_000_000,
      contract_end: '2029-06-30',
      source: 'fm27_live_reader',
    },
    ...overrides,
  }
}

function agentAnswer() {
  return {
    conclusion: '青年前锋群仍有成长空间，但一线队缺少即战力。',
    sections: [{ title: '推荐', text: '优先考察 21 岁以下、CA 140 以上的前锋。' }],
    sample_size: 1,
    filters: {},
    evidence: [],
    disclaimers: ['基于本地数据，不含未来预测。'],
    confidence: 'medium',
    data_gaps: [],
    mode: 'deterministic',
    reliability: null,
    citations: [],
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
        source_tool: 'search_players',
      },
    ],
  }
}

async function mockApi(page: Page): Promise<void> {
  const calls = { patch: [] as string[], post: [] as string[] }
  ;(page as unknown as { apiCalls: typeof calls }).apiCalls = calls

  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname
    const json = (body: unknown) => route.fulfill({ json: body })
    const method = route.request().method()

    if (path.endsWith('/meta/bootstrap')) return json(meta)
    if (path.endsWith('/watchlist/lists')) return json({ items: groups, total: groups.length })
    if (path.endsWith('/watchlist/alerts')) return json({ items: [], total: 0, unread: 0 })
    if (path.endsWith('/watchlist/refresh')) return json({ created: 0, rules: 0, items: [] })
    if (path.endsWith('/watchlist/items') && method === 'POST') {
      calls.post.push(route.request().postData() ?? '')
      return route.fulfill({ status: 201, json: watchItem({ id: 11 }) })
    }
    if (/\/watchlist\/items\/\d+$/.test(path) && method === 'PATCH') {
      calls.patch.push(route.request().postData() ?? '')
      return json(watchItem({ status: 'preparing' }))
    }
    if (path.endsWith('/watchlist')) {
      const listId = url.searchParams.get('list_id')
      const items = listId === '2' ? [watchItem()] : [watchItem(), watchItem({ id: 12, instance_id: 13, list_id: 1, list_name: '默认关注', status: 'preparing' })]
      return json({ items, total: items.length, lists: groups })
    }
    if (path.endsWith('/agent/conversations')) {
      if (method === 'POST') return route.fulfill({ status: 201, json: { id: 1, title: '新会话', save_id: 1, created_at: '2026-11-26T10:00:00Z', updated_at: '2026-11-26T10:00:00Z' } })
      return json({ items: [{ id: 1, title: '球探问答', save_id: 1, created_at: '2026-11-26T10:00:00Z', updated_at: '2026-11-26T10:00:00Z' }], total: 1 })
    }
    if (/\/agent\/conversations\/\d+\/messages$/.test(path)) {
      return json({
        items: [
          { id: 1, role: 'user', content: '帮我寻找年轻前锋。', created_at: '2026-11-26T10:00:00Z', tool_calls: [], answer: null },
          { id: 2, role: 'assistant', content: '分析完成', created_at: '2026-11-26T10:00:01Z', tool_calls: [], answer: agentAnswer() },
        ],
      })
    }
    if (path.endsWith('/recruitment/model')) return json({ positions: [], dimensions: [] })
    if (path.endsWith('/recruitment/search')) {
      return json({
        items: [
          {
            player: { instance_id: 12, name: 'Mario Bianchi', age: 24, position: 'ST', club: 'Northbridge United', market_value: 35_000_000 },
            score: 86,
            grade: 'S',
            grade_label: '重点推荐',
            score_coverage: 0.9,
            dimensions: [],
            strengths: [],
            risks: [],
          },
        ],
        total: 1,
        data_gaps: [],
        grade_rules: 'S≥85 / A≥75 / B≥65 / C≥55 / D<55；可用维度权重不足 60% 时标记为「数据不足」。',
      })
    }
    if (path.endsWith('/recruitment/shortlists')) return json({ items: [], total: 0 })
    if (path.endsWith('/squad/overview')) {
      return json({
        save_id: 1,
        club: { id: 1, name: 'Northbridge United', league: 'Premier Division', nation: 'England' },
        squad_size: 18,
        score: 78,
        profile: { key: 'balanced', name: '均衡评估', weights: {} },
        components: [],
        depth: [],
        age_structure: { average_age: 24, median_age: 24, buckets: [], missing: [] },
        wage_structure: { total: null, median: null, max: null, top3_share: null, earners: 0, top_earners: [], missing: [] },
        contracts: { buckets: {}, at_risk_count: 0, at_risk_names: [], missing: [] },
        weakness: [
          {
            slot: 'ST',
            slot_name: '中锋',
            severity: 7.5,
            count: 1,
            required: 3,
            status: 'thin',
            suggestion: '仅有 1 名可用中锋，建议补强。',
            evidence: ['人数 1 < 最低要求 3'],
          },
        ],
        succession: [],
        composition: { first_team: 18, reserve: 0, youth: 0, loaned_out: 0, loaned_in: 0, unknown: 0 },
        algorithm_version: 'squad-score-1',
        data_gaps: [],
      })
    }
    if (path.endsWith('/squad/weights')) {
      return json({ weights: {}, profile: { key: 'balanced', name: '均衡评估', weights: {} }, resolved_at: '2026-11-26T10:00:00Z' })
    }
    if (path.endsWith('/squad/depth')) return json({ items: [], total: 0, squad_size: 18, missing_position: 0 })
    if (path.endsWith('/squad/profiles')) return json({ items: [], total: 0, default_weights: {} })
    if (/\/saves\/\d+\/user-club$/.test(path)) return json({ club: { id: 1, name: 'Northbridge United' }, source: 'manual', confidence: 1 })
    if (path.endsWith('/players')) return json({ items: [], total: 0, coverage: {} })
    if (/\/players\/\d+$/.test(path)) return json({ summary: { name: 'Mario Bianchi', instance_id: 12 }, attributes: [] })
    return json({})
  })
}

test.beforeEach(async ({ page }) => {
  await mockApi(page)
})

test('关注名单：切换名单、搜索、状态与新建名单', async ({ page }) => {
  await page.goto('/watchlist')
  await expect(page.getByRole('heading', { name: '关注名单', level: 1 })).toBeVisible()
  await expect(page.locator('.watch-filters__lists')).toContainText('潜力新星')

  await page.locator('.watch-filters__lists button', { hasText: '潜力新星' }).click()
  await expect(page.locator('.watch-filters__search input').first()).toBeVisible()

  await page.getByPlaceholder('搜索关注球员姓名').fill('Mario')
  await expect(page.locator('.sm-table, table').first()).toContainText('Mario Bianchi')

  const statusSelect = page.locator('.watch-status-select').first()
  await statusSelect.locator('.el-select__wrapper').click()
  await page.locator('.el-select-dropdown__item', { hasText: '准备引进' }).last().click()

  await page.getByRole('button', { name: '新建名单' }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.getByPlaceholder('例如：潜力新星').fill('出售观察')
  await page.getByRole('button', { name: '创建' }).click()
  await expect(page.getByRole('dialog')).toBeHidden()
})

test('AI 球探助手：球员卡片可跳转与关注', async ({ page }) => {
  await page.goto('/agent')
  await expect(page.getByRole('heading', { name: 'AI 球探助手', level: 1 })).toBeVisible()
  const card = page.locator('.agent-card').first()
  await expect(card).toContainText('Mario Bianchi')
  await expect(card).toContainText('CA 152')

  await card.getByRole('button', { name: '关注' }).click()
  await expect(page.getByText('已关注 Mario Bianchi')).toBeVisible()

  await card.getByRole('button', { name: '查看详情' }).click()
  await expect(page).toHaveURL(/\/players\/12$/)
})

test('引援推荐：显示等级并可进入详情', async ({ page }) => {
  await page.goto('/recruitment')
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await expect(page.getByText('S · 重点推荐')).toBeVisible()
  await page.getByRole('button', { name: '详情' }).first().click()
  await expect(page).toHaveURL(/\/players\/12$/)
})

test('阵容分析：补强优先级可跳到智能引援', async ({ page }) => {
  await page.goto('/squad')
  await expect(page.getByText('补强优先级')).toBeVisible()
  await expect(page.locator('.priority__text', { hasText: '仅有 1 名可用中锋，建议补强。' })).toBeVisible()
  await page.getByRole('button', { name: '去引援' }).first().click()
  await expect(page).toHaveURL(/\/recruitment\?slot=ST$/)
})
