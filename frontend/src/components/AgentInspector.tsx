import { useMemo, useState } from 'react'
import type { AgentEvent, AgentInvocation, ContextStatus, MemoryMeta } from '../types/artflow'
import { Icon } from './Icon'

type Tab = 'process' | 'outputs' | 'logs' | 'memory'

const agentLabels: Record<string, string> = {
  memory_agent: 'Memory Agent', intent_router: 'Intent Router', brief_agent: 'Brief Agent', art_director: 'Art Director',
  composition_agent: 'Composition Agent', character_agent: 'Character Agent', color_agent: 'Color Agent', curator_agent: 'Curator Agent',
  prompt_compiler: 'Prompt Compiler', image_worker: 'Image Worker', assistant_agent: 'Assistant Agent', orchestrator: 'Orchestrator',
}
const memoryLabels: Record<string, string> = {
  project_goal: '项目目标', locked_constraints: '锁定约束', style_decisions: '风格决定', character_facts: '角色事实',
  composition_facts: '构图事实', rejected_directions: '已否决方向', active_image: '当前图片', open_questions: '待确认问题',
}

interface Props {
  events: AgentEvent[]
  invocations: AgentInvocation[]
  memory: Record<string, unknown>
  memoryMeta: MemoryMeta | null
  contextStatus: ContextStatus | null
  isGenerating: boolean
  runStatus?: string
  onRetry: () => void
  onResetCompaction: () => void
}

function JsonValue({ value }: { value: unknown }) {
  if (value == null || value === '' || (Array.isArray(value) && value.length === 0)) return <span className="empty-value">暂无</span>
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return <span>{String(value)}</span>
  return <pre>{JSON.stringify(value, null, 2)}</pre>
}

const layerLabels: Record<string, string> = {
  artifact_offload: '① 大结果落盘',
  snip: '② Snip 远古裁剪',
  micro_compact: '③ Micro-compact',
  context_collapse: '④ Context Collapse',
  auto_compact: '⑤ Auto-compact',
}

function statusLabel(status: unknown) {
  if (status === 'open') return '已熔断'
  if (status === 'requested') return '待压缩'
  if (status === 'completed') return '已完成'
  if (status === 'failed') return '失败'
  return '运行中'
}

export function AgentInspector({ events, invocations, memory, memoryMeta, contextStatus, isGenerating, runStatus, onRetry, onResetCompaction }: Props) {
  const [tab, setTab] = useState<Tab>('process')
  const latestInvocations = useMemo(() => [...invocations].reverse(), [invocations])
  const tabs: Array<{ id: Tab; label: string }> = [
    { id: 'process', label: '执行过程' }, { id: 'outputs', label: 'Agent 输出' }, { id: 'logs', label: '运行日志' }, { id: 'memory', label: 'Context Memory' },
  ]

  return (
    <aside className="agent-inspector" aria-label="Agent 信息">
      <div className="inspector-heading">
        <div><h2>Agent 信息</h2><span className={isGenerating ? 'live-indicator is-live' : 'live-indicator'}><span />{isGenerating ? '实时执行' : '已同步'}</span></div>
        <nav>{tabs.map((item) => <button type="button" className={tab === item.id ? 'is-active' : ''} key={item.id} onClick={() => setTab(item.id)}>{item.label}</button>)}</nav>
      </div>

      <div className="inspector-body">
        {runStatus === 'failed' ? <div className="retry-banner"><div><strong>本轮执行失败</strong><span>可以从 LangGraph checkpoint 恢复。</span></div><button type="button" onClick={onRetry}>恢复</button></div> : null}

        {tab === 'process' ? (
          events.length ? <ol className="agent-timeline">{events.map((event, index) => {
            const running = event.status === 'running'; const failed = event.status === 'failed' || event.status === 'rejected'
            return <li className={`agent-event status-${event.status}`} key={event.id}>
              <span className="event-rail"><span className="event-node"><Icon name={running ? 'loader' : failed ? 'x' : 'check'} className={running ? 'spin' : undefined} size={14} /></span>{index < events.length - 1 ? <span className="event-line" /> : null}</span>
              <div className="event-content"><div className="event-heading"><strong>{agentLabels[event.agent] ?? event.title}</strong><span>{event.event_type === 'agent_skipped' ? '已跳过' : running ? '执行中' : failed ? '需注意' : '完成'}</span></div><p>{event.summary}</p></div>
            </li>
          })}</ol> : <div className="inspector-empty"><Icon name="clock" size={24} /><strong>等待任务</strong><p>发送消息后可在此查看完整执行链。</p></div>
        ) : null}

        {tab === 'outputs' ? (
          <div className="output-list">{latestInvocations.length ? latestInvocations.map((item) => <article className="output-card" key={item.id}><header><strong>{agentLabels[item.agent] ?? item.agent}</strong><span className={`log-status is-${item.status}`}>{item.status === 'skipped' ? '跳过' : item.status === 'failed' ? '失败' : '完成'}</span></header><p>{item.output_summary || item.reason}</p><details><summary>结构化输出</summary><JsonValue value={item.structured_output} /></details></article>) : <div className="inspector-empty"><strong>暂无输出</strong></div>}</div>
        ) : null}

        {tab === 'logs' ? (
          <div className="log-list">{latestInvocations.length ? latestInvocations.map((item) => <article className="log-card" key={item.id}><header><span>{agentLabels[item.agent] ?? item.agent}</span><time>{new Date(item.started_at).toLocaleTimeString('zh-CN')}</time></header><div className="log-metrics"><span>{item.model}</span><span>{item.latency_ms} ms</span><span>{item.input_tokens + item.output_tokens} tokens</span><span>attempt {item.attempt}</span></div><p><strong>原因</strong>{item.reason || '工作流节点执行'}</p><p><strong>输入</strong>{item.input_summary}</p><p><strong>输出</strong>{item.output_summary || item.error_message || '本轮跳过'}</p></article>) : <div className="inspector-empty"><Icon name="terminal" size={24} /><strong>暂无调用日志</strong></div>}</div>
        ) : null}

        {tab === 'memory' ? (
          <div className="memory-panel">
            <div className="memory-summary"><Icon name="memory" size={18} /><div><strong>结构化上下文</strong><span>{memoryMeta ? `已汇总 ${memoryMeta.source_message_count} 条消息 · 至第 ${memoryMeta.summarized_through_sequence} 轮` : '首轮完成后建立'}</span></div></div>
            {contextStatus ? <>
              <section className="context-overview">
                <div><span>CLAUDE.md</span><strong>v{contextStatus.claude.version}</strong></div>
                <div><span>Artifacts</span><strong>{contextStatus.artifact_count ?? 0}</strong></div>
                <div><span>向量记忆</span><strong>{contextStatus.memory_item_count ?? 0}</strong></div>
              </section>
              <section className="context-storage">
                <span>BLOB · {contextStatus.storage.blob.backend}</span>
                <span>VECTOR · {contextStatus.storage.vector.backend}</span>
                <span>EMBED · {contextStatus.storage.embedding.backend}/{contextStatus.storage.embedding.dimension}</span>
              </section>
              <section className="context-budget">
                <header><span>上下文预算</span><strong>{Math.round((contextStatus.budget?.usage_ratio ?? 0) * 100)}%</strong></header>
                <div><span style={{ width: `${Math.min(100, Math.round((contextStatus.budget?.usage_ratio ?? 0) * 100))}%` }} /></div>
                <p>{contextStatus.budget?.estimated_tokens ?? 0} / {contextStatus.budget?.max_tokens ?? 0} estimated tokens</p>
              </section>
              <div className="context-layers">{Object.entries(layerLabels).map(([key, label]) => {
                const layer = contextStatus.layers[key] ?? {}
                const layerStatus = layer.status
                return <article key={key} className={layerStatus === 'open' || layerStatus === 'failed' ? 'is-warning' : ''}><div><strong>{label}</strong><span>{statusLabel(layerStatus)}</span></div><p>{key === 'snip' ? `完整 ${String(layer.full ?? 0)} · 微缩 ${String(layer.micro ?? 0)} · 引用 ${String(layer.snipped ?? 0)}` : key === 'artifact_offload' ? `${String(layer.backend ?? 'local')} · 阈值 ${String(layer.inline_char_limit ?? 0)} 字符` : key === 'micro_compact' ? `完整 ${String(layer.full_turns ?? 2)} 轮 · 微缩至 ${String(layer.micro_turns ?? 8)} 轮` : key === 'context_collapse' ? '按 Agent 职责生成读时投影' : `连续失败 ${contextStatus.compaction?.consecutive_failures ?? 0}/3`}</p></article>
              })}</div>
              {contextStatus.compaction?.circuit_state === 'open' ? <section className="compaction-breaker"><div><strong>Auto-compact 已熔断</strong><span>{contextStatus.compaction.last_error || '连续失败 3 次'}</span></div><button type="button" onClick={onResetCompaction}>复位</button></section> : null}
              <details className="claude-preview"><summary>查看 CLAUDE.md 自动记忆</summary><pre>{contextStatus.claude_preview}</pre><span>{contextStatus.claude.path}</span></details>
            </> : null}
            {Object.entries(memoryLabels).map(([key, label]) => <section className="memory-field" key={key}><h3>{label}</h3><JsonValue value={memory[key]} /></section>)}
          </div>
        ) : null}
      </div>
    </aside>
  )
}
