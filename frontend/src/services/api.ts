import type { AgentEvent, AgentInvocation, BackendHealth, ConversationInput, ConversationSummary, GenerationInput, ProjectPayload, RunStarted } from '../types/artflow'

export const API_BASE = import.meta.env.VITE_API_URL ?? (import.meta.env.DEV ? 'http://127.0.0.1:8000' : window.location.origin)

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const error = (await response.json().catch(() => null)) as { detail?: string } | null
    throw new Error(error?.detail ?? `请求失败 (${response.status})`)
  }
  return response.json() as Promise<T>
}

export function resolveAssetUrl(path: string): string {
  if (path.startsWith('http://') || path.startsWith('https://') || path.startsWith('blob:') || path.startsWith('data:')) return path
  return `${API_BASE}${path}`
}

function conversationForm(input: ConversationInput): FormData {
  const form = new FormData()
  form.set('message', input.message)
  form.set('world_context', input.worldContext)
  form.set('aspect_ratio', input.aspectRatio)
  input.files.forEach((file) => form.append('reference_images', file))
  return form
}

export const api = {
  async getHealth(): Promise<BackendHealth> { return parseResponse(await fetch(`${API_BASE}/api/health`)) },
  async listConversations(): Promise<ConversationSummary[]> {
    const payload = await parseResponse<{ items: ConversationSummary[] }>(await fetch(`${API_BASE}/api/conversations`))
    return payload.items
  },
  async createConversation(name: string): Promise<ProjectPayload> {
    return parseResponse(await fetch(`${API_BASE}/api/conversations`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }),
    }))
  },
  async deleteConversation(sessionId: string): Promise<void> {
    await parseResponse(await fetch(`${API_BASE}/api/conversations/${sessionId}`, { method: 'DELETE' }))
  },
  async getRecentProject(): Promise<ProjectPayload> { return parseResponse(await fetch(`${API_BASE}/api/projects/recent`)) },
  async getSession(sessionId: string): Promise<ProjectPayload> { return parseResponse(await fetch(`${API_BASE}/api/sessions/${sessionId}`)) },
  async getProject(projectId: string): Promise<ProjectPayload> { return parseResponse(await fetch(`${API_BASE}/api/projects/${projectId}`)) },
  async createTurn(sessionId: string, input: ConversationInput): Promise<RunStarted> {
    return parseResponse(await fetch(`${API_BASE}/api/sessions/${sessionId}/turns`, { method: 'POST', body: conversationForm(input) }))
  },
  async generate(projectId: string, input: GenerationInput): Promise<RunStarted> {
    const form = new FormData()
    form.set('prompt', input.prompt); form.set('world_context', input.worldContext); form.set('aspect_ratio', input.aspectRatio)
    form.set('image_count', String(input.imageCount)); input.files.forEach((file) => form.append('reference_images', file))
    return parseResponse(await fetch(`${API_BASE}/api/projects/${projectId}/generate`, { method: 'POST', body: form }))
  },
  async retryRun(runId: string): Promise<RunStarted> { return parseResponse(await fetch(`${API_BASE}/api/runs/${runId}/retry`, { method: 'POST' })) },
  async resetCompactionBreaker(sessionId: string): Promise<void> {
    await parseResponse(await fetch(`${API_BASE}/api/sessions/${sessionId}/context/compaction/reset`, { method: 'POST' }))
  },
  async getAgentLogs(runId: string): Promise<AgentInvocation[]> {
    const payload = await parseResponse<{ items: AgentInvocation[] }>(await fetch(`${API_BASE}/api/runs/${runId}/agent-logs`))
    return payload.items
  },
  watchRun(runId: string, after: number, handlers: { onEvent: (event: AgentEvent) => void; onComplete: () => void; onFailure: (message: string) => void }): () => void {
    const source = new EventSource(`${API_BASE}/api/runs/${runId}/events?after=${after}`)
    source.addEventListener('agent_event', (message) => handlers.onEvent(JSON.parse(message.data) as AgentEvent))
    source.addEventListener('run_completed', () => handlers.onComplete())
    source.addEventListener('run_failed', (message) => {
      const payload = JSON.parse(message.data) as { status: string }
      handlers.onFailure(`Agent 工作流${payload.status === 'failed' ? '执行失败' : '已中断'}`)
    })
    return () => source.close()
  },
  async saveCanvas(projectId: string, selectedImageId: string): Promise<void> {
    await parseResponse(await fetch(`${API_BASE}/api/projects/${projectId}/canvas`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ selected_image_id: selectedImageId }) }))
  },
  downloadUrl(imageId: string): string { return `${API_BASE}/api/images/${imageId}/download` },
}
