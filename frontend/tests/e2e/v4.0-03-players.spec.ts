import { test, expect, type Page } from '@playwright/test'

/**
 * V4.0-03 球员探索回归契约（Premium Light）。
 *
 * 全部接口使用本地 mock：只验证界面结构与请求参数，不代表真实 FM27 数据验收。
 * 真实数据截图与验收状态见 docs/reports/V4.0-03-PLAYER-EXPLORER-REPORT.md。
 */

const meta = {
  product: 'ScoutMind',
  version: '4.0.3',
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
      player_count: 60,
      snapshot_count: 120,
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

interface MockPlayer {
  instance_id: number
  player_id: number
  name: string
  age: number
  nationality: string
  position: string
  position_group: string
  club: string
  club_id: number
  league: string
  ca: number
  pa: number
  market_value: number
  wage: number
  contract_end: string
  height_cm: number
  foot: 'left' | 'right' | 'both'
  observed_at: string
  data_completeness: number
  watched: boolean
}

function basePlayers(): MockPlayer[] {
  const named: MockPlayer[] = [
    {
      instance_id: 12,
      player_id: 1,
      name: 'Mario Bianchi',
      age: 24,
      nationality: 'Italy',
      position: 'ST',
      position_group: 'FW',
      club: 'Northbridge United',
      club_id: 1,
      league: 'Premier Division',
      ca: 152,
      pa: 168,
      market_value: 35_000_000,
      wage: 80_000,
      contract_end: '2029-06-30',
      height_cm: 183,
      foot: 'right',
      observed_at: '2026-11-26T10:00:00Z',
      data_completeness: 0.9,
      watched: false,
    },
    {
      instance_id: 13,
      player_id: 2,
      name: 'Luca Verdi',
      age: 20,
      nationality: 'Italy',
      position: 'AMC',
      position_group: 'MF',
      club: 'Northbridge United',
      club_id: 1,
      league: 'Premier Division',
      ca: 138,
      pa: 175,
      market_value: 22_000_000,
      wage: 35_000,
      contract_end: '2028-06-30',
      height_cm: 178,
      foot: 'left',
      observed_at: '2026-11-25T10:00:00Z',
      data_completeness: 0.85,
      watched: false,
    },
    {
      instance_id: 14,
      player_id: 3,
      name: 'Diego Ruiz',
      age: 29,
      nationality: 'Spain',
      position: 'DC',
      position_group: 'DF',
      club: 'Kingsport City',
      club_id: 2,
      league: 'La Liga',
      ca: 145,
      pa: 150,
      market_value: 8_000_000,
      wage: 42_000,
      contract_end: '2027-01-31',
      height_cm: 191,
      foot: 'left',
      observed_at: '2026-11-24T10:00:00Z',
      data_completeness: 0.72,
      watched: true,
    },
    {
      instance_id: 15,
      player_id: 4,
      name: 'Kenji Sato',
      age: 18,
      nationality: 'Japan',
      position: 'GK',
      position_group: 'GK',
      club: 'Kingsport City',
      club_id: 2,
      league: 'La Liga',
      ca: 99,
      pa: 150,
      market_value: 1_200_000,
      wage: 6_000,
      contract_end: '2029-06-30',
      height_cm: 188,
      foot: 'right',
      observed_at: '2026-11-23T10:00:00Z',
      data_completeness: 0.8,
      watched: false,
    },
  ]
  const filler: MockPlayer[] = Array.from({ length: 56 }, (_, index) => ({
    instance_id: 100 + index,
    player_id: 100 + index,
    name: `Filler Player ${String(index + 1).padStart(2, '0')}`,
    age: 19 + (index % 15),
    nationality: index % 2 === 0 ? 'England' : 'Brazil',
    position: index % 3 === 0 ? 'MC' : index % 3 === 1 ? 'DL' : 'ST',
    position_group: index % 3 === 0 ? 'MF' : index % 3 === 1 ? 'DF' : 'FW',
    club: index % 2 === 0 ? 'Northbridge United' : 'Kingsport City',
    club_id: index % 2 === 0 ? 1 : 2,
    league: index % 2 === 0 ? 'Premier Division' : 'La Liga',
    ca: 80 + (index % 60),
    pa: 110 + (index % 70),
    market_value: 500_000 + index * 250_000,
    wage: 5_000 + index * 500,
    contract_end: index % 4 === 0 ? '2027-06-30' : '2030-06-30',
    height_cm: 170 + (index % 25),
    foot: index % 3 === 0 ? 'both' : 'right',
    observed_at: '2026-11-20T10:00:00Z',
    data_completeness: 0.7,
    watched: false,
  }))
  return [...named, ...filler]
}

interface MockOptions {
  empty?: boolean
  failPlayers?: boolean
  slowPlayers?: number
}

function summary(player: MockPlayer, watched: Set<number>) {
  return {
    instance_id: player.instance_id,
    player_id: player.player_id,
    save_local_uid: `UID-${player.instance_id}`,
    name: player.name,
    age: player.age,
    birth_date: null,
    nationality: player.nationality,
    position: player.position,
    position_group: player.position_group,
    club: player.club,
    club_id: player.club_id,
    ca: player.ca,
    pa: player.pa,
    market_value: player.market_value,
    wage: player.wage,
    contract_end: player.contract_end,
    observed_at: player.observed_at,
    data_completeness: player.data_completeness,
    source: 'fm27_live_reader',
    is_watched: watched.has(player.instance_id),
  }
}

function detailOf(player: MockPlayer) {
  return {
    summary: {
      ...summary(player, new Set()),
      height_cm: player.height_cm,
      foot: player.foot,
    },
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
    last_seen: '2026-11-26',
    latest_snapshot_id: 1000 + player.instance_id,
    valuation: null,
    tags: ['重点观察'],
    notes: null,
  }
}

async function mockApi(page: Page, options: MockOptions = {}): Promise<{ calls: URL[] }> {
  const calls: URL[] = []
  const watched = new Set<number>([14])
  const dataset = options.empty ? [] : basePlayers()
  let watchItemSeq = 900
  const watchItemByInstance = new Map<number, number>([[14, 899]])

  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url())
    calls.push(url)
    const path = url.pathname
    const method = route.request().method()
    const json = (body: unknown, status = 200) => route.fulfill({ status, json: body })

    if (path.endsWith('/meta/bootstrap')) return json(meta)
    if (path.endsWith('/meta/saves')) return json({ items: meta.saves })
    if (path.endsWith('/system/data-health')) {
      return json({
        save: { id: 1, name: '测试存档', game_date: '2026-07-01' },
        players: { count: dataset.length, linked: dataset.length, unlinked: 0, missing_source_field: 0 },
        clubs: { count: 2, linked_players: dataset.length },
        transfers: { count: 0, completed: 0 },
        opportunities: { active: 0, confirmed: 0, inferred: 0 },
        status: { level: 'ok', label: '数据完整', reasons: [] },
        last_updated_at: '2026-11-26T10:00:00Z',
        background: { active: 0, latest: null },
        can_repair: false,
        notes: [],
      })
    }
    if (path.endsWith('/system/onboarding')) {
      return json({ status: 'ready', data: { has_players: dataset.length > 0 }, summary: {}, actions: [] })
    }
    if (path.endsWith('/data-hub/status')) {
      return json({
        game: { running: true, detected: true, pid: 1, version: '27.1', exe_path: null, message: '', compatibility: 'supported', compatibility_message: '' },
        save: { id: 1, name: '测试存档', recognized: true, identity_status: 'verified', can_sync: true, message: '' },
        records: { players: dataset.length, clubs: 2, transfers: 0, snapshots: 0 },
        last_sync: null,
        health: { status: 'ok', issues: [] },
        needs_confirmation: { unresolved_players: 0, identity_conflicts: 0, quarantined_rows: 0, total: 0 },
        repairs: {},
      })
    }
    if (path.endsWith('/imports')) return json({ items: [], total: 0, limit: 5, offset: 0 })
    if (path.endsWith('/analytics/overview')) {
      return json({ save_id: 1, save: meta.saves[0], players: dataset.length, snapshots: 0, transfers: 0, clubs: 2, coverage: {} })
    }
    if (path.endsWith('/clubs/search')) return json({ items: [], total: 0 })
    if (path.endsWith('/clubs')) {
      return json({
        items: [
          { club_id: 1, name: 'Northbridge United', nation: 'England', league: 'Premier Division', reputation: 7000, is_user_club: true, currency: 'EUR' },
          { club_id: 2, name: 'Kingsport City', nation: 'Spain', league: 'La Liga', reputation: 6500, is_user_club: false, currency: 'EUR' },
        ],
        total: 2,
      })
    }
    if (path.endsWith('/compatibility')) return json({ items: [], reader_versions: [] })

    if (path.endsWith('/players/facets')) {
      const nationalities = new Map<string, number>()
      const leagues = new Map<string, number>()
      for (const player of dataset) {
        nationalities.set(player.nationality, (nationalities.get(player.nationality) ?? 0) + 1)
        leagues.set(player.league, (leagues.get(player.league) ?? 0) + 1)
      }
      return json({
        total_players: dataset.length,
        nationalities: [...nationalities].map(([value, count]) => ({ value, count })),
        leagues: [...leagues].map(([value, count]) => ({ value, count })),
      })
    }

    if (method === 'POST' && path.endsWith('/watchlist/items')) {
      const body = route.request().postDataJSON() as { instance_id: number }
      const id = ++watchItemSeq
      watched.add(body.instance_id)
      watchItemByInstance.set(body.instance_id, id)
      return json({ id, instance_id: body.instance_id, list_id: 1, status: 'watching', tag: null, note: null }, 201)
    }
    if (method === 'DELETE' && /\/watchlist\/items\/\d+$/.test(path)) {
      for (const [instanceId, itemId] of watchItemByInstance) {
        if (String(itemId) === path.split('/').pop()) {
          watched.delete(instanceId)
          watchItemByInstance.delete(instanceId)
        }
      }
      return route.fulfill({ status: 204 })
    }
    if (path.endsWith('/watchlist/lists')) return json({ items: [{ id: 1, name: '默认关注', count: watched.size, is_default: true }], total: 1 })
    if (path.endsWith('/watchlist')) {
      return json({
        items: dataset
          .filter((player) => watched.has(player.instance_id))
          .map((player) => ({
            id: watchItemByInstance.get(player.instance_id) ?? 1,
            instance_id: player.instance_id,
            list_id: 1,
            list_name: '默认关注',
            player: summary(player, watched),
            status: 'watching',
            tag: null,
            note: null,
            source: 'fm27_live_reader',
            added_at: '2026-11-01T00:00:00Z',
          })),
        total: watched.size,
        lists: [{ id: 1, name: '默认关注', count: watched.size, is_default: true }],
      })
    }

    if (path.endsWith('/players') && method === 'GET') {
      if (options.failPlayers) return json({ error: { code: 'server_error', message: '模拟的球员接口故障' } }, 500)
      if (options.slowPlayers) await new Promise((resolve) => setTimeout(resolve, options.slowPlayers))
      const params = url.searchParams
      let rows = [...dataset]
      const query = params.get('query')
      if (query) rows = rows.filter((player) => player.name.toLowerCase().includes(query.toLowerCase()))
      const position = params.get('position')
      if (position) rows = rows.filter((player) => player.position === position)
      const group = params.get('position_group')
      if (group) rows = rows.filter((player) => player.position_group === group)
      const minAge = params.get('min_age')
      if (minAge) rows = rows.filter((player) => player.age >= Number(minAge))
      const maxAge = params.get('max_age')
      if (maxAge) rows = rows.filter((player) => player.age <= Number(maxAge))
      const minCa = params.get('min_ca')
      if (minCa) rows = rows.filter((player) => player.ca >= Number(minCa))
      const maxPa = params.get('max_pa')
      if (maxPa) rows = rows.filter((player) => player.pa <= Number(maxPa))
      const maxValue = params.get('max_value')
      if (maxValue) rows = rows.filter((player) => player.market_value <= Number(maxValue))
      const maxWage = params.get('max_wage')
      if (maxWage) rows = rows.filter((player) => player.wage <= Number(maxWage))
      const clubId = params.get('club_id')
      if (clubId) rows = rows.filter((player) => player.club_id === Number(clubId))
      const nationality = params.get('nationality')
      if (nationality) rows = rows.filter((player) => player.nationality === nationality)
      const league = params.get('league')
      if (league) rows = rows.filter((player) => player.league === league)
      const foot = params.get('foot')
      if (foot) rows = rows.filter((player) => player.foot === foot)
      const minHeight = params.get('min_height')
      if (minHeight) rows = rows.filter((player) => player.height_cm >= Number(minHeight))
      const maxHeight = params.get('max_height')
      if (maxHeight) rows = rows.filter((player) => player.height_cm <= Number(maxHeight))
      const contractBefore = params.get('contract_end_before')
      if (contractBefore) rows = rows.filter((player) => player.contract_end <= contractBefore)
      if (params.get('watchlist_only') === 'true') rows = rows.filter((player) => watched.has(player.instance_id))

      const sort = params.get('sort') ?? '-updated_at'
      const desc = sort.startsWith('-')
      const key = sort.replace(/^-/, '')
      const value = (player: MockPlayer) => {
        if (key === 'age') return player.age
        if (key === 'ca') return player.ca
        if (key === 'pa') return player.pa
        if (key === 'market_value') return player.market_value
        if (key === 'name') return player.name
        return player.observed_at
      }
      rows.sort((left, right) => {
        const a = value(left)
        const b = value(right)
        const compared = typeof a === 'string' && typeof b === 'string' ? a.localeCompare(b) : Number(a) - Number(b)
        return desc ? -compared : compared
      })

      const total = rows.length
      const limit = Number(params.get('limit') ?? 50)
      const offset = Number(params.get('offset') ?? 0)
      return json({
        items: rows.slice(offset, offset + limit).map((player) => summary(player, watched)),
        total,
        coverage: { ca: 1, pa: 1, market_value: 1 },
      })
    }

    if (/^\/api\/v1\/players\/\d+$/.test(path)) {
      const id = Number(path.split('/').pop())
      const player = dataset.find((item) => item.instance_id === id) ?? dataset[0]
      return json(detailOf(player))
    }
    if (/^\/api\/v1\/players\/\d+\/status$/.test(path)) {
      return json({
        instance_id: Number(path.split('/')[4]),
        player_name: null,
        current: {
          observed_at: '2026-11-26T10:00:00Z',
          game_date: '2026-07-01',
          flags: { listed: false, loan_listed: false },
          injury: { proneness: null, injured: false, start_date: null, expected_return: null, note: null },
          registration: { parent_club: 'Northbridge United', loan_club: null, team_type: 'senior' },
          agreed_transfer: null,
        },
        history: [],
        changes: [],
        first_seen: {},
        loans: [],
        candidates: [],
        data_gaps: [],
        algorithm_version: 'test',
      })
    }
    if (/^\/api\/v1\/players\/\d+\/(history|development)$/.test(path)) {
      return json({
        points: [],
        coverage: { points: null, attributes: null },
        summary: { snapshots: 2, ca_delta: null, market_value_delta: null, minutes_delta: null, window_start: null, window_end: null },
        records: [],
        attributions: [],
        data_gaps: [],
      })
    }
    if (path.endsWith('/transfers/valuation')) {
      return json({
        low: null,
        mid: null,
        high: null,
        sample_size: 0,
        method: null,
        algorithm_version: 'test',
        confidence: null,
        insufficient_sample: true,
        coverage: null,
      })
    }
    if (path.endsWith('/transfers/similar')) return json({ items: [], total: 0, weights: {}, effective_weights: {}, message: null })
    if (path.endsWith('/scouting/roles')) return json({ items: [] })

    return json({})
  })

  return { calls }
}

function playerCalls(calls: URL[]): URL[] {
  return calls.filter((url) => url.pathname === '/api/v1/players' && !url.searchParams.has('watchlist_only'))
}

async function expectParam(calls: URL[], name: string, value: string | null): Promise<void> {
  await expect.poll(() => playerCalls(calls).at(-1)?.searchParams.get(name) ?? null).toBe(value)
}

async function openPage(page: Page, options: MockOptions = {}): Promise<{ calls: URL[] }> {
  await page.addInitScript(() => {
    window.localStorage.clear()
    window.localStorage.setItem('scoutmind.onboardingDismissed', '1')
  })
  const mocked = await mockApi(page, options)
  await page.goto('/players')
  await expect(page.getByRole('heading', { name: '球员探索', level: 1 })).toBeVisible()
  return mocked
}

test('默认加载：紧凑页头、搜索入口、状态栏与密度列表', async ({ page }) => {
  await openPage(page)

  await expect(page.getByPlaceholder('输入球员姓名')).toBeVisible()
  const status = page.locator('.pw-status')
  await expect(status).toContainText('存档球员')
  await expect(status).toContainText('60')
  await expect(status).toContainText('当前结果')
  await expect(page.getByRole('button', { name: '高级筛选' })).toBeVisible()
  await expect(page.locator('.pw-row')).toHaveCount(50)
  await expect(page.getByText('Mario Bianchi').first()).toBeVisible()
  await expect(page.locator('.pw-table__head')).toContainText('球员')
  // 旧版大面积概览卡与四项指标横排不再存在。
  await expect(page.getByText('球探概览')).toHaveCount(0)
  await expect(page.locator('.stat-strip')).toHaveCount(0)
})

test('姓名搜索：输入即查询并使用防抖参数', async ({ page }) => {
  const { calls } = await openPage(page)
  await page.getByPlaceholder('输入球员姓名').fill('Mario')
  await expect(page.locator('.pw-row')).toHaveCount(1)
  await expectParam(calls, 'query', 'Mario')
  await expect(page.locator('.pw-chip')).toContainText('姓名「Mario」')
})

test('位置筛选：位置组胶囊与清除单个条件', async ({ page }) => {
  const { calls } = await openPage(page)
  await page.getByRole('button', { name: '前锋', exact: true }).click()
  await expectParam(calls, 'position_group', 'FW')
  await expect(page.locator('.pw-chip')).toContainText('位置 前锋')
  await page.getByRole('button', { name: '清除 位置 前锋' }).click()
  await expectParam(calls, 'position_group', null)
  await expect(page.locator('.pw-chip')).toHaveCount(0)
})

test('年龄筛选：最小值写入请求', async ({ page }) => {
  const { calls } = await openPage(page)
  const minAge = page.getByLabel('最小年龄')
  await minAge.fill('25')
  await minAge.press('Tab')
  await expectParam(calls, 'min_age', '25')
  await expect(page.locator('.pw-chip')).toContainText('年龄 25–不限')
})

test('能力筛选：CA 下限写入请求', async ({ page }) => {
  const { calls } = await openPage(page)
  const minCa = page.getByLabel('当前能力下限')
  await minCa.fill('140')
  await minCa.press('Tab')
  await expectParam(calls, 'min_ca', '140')
})

test('身价筛选：万单位换算为基础单位', async ({ page }) => {
  const { calls } = await openPage(page)
  const value = page.getByLabel('身价上限，单位万')
  await value.fill('1000')
  await value.press('Tab')
  await expectParam(calls, 'max_value', '10000000')
  await expect(page.locator('.pw-chip')).toContainText('身价 ≤ 1000 万')
})

test('高级筛选：国籍/联赛/俱乐部/脚型/身高/合同全部来自真实字段', async ({ page }) => {
  const { calls } = await openPage(page)
  await page.getByRole('button', { name: '高级筛选' }).click()
  const dialog = page.getByRole('dialog', { name: '高级筛选' })
  await expect(dialog).toBeVisible()

  await dialog.locator('.pw-field', { hasText: '国籍' }).locator('select').selectOption('Italy')
  await expectParam(calls, 'nationality', 'Italy')

  await dialog.locator('.pw-field', { hasText: '联赛' }).locator('select').selectOption('La Liga')
  await expectParam(calls, 'league', 'La Liga')

  await dialog.locator('.pw-field', { hasText: '俱乐部' }).locator('select').selectOption('2')
  await expectParam(calls, 'club_id', '2')

  await dialog.locator('.pw-field', { hasText: '惯用脚' }).locator('select').selectOption('left')
  await expectParam(calls, 'foot', 'left')

  const minHeight = dialog.getByLabel('最低身高')
  await minHeight.fill('180')
  await minHeight.press('Tab')
  await expectParam(calls, 'min_height', '180')

  const wage = dialog.getByLabel('周薪上限，单位万')
  await wage.fill('5')
  await wage.press('Tab')
  await expectParam(calls, 'max_wage', '50000')

  await dialog.locator('.pw-field', { hasText: '合同到期' }).locator('select').selectOption({ label: '12 个月内到期' })
  await expect.poll(() => playerCalls(calls).at(-1)?.searchParams.has('contract_end_before')).toBe(true)
})

test('多条件组合：摘要、结果数量与清空全部', async ({ page }) => {
  const { calls } = await openPage(page)
  await page.getByPlaceholder('输入球员姓名').fill('a')
  await page.getByRole('button', { name: '中场', exact: true }).click()
  const minAge = page.getByLabel('最小年龄')
  await minAge.fill('20')
  await minAge.press('Tab')

  await expect(page.locator('.pw-chip')).toHaveCount(3)
  await expect
    .poll(() => {
      const latest = playerCalls(calls).at(-1)
      return [latest?.searchParams.get('query'), latest?.searchParams.get('position_group'), latest?.searchParams.get('min_age')].join('|')
    })
    .toBe('a|MF|20')

  await page.getByRole('button', { name: '清空全部' }).click()
  await expect(page.locator('.pw-chip')).toHaveCount(0)
  await expectParam(calls, 'query', null)
})

test('排序：服务端排序参数随选择变化', async ({ page }) => {
  const { calls } = await openPage(page)
  await page.getByLabel('排序方式').selectOption('-ca')
  await expectParam(calls, 'sort', '-ca')
  await expect(page.locator('.pw-row').first()).toBeVisible()
  await page.getByLabel('排序方式').selectOption('age')
  await expectParam(calls, 'sort', 'age')
})

test('分页：下一页使用 offset，页大小可切换', async ({ page }) => {
  const { calls } = await openPage(page)
  await expect(page.locator('.pw-row')).toHaveCount(50)
  await page.getByRole('button', { name: '下一页' }).click()
  await expectParam(calls, 'offset', '50')
  await expect(page.locator('.pw-row')).toHaveCount(10)

  await page.getByLabel('每页数量').selectOption('25')
  await expectParam(calls, 'limit', '25')
  await expectPollOffset(calls, '0')
})

async function expectPollOffset(calls: URL[], value: string): Promise<void> {
  await expect.poll(() => playerCalls(calls).at(-1)?.searchParams.get('offset') ?? null).toBe(value)
}

test('清空筛选：从筛选无结果回到完整列表', async ({ page }) => {
  await openPage(page)
  await page.getByPlaceholder('输入球员姓名').fill('zzz-no-match')
  await expect(page.getByText('没有找到符合条件的球员')).toBeVisible()
  await page.getByRole('button', { name: '清空筛选条件' }).click()
  await expect(page.locator('.pw-row').first()).toBeVisible()
  await expect(page.locator('.pw-chip')).toHaveCount(0)
})

test('关注：列表内添加关注并实时反馈', async ({ page }) => {
  await openPage(page)
  const row = page.locator('.pw-row', { hasText: 'Mario Bianchi' })
  await row.getByRole('button', { name: '关注 Mario Bianchi' }).click()
  await expect(row.getByRole('button', { name: '取消关注 Mario Bianchi' })).toBeVisible()
  await expect(page.locator('.pw-toast')).toContainText('已加入关注名单')
})

test('取消关注：使用既有关注记录并失败可恢复', async ({ page }) => {
  await openPage(page)
  const row = page.locator('.pw-row', { hasText: 'Diego Ruiz' })
  await row.getByRole('button', { name: '取消关注 Diego Ruiz' }).click()
  await expect(row.getByRole('button', { name: '关注 Diego Ruiz' })).toBeVisible()
})

test('球员对比：选择数量与上限入口', async ({ page }) => {
  await openPage(page)
  const row = page.locator('.pw-row', { hasText: 'Mario Bianchi' })
  await row.getByRole('button', { name: '对比' }).click()
  await expect(page.getByRole('button', { name: '球员对比（1/4）' })).toBeVisible()
  await expect(row.getByRole('button', { name: '已选' })).toBeVisible()
})

test('详情抽屉：打开、分组内容与关注/对比操作', async ({ page }) => {
  await openPage(page)
  await page.locator('.pw-row', { hasText: 'Mario Bianchi' }).getByRole('button', { name: 'Mario Bianchi', exact: true }).click()
  const drawer = page.getByRole('dialog', { name: '球员详情' })
  await expect(drawer).toBeVisible()
  await expect(drawer.getByRole('heading', { name: 'Mario Bianchi' })).toBeVisible()
  await expect(drawer.getByText('能力结构')).toBeVisible()
  await expect(drawer.getByText('合同与市场')).toBeVisible()
  await expect(drawer.getByText('状态与风险')).toBeVisible()
  await expect(drawer.getByRole('link', { name: '打开完整档案' })).toBeVisible()
  await drawer.getByRole('button', { name: '关注' }).click()
  await expect(drawer.getByRole('button', { name: '已关注' })).toBeVisible()
})

test('详情抽屉：关闭与切换上一位/下一位', async ({ page }) => {
  await openPage(page)
  await page.locator('.pw-row', { hasText: 'Mario Bianchi' }).getByRole('button', { name: 'Mario Bianchi', exact: true }).click()
  const drawer = page.getByRole('dialog', { name: '球员详情' })
  await drawer.getByRole('button', { name: '下一位球员' }).click()
  await expect(drawer.getByRole('heading', { name: 'Luca Verdi' })).toBeVisible()
  await drawer.getByRole('button', { name: '关闭球员详情' }).click()
  await expect(drawer).toBeHidden()
})

test('空数据：同步引导而不是空白表格', async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.clear()
    window.localStorage.setItem('scoutmind.onboardingDismissed', '1')
  })
  await mockApi(page, { empty: true })
  await page.goto('/players')
  await expect(page.getByText('还没有可探索的球员')).toBeVisible()
  await expect(page.getByText('同步 FM27 游戏数据后，即可开始搜索和分析球员。')).toBeVisible()
  await expect(page.getByRole('button', { name: '同步游戏数据' })).toBeVisible()
})

test('加载状态：浅色骨架屏保持结构稳定', async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.clear()
    window.localStorage.setItem('scoutmind.onboardingDismissed', '1')
  })
  await mockApi(page, { slowPlayers: 1500 })
  await page.goto('/players')
  await expect(page.locator('.pw-skeleton')).toBeVisible()
  await expect(page.locator('.pw-skeleton')).toHaveAttribute('aria-busy', 'true')
})

test('错误状态：可理解提示与重试入口', async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.clear()
    window.localStorage.setItem('scoutmind.onboardingDismissed', '1')
  })
  await mockApi(page, { failPlayers: true })
  await page.goto('/players')
  await expect(page.getByText('球员列表加载失败')).toBeVisible()
  await expect(page.getByRole('button', { name: '重试' })).toBeVisible()
  await expect(page.getByRole('button', { name: '检查数据同步' })).toBeVisible()
})

test('卡片视图：紧凑卡片展示能力与操作', async ({ page }) => {
  await openPage(page)
  await page.getByRole('button', { name: '卡片', exact: true }).click()
  await expect(page.locator('.pw-card').first()).toBeVisible()
  const card = page.locator('.pw-card', { hasText: 'Mario Bianchi' })
  await expect(card.getByText('CA')).toBeVisible()
  await expect(card.getByRole('button', { name: '加入对比' })).toBeVisible()
  await card.getByRole('button', { name: '查看档案' }).click()
  await expect(page.getByRole('dialog', { name: '球员详情' })).toBeVisible()
})

for (const [width, height] of [
  [1366, 768],
  [1600, 900],
  [1920, 1080],
] as const) {
  test(`${width}×${height} 下页面无横向溢出，主要操作可用`, async ({ page }) => {
    await page.setViewportSize({ width, height })
    await openPage(page)
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    expect(overflow).toBeLessThanOrEqual(1)
    await expect(page.getByRole('button', { name: '高级筛选' })).toBeVisible()
    await expect(page.getByRole('button', { name: '下一页' })).toBeVisible()
  })
}
