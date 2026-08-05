import { useCallback, useEffect, useRef, useState } from 'react'
import { AgentInspector } from './components/AgentInspector'
import { AppHeader } from './components/AppHeader'
import { ArtCanvas } from './components/ArtCanvas'
import { ConversationPanel } from './components/ConversationPanel'
import { ConversationSidebar } from './components/ConversationSidebar'
import { HomeScreen } from './components/HomeScreen'
import { Icon } from './components/Icon'
import { QwenConfigDialog } from './components/QwenConfigDialog'
import { api } from './services/api'
import type { BackendHealth, ConversationInput, ConversationSummary, ProjectPayload } from './types/artflow'

function titleFromMessage(message: string) {
  const title = message.replace(/\s+/g, ' ').replace(/[。！？!?，,；;：:]$/u, '').trim()
  return title.length > 24 ? `${title.slice(0, 24)}…` : title || '未命名对话'
}

export default function App() {
  const [data, setData] = useState<ProjectPayload | null>(null)
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [health, setHealth] = useState<BackendHealth | null>(null)
  const [loading, setLoading] = useState(true)
  const [openingSessionId, setOpeningSessionId] = useState<string | null>(null)
  const [isGenerating, setIsGenerating] = useState(false)
  const [configOpen, setConfigOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const closeStream = useRef<null | (() => void)>(null)
  const activeProjectId = useRef<string | null>(null)

  const refreshConversations = useCallback(async () => {
    setConversations(await api.listConversations())
  }, [])

  const connectRun = useCallback((projectId: string, runId: string, after = 0) => {
    closeStream.current?.()
    setIsGenerating(true)
    closeStream.current = api.watchRun(runId, after, {
      onEvent: (event) => {
        if (activeProjectId.current !== projectId) return
        setData((current) => !current || current.project.id !== projectId || current.events.some((item) => item.id === event.id) ? current : { ...current, events: [...current.events, event] })
        void api.getAgentLogs(runId).then((items) => setData((current) => current?.project.id === projectId ? { ...current, agent_invocations: items } : current)).catch(() => undefined)
      },
      onComplete: async () => {
        closeStream.current?.(); closeStream.current = null
        try {
          const [payload] = await Promise.all([api.getProject(projectId), refreshConversations()])
          if (activeProjectId.current === projectId) setData(payload)
        } catch (reason) {
          if (activeProjectId.current === projectId) setError(reason instanceof Error ? reason.message : '无法读取本轮结果')
        } finally {
          if (activeProjectId.current === projectId) setIsGenerating(false)
        }
      },
      onFailure: async (message) => {
        closeStream.current?.(); closeStream.current = null
        try {
          const payload = await api.getProject(projectId)
          if (activeProjectId.current === projectId) { setData(payload); setError(payload.run?.error || message) }
          await refreshConversations()
        } catch { if (activeProjectId.current === projectId) setError(message) }
        finally { if (activeProjectId.current === projectId) setIsGenerating(false) }
      },
    })
  }, [refreshConversations])

  useEffect(() => {
    let active = true
    Promise.all([api.listConversations(), api.getHealth()]).then(([items, backend]) => {
      if (!active) return
      setConversations(items); setHealth(backend)
      // Deliberately do not open the most recent conversation. Every page load
      // begins on the neutral home screen until the user chooses one.
    }).catch((reason: Error) => { if (active) setError(reason.message) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false; closeStream.current?.() }
  }, [])

  const handleNew = () => {
    closeStream.current?.(); closeStream.current = null
    activeProjectId.current = null
    setData(null); setIsGenerating(false); setError(null)
  }

  const handleOpen = async (item: ConversationSummary) => {
    if (openingSessionId) return
    closeStream.current?.(); closeStream.current = null
    setOpeningSessionId(item.session_id); setError(null)
    activeProjectId.current = item.project_id
    try {
      const payload = await api.getSession(item.session_id)
      setData(payload)
      if (payload.run?.status === 'running') connectRun(payload.project.id, payload.run.id, payload.events.at(-1)?.sequence ?? 0)
      else setIsGenerating(false)
    } catch (reason) {
      activeProjectId.current = null
      setData(null); setError(reason instanceof Error ? reason.message : '无法打开对话')
    } finally { setOpeningSessionId(null) }
  }

  const handleDelete = async (item: ConversationSummary) => {
    if (data?.session?.id === item.session_id) handleNew()
    await api.deleteConversation(item.session_id)
    await refreshConversations()
  }

  const handleSend = async (input: ConversationInput) => {
    if (isGenerating) return
    setError(null); setIsGenerating(true)
    let target = data
    try {
      if (!target) {
        target = await api.createConversation(titleFromMessage(input.message))
        activeProjectId.current = target.project.id
        setData(target)
        await refreshConversations()
      }
      if (!target.session) throw new Error('对话会话创建失败')
      const targetProjectId = target.project.id
      const optimisticId = `optimistic-${Date.now()}`
      const optimisticMessage = { id: optimisticId, role: 'user' as const, content: input.message, attachments: [], metadata: {}, created_at: new Date().toISOString() }
      setData((current) => current && current.project.id === targetProjectId ? { ...current, events: [], agent_invocations: [], messages: [...current.messages, optimisticMessage] } : current)
      try {
        const run = await api.createTurn(target.session.id, input)
        const projectId = target.project.id
        setData((current) => current?.project.id === projectId ? { ...current, run: { id: run.run_id, project_id: projectId, session_id: current.session?.id, turn_id: run.turn_id, status: 'running', backend: `langgraph+${health?.image_backend ?? 'mock'}`, retry_count: 0, error: null, started_at: new Date().toISOString(), completed_at: null } } : current)
        await refreshConversations()
        connectRun(projectId, run.run_id)
      } catch (reason) {
        setData((current) => current && current.project.id === targetProjectId ? { ...current, messages: current.messages.filter((item) => item.id !== optimisticId) } : current)
        throw reason
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '无法发送本轮消息')
      setIsGenerating(false)
    }
  }

  const handleRetry = async () => {
    if (!data?.run || data.run.status !== 'failed' || isGenerating) return
    setError(null); setIsGenerating(true)
    try { await api.retryRun(data.run.id); connectRun(data.project.id, data.run.id, data.events.at(-1)?.sequence ?? 0) }
    catch (reason) { setError(reason instanceof Error ? reason.message : '无法恢复任务'); setIsGenerating(false) }
  }

  const handleResetCompaction = async () => {
    if (!data?.session) return
    setError(null)
    try {
      await api.resetCompactionBreaker(data.session.id)
      const payload = await api.getProject(data.project.id)
      setData(payload)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '无法复位 Auto-compact 熔断器')
    }
  }

  const handleSelect = (imageId: string) => {
    if (!data) return
    setData((current) => current ? { ...current, project: { ...current.project, selected_image_id: imageId, updated_at: new Date().toISOString() } } : current)
    void api.saveCanvas(data.project.id, imageId).catch((reason: Error) => setError(reason.message))
  }

  if (loading) return <div className="startup-screen"><span className="startup-mark"><span /><span /><span /></span><p>正在打开 ArtFlow Studio</p></div>
  if (!health) return <div className="fatal-screen"><Icon name="image" size={32} /><h1>无法连接工作室</h1><p>{error ?? '请确认本地后端已经启动。'}</p><button type="button" onClick={() => window.location.reload()}>重新连接</button></div>

  const backend = health.image_backend
  return (
    <div className="app-shell">
      <AppHeader projectName={data?.project.name ?? '新对话'} updatedAt={data?.project.updated_at} agentModel={health.agent_model} imageModel={health.image_backend_health.model ?? backend} demoMode={health.demo_mode} />
      {error ? <div className="error-toast"><span>{error}</span><button type="button" aria-label="关闭错误" onClick={() => setError(null)}><Icon name="x" size={14} /></button></div> : null}
      <div className="app-body">
        <ConversationSidebar conversations={conversations} activeSessionId={data?.session?.id} openingSessionId={openingSessionId} onNew={handleNew} onSelect={(item) => void handleOpen(item)} onDelete={handleDelete} />
        {data ? <div className="studio-layout">
          <main className={`workspace-column${health.demo_mode ? ' has-mode-banner' : ''}`}>
            {health.demo_mode ? <div className="active-demo-banner"><Icon name="alert" size={14} /><span>演示模式：当前图片为本地示例，未调用千问 API</span><button type="button" onClick={() => setConfigOpen(true)}>配置千问</button></div> : null}
            <ArtCanvas images={data.images} selectedId={data.project.selected_image_id} onSelect={handleSelect} backend={backend} backendAvailable={health.image_backend_health.available} />
            <ConversationPanel messages={data.messages} worldContext={data.project.world_context} aspectRatio={data.project.aspect_ratio} isGenerating={isGenerating} turnCount={data.turns.length} onSend={handleSend} />
          </main>
          <AgentInspector events={data.events} invocations={data.agent_invocations} memory={data.memory} memoryMeta={data.memory_meta} contextStatus={data.context_status} isGenerating={isGenerating} runStatus={data.run?.status} onRetry={handleRetry} onResetCompaction={() => void handleResetCompaction()} />
        </div> : <HomeScreen demoMode={health.demo_mode} isGenerating={isGenerating} onConfigure={() => setConfigOpen(true)} onSend={handleSend} />}
      </div>
      <QwenConfigDialog open={configOpen} onClose={() => setConfigOpen(false)} />
    </div>
  )
}
