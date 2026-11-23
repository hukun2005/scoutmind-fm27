import { test, expect } from '@playwright/test'

const overview = {
  save_id: 1, total_snapshots: 120, unique_game_dates: 2, players: 10,
  canonical_groups: 10, resolved_auto: 8, resolved_manual: 1, needs_review: 1,
  excluded: 0, review_required: 0, quality_anomalies: 2,
  quality_error_groups: 0, quality_warning_groups: 1,
  conflict_types: [{ type: 'ability_changed', count: 1 }],
}
const queue = {
  items: [{
    id: 1, player_instance_id: 5, player_name: 'Test Player', player_uid: '123',
    game_date: '2026-07-14', status: 'needs_review', conflict: true,
    snapshot_count: 2, distinct_content_count: 2,
    conflict_types: ['ability_changed'], canonical_snapshot_id: null, reason: '同日内容冲突',
  }],
  total: 1, limit: 20, offset: 0,
}
const detail = {
  canonical: {
    ...queue.items[0], fm_save_id: 1,
  },
  snapshots: [
    { id: 11, observed_at: '2026-07-14T10:00:00', game_date: '2026-07-14', ca: 100, pa: 120, wage: null, market_value: null, contract_end: null, club_id: 1, club_name: 'Club A', position: 'ST', height_cm: 180, foot: 'right', source: 'fm27_live_reader', reader_version: '0.1.0', game_build: '26620374', attributes: [{ key: 'pace', name: 'Pace', name_zh: '速度', category: 'physical', value: 12 }] },
    { id: 12, observed_at: '2026-07-14T12:00:00', game_date: '2026-07-14', ca: 101, pa: 120, wage: null, market_value: null, contract_end: null, club_id: 1, club_name: 'Club A', position: 'ST', height_cm: 180, foot: 'right', source: 'fm27_live_reader', reader_version: '0.1.0', game_build: '26620374', attributes: [{ key: 'pace', name: 'Pace', name_zh: '速度', category: 'physical', value: 13 }] },
  ],
  timeline: [{ id: 1, game_date: '2026-07-14', status: 'needs_review', canonical_snapshot_id: null, snapshot: 2, reason: '冲突' }],
  suggestion: { risk_score: 60, priority: 'high', evidence_completeness: 1, recommended_snapshot_id: 12, reason: '建议，不入库', auto_applied: false },
}

test.beforeEach(async ({ page }) => {
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/data-quality/governance/overview')) return route.fulfill({ json: overview })
    if (path.endsWith('/data-quality/canonical/review-queue')) return route.fulfill({ json: queue })
    if (path.endsWith('/data-quality/canonical/1/history')) return route.fulfill({ json: { canonical_id: 1, status: 'needs_review', items: [] } })
    if (path.endsWith('/data-quality/canonical/1')) return route.fulfill({ json: detail })
    return route.fulfill({ json: {} })
  })
})

test('governance queue opens snapshot diff and suggestion', async ({ page }) => {
  await page.goto('/governance')
  await expect(page.getByRole('heading', { name: '数据治理中心' })).toBeVisible()
  await expect(page.getByText('Test Player')).toBeVisible()
  await page.locator('.sm-table__grid tbody').first().locator('tr').first().click()
  await expect(page.getByText('核心字段差异')).toBeVisible()
  await expect(page.getByText(/风险 60/)).toBeVisible()
  await expect(page.getByRole('button', { name: '提交审核' })).toBeVisible()
})

test('governance page supports empty queue state', async ({ page }) => {
  await page.route('**/api/v1/data-quality/canonical/review-queue**', (route) =>
    route.fulfill({ json: { items: [], total: 0, limit: 20, offset: 0 } }),
  )
  await page.goto('/governance')
  await expect(page.getByText('选择一组 canonical 冲突')).toBeVisible()
})
