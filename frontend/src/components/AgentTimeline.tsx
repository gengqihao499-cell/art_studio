import type { AgentEvent } from '../types/artflow'
import { Icon } from './Icon'

interface AgentTimelineProps {
  events: AgentEvent[]
  isGenerating: boolean
  runStatus?: string
  retryCount?: number
  onRetry: () => void
}

const agentLabels: Record<string, string> = {
  brief_agent: 'Brief Agent',
  art_director: 'Art Director',
  composition_agent: 'Composition Agent',
  character_agent: 'Character Agent',
  color_agent: 'Color Agent',
  curator_agent: 'Curator Agent',
  workflow_compiler: 'Workflow Compiler',
  image_worker: 'Image Worker',
}

function statusLabel(event: AgentEvent) {
  if (event.status === 'running') return event.attempt > 1 ? `重试 ${event.attempt}/3` : '执行中'
  if (event.status === 'rejected') return '未通过'
  if (event.status === 'waiting') return '等待中'
  if (event.status === 'passed') return '已通过'
  if (event.status === 'failed') return '失败'
  return '已完成'
}

export function AgentTimeline({ events, isGenerating, runStatus, retryCount = 0, onRetry }: AgentTimelineProps) {
  return (
    <aside className="timeline-panel panel-scroll" aria-labelledby="timeline-heading">
      <div className="panel-heading timeline-title">
        <h2 id="timeline-heading">Agent 执行过程</h2>
        <span className={isGenerating ? 'live-indicator is-live' : 'live-indicator'}>
          <span /> {isGenerating ? '实时协作' : '已同步'}
        </span>
      </div>

      {runStatus === 'failed' ? (
        <div className="retry-banner">
          <div>
            <strong>生成后端执行失败</strong>
            <span>可从最后 checkpoint 继续，无需重跑前置 Agent。</span>
          </div>
          <button type="button" onClick={onRetry}>恢复任务{retryCount > 0 ? ` · ${retryCount}` : ''}</button>
        </div>
      ) : null}

      {events.length === 0 ? (
        <div className="timeline-empty">
          <Icon name="clock" size={24} />
          <strong>等待任务开始</strong>
          <p>结构化事件会在这里持续更新。</p>
        </div>
      ) : (
        <ol className="agent-timeline">
          {events.map((event, index) => {
            const rejected = event.status === 'rejected'
            const running = event.status === 'running'
            const instructions = Array.isArray(event.payload.revision_instructions)
              ? event.payload.revision_instructions as string[]
              : []
            return (
              <li className={`agent-event status-${event.status}`} key={event.id}>
                <span className="event-rail">
                  <span className="event-node">
                    <Icon name={running ? 'loader' : rejected || event.status === 'failed' ? 'x' : 'check'} size={16} className={running ? 'spin' : undefined} />
                  </span>
                  {index < events.length - 1 ? <span className="event-line" /> : null}
                </span>
                <div className="event-content">
                  <div className="event-heading">
                    <strong>{agentLabels[event.agent] ?? event.title}</strong>
                    <span>{statusLabel(event)}</span>
                  </div>
                  <p>{event.summary}</p>
                  {rejected ? (
                    <div className="review-note">
                      <span>评审反馈 · 第 {event.attempt} 轮</span>
                      <p>{instructions.join('；') || event.summary}</p>
                    </div>
                  ) : null}
                </div>
              </li>
            )
          })}
        </ol>
      )}
    </aside>
  )
}
