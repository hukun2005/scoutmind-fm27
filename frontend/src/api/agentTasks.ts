/** V3.3.3-01 Agent 任务 API：创建、查询、事件、确认与取消。 */

import type {
  AgentApprovalListResponse,
  AgentTask,
  AgentTaskEventListResponse,
  AgentTaskListResponse,
} from '../types/agentTask'
import { apiGet, apiPost } from './client'

export interface AgentTaskCreateBody {
  goal: string
  task_type?: string
  conversation_id?: number
}

/** `POST /agent/tasks` — 创建并异步执行一个 Agent 任务。 */
export function createAgentTask(body: AgentTaskCreateBody): Promise<AgentTask> {
  return apiPost<AgentTask>('/agent/tasks', body)
}

/** `GET /agent/tasks` — 当前存档任务列表。 */
export function listAgentTasks(params?: { status?: string; limit?: number; offset?: number }): Promise<AgentTaskListResponse> {
  return apiGet<AgentTaskListResponse>('/agent/tasks', params)
}

/** `GET /agent/tasks/{id}` — 任务详情。 */
export function getAgentTask(taskId: string): Promise<AgentTask> {
  return apiGet<AgentTask>(`/agent/tasks/${taskId}`)
}

/** `GET /agent/tasks/{id}/events` — 按游标重放事件。 */
export function listAgentTaskEvents(taskId: string, after = 0): Promise<AgentTaskEventListResponse> {
  return apiGet<AgentTaskEventListResponse>(`/agent/tasks/${taskId}/events`, { after })
}

/** `GET /agent/tasks/{id}/approvals` — 待确认操作。 */
export function listAgentTaskApprovals(taskId: string): Promise<AgentApprovalListResponse> {
  return apiGet<AgentApprovalListResponse>(`/agent/tasks/${taskId}/approvals`)
}

/** `POST /agent/tasks/{id}/approvals/{approvalId}/approve` — 确认并继续执行。 */
export function approveAgentTask(taskId: string, approvalId: string): Promise<AgentTask> {
  return apiPost<AgentTask>(`/agent/tasks/${taskId}/approvals/${approvalId}/approve`, {}, { timeout: 120000 })
}

/** `POST /agent/tasks/{id}/approvals/{approvalId}/reject` — 拒绝并安全结束。 */
export function rejectAgentTask(taskId: string, approvalId: string): Promise<AgentTask> {
  return apiPost<AgentTask>(`/agent/tasks/${taskId}/approvals/${approvalId}/reject`, {}, { timeout: 120000 })
}

/** `POST /agent/tasks/{id}/cancel` — 取消任务（幂等）。 */
export function cancelAgentTask(taskId: string): Promise<AgentTask> {
  return apiPost<AgentTask>(`/agent/tasks/${taskId}/cancel`, {})
}
