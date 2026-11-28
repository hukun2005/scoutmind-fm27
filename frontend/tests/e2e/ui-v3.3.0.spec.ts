import { test, expect } from '@playwright/test'

/**
 * V3.3.0 全站 UI 简化回归：中文标题、空状态区分、系统设置与桌面分辨率。
 *
 * 全部接口使用本地 mock，不依赖后端与真实 FM27 数据；断言只覆盖界面契约。
 */

const meta = {
  product: 'ScoutMind',
  version: '3.3.0',
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
      player_count: 0,
      snapshot_count: 0,
      transfer_count: 0,
      last_import_at: null,
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

const emptyPlayers = { items: [], total: 0, page: 1, page_size: 25, note: '' }

const hubStatus = {
  game: {
    running: false,
    detected: true,
    pid: null,
    version: null,
    exe_path: null,
    message: '未检测到 Football Manager 27',
    compatibility: 'unknown',
    compatibility_message: '',
  },
  save: { id: 1, name: '测试存档', recognized: true, identity_status: 'verified', can_sync: true, message: '' },
  records: { players: 0, clubs: 0, transfers: 0, snapshots: 0 },
  last_sync: null,
  health: { status: 'empty', issues: [] },
  needs_confirmation: { unresolved_players: 0, identity_conflicts: 0, quarantined_rows: 0, total: 0 },
  repairs: {},
}

test.beforeEach(async ({ page }) => {
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname
    if (path.endsWith('/meta/bootstrap')) return route.fulfill({ json: meta })
    if (path.endsWith('/data-hub/status')) return route.fulfill({ json: hubStatus })
    if (path.endsWith('/clubs')) return route.fulfill({ json: { items: [], total: 0 } })
    if (path.endsWith('/players')) return route.fulfill({ json: emptyPlayers })
    if (path.endsWith('/imports')) return route.fulfill({ json: { items: [], total: 0, limit: 5, offset: 0 } })
    return route.fulfill({ json: {} })
  })
})

test('球员中心在没有数据时引导同步，而不是只显示空表', async ({ page }) => {
  await page.goto('/players')
  await expect(page.getByRole('heading', { name: '球员探索', level: 1 })).toBeVisible()
  await expect(page.getByText('还没有球员数据')).toBeVisible()
  await expect(page.getByRole('button', { name: '同步游戏数据' })).toBeVisible()
  await expect(page.getByPlaceholder('输入球员姓名')).toBeVisible()
})

test('球员中心在筛选无结果时提供清除条件，而不是提示没有数据', async ({ page }) => {
  await page.goto('/players')
  await page.getByPlaceholder('输入球员姓名').fill('不存在的人')
  await expect(page.getByText('没有找到符合条件的球员')).toBeVisible()
  await expect(page.getByRole('button', { name: '清除筛选条件' })).toBeVisible()
})

test('首页没有数据时给出明确入口', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: /欢迎回来/ })).toBeVisible()
  await expect(page.getByText('还没有球队数据')).toBeVisible()
})

test('系统设置默认只显示常用信息，内部配置折叠', async ({ page }) => {
  await page.goto('/settings')
  await expect(page.getByRole('heading', { name: '系统设置', level: 1 })).toBeVisible()
  await expect(page.getByText('数据存储位置')).toBeVisible()
  await expect(page.getByText('开发者选项（内部配置）')).toBeVisible()
  // 折叠状态下内部凭据输入框不可见。
  await expect(page.getByLabel('访问令牌')).toBeHidden()
  await page.getByText('开发者选项（内部配置）').click()
  await expect(page.getByLabel('访问令牌')).toBeVisible()
})

for (const [width, height] of [
  [1280, 720],
  [1366, 768],
  [1920, 1080],
] as const) {
  test(`${width}×${height} 下页面不出现横向溢出`, async ({ page }) => {
    await page.setViewportSize({ width, height })
    for (const path of ['/', '/players', '/settings']) {
      await page.goto(path)
      await page.waitForLoadState('networkidle')
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
      expect(overflow, `${path} 在 ${width}px 宽度出现横向滚动`).toBeLessThanOrEqual(1)
    }
  })
}
