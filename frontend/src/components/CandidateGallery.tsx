import type { CandidateImage } from '../types/artflow'
import { resolveAssetUrl } from '../services/api'
import { Icon } from './Icon'

interface CandidateGalleryProps {
  images: CandidateImage[]
  selectedId: string | null
  onSelect: (imageId: string) => void
}

export function CandidateGallery({ images, selectedId, onSelect }: CandidateGalleryProps) {
  if (images.length === 0) {
    return (
      <div className="canvas-empty">
        <span className="canvas-empty-icon"><Icon name="image" size={28} /></span>
        <strong>画布等待 Agent 结果</strong>
        <p>提交需求后，结构化提案、审核与候选图会依次生成。</p>
      </div>
    )
  }

  return (
    <div className="candidate-grid">
      {images.map((image) => {
        const selected = image.id === selectedId
        return (
          <article
            className={`candidate-card${selected ? ' is-selected' : ''}`}
            key={image.id}
            onClick={() => onSelect(image.id)}
            title={`${image.backend.toUpperCase()} · ${image.model} · Seed ${image.seed}`}
          >
            <div className="candidate-frame">
              <img src={resolveAssetUrl(image.public_url)} alt={`${image.label} · ${image.title}`} />
              <span className="candidate-letter">{image.label}</span>
              {selected ? <span className="candidate-check"><Icon name="check" size={15} /></span> : null}
            </div>
            <div className="candidate-caption">
              <strong>{image.title}</strong>
              <span>V{image.version_number} · {image.variation}</span>
            </div>
          </article>
        )
      })}
    </div>
  )
}
