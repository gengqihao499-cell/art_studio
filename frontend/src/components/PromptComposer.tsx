import { useEffect, useMemo, useState, type ChangeEvent, type KeyboardEvent } from 'react'
import type { ConversationInput } from '../types/artflow'
import { Icon } from './Icon'

interface Props {
  initialWorldContext?: string
  initialAspectRatio?: string
  isGenerating: boolean
  placeholder: string
  suggestedPrompt?: string
  compact?: boolean
  onSend: (input: ConversationInput) => Promise<void>
}

export function PromptComposer({
  initialWorldContext = '', initialAspectRatio = '1:1', isGenerating, placeholder,
  suggestedPrompt, compact = false, onSend,
}: Props) {
  const [message, setMessage] = useState('')
  const [worldContext, setWorldContext] = useState(initialWorldContext)
  const [aspectRatio, setAspectRatio] = useState(initialAspectRatio)
  const [files, setFiles] = useState<File[]>([])
  const previews = useMemo(() => files.map((file) => ({ file, url: URL.createObjectURL(file) })), [files])

  useEffect(() => () => previews.forEach((item) => URL.revokeObjectURL(item.url)), [previews])
  useEffect(() => { if (suggestedPrompt) setMessage(suggestedPrompt) }, [suggestedPrompt])
  useEffect(() => { setWorldContext(initialWorldContext) }, [initialWorldContext])
  useEffect(() => { setAspectRatio(initialAspectRatio) }, [initialAspectRatio])

  const addFiles = (event: ChangeEvent<HTMLInputElement>) => {
    const next = Array.from(event.target.files ?? []).filter((file) => file.type.startsWith('image/'))
    setFiles((current) => [...current, ...next].slice(0, 5))
    event.target.value = ''
  }
  const submit = async () => {
    if (isGenerating || message.trim().length < 2) return
    const input = { message: message.trim(), worldContext, aspectRatio, files }
    setMessage(''); setFiles([])
    await onSend(input)
  }
  const handleKey = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void submit() }
  }

  return (
    <div className={`composer-shell${compact ? ' is-compact' : ''}`}>
      {previews.length ? <div className="composer-previews">{previews.map((item, index) => <span key={item.url}><img src={item.url} alt={item.file.name} /><button type="button" aria-label={`移除 ${item.file.name}`} onClick={() => setFiles((current) => current.filter((_, i) => i !== index))}><Icon name="x" size={11} /></button></span>)}</div> : null}
      <textarea value={message} onChange={(event) => setMessage(event.target.value)} onKeyDown={handleKey} placeholder={placeholder} rows={compact ? 1 : 2} maxLength={1600} autoFocus={!compact} />
      <div className="composer-tools">
        <label className="attach-button" title="添加参考图"><Icon name="paperclip" size={15} /><input type="file" accept="image/png,image/jpeg,image/webp" multiple onChange={addFiles} /></label>
        <input className="world-input" value={worldContext} onChange={(event) => setWorldContext(event.target.value)} placeholder="世界观（可选）" maxLength={200} />
        <select value={aspectRatio} onChange={(event) => setAspectRatio(event.target.value)} aria-label="画面比例">
          <option value="1:1">1:1</option><option value="4:3">4:3</option><option value="3:4">3:4</option><option value="16:9">16:9</option><option value="9:16">9:16</option>
        </select>
        <span className="composer-count">{message.length}/1600</span>
        <button className="send-button" type="button" disabled={isGenerating || message.trim().length < 2} onClick={() => void submit()} aria-label={isGenerating ? 'Agent 执行中' : '发送'}>
          <Icon name={isGenerating ? 'loader' : 'send'} className={isGenerating ? 'spin' : undefined} size={16} />
          {!compact ? <span>{isGenerating ? '执行中' : '发送'}</span> : null}
        </button>
      </div>
      <p className="composer-hint">Enter 发送 · Shift + Enter 换行 · 最多 5 张参考图</p>
    </div>
  )
}
