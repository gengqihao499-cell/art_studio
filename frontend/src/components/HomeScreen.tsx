import { useState } from 'react'
import type { ConversationInput } from '../types/artflow'
import { Icon } from './Icon'
import { PromptComposer } from './PromptComposer'

interface Props {
  demoMode: boolean
  isGenerating: boolean
  onConfigure: () => void
  onSend: (input: ConversationInput) => Promise<void>
}

const starters = [
  ['角色概念', '设计一名具有清晰剪影和标志性武器的游戏角色概念图'],
  ['场景设计', '设计一个具有明确视觉焦点和叙事线索的游戏场景'],
  ['道具设计', '设计一件能够体现世界观与使用痕迹的关键道具'],
] as const

export function HomeScreen({ demoMode, isGenerating, onConfigure, onSend }: Props) {
  const [suggestedPrompt, setSuggestedPrompt] = useState('')
  return (
    <main className="home-screen">
      <section className="home-content">
        <div className="home-kicker"><span /> MULTI-AGENT ART WORKSPACE</div>
        <h1>我们从哪里开始？</h1>
        <p>描述你想创作的游戏美术，多个专业 Agent 会协作完成。</p>
        <div className="starter-grid">
          {starters.map(([label, prompt], index) => <button type="button" key={label} onClick={() => setSuggestedPrompt(`${prompt}。`)}><Icon name={index === 0 ? 'sparkles' : 'image'} size={17} /><span>{label}</span><Icon name="chevron-right" size={14} /></button>)}
        </div>
        {demoMode ? <div className="demo-warning"><Icon name="alert" size={16} /><span><strong>当前为演示模式</strong>，不会调用千问 API；生成结果为本地示例图。</span><button type="button" onClick={onConfigure}>配置千问<Icon name="chevron-right" size={13} /></button></div> : null}
        <PromptComposer isGenerating={isGenerating} placeholder="描述你的美术需求…" suggestedPrompt={suggestedPrompt} compact onSend={onSend} />
      </section>
    </main>
  )
}
