import { useEffect, useMemo, useState, type ChangeEvent, type DragEvent } from 'react'
import { resolveAssetUrl } from '../services/api'
import type { GenerationInput, Message } from '../types/artflow'
import { Icon } from './Icon'

interface ChatPanelProps {
  initialPrompt: string
  initialWorldContext: string
  initialAspectRatio: string
  initialImageCount: number
  initialReferences: string[]
  messages: Message[]
  isGenerating: boolean
  onGenerate: (input: GenerationInput) => void
}

export function ChatPanel({
  initialPrompt,
  initialWorldContext,
  initialAspectRatio,
  initialImageCount,
  initialReferences,
  messages,
  isGenerating,
  onGenerate,
}: ChatPanelProps) {
  const [prompt, setPrompt] = useState(initialPrompt)
  const [worldContext, setWorldContext] = useState(initialWorldContext)
  const [aspectRatio, setAspectRatio] = useState(initialAspectRatio)
  const [imageCount, setImageCount] = useState(initialImageCount)
  const [files, setFiles] = useState<File[]>([])
  const [dragging, setDragging] = useState(false)

  useEffect(() => {
    setPrompt(initialPrompt)
    setWorldContext(initialWorldContext)
    setAspectRatio(initialAspectRatio)
    setImageCount(initialImageCount)
    setFiles([])
  }, [initialAspectRatio, initialImageCount, initialPrompt, initialWorldContext])

  const localPreviews = useMemo(
    () => files.map((file) => ({ name: file.name, url: URL.createObjectURL(file) })),
    [files],
  )

  useEffect(() => () => localPreviews.forEach((preview) => URL.revokeObjectURL(preview.url)), [localPreviews])

  const assistantMessage = messages.find((message) => message.role === 'assistant')?.content
    ?? '你好，我是 ArtFlow 助手。我会协调多个专业 Agent，为你打造最合适的游戏美术方案。'

  const addFiles = (nextFiles: File[]) => {
    const accepted = nextFiles.filter((file) => file.type.startsWith('image/'))
    setFiles((current) => [...current, ...accepted].slice(0, 5))
  }

  const handleFileInput = (event: ChangeEvent<HTMLInputElement>) => {
    addFiles(Array.from(event.target.files ?? []))
    event.target.value = ''
  }

  const handleDrop = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault()
    setDragging(false)
    addFiles(Array.from(event.dataTransfer.files))
  }

  const references = localPreviews.length > 0
    ? localPreviews
    : initialReferences.map((url, index) => ({ name: `参考图 ${index + 1}`, url: resolveAssetUrl(url) }))

  return (
    <aside className="input-panel panel-scroll" aria-labelledby="input-heading">
      <div className="panel-heading">
        <h2 id="input-heading">对话与输入</h2>
      </div>

      <div className="assistant-message">
        <span className="assistant-symbol"><Icon name="sparkles" size={19} /></span>
        <div>
          <p>{assistantMessage}</p>
          <time>工作室助手</time>
        </div>
      </div>

      <form className="brief-form" onSubmit={(event) => {
        event.preventDefault()
        onGenerate({ prompt, worldContext, aspectRatio, imageCount, files })
      }}>
        <label className="field-group">
          <span>你的需求</span>
          <span className="textarea-wrap">
            <textarea
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              maxLength={1000}
              placeholder="描述角色、场景、风格与输出用途…"
              rows={5}
            />
            <small>{prompt.length}/1000</small>
          </span>
        </label>

        <label className="field-group">
          <span>世界观 <em>（可选）</em></span>
          <span className="textarea-wrap compact">
            <textarea
              value={worldContext}
              onChange={(event) => setWorldContext(event.target.value)}
              maxLength={200}
              placeholder="时代、地点、阵营或叙事背景"
              rows={2}
            />
            <small>{worldContext.length}/200</small>
          </span>
        </label>

        <div className="field-group">
          <span>参考图 <em>（可选，最多 5 张）</em></span>
          <label
            className={`upload-zone${dragging ? ' is-dragging' : ''}`}
            onDragOver={(event) => { event.preventDefault(); setDragging(true) }}
            onDragLeave={() => setDragging(false)}
            onDrop={handleDrop}
          >
            <input type="file" accept="image/png,image/jpeg,image/webp" multiple onChange={handleFileInput} />
            <div className="reference-strip">
              {references.slice(0, 3).map((reference, index) => (
                <span className="reference-thumb" key={`${reference.url}-${index}`}>
                  <img src={reference.url} alt={reference.name} />
                  {localPreviews.length > 0 ? (
                    <button type="button" onClick={(event) => { event.preventDefault(); setFiles((current) => current.filter((_, fileIndex) => fileIndex !== index)) }} aria-label={`移除 ${reference.name}`}>
                      <Icon name="x" size={13} />
                    </button>
                  ) : null}
                </span>
              ))}
              <span className="upload-instruction">
                <Icon name="upload" size={21} />
                <strong>点击或拖拽上传</strong>
                <small>PNG / JPG / WebP · 单图 ≤ 10MB</small>
              </span>
            </div>
          </label>
        </div>

        <div className="controls-row">
          <label className="field-group select-field">
            <span>画面比例</span>
            <select value={aspectRatio} onChange={(event) => setAspectRatio(event.target.value)}>
              <option value="1:1">1:1 · 正方形</option>
              <option value="4:3">4:3 · 横向</option>
              <option value="3:4">3:4 · 竖向</option>
            </select>
          </label>

          <div className="field-group count-field">
            <span>生成数量</span>
            <div className="stepper">
              <button type="button" onClick={() => setImageCount((count) => Math.max(3, count - 1))} disabled={imageCount <= 3}><Icon name="minus" size={15} /></button>
              <strong>{imageCount}</strong>
              <button type="button" onClick={() => setImageCount((count) => Math.min(4, count + 1))} disabled={imageCount >= 4}><Icon name="plus" size={15} /></button>
            </div>
          </div>
        </div>

        <button className="generate-button" type="submit" disabled={isGenerating || prompt.trim().length < 8}>
          <Icon name={isGenerating ? 'loader' : 'sparkles'} size={20} className={isGenerating ? 'spin' : undefined} />
          {isGenerating ? 'Agent 正在协作…' : '开始生成'}
        </button>
      </form>
    </aside>
  )
}

