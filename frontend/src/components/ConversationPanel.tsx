import { useEffect, useRef } from 'react'
import { resolveAssetUrl } from '../services/api'
import type { ConversationInput, Message } from '../types/artflow'
import { Icon } from './Icon'
import { PromptComposer } from './PromptComposer'

interface Props {
  messages: Message[]
  worldContext: string
  aspectRatio: string
  isGenerating: boolean
  turnCount: number
  onSend: (input: ConversationInput) => Promise<void>
}

export function ConversationPanel({ messages, worldContext: initialWorld, aspectRatio: initialAspect, isGenerating, turnCount, onSend }: Props) {
  const listRef = useRef<HTMLDivElement>(null)
  useEffect(() => { listRef.current?.scrollTo({ top: listRef.current.scrollHeight }) }, [messages, isGenerating])

  return (
    <section className="conversation-panel" aria-label="持续对话">
      <div className="conversation-heading">
        <div><Icon name="sparkles" size={15} /><strong>创作对话</strong><span>{turnCount} 轮</span></div>
        <span>首轮 4 张 · 后续 2 张 · 基于选中版本</span>
      </div>
      <div className="message-thread" ref={listRef}>
        {messages.map((item) => (
          <article className={`message-row is-${item.role}`} key={item.id}>
            <span className="message-avatar">{item.role === 'assistant' ? 'AF' : '你'}</span>
            <div>
              <header><strong>{item.role === 'assistant' ? 'ArtFlow Assistant' : '你'}</strong><time>{new Date(item.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}</time></header>
              <p>{item.content}</p>
              {item.attachments?.length ? <div className="message-attachments">{item.attachments.map((url) => <img src={resolveAssetUrl(url)} alt="参考图" key={url} />)}</div> : null}
            </div>
          </article>
        ))}
        {isGenerating ? <div className="thinking-row"><Icon name="loader" className="spin" size={14} /><span>多个 Agent 正在协作，本轮结束后会自动加入对话…</span></div> : null}
      </div>
      <PromptComposer initialWorldContext={initialWorld} initialAspectRatio={initialAspect} isGenerating={isGenerating} placeholder={turnCount ? '继续修改：例如“把月亮放大，其他元素保持不变”…' : '描述你想生成的游戏美术…'} onSend={onSend} />
    </section>
  )
}
