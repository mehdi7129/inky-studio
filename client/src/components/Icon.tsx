import type { SVGProps } from 'react'

const paths = {
  home: 'm3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1Z',
  queue: 'M9 6h12M9 12h12M9 18h12M3 6h.01M3 12h.01M3 18h.01',
  history: 'M3 11a9 9 0 1 1 2.6 7.4M3 4v7h7M12 7v5l3 2',
  settings: 'm9 3-1 3-3 1-2 3 2 2-1 3 2 3 3-1 3 2 3-2 3 1 2-3-1-3 2-2-2-3-3-1-1-3ZM15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0',
  image: 'M4 3h16a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1ZM3 17l6-6 4 4 3-3 5 5M8 7h.01',
  trash: 'M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7',
  grip: 'M9 5h.01M15 5h.01M9 12h.01M15 12h.01M9 19h.01M15 19h.01',
  lock: 'M6 10h12v11H6ZM8 10V7a4 4 0 0 1 8 0v3M12 14v3',
  arrowRight: 'M4 12h16m-6-6 6 6-6 6',
  arrowLeft: 'M20 12H4m6-6-6 6 6 6',
  clock: 'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0ZM12 7v5l3 2',
  monitor: 'M3 3h18v14H3ZM7 21h10M12 17v4',
  refresh: 'M20 7a9 9 0 0 0-15-1L3 9m0-6v6h6m-5 8a9 9 0 0 0 15 1l2-3m0 6v-6h-6',
  plus: 'M12 5v14M5 12h14',
  upload: 'M12 16V3m-5 5 5-5 5 5M4 16v5h16v-5',
  check: 'm5 12 4 4L19 6',
  close: 'm6 6 12 12M6 18 18 6',
  logout: 'M9 3H3v18h6M9 12h12m-5-5 5 5-5 5',
  chevronRight: 'm9 5 7 7-7 7',
  chevronLeft: 'm15 5-7 7 7 7',
  arrowUp: 'M12 20V4m-6 6 6-6 6 6',
  arrowDown: 'M12 4v16m-6-6 6 6 6-6',
  crop: 'M6 3v15h15M3 6h15v15',
  sun: 'M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0ZM12 2v2M12 20v2M2 12h2M20 12h2m-3-7 1-1M4 20l1-1M4 4l1 1m14 14 1 1',
  contrast: 'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0ZM12 3v18',
  info: 'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0ZM12 11v6M12 7h.01',
} as const

export type IconName = keyof typeof paths

export function Icon({ name, size = 20, ...props }: SVGProps<SVGSVGElement> & { name: IconName; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
      <path d={paths[name]} />
    </svg>
  )
}
