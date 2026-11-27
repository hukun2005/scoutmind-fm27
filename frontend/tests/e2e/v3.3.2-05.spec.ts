import { test, expect, type Page } from '@playwright/test'

/**
 * V3.3.2-05 AI 转会总监 UI 契约：入口、总览、球员分析、三套报价、草稿、谈判与复盘。
 * 所有接口使用 page.route Mock；真实后端联调由后端测试与真实数据验收覆盖。
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
  message: '当前存档有 4 名球员，其中 3 名有合同到期日；转会记录 0 条。',
}

const playerSummary = {
  instance_id: 12,
  player_id: 2,
  name: 'Mario Bianchi',
  age: 24,
  birth_date: '2002-03-01',
  nationality: 'Italy',
  position: 'ST',
  position_group: 'FW',
  club: 'Kingsport City',
  club_id: 5,
  ca: 152,
  pa: 168,
  market_value: 35_000_000,
  wage: 45_000,
  contract_end: '2028-06-30',
}

const offers = [
  {
    offer_type: 'conservative',
    currency: 'EUR',
    base_fee: 29_750_000,
    immediate_payment: 29_750_000,
    installments_total: null,
    addons_potential: null,
    total_committed: 29_750_000,
    potential_total: 29_750_000,
    sell_on_pct: null,
    wage_impact: 2_340_000,
    risk_level: 'low',
    rationale: { reason: '一次性付清、低于估值 15%，先试探卖方底线；成交概率最低' },
    budget_feasible: null,
  },
  {
    offer_type: 'competitive',
    currency: 'EUR',
    base_fee: 35_000_000,
    immediate_payment: 21_000_000,
    installments_total: 14_000_000,
    addons_potential: 1_750_000,
    total_committed: 35_000_000,
    potential_total: 36_750_000,
    sell_on_pct: null,
    wage_impact: 2_340_000,
    risk_level: 'medium',
    rationale: { reason: '固定费用贴近估值，60% 首付 + 40% 分期' },
    budget_feasible: null,
  },
  {
    offer_type: 'fast_close',
    currency: 'EUR',
    base_fee: 41_300_000,
    immediate_payment: 41_300_000,
    installments_total: null,
    addons_potential: 2_065_000,
    total_committed: 41_300_000,
    potential_total: 43_365_000,
    sell_on_pct: null,
    wage_impact: 2_340_000,
    risk_level: 'high',
    rationale: { reason: '溢价 18% 并全额首付，用于必须拿下的目标' },
    budget_feasible: null,
  },
]

const purchaseBundle = {
  instance_id: 12,
  direction: 'purchase',
  currency: 'EUR',
  available: true,
  offers,
  factors: {},
  basis: { kind: 'market_value_only', base: 35_000_000, sample_size: 0, confidence: 'low' },
  budget: { provided: false, value: null },
  warnings: [
    '可比成交样本不足，以下方案仅以当前身价为基准；身价不是成交价',
    '当前未获取可靠预算数据，报价方案不包含预算可行性保证',
  ],
  missing_fields: ['loan_terms', 'transfer_budget', 'transfer_history'],
  algorithm_version: 'transfer-offer-1',
}

const saleBundle = {
  ...purchaseBundle,
  direction: 'sale',
  offers: offers.map((offer, index) => ({
    ...offer,
    offer_type: ['quick_sale', 'fair_sale', 'max_value'][index],
    sell_on_pct: index === 2 ? 10 : null,
  })),
  squad_impact: { position: 'ST', same_position_peers: 2, squad_gap_risk: 'medium', wage_release: 2_340_000 },
  basis: {},
}

const analysis = {
  instance_id: 12,
  save_id: 1,
  player: {
    name: 'Mario Bianchi',
    club_id: 5,
    club_name: 'Kingsport City',
    position: 'ST',
    age: 24,
    ca: 152,
    pa: 168,
    market_value: 35_000_000,
  },
  contract: {
    club_id: 5,
    contract_end: '2028-06-30',
    contract_start: null,
    wage: 45_000,
    wage_period: 'week',
    annual_wage: 2_340_000,
    remaining_months: 20,
    contract_status: 'active',
    contract_type: null,
    release_clause: null,
    observed_at: '2026-11-26T10:00:00',
    source: 'fm27_live_reader',
    confidence: 0.9,
    listed: false,
    loan_listed: false,
    not_for_sale: null,
    missing_fields: [],
    warnings: [],
  },
  availability: {},
  loan: { available: false, note: '当前数据源没有该球员的租借记录；未获取不等于没有条款' },
  transfer_history: [],
  clauses: [],
  valuation: {
    low: null,
    mid: null,
    high: null,
    sample_size: 0,
    confidence: 'insufficient',
    insufficient_sample: true,
    method: 'similar_transfers_quantile',
    algorithm_version: 'valuation-1',
    warnings: ['可比成交只有 0 笔，低于最小样本，不给出估值区间'],
  },
  purchase_preview: purchaseBundle,
  sale_preview: saleBundle,
  missing_fields: ['loan_terms', 'transfer_budget', 'transfer_history'],
  sources: {},
}

const transferList = {
  items: [
    {
      transfer_id: 1,
      player_name: 'Luca Ferri',
      from_club_name: 'Old Town',
      to_club_name: 'Kingsport City',
      transfer_type: 'permanent',
      status: 'completed',
      transfer_date: '2026-07-01',
      currency: 'EUR',
      base_fee: 12_000_000,
      effective_fee: 12_000_000,
      addons_potential: null,
      source: 'local_import',
    },
  ],
  total: 1,
  coverage: {},
}

const clubSummary = {
  club_id: 3,
  club_name: 'Northbridge United',
  purchases: 2,
  sales: 1,
  incoming_by_type: { permanent: 2 },
  outgoing_by_type: { loan: 1 },
  completed_incoming: 2,
  completed_outgoing: 1,
  cash_in_by_currency: { EUR: 5_000_000 },
  cash_out_by_currency: { EUR: 20_000_000 },
  agreed: 0,
  pending: 1,
  cancelled: 0,
  warning: null,
}

const negotiation = {
  negotiation_id: 1,
  instance_id: 12,
  offer_id: null,
  direction: 'purchase',
  status: 'DRAFT',
  round_count: 0,
  initial_ask: 35_000_000,
  user_offer: null,
  counter_offer: null,
  final_fee: null,
  currency: 'EUR',
  final_terms: {},
  reject_reason: null,
  source: 'user_confirmed',
  created_at: '2026-11-27T10:00:00',
  completed_at: null,
  events: [
    {
      event_id: 1,
      event_type: 'draft_created',
      amount: 35_000_000,
      data: {},
      occurred_at: '2026-11-27T10:00:00',
    },
  ],
}

const review = {
  negotiation_id: 1,
  instance_id: 12,
  direction: 'purchase',
  status: 'COMPLETED',
  outcome: '成交',
  initial_valuation: { low: null, mid: null, high: null, sample_size: 0, confidence: 'insufficient', insufficient_sample: true, method: '', algorithm_version: '', warnings: [] },
  initial_offer: 35_000_000,
  final_fee: 36_000_000,
  delta: 1_000_000,
  delta_pct: 2.9,
  round_count: 2,
  counter_offer: 37_000_000,
  reject_reason: null,
  final_terms: {},
  completed_samples_in_save: 1,
  warnings: ['当前历史谈判样本不足，暂不形成可靠规律'],
  algorithm_version: 'negotiation-review-1',
}

const opportunityItem = {
  opportunity_id: 1,
  instance_id: 12,
  player_name: 'Mario Bianchi',
  club_id: null,
  club_name: null,
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
  types: ['listed', 'contract_expiring'],
  first_seen_at: '2026-11-27T08:00:00Z',
  last_seen_at: '2026-11-27T08:00:00Z',
}

const opportunitySummary = {
  save_id: 1,
  scan_version: 'transfer-radar-1',
  last_scan_at: '2026-11-27T08:00:00Z',
  counts: { listed: 12, loan_listed: 34, release_listed: 2, contract_expiring: 120, ai_inferred: 3, new_24h: 5 },
  groups: { strong: 4, watch: 8, loan: 2, long_term: 1, not_recommended: 3 },
  group_labels: {},
  top_recommendations: [],
  alerts_unread: 1,
  capabilities: {
    total_players: 4,
    known_club_players: 4,
    missing_contract: 1,
    transfer_intent: 'unsupported',
    transfer_budget: 'unsupported',
  },
  unsupported_fields: ['transfer_intent', 'transfer_budget'],
  auto_scan: null,
}

const alerts = {
  items: [
    {
      alert_id: 5,
      instance_id: 12,
      player_name: 'Mario Bianchi',
      type: 'listed',
      severity: 'info',
      title: '新增挂牌球员：Mario Bianchi',
      message: '已挂牌，更新时间 2026-11-27',
      read_at: null,
      created_at: '2026-11-27T08:00:00Z',
    },
  ],
  unread: 1,
}

const strategyCases = {
  items: [
    {
      case_id: 'transfer:1',
      player_instance_id: 12,
      player_name: 'Luca Ferri',
      player_position: 'ST',
      player_age: 24,
      player_value: null,
      contract_remaining: 12,
      selling_club: 'Old Town',
      buying_club: 'Kingsport City',
      transfer_type: 'permanent',
      transfer_status: 'completed',
      actual_fee: 12_000_000,
      base_fee: 12_000_000,
      effective_fee: 12_000_000,
      addons_potential: null,
      installments: { count: 2, amount: 4_800_000 },
      addons: { count: 0, amount: null },
      loan_terms: null,
      sell_on_clause: null,
      deal_result: 'completed',
      data_source: 'csv_import',
      case_origin: 'imported',
      confidence: 1.0,
      observed_at: '2026-11-20T00:00:00Z',
    },
  ],
  total: 1,
  available: true,
  message: null,
}

const strategyInsights = {
  save_id: 1,
  available: true,
  patterns: [
    {
      key: 'installments',
      label: '分期付款',
      sample_size: 4,
      sufficient_sample: true,
      case_ids: ['transfer:1'],
      summary: '分期付款在成交中多次出现；共 4 个案例，引用 transfer:1',
    },
    {
      key: 'sell_on',
      label: '二次转会分成',
      sample_size: 1,
      sufficient_sample: false,
      case_ids: ['transfer:1'],
      summary: '样本不足（1 < 3），暂不归纳策略',
    },
  ],
  totals: { cases: 1, demo_cases: 0, imported_cases: 1 },
  message: null,
  min_sample: 3,
}

const loanBundle = {
  instance_id: 12,
  direction: 'loan',
  currency: 'EUR',
  available: true,
  offers: [
    {
      offer_type: 'low_cost_loan',
      currency: 'EUR',
      base_fee: 350_000,
      immediate_payment: 350_000,
      installments_total: null,
      addons_potential: null,
      total_committed: 350_000,
      potential_total: 350_000,
      sell_on_pct: null,
      wage_impact: 13_500,
      loan_fee: 350_000,
      wage_contribution_pct: 30,
      buy_option_fee: null,
      buy_obligation_fee: null,
      loan_months: 12,
      risk_level: 'low',
      rationale: { reason: '只承担 1% 租借费与 30% 工资，成本最低' },
      algorithm_version: 'transfer-loan-offer-1',
    },
    {
      offer_type: 'development_loan',
      currency: 'EUR',
      base_fee: 1_050_000,
      immediate_payment: 1_050_000,
      installments_total: null,
      addons_potential: null,
      total_committed: 1_050_000,
      potential_total: 34_300_000,
      sell_on_pct: null,
      wage_impact: 22_500,
      loan_fee: 1_050_000,
      wage_contribution_pct: 50,
      buy_option_fee: 33_250_000,
      buy_obligation_fee: null,
      loan_months: 12,
      risk_level: 'medium',
      rationale: { reason: '保留 95% 估值的买断选择权' },
      algorithm_version: 'transfer-loan-offer-1',
    },
    {
      offer_type: 'loan_to_buy',
      currency: 'EUR',
      base_fee: 1_750_000,
      immediate_payment: 1_750_000,
      installments_total: null,
      addons_potential: null,
      total_committed: 1_750_000,
      potential_total: 36_750_000,
      sell_on_pct: null,
      wage_impact: 31_500,
      loan_fee: 1_750_000,
      wage_contribution_pct: 70,
      buy_option_fee: null,
      buy_obligation_fee: 35_000_000,
      loan_months: 12,
      risk_level: 'high',
      rationale: { reason: '附带等值强制买断' },
      algorithm_version: 'transfer-loan-offer-1',
    },
  ],
  basis: {},
  factors: {},
  warnings: ['游戏内未标记可租借，报价可能被拒绝'],
  missing_fields: ['transfer_budget'],
  algorithm_version: 'transfer-loan-offer-1',
}

async function mockApi(page: Page) {
  const calls: Array<{ path: string; method: string; body: unknown }> = []
  let negotiationState = { ...negotiation }

  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname
    const method = route.request().method()
    const json = (body: unknown) => route.fulfill({ json: body })
    const body = route.request().postData() ? JSON.parse(route.request().postData() as string) : null
    if (method !== 'GET') calls.push({ path, method, body })

    if (path.endsWith('/meta/bootstrap')) return json(meta)
    if (path.endsWith('/transfer-director/opportunities/summary')) return json(opportunitySummary)
    if (path.endsWith('/transfer-director/opportunities/refresh') && method === 'POST') {
      return json({ created: 3, updated: 1, deactivated: 0, events: 3, alerts_created: 1, scanned_players: 4 })
    }
    if (path.endsWith('/transfer-director/opportunities/12')) {
      return json({ opportunity: { ...opportunityItem, items: [opportunityItem] }, context: analysis })
    }
    if (path.endsWith('/transfer-director/opportunities')) {
      return json({ items: [opportunityItem], total: 1, limit: 20, offset: 0, sort: 'score' })
    }
    if (path.endsWith('/transfer-director/alerts')) return json(alerts)
    if (path.endsWith('/transfer-director/alerts/5/read') && method === 'POST') {
      return json({ alert_id: 5, read_at: '2026-11-27T09:00:00Z' })
    }
    if (path.endsWith('/transfer-director/strategy-cases/similar/12')) {
      return json({ instance_id: 12, available: true, items: [{ ...strategyCases.items[0], match_pct: 82.5, matched_features: ['位置组相同', '年龄接近'], differences: [] }], total: 1, message: null })
    }
    if (path.endsWith('/transfer-director/strategy-cases')) return json(strategyCases)
    if (path.endsWith('/transfer-director/strategy-insights')) return json(strategyInsights)
    if (path.endsWith('/player/12/loan-offers') && method === 'POST') return json(loanBundle)
    if (path.endsWith('/transfer-director/overview')) return json(overview)
    if (path.endsWith('/transfer-director/club-summary')) return json(clubSummary)
    if (path.endsWith('/transfer-director/player/12')) return json({ ...analysis, loan_preview: loanBundle })
    if (path.endsWith('/player/12/purchase-offers')) return json(purchaseBundle)
    if (path.endsWith('/player/12/sale-offers')) return json(saleBundle)
    if (path.endsWith('/transfer-director/offers') && method === 'POST') {
      return json({ ...offers[0], offer_id: 9, status: 'saved', created_at: '2026-11-27T10:00:00' })
    }
    if (path.endsWith('/transfer-director/negotiations') && method === 'POST') {
      negotiationState = { ...negotiationState, ...body }
      return json(negotiationState)
    }
    if (path.endsWith('/transfer-director/negotiations/1/events') && method === 'POST') {
      negotiationState = {
        ...negotiationState,
        status: body.event_type === 'completed' ? 'COMPLETED' : 'SUBMITTED',
        round_count: negotiationState.round_count + 1,
        user_offer: body.amount ?? negotiationState.user_offer,
        events: [
          ...(negotiationState.events ?? []),
          {
            event_id: 99,
            event_type: body.event_type,
            amount: body.amount ?? null,
            data: body.data ?? {},
            occurred_at: '2026-11-27T11:00:00',
          },
        ],
      }
      return json({ duplicate: false, event: negotiationState.events.at(-1), negotiation: negotiationState })
    }
    if (path.endsWith('/transfer-director/negotiations/1/review')) return json(review)
    if (path.endsWith('/transfer-director/negotiations/1')) return json(negotiationState)
    if (path.endsWith('/transfer-director/negotiations')) return json({ items: [negotiationState], total: 1 })
    if (path.endsWith('/transfers')) return json(transferList)
    if (path.endsWith('/players')) return json({ items: [playerSummary], total: 1, coverage: {} })
    if (path.endsWith('/meta/saves')) return json({ items: meta.saves })
    return json({})
  })
  return calls
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => window.localStorage.clear())
})

test('AI 转会总监：导航入口、总览与数据能力提示', async ({ page }) => {
  await mockApi(page)
  await page.goto('/transfer-director?section=workbench')

  await expect(page.getByRole('heading', { name: 'AI 转会总监' })).toBeVisible()
  await expect(page.getByText('当前存档有 4 名球员')).toBeVisible()
  await expect(page.getByText('当前数据源不提供自动历史转会与成交金额')).toBeVisible()
  await expect(page.getByText('自动合同：可用（周薪/到期日）')).toBeVisible()
  await expect(page.getByRole('cell', { name: 'Luca Ferri' })).toBeVisible()
})

test('AI 买入报价：三套方案、预算提示、保存草稿与记录谈判', async ({ page }) => {
  const calls = await mockApi(page)
  await page.goto('/transfer-director?tab=purchase')

  await page.getByPlaceholder('搜索球员姓名后选择目标').fill('Mario')
  await page.getByRole('button', { name: '搜索', exact: true }).click()
  await page.locator('.picker-select').click()
  await page.getByText('Mario Bianchi · Kingsport City · ST').click()

  await page.getByRole('tab', { name: 'AI 买入报价' }).click()
  const purchasePanel = page.getByRole('tabpanel', { name: 'AI 买入报价' })
  await expect(purchasePanel.getByText('保守方案')).toBeVisible()
  await expect(purchasePanel.getByText('竞争性方案')).toBeVisible()
  await expect(purchasePanel.getByText('快速成交方案')).toBeVisible()
  await expect(purchasePanel.getByText('当前未获取可靠预算数据')).toBeVisible()
  await expect(purchasePanel.getByText('可比成交仅 0 笔')).toBeVisible()

  await purchasePanel.getByRole('button', { name: '保存草稿' }).first().click()
  await expect(page.getByText('报价草稿已保存')).toBeVisible()
  const saved = calls.find((item) => item.path.endsWith('/transfer-director/offers'))
  expect(saved?.body).toMatchObject({ direction: 'purchase', offer_type: 'conservative' })

  await purchasePanel.getByRole('button', { name: '记录谈判' }).first().click()
  await expect(page.getByText('谈判记录已创建')).toBeVisible()
  await expect(page.getByText('谈判详情')).toBeVisible()
})

test('出售方案与阵容缺口提示', async ({ page }) => {
  await mockApi(page)
  await page.goto('/transfer-director?tab=sale&instance_id=12')

  await page.getByRole('tab', { name: 'AI 出售报价' }).click()
  const salePanel = page.getByRole('tabpanel', { name: 'AI 出售报价' })
  await expect(salePanel.getByText('快速出售')).toBeVisible()
  await expect(salePanel.getByText('合理出售')).toBeVisible()
  await expect(salePanel.getByText('价值最大化')).toBeVisible()
  await expect(salePanel.getByText('同位置队友：2')).toBeVisible()
  await expect(salePanel.getByText('缺口风险：medium')).toBeVisible()
})

test('合同与条款：缺失字段显示未知而不是 0', async ({ page }) => {
  await mockApi(page)
  await page.goto('/transfer-director?tab=contract&instance_id=12')

  await page.getByRole('tab', { name: '合同与条款' }).click()
  const contractPanel = page.getByRole('tabpanel', { name: '合同与条款' })
  await expect(contractPanel.getByText('数据源不提供').first()).toBeVisible()
  await expect(contractPanel.getByText('没有可验证的条款记录；未知条款不等于不存在')).toBeVisible()
  await expect(contractPanel.getByText('当前存档没有该球员的转会记录')).toBeVisible()
})

test('桌面端 1280×720 无横向溢出', async ({ page }) => {
  await mockApi(page)
  await page.setViewportSize({ width: 1280, height: 720 })
  await page.goto('/transfer-director?section=workbench&instance_id=12')
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(1)
})

test('谈判记录：事件、幂等提示与复盘', async ({ page }) => {
  await mockApi(page)
  await page.goto('/transfer-director?tab=negotiation')

  await expect(page.getByRole('button', { name: /#1 · 买入/ })).toBeVisible()
  await page.getByRole('button', { name: /#1 · 买入/ }).click()
  await expect(page.getByText('谈判详情')).toBeVisible()
  await expect(page.getByRole('definition').filter({ hasText: 'DRAFT' })).toBeVisible()

  await page.getByPlaceholder('备注（可选）').fill('首轮试探')
  await page.getByRole('button', { name: '记录事件' }).click()
  await expect(page.getByText('已记录')).toBeVisible()
  await expect(page.getByText('对方反报价')).toBeVisible()

  await page.getByRole('button', { name: '生成复盘' }).click()
  await expect(page.getByText('当前历史谈判样本不足，暂不形成可靠规律')).toBeVisible()
  await expect(page.getByText('2.9%')).toBeVisible()
})

test('机会雷达：统计、表格、未知俱乐部与详情抽屉', async ({ page }) => {
  await mockApi(page)
  await page.goto('/transfer-director')

  await expect(page.locator('.radar-stat').filter({ hasText: '已挂牌' })).toBeVisible()
  await expect(page.getByText('当前数据源不提供离队意愿字段')).toBeVisible()
  await expect(page.getByRole('cell', { name: /Mario Bianchi/ })).toBeVisible()
  await expect(page.getByRole('cell', { name: '未知' }).first()).toBeVisible()

  await page.getByRole('cell', { name: /Mario Bianchi/ }).click()
  await expect(page.getByText('机会详情')).toBeVisible()
  await expect(page.getByText('当前没有可靠预算来源，财务可行性未计算')).toBeVisible()
  await expect(page.getByRole('button', { name: '在报价工作台打开' })).toBeVisible()
})

test('机会雷达：提醒可标记已读', async ({ page }) => {
  await mockApi(page)
  await page.goto('/transfer-director')
  await page.getByRole('button', { name: /提醒/ }).click()
  await expect(page.getByText('新增挂牌球员：Mario Bianchi')).toBeVisible()
  await page.getByText('新增挂牌球员：Mario Bianchi').click()
  await expect(page.getByText('转会提醒')).toBeVisible()
})

test('成交策略：案例、样本量提示与相似案例', async ({ page }) => {
  await mockApi(page)
  await page.goto('/transfer-director?section=workbench&instance_id=12')
  await page.getByRole('tab', { name: '成交策略' }).click()

  await expect(page.getByText('分期付款在成交中多次出现')).toBeVisible()
  await expect(page.getByText('样本不足（1 < 3），暂不归纳策略')).toBeVisible()
  await expect(page.getByText('Luca Ferri').first()).toBeVisible()
  await expect(page.getByText('位置组相同、年龄接近')).toBeVisible()
  await expect(page.getByText('82.5%')).toBeVisible()
})

test('租借报价：三套方案与未标记可租借提示', async ({ page }) => {
  await mockApi(page)
  await page.goto('/transfer-director?tab=loan&instance_id=12')

  await expect(page.getByText('低成本租借')).toBeVisible()
  await expect(page.getByText('发展型租借')).toBeVisible()
  await expect(page.getByText('租借后买断')).toBeVisible()
  await expect(page.getByText('游戏内未标记可租借，报价可能被拒绝').first()).toBeVisible()
  const buyoutCard = page.locator('.offer-card').filter({ hasText: '租借后买断' })
  await expect(buyoutCard).toContainText('3500 万')
})
