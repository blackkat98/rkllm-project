export interface User {
  id: number
  username: string
  email: string
  display_name: string | null
  role: 'admin' | 'user'
  is_active: boolean
  custom_instructions: string | null
  settings: { default_model_id?: number | null, theme?: string, [k: string]: unknown }
  created_at: string
  last_login_at: string | null
}

export interface ModelPublic {
  id: number
  display_name: string
  family: string
  max_context_len: number
  param_hint_b: number | null
  is_default: boolean
  loaded: boolean
}

export interface ModelAdmin {
  id: number
  filename: string
  display_name: string
  family: string
  max_context_len: number
  max_new_tokens: number
  sampling: Record<string, number>
  enabled: boolean
  keep_loaded: boolean
  sort_order: number
  status: 'ok' | 'missing' | 'too_large' | 'over_ram'
  status_detail: string | null
  file_size: number
  param_hint_b: number | null
  measured_ram_mb: number | null
  tokenizer_path: string | null
  scanned_at: string
  is_default: boolean
  loaded: boolean
  est_ram_mb: number
  warnings: string[]
}

export interface ModelPolicy {
  max_param_b: number
  max_file_gb: number
  max_ram_mb: number
  min_free_ram_mb: number
}

export interface Conversation {
  id: string
  title: string
  model_id: number | null
  system_prompt: string | null
  pinned: boolean
  archived: boolean
  created_at: string
  updated_at: string
  has_summary: boolean
}

export type MessageStatus = 'complete' | 'streaming' | 'aborted' | 'error'

export interface Message {
  id: number
  seq: number
  role: 'user' | 'assistant' | 'system'
  content: string
  model_id: number | null
  status: MessageStatus
  error: string | null
  prompt_tokens: number | null
  completion_tokens: number | null
  tok_per_s: number | null
  used_kv_cache: boolean
  created_at: string
}

export interface ConversationDetail extends Conversation {
  messages: Message[]
  summary: string | null
  summary_upto_seq: number
  generating: boolean
}

export interface EngineStatus {
  loaded_model_id: number | null
  loaded_model_name: string | null
  busy: boolean
  current_kind: string | null
  queue_length: number
  hot_conversation_id: string | null
}

export interface AppSettings {
  open_signup: boolean
  default_model_id: number | null
  auto_title: boolean
  global_system_prompt: string | null
}

export interface ApiKey {
  id: number
  name: string
  prefix: string
  created_at: string
  last_used_at: string | null
  key?: string
}

export type Phase = 'idle' | 'queued' | 'loading_model' | 'summarizing' | 'started' | 'streaming'
