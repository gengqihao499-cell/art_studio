export type ProjectStatus = 'ready' | 'generating' | 'completed' | 'failed'

export interface Project {
  id: string
  name: string
  user_request: string
  world_context: string
  aspect_ratio: string
  image_count: number
  reference_images: string[]
  selected_image_id: string | null
  status: ProjectStatus
  created_at: string
  updated_at: string
}

export interface Session { id: string; project_id: string; title: string; created_at: string; updated_at: string }

export interface AgentRun {
  id: string
  project_id: string
  session_id?: string
  turn_id?: string
  status: string
  backend: string
  retry_count: number
  error: string | null
  started_at: string
  completed_at: string | null
}

export interface BackendHealth {
  status: string
  orchestrator: string
  image_backend: 'mock' | 'comfyui' | 'qwen_image'
  image_backend_health: { available: boolean; base_url?: string; mode?: string; model?: string; error?: string }
  agent_backend: 'mock' | 'qwen'
  agent_model: string
  agent_backend_health: { available: boolean; mode?: string; model?: string; error?: string }
  database: string
  context_engine?: Record<string, unknown>
  demo_mode: boolean
}

export interface ContextCompactionStatus {
  consecutive_failures: number
  circuit_state: 'closed' | 'open'
  last_error: string
  last_attempt_at: string | null
  last_success_at: string | null
  snapshot_version: number
}

export interface ContextStatus {
  claude: {
    path: string
    hash: string
    project_hash: string
    version: number
    auto_managed: boolean
  }
  claude_preview: string
  compaction: ContextCompactionStatus | null
  layers: Record<string, Record<string, unknown>>
  budget?: {
    estimated_tokens?: number
    max_tokens?: number
    usage_ratio?: number
    raw_conversation_tokens?: number
  }
  retrieval?: { backend?: string; embedding_backend?: string; count?: number; error?: string }
  artifact_count?: number
  memory_item_count?: number
  storage: {
    blob: { backend: string }
    vector: { backend: string }
    embedding: { backend: string; dimension: number }
  }
}

export interface ConversationSummary {
  session_id: string
  project_id: string
  title: string
  preview: string
  status: ProjectStatus
  turn_count: number
  image_count: number
  created_at: string
  updated_at: string
}

export interface RunStarted { run_id: string; turn_id?: string; status: 'running'; resumed_from_checkpoint?: boolean }

export interface CandidateImage {
  id: string
  project_id: string
  run_id: string
  label: string
  title: string
  variation: string
  public_url: string
  file_path: string
  prompt: string
  backend: string
  model: string
  negative_prompt: string
  loras: Array<{ id: string; filename: string; weight: number; trigger_word: string }>
  variant_key: 'constraint' | 'composition' | 'silhouette' | 'palette'
  prompt_id: string | null
  workflow_template: string | null
  workflow_path: string | null
  generation_params: Record<string, unknown>
  seed: number
  width: number
  height: number
  parent_image_id: string | null
  source_turn_id: string | null
  version_number: number
  created_at: string
}

export interface AgentEvent {
  id: string
  event_type: string
  agent: string
  stage: string
  status: 'completed' | 'passed' | 'rejected' | 'running' | 'waiting' | 'failed' | 'skipped'
  attempt: number
  title: string
  summary: string
  sequence: number
  created_at: string
  payload: Record<string, unknown>
}

export interface AgentInvocation {
  id: string
  run_id: string
  turn_id: string | null
  agent: string
  status: 'completed' | 'failed' | 'skipped'
  attempt: number
  model: string
  reason: string
  input_summary: string
  output_summary: string
  structured_output: Record<string, unknown>
  latency_ms: number
  input_tokens: number
  output_tokens: number
  error_message: string
  started_at: string
}

export interface Message {
  id: string
  turn_id?: string | null
  role: 'assistant' | 'user'
  content: string
  attachments: string[]
  metadata: Record<string, unknown>
  created_at: string
}

export interface ConversationTurn {
  id: string
  sequence: number
  run_id: string
  status: string
  route: string
  parent_image_id: string | null
  requested_count: number
  created_at: string
}

export interface MemoryMeta { summarized_through_sequence: number; source_message_count: number; updated_at: string }

export interface ProjectPayload {
  project: Project
  session: Session | null
  run: AgentRun | null
  images: CandidateImage[]
  events: AgentEvent[]
  messages: Message[]
  turns: ConversationTurn[]
  memory: Record<string, unknown>
  memory_meta: MemoryMeta | null
  agent_invocations: AgentInvocation[]
  context_status: ContextStatus | null
}

export interface ConversationInput { message: string; worldContext: string; aspectRatio: string; files: File[] }
export interface GenerationInput { prompt: string; worldContext: string; aspectRatio: string; imageCount: number; files: File[] }
