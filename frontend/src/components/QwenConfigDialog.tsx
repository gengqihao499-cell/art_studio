import { Icon } from './Icon'

interface Props { open: boolean; onClose: () => void }

export function QwenConfigDialog({ open, onClose }: Props) {
  if (!open) return null
  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="config-dialog" role="dialog" aria-modal="true" aria-labelledby="config-title" onMouseDown={(event) => event.stopPropagation()}>
        <header><div><span>QWEN / BEIJING</span><h2 id="config-title">连接千问 API</h2></div><button type="button" aria-label="关闭" onClick={onClose}><Icon name="x" size={17} /></button></header>
        <p>编辑当前安装目录中的 <code>backend\.env</code>。保存后完全关闭并重新双击 <code>Start-ArtFlow.cmd</code>。</p>
        <pre>{`ARTFLOW_AGENT_BACKEND=qwen
ARTFLOW_IMAGE_BACKEND=qwen_image
DASHSCOPE_API_KEY=你的_API_Key
DASHSCOPE_WORKSPACE_ID=ws-开头的业务空间ID
QWEN_CHAT_MODEL=qwen-plus
QWEN_IMAGE_MODEL=qwen-image-2.0`}</pre>
        <div className="config-note"><Icon name="alert" size={16} /><span>API Key 只写在本机 .env，不要粘贴到聊天、前端代码或截图中。</span></div>
        <footer><span>启动窗口会打印实际读取的 .env 路径和当前模式。</span><button type="button" onClick={onClose}>知道了</button></footer>
      </section>
    </div>
  )
}
