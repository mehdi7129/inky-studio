import type { ReactNode } from 'react'
import type { DisplayInfo, HealthResponse } from '../lib/api'

export type TabId = 'dashboard' | 'queue' | 'settings' | 'history'

interface LayoutProps {
  activeTab: TabId
  onTabChange: (tab: TabId) => void
  display: DisplayInfo | null
  health: HealthResponse | null
  queueCount: number
  children: ReactNode
}

const TABS: { id: TabId; label: string }[] = [
  { id: 'dashboard', label: 'Tableau de bord' },
  { id: 'queue', label: "File d'attente" },
  { id: 'settings', label: 'Paramètres' },
  { id: 'history', label: 'Historique' },
]

export function Layout({ activeTab, onTabChange, display, health, queueCount, children }: LayoutProps) {
  return (
    <div className="min-h-screen">
      <header className="border-b border-neutral-200 dark:border-neutral-800 bg-white/70 dark:bg-neutral-950/70 backdrop-blur sticky top-0 z-10">
        <div className="max-w-6xl mx-auto px-6 py-3 flex items-center justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">Inky Studio</h1>
            {display && (
              <p className="text-xs text-neutral-500 mt-0.5">
                {display.model} · {display.width}×{display.height} · {display.colors} couleurs
                {display.is_mock && (
                  <span className="ml-2 px-1.5 py-0.5 rounded bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300 text-[10px] font-medium">
                    MOCK
                  </span>
                )}
                {health && <span className="ml-2 opacity-60">v{health.version}</span>}
              </p>
            )}
          </div>
          <nav className="flex gap-1 text-sm" aria-label="Sections principales">
            {TABS.map((tab) => {
              const isActive = activeTab === tab.id
              const isQueue = tab.id === 'queue'
              return (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => onTabChange(tab.id)}
                  className={[
                    'px-3 py-1.5 rounded-md transition',
                    isActive
                      ? 'bg-neutral-900 text-white dark:bg-neutral-100 dark:text-neutral-900'
                      : 'text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800',
                  ].join(' ')}
                >
                  {tab.label}
                  {isQueue && queueCount > 0 && (
                    <span
                      className={[
                        'ml-1.5 inline-flex items-center justify-center text-[10px] font-semibold rounded-full min-w-[1.25rem] h-5 px-1.5',
                        isActive
                          ? 'bg-white/20 text-white dark:bg-neutral-900/20 dark:text-neutral-900'
                          : 'bg-neutral-200 text-neutral-700 dark:bg-neutral-700 dark:text-neutral-200',
                      ].join(' ')}
                    >
                      {queueCount}
                    </span>
                  )}
                </button>
              )
            })}
          </nav>
        </div>
      </header>
      <main className="max-w-6xl mx-auto px-6 py-8">{children}</main>
    </div>
  )
}
