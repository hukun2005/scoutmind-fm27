/** Types for §10 AI 决策中心 (`/agent/*`). */

import type { ConfidenceLevel } from './common'

/** One conversation of `GET /agent/conversations`. */
export interface Conversation {
  id: number
  title: string
  created_at: string | null
  message_count: number
}

/** `GET /agent/conversations` payload. */
export interface ConversationListResponse {
  items: Conversation[]
  total: number
}

/** Table payload of a structured answer section. */
export interface AnswerTable {
  columns: string[]
  rows: Array<Array<string | number | null>>
}

/** One structured section of an agent answer (`sample`, `stats`, `comparables`, `risks`, …). */
export interface AnswerSection {
  key: string
  title: string
  bullets?: string[]
  table?: AnswerTable
  /** Reliability class of this section: database fact, computed value, inference or unavailable data. */
  reliability?: string
}

/** Four-way reliability split required by the product spec (facts / computed / inferences / unavailable). */
export interface AnswerReliability {
  facts: string[]
  computed: string[]
  inferences: string[]
  unavailable: string[]
  rule?: string
}

/** One tool result a statement can be traced back to. */
export interface AnswerCitation {
  tool: string
  arguments: Record<string, unknown>
  summary: string
  warnings: string[]
}

/** Evidence row describing which tool produced a number. */
export interface AnswerEvidence {
  type: string
  label: string
  value: Record<string, unknown> | string | number | null
}

/** One player actually returned by the tools behind an answer; safe to link and follow. */
export interface AgentPlayerCard {
  instance_id: number
  name: string
  age: number | null
  position: string | null
  club: string | null
  ca: number | null
  pa: number | null
  market_value: number | null
  source_tool: string
}

/** Structured answer rendered by the agent screen. */
export interface AgentAnswer {
  conclusion: string
  sections: AnswerSection[]
  sample_size: number | null
  filters: Record<string, unknown>
  evidence: AnswerEvidence[]
  disclaimers: string[]
  confidence: ConfidenceLevel | null
  data_gaps: string[]
  mode: string
  /** Present when the backend surfaces non-fatal data problems for this answer. */
  warnings?: string[]
  /** Facts / computed / inferences / unavailable split added by the V2 assistant. */
  reliability?: AnswerReliability
  /** Tool results behind every number in the answer. */
  citations?: AnswerCitation[]
  /** Players that appeared in the tool results; empty when the answer is not player-centric. */
  player_cards?: AgentPlayerCard[]
}

/** One tool invocation exposed under 工具调用. */
export interface AgentToolCall {
  name: string
  arguments: Record<string, unknown>
  result_summary?: string | null
}

/** One message of `GET /agent/conversations/{id}/messages`. */
export interface AgentMessage {
  id: number
  role: 'user' | 'assistant' | string
  content: string
  created_at: string | null
  tool_calls: AgentToolCall[]
  answer: AgentAnswer | null
}

/** `GET /agent/conversations/{id}/messages` payload. */
export interface AgentMessageListResponse {
  items: AgentMessage[]
}

/** Request body of `POST /agent/conversations/{id}/messages`. */
export interface SendMessageRequest {
  question: string
  save_id?: number
  instance_id?: number
}

/** `POST /agent/conversations/{id}/messages` payload. */
export interface SendMessageResponse {
  message_id: number
  mode: string
  answer: AgentAnswer | null
  tool_calls: AgentToolCall[]
}
