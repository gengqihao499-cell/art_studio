import { useMemo, useState } from 'react'
import type { CandidateImage } from '../types/artflow'
import { CandidateGallery } from './CandidateGallery'
import { DownloadButton } from './DownloadButton'

interface Props { images: CandidateImage[]; selectedId: string | null; onSelect: (id: string) => void; backend: string; backendAvailable: boolean }

export function ArtCanvas({ images, selectedId, onSelect, backend, backendAvailable }: Props) {
  const versions = useMemo(() => [...new Set(images.map((item) => item.version_number))].sort((a, b) => b - a), [images])
  const selected = images.find((item) => item.id === selectedId) ?? images[0]
  const [manualVersion, setManualVersion] = useState<number | null>(null)
  const activeVersion = manualVersion && versions.includes(manualVersion) ? manualVersion : (selected?.version_number ?? versions[0] ?? 1)
  const visible = images.filter((item) => item.version_number === activeVersion)

  return (
    <section className="canvas-panel" aria-labelledby="canvas-heading">
      <div className="canvas-toolbar">
        <div className="canvas-title-group">
          <h2 id="canvas-heading">版本画布</h2>
          <span>{visible.length ? `${visible.length} 个候选` : '等待生成'}</span>
          <span className={`backend-badge${backendAvailable ? '' : ' is-offline'}`}>{backend === 'qwen_image' ? 'QWEN IMAGE' : backend.toUpperCase()}</span>
        </div>
        <div className="canvas-actions">
          <div className="version-switcher" aria-label="版本历史">
            {versions.slice(0, 6).map((version) => <button type="button" className={version === activeVersion ? 'is-active' : ''} key={version} onClick={() => setManualVersion(version)}>V{version}</button>)}
          </div>
          {selected ? <DownloadButton imageId={selected.id} /> : null}
        </div>
      </div>
      <div className="canvas-surface">
        <div className="version-note"><span>V{activeVersion}</span><strong>{activeVersion === Math.max(...versions) ? '当前版本' : '历史版本'}</strong>{visible[0]?.parent_image_id ? <em>基于上一选中图分支</em> : <em>初始方案</em>}</div>
        <CandidateGallery images={visible} selectedId={selectedId} onSelect={onSelect} />
      </div>
    </section>
  )
}
