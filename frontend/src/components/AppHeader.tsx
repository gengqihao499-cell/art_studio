import { Icon } from './Icon'

interface AppHeaderProps {
  projectName: string
  updatedAt?: string
  agentModel?: string
  imageModel?: string
  demoMode?: boolean
}

function formatSyncTime(value?: string) {
  if (!value) return '本地待命'
  return `已保存 · ${new Date(value).toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
  })}`
}

export function AppHeader({ projectName, updatedAt, agentModel, imageModel, demoMode }: AppHeaderProps) {
  return (
    <header className="app-header">
      <div className="brand-lockup" aria-label="ArtFlow Studio">
        <span className="brand-mark"><span /> <span /> <span /></span>
        <span className="brand-wordmark">ARTFLOW STUDIO</span>
      </div>
      <div className="project-heading">
        <strong>{projectName}</strong>
        <span className="project-divider" />
        <span className="sync-state"><Icon name="cloud" size={16} /> {formatSyncTime(updatedAt)}</span>
      </div>
      <div className="header-models"><span>{agentModel ?? 'Agent'}</span><span className={demoMode ? 'is-demo' : ''}>{demoMode ? 'MOCK' : imageModel ?? 'Image'}</span></div>
    </header>
  )
}
