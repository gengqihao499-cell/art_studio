import type { SVGProps } from 'react'

type IconName =
  | 'plus'
  | 'cloud'
  | 'sparkles'
  | 'upload'
  | 'x'
  | 'minus'
  | 'check'
  | 'loader'
  | 'clock'
  | 'download'
  | 'image'
  | 'send'
  | 'paperclip'
  | 'terminal'
  | 'memory'
  | 'trash'
  | 'alert'
  | 'chevron-right'

interface IconProps extends SVGProps<SVGSVGElement> {
  name: IconName
  size?: number
}

export function Icon({ name, size = 18, ...props }: IconProps) {
  const common = {
    width: size,
    height: size,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.8,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    'aria-hidden': true,
  }

  const paths: Record<IconName, React.ReactNode> = {
    plus: <><path d="M12 5v14M5 12h14" /></>,
    cloud: <><path d="M7.5 18h9.25a4.25 4.25 0 0 0 .6-8.46A5.8 5.8 0 0 0 6.2 8.1 4.95 4.95 0 0 0 7.5 18Z" /></>,
    sparkles: <><path d="m12 3 1.2 3.8L17 8l-3.8 1.2L12 13l-1.2-3.8L7 8l3.8-1.2L12 3ZM5 15l.8 2.2L8 18l-2.2.8L5 21l-.8-2.2L2 18l2.2-.8L5 15ZM19 13l.7 1.8 1.8.7-1.8.7L19 18l-.7-1.8-1.8-.7 1.8-.7L19 13Z" /></>,
    upload: <><path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5" /><path d="M5 14v5h14v-5" /></>,
    x: <><path d="m7 7 10 10M17 7 7 17" /></>,
    minus: <><path d="M5 12h14" /></>,
    check: <><path d="m6.5 12 3.2 3.2 7.8-8" /></>,
    loader: <><path d="M20 12a8 8 0 1 1-2.34-5.66" /><path d="M17 3.5v4h4" /></>,
    clock: <><circle cx="12" cy="12" r="8.5" /><path d="M12 7v5l3 2" /></>,
    download: <><path d="M12 4v11m0 0 4-4m-4 4-4-4" /><path d="M5 19h14" /></>,
    image: <><rect x="3" y="4" width="18" height="16" rx="2" /><circle cx="8.5" cy="9" r="1.5" /><path d="m5 17 4.5-4 3.2 2.8 2.3-2.2 4 3.4" /></>,
    send: <><path d="m4 4 16 8-16 8 3-8-3-8Z" /><path d="M7 12h13" /></>,
    paperclip: <><path d="m9 12.5 5.2-5.2a3 3 0 1 1 4.2 4.2l-7.3 7.3a5 5 0 0 1-7.1-7.1l7.1-7.1" /></>,
    terminal: <><rect x="3" y="4" width="18" height="16" rx="2" /><path d="m7 9 3 3-3 3M12 16h5" /></>,
    memory: <><rect x="5" y="5" width="14" height="14" rx="2" /><path d="M9 1v4m6-4v4M9 19v4m6-4v4M1 9h4m-4 6h4m14-6h4m-4 6h4" /></>,
    trash: <><path d="M4 7h16M9 7V4h6v3M7 7l1 13h8l1-13M10 11v5m4-5v5" /></>,
    alert: <><path d="M12 3 2.8 19h18.4L12 3Z" /><path d="M12 9v4m0 3h.01" /></>,
    'chevron-right': <><path d="m9 5 7 7-7 7" /></>,
  }

  return <svg {...common} {...props}>{paths[name]}</svg>
}
