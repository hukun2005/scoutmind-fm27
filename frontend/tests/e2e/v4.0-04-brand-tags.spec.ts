import { test, expect, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import path from 'node:path'

import {
  INTERNAL_TAG_KEYS,
  TAG_CATALOG,
  TAG_ALIASES,
  contractTag,
  isInternalTag,
  resolveTag,
  riskTag,
  visibleTags,
} from '../../src/utils/tags'

/**
 * V4.0-04 品牌与标签契约测试。
 *
 * 1. 标签目录：语义、去重、内部技术标签过滤；
 * 2. 品牌资源：SVG / PNG / ICO 存在，尺寸与格式正确，且形状来自同一路径；
 * 3. 运行时接入：导航品牌标识、Favicon、球员详情标签。
 *
 * 所有接口仍为本地 mock；真实 FM27 数据验收状态见报告。
 */

const brandDir = path.resolve(process.cwd(), 'public', 'brand')

function pngSize(file: string): { width: number; height: number } {
  const buffer = readFileSync(file)
  expect(buffer.subarray(1, 4).toString('ascii'), `${file} 不是 PNG`).toBe('PNG')
  return { width: buffer.readUInt32BE(16), height: buffer.readUInt32BE(20) }
}

function icoSizes(file: string): number[] {
  const buffer = readFileSync(file)
  const count = buffer.readUInt16LE(4)
  const sizes: number[] = []
  for (let index = 0; index < count; index += 1) {
    const width = buffer[6 + index * 16]
    sizes.push(width === 0 ? 256 : width)
  }
  return sizes.sort((left, right) => left - right)
}

test.describe('标签语义目录', () => {
  test('所有标签都有合法分类、语义色和唯一键', () => {
    const keys = new Set<string>()
    const labels = new Map<string, string>()
    for (const [key, tag] of Object.entries(TAG_CATALOG)) {
      expect(tag.key, `${key} 的 key 必须与目录键一致`).toBe(key)
      expect(['business', 'runtime', 'risk', 'internal']).toContain(tag.category)
      expect(['success', 'info', 'warning', 'danger', 'neutral', 'brand']).toContain(tag.tone)
      expect(tag.label.trim().length, `${key} 必须有中文名称`).toBeGreaterThan(0)
      expect(keys.has(tag.key), `${key} 重复`).toBe(false)
      keys.add(tag.key)
      // 同一名称只能对应一个语义，避免不同页面显示不一致。
      expect(labels.has(tag.label), `名称重复：${tag.label}`).toBe(false)
      labels.set(tag.label, key)
    }
  })

  test('内部技术标签默认隐藏，风险与待确认标签仍然可见', () => {
    const raw = ['scan_id', 'source_hash', 'database_version', '合同风险', '需要你确认']
    const visible = visibleTags(raw)
    expect(visible.map((tag) => tag.key)).toEqual(['contract_risk', 'needs_confirmation'])
    expect(visible.some((tag) => INTERNAL_TAG_KEYS.has(tag.key))).toBe(false)

    const diagnostics = visibleTags(raw, { diagnostics: true })
    expect(diagnostics.map((tag) => tag.key)).toContain('scan_id')
  })

  test('历史文案合并到统一名称，未知自由文本原样保留', () => {
    expect(resolveTag('核心培养')?.label).toBe('核心球员')
    expect(resolveTag('重点观察')?.label).toBe('值得观察')
    expect(resolveTag('出售候选')?.label).toBe('可出售')
    expect(resolveTag('引援候选')?.label).toBe('引援目标')
    expect(resolveTag('合同风险')?.tone).toBe('danger')
    expect(resolveTag('我的自定义标签')?.label).toBe('我的自定义标签')
    expect(resolveTag('我的自定义标签')?.tone).toBe('neutral')
  })

  test('标签去重后同一状态只出现一次', () => {
    expect(visibleTags(['重点关注', 'focus', '重点关注']).map((tag) => tag.key)).toEqual(['focus'])
  })

  test('风险与合同辅助函数输出统一语义', () => {
    expect(riskTag('high').label).toBe('高风险')
    expect(riskTag('medium').tone).toBe('warning')
    expect(riskTag('low').tone).toBe('success')
    expect(contractTag(3).key).toBe('risk_high')
    expect(contractTag(9).key).toBe('risk_medium')
    expect(contractTag(24).key).toBe('risk_low')
    expect(contractTag(null).key).toBe('unknown')
  })

  test('别名不得指向不存在的目录键', () => {
    for (const target of Object.values(TAG_ALIASES)) {
      expect(TAG_CATALOG[target], `别名目标不存在：${target}`).toBeTruthy()
    }
  })

  test('内部标签识别不依赖字符串前缀猜测', () => {
    expect(isInternalTag('scan_id')).toBe(true)
    expect(isInternalTag('scanning')).toBe(false)
    expect(isInternalTag('合同风险')).toBe(false)
  })
})

test.describe('品牌资源', () => {
  test('SVG 变体存在且使用同一 S 几何', () => {
    const files = [
      'scoutmind-mark.svg',
      'scoutmind-mark-dark.svg',
      'scoutmind-mark-mono.svg',
      'scoutmind-app-icon.svg',
    ]
    for (const name of files) {
      const content = readFileSync(path.join(brandDir, name), 'utf8')
      expect(content, `${name} 必须包含 viewBox`).toContain('viewBox="0 0 256 256"')
      expect(content, `${name} 必须使用统一路径`).toContain(
        'M174 64H108A34 34 0 0 0 108 132H148A34 34 0 0 1 148 200H82',
      )
    }
  })

  test('透明主标识与应用图标 PNG 尺寸正确', () => {
    for (const size of [64, 128, 256, 512, 1024]) {
      const mark = pngSize(path.join(brandDir, `scoutmind-mark-${size}.png`))
      expect(mark).toEqual({ width: size, height: size })
      const icon = pngSize(path.join(brandDir, `scoutmind-app-icon-${size}.png`))
      expect(icon).toEqual({ width: size, height: size })
    }
    expect(pngSize(path.join(brandDir, 'scoutmind-mark-dark-512.png'))).toEqual({ width: 512, height: 512 })
    expect(pngSize(path.join(brandDir, 'scoutmind-mark-mono-512.png'))).toEqual({ width: 512, height: 512 })
  })

  test('Windows ICO 包含 16–256 六个尺寸', () => {
    expect(icoSizes(path.resolve(process.cwd(), '..', 'desktop', 'build', 'icon.ico'))).toEqual([
      16, 32, 48, 64, 128, 256,
    ])
    expect(icoSizes(path.join(brandDir, 'scoutmind.ico'))).toEqual([16, 32, 48, 64, 128, 256])
    expect(icoSizes(path.resolve(process.cwd(), 'public', 'favicon.ico'))).toEqual([16, 32, 48])
  })

  test('Favicon PNG 为 32×32', () => {
    expect(pngSize(path.resolve(process.cwd(), 'public', 'favicon.png'))).toEqual({ width: 32, height: 32 })
  })

  test('Electron 构建图标与品牌资源一致', () => {
    const desktopIcon = pngSize(path.resolve(process.cwd(), '..', 'desktop', 'build', 'icon.png'))
    expect(desktopIcon).toEqual({ width: 512, height: 512 })
  })
})

/* ------------------------------------------------------------------ */
/* 运行时接入                                                          */
/* ------------------------------------------------------------------ */

const meta = {
  product: 'ScoutMind',
  version: '4.0.4',
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
      player_count: 1,
      snapshot_count: 2,
      transfer_count: 0,
      last_import_at: '2026-11-26T10:00:00Z',
    },
  ],
  data_sources: [],
  capabilities: { live_reader: true, save_parser: true, agent_llm: false, watchlist: true, transfer_intelligence: true },
  warnings: [],
}

const player = {
  instance_id: 77,
  player_id: 7,
  save_local_uid: 'UID-77',
  name: 'Alessandro Conti',
  age: 22,
  birth_date: null,
  nationality: 'Italy',
  position: 'AMC',
  position_group: 'MF',
  club: 'Northbridge United',
  club_id: 1,
  ca: 141,
  pa: 172,
  market_value: 28_000_000,
  wage: 45_000,
  contract_end: '2029-06-30',
  height_cm: 181,
  foot: 'right',
  observed_at: '2026-11-26T10:00:00Z',
  data_completeness: 0.86,
  source: 'fm27_live_reader',
  is_watched: false,
}

async function mockPlayers(page: Page): Promise<void> {
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url())
    const routePath = url.pathname
    const method = route.request().method()
    const json = (body: unknown, status = 200) => route.fulfill({ status, json: body })

    if (routePath.endsWith('/meta/bootstrap')) return json(meta)
    if (routePath.endsWith('/meta/saves')) return json({ items: meta.saves })
    if (routePath.endsWith('/system/onboarding')) {
      return json({ status: 'ready', data: { has_players: true }, summary: {}, actions: [] })
    }
    if (routePath.endsWith('/data-hub/status')) {
      return json({
        game: { running: true, detected: true, pid: 1, version: '27.1', exe_path: null, message: '', compatibility: 'supported', compatibility_message: '' },
        save: { id: 1, name: '测试存档', recognized: true, identity_status: 'verified', can_sync: true, message: '' },
        records: { players: 1, clubs: 1, transfers: 0, snapshots: 0 },
        last_sync: null,
        health: { status: 'ok', issues: [] },
        needs_confirmation: { unresolved_players: 0, identity_conflicts: 0, quarantined_rows: 0, total: 0 },
        repairs: {},
      })
    }
    if (routePath.endsWith('/players/facets')) {
      return json({
        total_players: 1,
        nationalities: [{ value: 'Italy', count: 1 }],
        leagues: [{ value: 'Premier Division', count: 1 }],
      })
    }
    if (routePath.endsWith('/clubs/search')) return json({ items: [], total: 0 })
    if (routePath.endsWith('/clubs')) {
      return json({
        items: [{ club_id: 1, name: 'Northbridge United', nation: 'England', league: 'Premier Division', reputation: 7000, is_user_club: true, currency: 'EUR' }],
        total: 1,
      })
    }
    if (routePath.endsWith('/watchlist/lists')) {
      return json({ items: [{ id: 1, name: '默认关注', count: 0, is_default: true }], total: 1 })
    }
    if (routePath.endsWith('/watchlist')) return json({ items: [], total: 0, lists: [] })
    if (routePath.endsWith('/players') && method === 'GET') {
      return json({ items: [player], total: 1, coverage: { ca: 1, pa: 1, market_value: 1 } })
    }
    if (/^\/api\/v1\/players\/\d+$/.test(routePath)) {
      return json({
        summary: player,
        attributes: [
          { key: 'passing', name: '传球', category: 'technical', value: 16 },
          { key: 'composure', name: '镇定', category: 'mental', value: 15 },
          { key: 'pace', name: '速度', category: 'physical', value: 14 },
        ],
        snapshot_count: 2,
        first_seen: '2026-10-01',
        last_seen: '2026-11-26',
        latest_snapshot_id: 1077,
        valuation: null,
        // 历史自由文本 + 内部技术字段混入，验证只展示业务语义。
        tags: ['重点观察', '合同风险', 'scan_id', 'source_hash'],
        notes: null,
      })
    }
    if (/^\/api\/v1\/players\/\d+\/status$/.test(routePath)) {
      return json({
        instance_id: player.instance_id,
        player_name: player.name,
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
    if (/^\/api\/v1\/players\/\d+\/(history|development)$/.test(routePath)) {
      return json({
        points: [],
        coverage: { points: null, attributes: null },
        summary: { snapshots: 2, ca_delta: null, market_value_delta: null, minutes_delta: null, window_start: null, window_end: null },
        records: [],
        attributions: [],
        data_gaps: [],
      })
    }
    if (routePath.endsWith('/transfers/valuation')) {
      return json({ low: null, mid: null, high: null, sample_size: 0, method: null, algorithm_version: 'test', confidence: null, insufficient_sample: true, factors: [], notes: [] })
    }
    return json({ items: [], total: 0 })
  })
}

test.describe('运行时品牌接入', () => {
  test('导航品牌标识与 favicon 正常加载', async ({ page, request }) => {
    await mockPlayers(page)
    await page.goto('/players')

    await expect(page.locator('[data-testid="app-logo"]').first()).toBeVisible()
    await expect(page.locator('link[rel="icon"][type="image/svg+xml"]')).toHaveAttribute('href', '/favicon.svg')

    const svg = await request.get('/favicon.svg')
    expect(svg.ok()).toBeTruthy()
    expect(svg.headers()['content-type']).toContain('image/svg+xml')

    const ico = await request.get('/favicon.ico')
    expect(ico.ok()).toBeTruthy()
  })

  test('球员详情只展示业务标签，内部技术标签被隐藏', async ({ page }) => {
    await mockPlayers(page)
    await page.goto('/players')

    await page.getByRole('button', { name: '查看球员档案' }).first().click()
    const drawer = page.locator('.pd-panel').first()
    await expect(drawer).toBeVisible()

    await expect(drawer.locator('.pd-tags .app-tag', { hasText: '值得观察' })).toBeVisible()
    await expect(drawer.locator('.pd-tags .app-tag', { hasText: '合同风险' })).toBeVisible()
    await expect(drawer.getByText('扫描编号')).toHaveCount(0)
    await expect(drawer.getByText('源指纹')).toHaveCount(0)
  })
})
