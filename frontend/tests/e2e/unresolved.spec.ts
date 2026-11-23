import { test, expect } from '@playwright/test'

/** SM-119：自由球员待确认界面的列表、空态、失败、权限与人工确认流程。 */

const candidate = {
  id: 1,
  save_id: 1,
  status: 'pending',
  display_name: 'Free Agent One',
  normalized_name: 'free agent one',
  birth_date: '2003-07-01',
  nationality: 'England',
  position: 'ST',
  observation_count: 1,
  first_seen_at: '2026-11-23T10:00:00Z',
  last_seen_at: '2026-11-23T10:00:00Z',
  uid: {
    status: 'sentinel',
    reason: 'sentinel_uid',
    raw_uid: '4294967295',
    note: '原始 UID 只作为证据保存，不会写入 save_local_uid',
  },
  latest_observation: {
    observation_id: 11,
    scan_id: 'scan-1',
    row_index: 14,
    observed_at: '2026-11-23T10:00:00Z',
    game_date: '2026-11-01',
    ca: 118,
    pa: 132,
    club_name: null,
    contract_end: null,
  },
  resolution: null,
  dismissal: null,
  suggestions_are_advisory: true,
}

const list = {
  items: [candidate],
  total: 1,
  page: 1,
  page_size: 20,
  counts: { pending: 1, review_required: 0, resolved: 0, dismissed: 0 },
  note: '这些球员没有可用身份；确认之前不进入任何正式统计',
}

const detail = {
  ...candidate,
  evidence_summary: { scan_id: 'scan-1', row_index: 14, identity: { uid_status: 'sentinel' } },
  suggestions: {
    player_matches: [
      {
        kind: 'player_instance',
        player_id: 9,
        player_instance_id: 9,
        name: 'Free Agent One',
        birth_date: '2003-07-01',
        save_local_uid: '1001',
        confidence: 0.9,
        reasons: ['姓名一致', '出生日期一致'],
      },
    ],
    sibling_candidates: [],
    note: '以上只是匹配建议，不会自动合并；确认后才建立身份关联',
  },
  history: [],
  retention: '观察与审计记录永久保留；忽略候选不会删除任何观察',
}

const observations = {
  candidate_id: 1,
  items: [
    {
      id: 11,
      scan_id: 'scan-1',
      row_index: 14,
      observed_at: '2026-11-23T10:00:00Z',
      game_date: '2026-11-01',
      raw_uid: '4294967295',
      uid_status: 'sentinel',
      name: 'Free Agent One',
      birth_date: '2003-07-01',
      nationality: 'England',
      position: 'ST',
      ca: 118,
      pa: 132,
      club_name: null,
      contract_end: null,
      import_job_id: 3,
      payload_hash: 'a'.repeat(64),
    },
  ],
  total: 1,
  page: 1,
  page_size: 20,
  import_job_ids: [3],
}

const resolveResponse = {
  id: 1,
  status: 'resolved',
  resolution_method: 'manual_attached',
  player_id: 9,
  player_instance_id: 9,
  resolved_at: '2026-11-23T11:00:00Z',
  evidence: { candidate_id: 1 },
  audit_action_id: 5,
  note: '身份关联已写入，原始观察历史保留',
}

const errorBody = (code: string, message: string) => ({ error: { code, message } })

test.beforeEach(async ({ page }) => {
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (path.endsWith('/unresolved-players/1/resolve')) {
      return route.fulfill({ json: resolveResponse })
    }
    if (path.endsWith('/unresolved-players/1/dismiss')) {
      return route.fulfill({
        json: {
          id: 1,
          status: 'dismissed',
          dismiss_reason: '不是目标球员',
          dismissed_at: '2026-11-23T11:00:00Z',
          observations_kept: 1,
          audit_action_id: 6,
        },
      })
    }
    if (path.endsWith('/unresolved-players/1/observations')) {
      return route.fulfill({ json: observations })
    }
    if (path.endsWith('/unresolved-players/1')) {
      return route.fulfill({ json: detail })
    }
    if (path.endsWith('/unresolved-players')) {
      return route.fulfill({ json: list })
    }
    return route.fulfill({ json: {} })
  })
})

test('list shows candidates with raw UID evidence', async ({ page }) => {
  await page.goto('/unresolved')
  await expect(page.getByRole('heading', { name: '自由球员待确认' })).toBeVisible()
  await expect(page.getByText('Free Agent One')).toBeVisible()
  await expect(page.getByText('上游哨兵 0xFFFFFFFF（4294967295）')).toBeVisible()
  await expect(page.locator('.sm-table__grid tbody tr').first()).toContainText('待确认')
})

test('empty list shows an actionable empty state', async ({ page }) => {
  await page.route('**/api/v1/unresolved-players**', (route) =>
    route.fulfill({
      json: {
        items: [],
        total: 0,
        page: 1,
        page_size: 20,
        counts: { pending: 0, review_required: 0, resolved: 0, dismissed: 0 },
        note: '这些球员没有可用身份；确认之前不进入任何正式统计',
      },
    }),
  )
  await page.goto('/unresolved')
  await expect(page.getByText('暂无待确认的自由球员')).toBeVisible()
})

test('load failure shows the normalized error and a retry action', async ({ page }) => {
  await page.route('**/api/v1/unresolved-players**', (route) =>
    route.fulfill({ status: 500, json: errorBody('internal_error', '后端处理失败') }),
  )
  await page.goto('/unresolved')
  await expect(page.getByText('加载失败')).toBeVisible()
  await expect(page.getByText('后端处理失败')).toBeVisible()
  await expect(page.getByRole('button', { name: '重试' }).first()).toBeVisible()
})

test('unauthorized response explains the missing token', async ({ page }) => {
  await page.route('**/api/v1/unresolved-players**', (route) =>
    route.fulfill({ status: 401, json: errorBody('unauthorized', '缺少或错误的本地授权令牌') }),
  )
  await page.goto('/unresolved')
  await expect(page.getByText('加载失败')).toBeVisible()
  await expect(page.getByText(/SCOUTMIND_API_TOKEN/).first()).toBeVisible()
})

test('manual confirmation links the candidate after an explicit second confirmation', async ({ page }) => {
  await page.goto('/unresolved')
  await page.locator('.sm-table__grid tbody').first().locator('tr').first().click()
  await expect(page.getByText('匹配建议（建议，不是事实）')).toBeVisible()

  await page.locator('.unresolved__suggestions').getByRole('button', { name: '确认关联' }).click()
  await expect(page.locator('.el-message-box')).toBeVisible()
  await page.locator('.el-message-box').getByRole('button', { name: '确认关联' }).click()

  await expect(page.getByText('身份关联已写入，原始观察历史保留')).toBeVisible()
})

test('duplicate confirmation is rejected without a second link', async ({ page }) => {
  await page.route('**/api/v1/unresolved-players/1/resolve', (route) =>
    route.fulfill({ status: 409, json: errorBody('unresolved_already_decided', '候选已处理') }),
  )
  await page.goto('/unresolved')
  await page.locator('.sm-table__grid tbody').first().locator('tr').first().click()
  await page.locator('.unresolved__suggestions').getByRole('button', { name: '确认关联' }).click()
  await page.locator('.el-message-box').getByRole('button', { name: '确认关联' }).click()
  await expect(page.getByText('该候选已经处理过，不能重复确认。')).toBeVisible()
})

test('candidate from another save is reported as not found', async ({ page }) => {
  await page.route('**/api/v1/unresolved-players/1', (route) =>
    route.fulfill({ status: 404, json: errorBody('unresolved_not_found', '待确认候选不存在') }),
  )
  await page.goto('/unresolved')
  await page.locator('.sm-table__grid tbody').first().locator('tr').first().click()
  await expect(page.getByText('无法查看该候选')).toBeVisible()
  await expect(page.getByText('待确认候选不存在').first()).toBeVisible()
})
