/** §10 AI 决策中心 endpoints. */

import type {
  AgentMessageListResponse,
  Conversation,
  ConversationListResponse,
  SendMessageRequest,
  SendMessageResponse,
} from '../types/agent'
import { apiGet, apiPost } from './client'

/**
 * `GET /agent/conversations` — conversation list of one save.
 * @param saveId Save identifier.
 * @returns Paged conversations.
 */
export function listConversations(saveId?: number): Promise<ConversationListResponse> {
  return apiGet<ConversationListResponse>('/agent/conversations', { save_id: saveId })
}

/**
 * `POST /agent/conversations` — create a conversation.
 * @param title Optional title; the backend derives one when omitted.
 * @returns The created conversation.
 */
export function createConversation(title?: string): Promise<Conversation> {
  return apiPost<Conversation>('/agent/conversations', title ? { title } : {})
}

/**
 * `GET /agent/conversations/{id}/messages` — full transcript.
 * @param conversationId Conversation identifier.
 * @returns Messages with optional structured answers.
 */
export function listMessages(conversationId: number): Promise<AgentMessageListResponse> {
  return apiGet<AgentMessageListResponse>(`/agent/conversations/${conversationId}/messages`)
}

/**
 * `POST /agent/conversations/{id}/messages` — ask a question.
 * @param conversationId Conversation identifier.
 * @param body Question plus optional save/instance context.
 * @returns The assistant message with its structured answer and tool calls.
 */
export function sendMessage(conversationId: number, body: SendMessageRequest): Promise<SendMessageResponse> {
  return apiPost<SendMessageResponse>(`/agent/conversations/${conversationId}/messages`, body, {
    timeout: 120000,
  })
}
