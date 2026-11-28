import { test, expect, type Page } from '@playwright/test'

/**
 * V4.1 主题一致性契约：
 *   - 设计令牌为 Premium Light（品牌蓝 #315FCE、浅色画布）；
 *   - 侧栏 / 顶栏 / 内容区为浅色表面；
 *   - 全部路由在切换后不出现深色背景块；
 *   - 下拉浮层保持浅色。
 *
 * 接口使用本地 mock，只验证视觉契约，不依赖后端与真实 FM27 数据。
 */

const meta = {
  product: 'ScoutMind',
  version: '4.1.0',
  demo_mode: false,
  auth_required: false,
  active_save_id: 1,
  saves: [],
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

const ROUTES = [
  '/',
  '/players',
  '/players/12',
  '/compare',
  '/watchlist',
  '/squad',
  '/scouting',
  '/recruitment',
  '/development',
  '/performance',
  '/transfers',
  '/agent',
  '/director',
  '/transfer-director',
  '/identity',
  '/identity-center',
  '/save-identity',
  '/unresolved',
  '/data',
  '/governance',
  '/settings',
]

async function mockApi(page: Page): Promise<void> {
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname
    const json = (body: unknown) => route.fulfill({ json: body })

    if (path.endsWith('/meta/bootstrap')) return json(meta)
    if (path.endsWith('/players')) return json({ items: [], total: 0, coverage: {} })
    if (path.endsWith('/transfers')) return json({ items: [], total: 0 })
    if (path.endsWith('/imports')) return json({ items: [], total: 0, limit: 5, offset: 0 })
    if (path.endsWith('/clubs/search')) return json({ items: [], total: 0 })
    return json({})
  })
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => window.localStorage.clear())
  await mockApi(page)
})

test('设计令牌为 Premium Light：品牌蓝 #315FCE 与浅色画布', async ({ page }) => {
  await page.goto('/')

  const tokens = await page.evaluate(() => {
    const style = getComputedStyle(document.documentElement)
    return {
      accent: style.getPropertyValue('--sm-accent-blue').trim(),
      bg: style.getPropertyValue('--sm-bg-primary').trim(),
      text: style.getPropertyValue('--sm-text-primary').trim(),
      border: style.getPropertyValue('--sm-border-subtle').trim(),
      danger: style.getPropertyValue('--sm-status-danger').trim(),
      colorScheme: style.colorScheme,
    }
  })

  expect(tokens.accent).toBe('#315fce')
  expect(tokens.bg).toBe('#f5f7fa')
  expect(tokens.text).toBe('#172033')
  expect(tokens.border).toBe('#e5eaf1')
  expect(tokens.danger).toBe('#c2414b')
  expect(tokens.colorScheme).toContain('light')
})

test('应用外壳：侧栏与顶栏为白色表面，画布为浅灰', async ({ page }) => {
  await page.goto('/')

  const body = await page.evaluate(() => getComputedStyle(document.body).backgroundColor)
  expect(body).toBe('rgb(245, 247, 250)')

  await expect(page.locator('.sidebar')).toHaveCSS('background-color', 'rgb(255, 255, 255)')
  await expect(page.locator('.topbar')).toHaveCSS('background-color', 'rgb(255, 255, 255)')
})

test('用户菜单浮层为浅色，不出现深色下拉', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: '用户菜单' }).click()

  const menu = page.locator('.el-dropdown-menu')
  await expect(menu).toBeVisible()
  await expect(menu).toHaveCSS('background-color', 'rgb(255, 255, 255)')
})

test('全部路由切换后不出现深色背景块', async ({ page }) => {
  for (const path of ROUTES) {
    await page.goto(path)
    await page.waitForTimeout(120)

    const darkBlocks = await page.evaluate(() => {
      const parse = (value: string): [number, number, number, number] | null => {
        const match = value.match(/rgba?\(\s*(\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?/)
        if (!match) return null
        const alpha = match[4] === undefined ? 1 : Number(match[4])
        return [Number(match[1]), Number(match[2]), Number(match[3]), alpha]
      }
      const offenders: string[] = []
      document.querySelectorAll('.shell *').forEach((node) => {
        const element = node as HTMLElement
        const rect = element.getBoundingClientRect()
        if (rect.width < 24 || rect.height < 24) return
        const style = getComputedStyle(element)
        // 渐变文字用深色 background 裁剪到文字，不是深色面板。
        if (style.backgroundClip === 'text' || style.webkitBackgroundClip === 'text') return
        const rgba = parse(style.backgroundColor)
        if (!rgba) return
        const [r, g, b, alpha] = rgba
        if (alpha < 0.2) return
        if (r < 70 && g < 70 && b < 70) {
          offenders.push(`${element.className || element.tagName} rgb(${r},${g},${b})`)
        }
      })
      return offenders.slice(0, 5)
    })

    expect(darkBlocks, `路由 ${path} 出现深色背景块：${darkBlocks.join(' | ')}`).toEqual([])
  }
})
