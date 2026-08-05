import { api } from '../services/api'
import { Icon } from './Icon'

interface DownloadButtonProps {
  imageId: string
}

export function DownloadButton({ imageId }: DownloadButtonProps) {
  return (
    <a
      className="toolbar-button"
      href={api.downloadUrl(imageId)}
      download
      aria-label="下载原图"
      title="下载原图"
    >
      <Icon name="download" size={17} />
      <span>下载原图</span>
    </a>
  )
}
