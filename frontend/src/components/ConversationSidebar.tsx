import { useState } from 'react'
import type { ConversationSummary } from '../types/artflow'
import { Icon } from './Icon'

interface Props {
  conversations: ConversationSummary[]
  activeSessionId?: string
  openingSessionId?: string | null
  onNew: () => void
  onSelect: (item: ConversationSummary) => void
  onDelete: (item: ConversationSummary) => Promise<void>
}

function formatWhen(value: string) {
  const date = new Date(value)
  const today = new Date()
  if (date.toDateString() === today.toDateString()) return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1)
  if (date.toDateString() === yesterday.toDateString()) return '昨天'
  return date.toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' })
}

export function ConversationSidebar({ conversations, activeSessionId, openingSessionId, onNew, onSelect, onDelete }: Props) {
  const [confirmId, setConfirmId] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const remove = async (item: ConversationSummary) => {
    setDeletingId(item.session_id)
    try { await onDelete(item); setConfirmId(null) } finally { setDeletingId(null) }
  }

  return (
    <aside className="conversation-sidebar" aria-label="对话历史">
      <button className="new-conversation-button" type="button" onClick={onNew}><Icon name="plus" size={17} />新建对话</button>
      <div className="sidebar-section-title"><span>最近对话</span><span>{conversations.length}</span></div>
      <div className="conversation-list">
        {conversations.length ? conversations.map((item) => (
          <div className={`conversation-list-item${activeSessionId === item.session_id ? ' is-active' : ''}`} key={item.session_id}>
            <button className="conversation-select" type="button" onClick={() => onSelect(item)} disabled={openingSessionId === item.session_id}>
              <strong>{item.title}</strong>
              <span>{openingSessionId === item.session_id ? '载入中…' : formatWhen(item.updated_at)}</span>
            </button>
            <button className="conversation-delete" type="button" aria-label={`删除 ${item.title}`} onClick={() => setConfirmId(item.session_id)}><Icon name="trash" size={14} /></button>
            {confirmId === item.session_id ? <div className="sidebar-delete-confirm"><span>删除此对话？</span><button type="button" disabled={deletingId === item.session_id} onClick={() => void remove(item)}>{deletingId === item.session_id ? '删除中' : '删除'}</button><button type="button" onClick={() => setConfirmId(null)}>取消</button></div> : null}
          </div>
        )) : <div className="sidebar-empty"><Icon name="clock" size={19} /><span>暂无本地对话</span></div>}
      </div>
      <p className="sidebar-footnote">对话、图片与 Agent 日志保存在本机</p>
    </aside>
  )
}
