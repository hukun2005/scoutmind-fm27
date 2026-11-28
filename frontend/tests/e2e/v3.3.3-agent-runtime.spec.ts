import { test, expect, type Page } from '@playwright/test'

/**
 * V3.3.3-01 Agent Runtime 前端契约：任务创建、进度、报告、确认卡片与刷新恢复。
 *
 * 全部接口使用本地 mock，不依赖后端与真实 FM27 数据；断言只覆盖界面契约，
 * 真实 Provider 与真实 FM27 验收状态见 docs/v333/V3.3.3-01-REPORT.md。
 */

const meta = {
  product: 'ScoutMind',
  version: '3.3.3',
  demo_mode: false,
  auth_required: false,
  active_save_id: 1,
  saves: [{ id: 1, name: '测试存档', game_version: '27.1', game_build: '26620374', created_at: '2026-11-01T00:00:00Z', is_active: true, player_count: 2, snapshot_count: 4, transfer_count: 2, last_import_at: '2026-11-26T10:00:00Z' }],
  data_sources: [],
  capabilities: { live_reader: true, save_parser: true, agent_llm: false, watchlist: true, transfer_intelligence: true },
  warnings: [],
}

function report(conclusion: string) {
  return {
    conclusion,
    sections: [],
    sample_size: 1,
    filters: {},
    evidence: [],
    disclaimers: ['结论是决策辅助，不是游戏内真实报价或官方市场价格。'],
    confidence: null,
    data_gaps: [],
    mode: 'deterministic',
    citations: [{ tool: 'squad_overview', arguments: {}, summary: '阵容 24 人', warnings: [] }],
    reliability: { facts: [], computed: ['阵容概览'], inferences: [], unavailable: [], rule: '四类分开呈现' },
    generated_at: '2026-11-28T10:00:00Z',
    task: { task_type: 'squad', provider_id: 'rule', model_id: null, step_count: 1, tool_call_count: 1, truncated: false },
  }
}

function task(overrides: Record<string, unknown> = {}) {
  return {
    id: 'task-1',
    task_type: 'squad',
    user_goal: '分析阵容短板并给出两条引援建议',
    status: 'running',
    progress: 40,
    current_step: '执行 squad_overview',
    mode: null,
    provider_id: 'rule',
    model_id: null,
    step_count: 1,
    tool_call_count: 1,
    pending_approvals: 0,
    report: null,
    error: null,
    created_at: '2026-11-28T10:00:00Z',
    updated_at: '2026-11-28T10:00:05Z',
    started_at: '2026-11-28T10:00:00Z',
    finished_at: null,
    ...overrides,
  }
}

const events = (taskId: string, status: 'running' | 'waiting' | 'completed') => {
  const base = [
    { id: 1, seq: 1, type: 'task_created', payload: { goal: '分析阵容短板' }, created_at: '2026-11-28T10:00:00Z' },
    { id: 2, seq: 2, type: 'task_started', payload: {}, created_at: '2026-11-28T10:00:01Z' },
    { id: 3, seq: 3, type: 'plan_created', payload: { steps: [{ tool: 'squad_overview' }] }, created_at: '2026-11-28T10:00:02Z' },
    { id: 4, seq: 4, type: 'step_started', payload: { tool: 'squad_overview' }, created_at: '2026-11-28T10:00:03Z' },
  ]
  if (status === 'waiting') {
    base.push({ id: 5, seq: 5, type: 'approval_required', payload: { approval_id: 'ap-1' }, created_at: '2026-11-28T10:00:04Z' })
  }
  if (status === 'completed') {
    base.push({ id: 5, seq: 5, type: 'tool_completed', payload: { tool: 'squad_overview', status: 'ok' }, created_at: '2026-11-28T10:00:04Z' })
    base.push({ id: 6, seq: 6, type: 'task_completed', payload: { mode: 'deterministic' }, created_at: '2026-11-28T10:00:05Z' })
  }
  return { items: base.map((item) => ({ ...item, task_id: taskId })), next: base.length, total: base.length }
}

async function mockApi(
  page: Page,
  state: { mode: 'instant' | 'approval' | 'restore' | 'switched'; approvals: number },
): Promise<void> {
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname
    const method = route.request().method()
    const json = (body: unknown) => route.fulfill({ json: body })

    if (path.endsWith('/meta/bootstrap')) return json(meta)
    if (path.endsWith('/meta/saves')) return json({ items: meta.saves })
    if (path.endsWith('/system/data-health')) return json({ status: 'ok', checks: [], summary: {} })
    if (path.endsWith('/system/onboarding')) return json({ status: 'ready', data: { has_players: true }, summary: {}, actions: [] })

    if (path.endsWith('/agent/tasks') && method === 'POST') {
      state.mode = state.mode === 'approval' ? 'approval' : state.mode
      return json(task({ status: 'running' }))
    }
    if (path.endsWith('/agent/tasks') && method === 'GET') {
      if (state.mode === 'switched') return json({ items: [], total: 0 })
      if (state.mode === 'restore') {
        return json({
          items: [
            task({
              status: 'waiting_approval',
              progress: 50,
              pending_approvals: 1,
              current_step: '等待确认：record_negotiation',
            }),
          ],
          total: 1,
        })
      }
      return json({ items: [task({ status: 'completed', progress: 100, report: report('阵容整体均衡，右后卫厚度不足。') })], total: 1 })
    }
    if (/\/agent\/tasks\/[^/]+$/.test(path) && method === 'GET') {
      if (state.mode === 'switched') {
        return route.fulfill({
          status: 404,
          json: { error: { code: 'AGENT_TASK_NOT_FOUND', message: '任务不存在' } },
        })
      }
      if (state.mode === 'restore') {
        return json(
          task({
            status: 'waiting_approval',
            progress: 50,
            pending_approvals: 1,
            current_step: '等待确认：record_negotiation',
          }),
        )
      }
      if (state.mode === 'approval' && state.approvals === 0) {
        return json(task({ status: 'waiting_approval', progress: 50, pending_approvals: 1, current_step: '等待确认：record_negotiation' }))
      }
      return json(
        task({
          status: 'completed',
          progress: 100,
          report: report(state.mode === 'approval' ? '已记录本次谈判。' : '阵容整体均衡，右后卫厚度不足。'),
          pending_approvals: 0,
        }),
      )
    }
    if (/\/agent\/tasks\/[^/]+\/events$/.test(path)) {
      const status = state.mode === 'instant' || state.approvals > 0 ? 'completed' : 'waiting'
      return json(events('task-1', status))
    }
    if (/\/agent\/tasks\/[^/]+\/approvals$/.test(path)) {
      const waiting = state.mode !== 'instant' && state.approvals === 0
      return json({
        items: waiting
          ? [
              {
                id: 'ap-1',
                task_id: 'task-1',
                approval_type: 'write_operation',
                operation_type: 'record_negotiation',
                payload: { tool: 'record_negotiation' },
                reason: '该操作会写入持久化记录，需要你确认',
                status: 'pending',
                expires_at: '2026-11-28T10:10:00Z',
                created_at: '2026-11-28T10:00:04Z',
                decided_at: null,
                consumed_at: null,
              },
            ]
          : [],
        total: waiting ? 1 : 0,
      })
    }
    if (/\/agent\/tasks\/[^/]+\/approvals\/[^/]+\/approve$/.test(path) && method === 'POST') {
      state.approvals += 1
      return json(task({ status: 'completed', progress: 100, report: report('已记录本次谈判。'), pending_approvals: 0 }))
    }
    if (/\/agent\/tasks\/[^/]+\/approvals\/[^/]+\/reject$/.test(path) && method === 'POST') {
      state.approvals += 1
      return json(task({ status: 'cancelled', progress: 50, pending_approvals: 0 }))
    }
    if (/\/agent\/tasks\/[^/]+\/cancel$/.test(path) && method === 'POST') {
      return json(task({ status: 'cancelled', pending_approvals: 0 }))
    }

    if (path.endsWith('/agent/conversations')) return json({ items: [], total: 0 })
    return json({})
  })
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.clear()
    window.localStorage.setItem('scoutmind.onboardingDismissed', '1')
  })
})

test('任务模式：创建后展示进度与结论报告', async ({ page }) => {
  const state = { mode: 'instant' as const, approvals: 0 }
  await mockApi(page, state)
  await page.goto('/agent')

  await expect(page.getByTestId('agent-task-current')).toBeHidden()
  await page.getByRole('textbox', { name: '任务目标' }).fill('分析阵容短板并给出两条引援建议')
  await page.getByRole('button', { name: '创建任务' }).click()

  await expect(page.getByTestId('agent-task-status')).toContainText('已完成')
  await expect(page.getByTestId('agent-task-report')).toContainText('阵容整体均衡，右后卫厚度不足。')
  await expect(page.getByTestId('agent-task-report')).toContainText('阵容 24 人')
})

test('确认卡片：写操作必须先确认，确认后任务完成', async ({ page }) => {
  const state = { mode: 'approval' as const, approvals: 0 }
  await mockApi(page, state)
  await page.goto('/agent')

  await page.getByRole('textbox', { name: '任务目标' }).fill('记录一次谈判')
  await page.getByRole('button', { name: '创建任务' }).click()

  await expect(page.getByTestId('agent-task-status')).toContainText('等待确认')
  const card = page.getByTestId('agent-task-approval')
  await expect(card).toContainText('记录谈判')
  await expect(card).toContainText('需要你确认')

  await page.getByRole('button', { name: '确认执行' }).click()
  await expect(page.getByTestId('agent-task-status')).toContainText('已完成')
  await expect(page.getByTestId('agent-task-approval')).toBeHidden()
})

test('刷新恢复：等待确认的任务在重新加载后仍可继续', async ({ page }) => {
  const state = { mode: 'restore' as const, approvals: 0 }
  await mockApi(page, state)
  await page.goto('/agent')

  await page.reload()
  await expect(page.getByTestId('agent-task-history')).toContainText('等待确认')
  await expect(page.getByTestId('agent-task-status')).toContainText('等待确认')
  await expect(page.getByTestId('agent-task-approval')).toContainText('该操作会写入持久化记录')
})

test('存档切换：旧任务不再展示，也不会残留上一存档的报告', async ({ page }) => {
  const state: { mode: 'instant' | 'approval' | 'restore' | 'switched'; approvals: number } = {
    mode: 'instant',
    approvals: 0,
  }
  await mockApi(page, state)
  await page.goto('/agent')

  await page.getByRole('textbox', { name: '任务目标' }).fill('分析阵容短板')
  await page.getByRole('button', { name: '创建任务' }).click()
  await expect(page.getByTestId('agent-task-report')).toBeVisible()

  state.mode = 'switched'
  await page.reload()
  await expect(page.getByTestId('agent-task-report')).toBeHidden()
  await expect(page.getByTestId('agent-task-current')).toBeHidden()
  await expect(page.getByTestId('agent-task-history')).toBeHidden()
})
