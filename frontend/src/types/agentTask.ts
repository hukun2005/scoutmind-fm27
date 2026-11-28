/** V3.3.3-01 Agent 任务（可恢复执行 + 人工确认）类型。 */

import type { AgentAnswer } from './agent'

export type AgentTaskStatus =
  | 'queued'
  | 'running'
  | 'waiting_approval'
  | 'paused'
  | 'completed'
  | 'failed'
  | 'cancelled'

export interface AgentTaskDiagnostics {
  task_type?: string | null
  provider_id?: string | null
  model_id?: string | null
  step_count?: number | null
  tool_call_count?: number | null
  truncated?: boolean
}

/** 任务报告沿用会话回答结构，额外带降级原因与诊断信息。 */
export interface AgentTaskReport extends AgentAnswer {
  llm_fallback?: string | null
  task?: AgentTaskDiagnostics
}

export interface AgentTask {
  id: string
  task_type: string
  user_goal: string
  status: AgentTaskStatus | string
  progress: number
  current_step: string | null
  mode: string | null
  provider_id: string | null
  model_id: string | null
  step_count: number
  tool_call_count: number
  pending_approvals: number
  report: AgentTaskReport | null
  error: { code: string; message: string } | null
  created_at: string | null
  updated_at: string | null
  started_at: string | null
  finished_at: string | null
}

export interface AgentTaskListResponse {
  items: AgentTask[]
  total: number
}

export interface AgentTaskEvent {
  id: number
  seq: number
  type: string
  payload: Record<string, unknown>
  created_at: string | null
}

export interface AgentTaskEventListResponse {
  items: AgentTaskEvent[]
  next: number
  total: number
}

export interface AgentApproval {
  id: string
  task_id: string
  approval_type: string
  operation_type: string
  payload: Record<string, unknown>
  reason: string
  status: string
  expires_at: string | null
  created_at: string | null
  decided_at: string | null
  consumed_at: string | null
}

export interface AgentApprovalListResponse {
  items: AgentApproval[]
  total: number
}
